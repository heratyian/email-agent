import sqlite3

from email_agent.db import Database
from email_agent.db.migrations import SCHEMA_VERSION


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def test_fresh_database_records_every_schema_migration(tmp_path):
    database = Database(tmp_path / "fresh.db")

    with database.connect() as db:
        versions = [row["version"] for row in db.execute("SELECT version FROM schema_migrations")]

    assert versions == list(range(1, SCHEMA_VERSION + 1))


def test_original_database_is_upgraded_without_losing_message_or_run(tmp_path):
    path = tmp_path / "legacy.db"
    with connect(path) as db:
        db.executescript(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY, account_id TEXT NOT NULL,
                provider_message_id TEXT NOT NULL, thread_id TEXT,
                from_address TEXT NOT NULL, from_name TEXT, subject TEXT NOT NULL,
                received_at TEXT NOT NULL, processed_at TEXT,
                UNIQUE(account_id, provider_message_id)
            );
            CREATE TABLE classifications (
                id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL UNIQUE, payload TEXT NOT NULL
            );
            CREATE TABLE drafts (
                id TEXT PRIMARY KEY, message_id INTEGER NOT NULL, account_id TEXT NOT NULL,
                source_message_id TEXT NOT NULL, recipient TEXT NOT NULL, subject TEXT NOT NULL,
                body TEXT NOT NULL, status TEXT NOT NULL, metadata TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE agent_runs (
                id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL, profile_id TEXT NOT NULL,
                profile_version INTEGER NOT NULL, prompt_version INTEGER NOT NULL,
                model TEXT NOT NULL, latency_ms INTEGER NOT NULL,
                draft_generated INTEGER NOT NULL, error TEXT, created_at TEXT
            );
            INSERT INTO messages VALUES(
                7, 'person@example.com', 'provider-7', NULL, 'sender@example.com', NULL,
                'Legacy', '2026-01-01T00:00:00+00:00', '2026-01-01T00:01:00+00:00'
            );
            INSERT INTO agent_runs VALUES(
                3, 7, 'person@example.com', 1, 1, 'openai:test', 25, 0, NULL,
                '2026-01-01T00:01:00+00:00'
            );
            """
        )

    database = Database(path)

    with database.connect() as db:
        message = db.execute("SELECT * FROM messages WHERE id=7").fetchone()
        run = db.execute("SELECT * FROM agent_runs WHERE id=3").fetchone()
        versions = [row["version"] for row in db.execute("SELECT version FROM schema_migrations")]

    assert message["provider_uid"] == "provider-7"
    assert message["provider_mailbox"] == "INBOX"
    assert message["triaged_at"] == message["processed_at"]
    assert message["classified_at"] == message["processed_at"]
    assert run["account_id"] == "person@example.com"
    assert run["model"] == "openai:test"
    assert "agent_version" not in run
    assert versions == list(range(1, SCHEMA_VERSION + 1))


def test_unversioned_current_database_preserves_category_copy_location(tmp_path):
    path = tmp_path / "current.db"
    with connect(path) as db:
        db.executescript(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY, account_id TEXT NOT NULL,
                provider_message_id TEXT NOT NULL, provider_uid TEXT,
                provider_mailbox TEXT NOT NULL DEFAULT 'INBOX', thread_id TEXT,
                from_address TEXT NOT NULL, from_name TEXT, subject TEXT NOT NULL,
                received_at TEXT NOT NULL, triaged_at TEXT, processed_at TEXT,
                attention_state TEXT NOT NULL DEFAULT 'open', snoozed_until TEXT, done_at TEXT,
                UNIQUE(account_id, provider_message_id)
            );
            CREATE TABLE classifications (
                id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL UNIQUE, payload TEXT NOT NULL
            );
            CREATE TABLE drafts (
                id TEXT PRIMARY KEY, message_id INTEGER NOT NULL, account_id TEXT NOT NULL,
                source_message_id TEXT NOT NULL, recipient TEXT NOT NULL, subject TEXT NOT NULL,
                body TEXT NOT NULL, status TEXT NOT NULL, metadata TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE agent_runs (
                id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL, account_id TEXT NOT NULL,
                agent_version INTEGER NOT NULL, prompt_version INTEGER NOT NULL,
                model TEXT NOT NULL, latency_ms INTEGER NOT NULL,
                draft_generated INTEGER NOT NULL, error TEXT, created_at TEXT
            );
            CREATE TABLE category_syncs (
                id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL,
                destination TEXT NOT NULL, provider_uid TEXT, provider_mailbox TEXT,
                active INTEGER NOT NULL DEFAULT 1, synced_at TEXT,
                UNIQUE(message_id, destination)
            );
            INSERT INTO messages VALUES(
                1, 'person@example.com', 'stable', '42', 'INBOX', NULL,
                'sender@example.com', NULL, 'Current', '2026-01-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00', NULL, 'open', NULL, NULL
            );
            INSERT INTO category_syncs VALUES(2, 1, 'travel', '99', 'travel', 1, NULL);
            """
        )

    database = Database(path)

    assert database.current_category_sync(1).destination == "travel"
    assert database.current_category_sync(1).provider_id == "99"
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM category_syncs").fetchone()[0] == 1
