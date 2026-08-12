from __future__ import annotations

import sqlite3
from collections.abc import Callable

Migration = Callable[[sqlite3.Connection], None]


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}


def _add_column(db: sqlite3.Connection, table: str, definition: str) -> None:
    name = definition.split()[0]
    if name not in _columns(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _v1_base(db: sqlite3.Connection) -> None:
    """Create the original local message, classification, draft, and run tables."""
    db.execute(
        """CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY, account_id TEXT NOT NULL,
            provider_message_id TEXT NOT NULL, thread_id TEXT,
            from_address TEXT NOT NULL, from_name TEXT, subject TEXT NOT NULL,
            received_at TEXT NOT NULL, processed_at TEXT,
            UNIQUE(account_id, provider_message_id)
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS classifications (
            id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL UNIQUE,
            payload TEXT NOT NULL, FOREIGN KEY(message_id) REFERENCES messages(id)
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS drafts (
            id TEXT PRIMARY KEY, message_id INTEGER NOT NULL, account_id TEXT NOT NULL,
            source_message_id TEXT NOT NULL, recipient TEXT NOT NULL, subject TEXT NOT NULL,
            body TEXT NOT NULL, status TEXT NOT NULL, metadata TEXT NOT NULL,
            created_at TEXT NOT NULL, FOREIGN KEY(message_id) REFERENCES messages(id)
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS agent_runs (
            id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL, profile_id TEXT NOT NULL,
            profile_version INTEGER NOT NULL, prompt_version INTEGER NOT NULL,
            model TEXT NOT NULL, latency_ms INTEGER NOT NULL,
            draft_generated INTEGER NOT NULL, error TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )"""
    )


def _v2_attention_workflow(db: sqlite3.Connection) -> None:
    """Add inbox triage timestamps and the open/snoozed/done workflow."""
    _add_column(db, "messages", "triaged_at TEXT")
    db.execute("UPDATE messages SET triaged_at=COALESCE(triaged_at, processed_at, CURRENT_TIMESTAMP)")
    _add_column(db, "messages", "attention_state TEXT NOT NULL DEFAULT 'open'")
    _add_column(db, "messages", "snoozed_until TEXT")
    _add_column(db, "messages", "done_at TEXT")


def _v3_provider_locations_and_accounts(db: sqlite3.Connection) -> None:
    """Track folder-scoped provider IDs and rename profiles to accounts."""
    _add_column(db, "messages", "provider_mailbox TEXT NOT NULL DEFAULT 'INBOX'")
    _add_column(db, "messages", "provider_uid TEXT")
    db.execute("UPDATE messages SET provider_uid=COALESCE(provider_uid, provider_message_id)")
    columns = _columns(db, "agent_runs")
    if "profile_id" in columns and "account_id" not in columns:
        db.execute("ALTER TABLE agent_runs RENAME COLUMN profile_id TO account_id")
    columns = _columns(db, "agent_runs")
    if "profile_version" in columns and "agent_version" not in columns:
        db.execute("ALTER TABLE agent_runs RENAME COLUMN profile_version TO agent_version")


def _v4_category_audit(db: sqlite3.Connection) -> None:
    """Record successful provider category operations for idempotency."""
    db.execute(
        """CREATE TABLE IF NOT EXISTS category_syncs (
            id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL,
            destination TEXT NOT NULL, synced_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(message_id, destination),
            FOREIGN KEY(message_id) REFERENCES messages(id)
        )"""
    )


def _v5_category_replacement(db: sqlite3.Connection) -> None:
    """Track the active managed category and copied provider location."""
    _add_column(db, "category_syncs", "provider_uid TEXT")
    _add_column(db, "category_syncs", "provider_mailbox TEXT")
    _add_column(db, "category_syncs", "active INTEGER NOT NULL DEFAULT 1")


def _v6_simplify_run_audit(db: sqlite3.Connection) -> None:
    """Remove duplicate configuration-version fields from run audit records."""
    columns = _columns(db, "agent_runs")
    if "agent_version" not in columns and "profile_version" not in columns:
        return
    db.execute(
        """CREATE TABLE agent_runs_v6 (
            id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL, account_id TEXT NOT NULL,
            model TEXT NOT NULL, latency_ms INTEGER NOT NULL,
            draft_generated INTEGER NOT NULL, error TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    account_column = "account_id" if "account_id" in columns else "profile_id"
    db.execute(
        f"""INSERT INTO agent_runs_v6(
                id, message_id, account_id, model, latency_ms,
                draft_generated, error, created_at
            )
            SELECT id, message_id, {account_column}, model, latency_ms,
                   draft_generated, error, created_at
            FROM agent_runs"""
    )
    db.execute("DROP TABLE agent_runs")
    db.execute("ALTER TABLE agent_runs_v6 RENAME TO agent_runs")


MIGRATIONS: tuple[tuple[int, Migration], ...] = (
    (1, _v1_base),
    (2, _v2_attention_workflow),
    (3, _v3_provider_locations_and_accounts),
    (4, _v4_category_audit),
    (5, _v5_category_replacement),
    (6, _v6_simplify_run_audit),
)

SCHEMA_VERSION = MIGRATIONS[-1][0]


def migrate(db: sqlite3.Connection) -> None:
    """Apply each missing migration exactly once in ascending order."""
    db.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    applied = {row["version"] for row in db.execute("SELECT version FROM schema_migrations")}
    for version, migration in MIGRATIONS:
        if version in applied:
            continue
        migration(db)
        db.execute("INSERT INTO schema_migrations(version) VALUES(?)", (version,))
