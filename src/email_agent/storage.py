from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from email_agent.models import Draft, DraftReply, EmailClassification, EmailMessage


class Database:
    """Small SQLite repository for metadata, classifications, drafts, and run records."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY, account_id TEXT NOT NULL,
                    provider_message_id TEXT NOT NULL, thread_id TEXT,
                    from_address TEXT NOT NULL, from_name TEXT, subject TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    triaged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    processed_at TEXT,
                    attention_state TEXT NOT NULL DEFAULT 'open',
                    snoozed_until TEXT,
                    done_at TEXT,
                    UNIQUE(account_id, provider_message_id)
                );
                CREATE TABLE IF NOT EXISTS classifications (
                    id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL UNIQUE,
                    payload TEXT NOT NULL, FOREIGN KEY(message_id) REFERENCES messages(id)
                );
                CREATE TABLE IF NOT EXISTS drafts (
                    id TEXT PRIMARY KEY, message_id INTEGER NOT NULL, account_id TEXT NOT NULL,
                    source_message_id TEXT NOT NULL, recipient TEXT NOT NULL, subject TEXT NOT NULL,
                    body TEXT NOT NULL, status TEXT NOT NULL, metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL, FOREIGN KEY(message_id) REFERENCES messages(id)
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL, account_id TEXT NOT NULL,
                    agent_version INTEGER NOT NULL, prompt_version INTEGER NOT NULL,
                    model TEXT NOT NULL, latency_ms INTEGER NOT NULL, draft_generated INTEGER NOT NULL,
                    error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS category_syncs (
                    id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL,
                    destination TEXT NOT NULL, synced_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(message_id, destination),
                    FOREIGN KEY(message_id) REFERENCES messages(id)
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(messages)")}
            if "triaged_at" not in columns:
                db.execute("ALTER TABLE messages ADD COLUMN triaged_at TEXT")
                db.execute(
                    "UPDATE messages SET triaged_at=COALESCE(processed_at, CURRENT_TIMESTAMP)"
                )
            if "attention_state" not in columns:
                db.execute(
                    "ALTER TABLE messages ADD COLUMN attention_state TEXT NOT NULL DEFAULT 'open'"
                )
            if "snoozed_until" not in columns:
                db.execute("ALTER TABLE messages ADD COLUMN snoozed_until TEXT")
            if "done_at" not in columns:
                db.execute("ALTER TABLE messages ADD COLUMN done_at TEXT")
            run_columns = {row["name"] for row in db.execute("PRAGMA table_info(agent_runs)")}
            if "profile_id" in run_columns and "account_id" not in run_columns:
                db.execute("ALTER TABLE agent_runs RENAME COLUMN profile_id TO account_id")
            if "profile_version" in run_columns and "agent_version" not in run_columns:
                db.execute("ALTER TABLE agent_runs RENAME COLUMN profile_version TO agent_version")

    def is_processed(self, account_id: str, provider_id: str) -> bool:
        """Return whether full agent processing—not merely inbox triage—completed."""
        with self.connect() as db:
            row = db.execute(
                "SELECT 1 FROM messages WHERE account_id=? AND provider_message_id=? AND processed_at IS NOT NULL",
                (account_id, provider_id),
            ).fetchone()
        return bool(row)

    @staticmethod
    def _upsert_message(
        db,
        message: EmailMessage,
        *,
        processed: bool,
        attention_state: str | None = None,
    ) -> int:
        db.execute(
            """
            INSERT INTO messages(
                account_id, provider_message_id, thread_id, from_address, from_name,
                subject, received_at, triaged_at, processed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP,
                      CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END)
            ON CONFLICT(account_id, provider_message_id) DO UPDATE SET
                thread_id=excluded.thread_id,
                from_address=excluded.from_address,
                from_name=excluded.from_name,
                subject=excluded.subject,
                received_at=excluded.received_at,
                triaged_at=CURRENT_TIMESTAMP,
                processed_at=CASE
                    WHEN ? THEN CURRENT_TIMESTAMP
                    ELSE messages.processed_at
                END
            """,
            (
                message.account_id,
                message.provider_id,
                message.thread_id,
                message.from_address,
                message.from_name,
                message.subject,
                message.received_at.isoformat(),
                processed,
                processed,
            ),
        )
        if attention_state is not None:
            db.execute(
                """
                UPDATE messages
                SET attention_state=?,
                    done_at=CASE WHEN ?='done' THEN CURRENT_TIMESTAMP ELSE NULL END,
                    snoozed_until=NULL
                WHERE account_id=? AND provider_message_id=?
                """,
                (attention_state, attention_state, message.account_id, message.provider_id),
            )
        return db.execute(
            "SELECT id FROM messages WHERE account_id=? AND provider_message_id=?",
            (message.account_id, message.provider_id),
        ).fetchone()[0]

    @staticmethod
    def _save_classification(db, message_id: int, classification: EmailClassification) -> None:
        db.execute(
            "INSERT OR REPLACE INTO classifications(message_id,payload) VALUES(?,?)",
            (message_id, classification.model_dump_json()),
        )

    def save_triage(self, message: EmailMessage, classification: EmailClassification) -> int:
        """Assign a local ID and save classification without marking processing complete."""
        with self.connect() as db:
            message_id = self._upsert_message(
                db,
                message,
                processed=False,
                attention_state=self.recommended_attention(classification),
            )
            self._save_classification(db, message_id, classification)
        return message_id

    def get_triage(
        self, account_id: str, provider_id: str
    ) -> tuple[int, EmailClassification] | None:
        """Return an existing local ID and classification for a mailbox message."""
        with self.connect() as db:
            row = db.execute(
                """
                SELECT m.id, c.payload
                FROM messages AS m
                JOIN classifications AS c ON c.message_id=m.id
                WHERE m.account_id=? AND m.provider_message_id=?
                """,
                (account_id, provider_id),
            ).fetchone()
        if not row:
            return None
        return row["id"], EmailClassification.model_validate_json(row["payload"])

    def update_classification(self, message_id: int, classification: EmailClassification) -> bool:
        """Replace a stored classification without changing attention state."""
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE classifications SET payload=? WHERE message_id=?",
                (classification.model_dump_json(), message_id),
            )
        return cursor.rowcount > 0

    @staticmethod
    def recommended_attention(classification: EmailClassification) -> str:
        """Translate an agent recommendation into the simple user-facing workflow."""
        needs_attention = (
            classification.requires_reply
            or classification.requires_escalation
            or classification.priority in {"high", "urgent"}
        )
        return "open" if needs_attention else "done"

    def save_result(
        self,
        message: EmailMessage,
        classification: EmailClassification,
        draft_reply: DraftReply | None,
    ) -> tuple[int, Draft | None]:
        """Persist the completed processing result and optional review draft."""
        with self.connect() as db:
            existing = db.execute(
                "SELECT attention_state FROM messages WHERE account_id=? AND provider_message_id=?",
                (message.account_id, message.provider_id),
            ).fetchone()
            attention = None if existing else self.recommended_attention(classification)
            message_id = self._upsert_message(
                db, message, processed=True, attention_state=attention
            )
            self._save_classification(db, message_id, classification)
            draft = None
            if draft_reply:
                draft = Draft(
                    account_id=message.account_id,
                    source_message_id=message.provider_id,
                    to=[draft_reply.recipient],
                    subject=draft_reply.subject,
                    body=draft_reply.body,
                )
                db.execute(
                    "INSERT INTO drafts(id,message_id,account_id,source_message_id,recipient,subject,body,status,metadata,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(draft.id),
                        message_id,
                        draft.account_id,
                        draft.source_message_id,
                        draft_reply.recipient,
                        draft.subject,
                        draft.body,
                        draft.status,
                        draft_reply.model_dump_json(),
                        draft.created_at.isoformat(),
                    ),
                )
        return message_id, draft

    def record_run(
        self,
        message_id: int,
        account_id: str,
        agent,
        latency_ms: int,
        drafted: bool,
        error: str | None = None,
    ) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO agent_runs(message_id,account_id,agent_version,prompt_version,model,latency_ms,draft_generated,error) VALUES(?,?,?,?,?,?,?,?)",
                (
                    message_id,
                    account_id,
                    agent.version,
                    agent.version,
                    f"{agent.model.provider}:{agent.model.model}",
                    latency_ms,
                    drafted,
                    error,
                ),
            )

    def list_drafts(self, account_id: str | None = None) -> list[sqlite3.Row]:
        query, params = "SELECT * FROM drafts", ()
        if account_id:
            query, params = query + " WHERE account_id=?", (account_id,)
        with self.connect() as db:
            return db.execute(query + " ORDER BY created_at DESC", params).fetchall()

    def show_message(self, message_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT m.*, c.payload classification FROM messages m LEFT JOIN classifications c ON c.message_id=m.id WHERE m.id=?",
                (message_id,),
            ).fetchone()

    def attention_state(self, message_id: int) -> str | None:
        """Return the effective state, reopening an expired snooze when necessary."""
        with self.connect() as db:
            row = db.execute(
                "SELECT attention_state, snoozed_until FROM messages WHERE id=?", (message_id,)
            ).fetchone()
            if not row:
                return None
            if (
                row["attention_state"] == "snoozed"
                and row["snoozed_until"]
                and datetime.fromisoformat(row["snoozed_until"]) <= datetime.now(UTC)
            ):
                db.execute(
                    "UPDATE messages SET attention_state='open', snoozed_until=NULL WHERE id=?",
                    (message_id,),
                )
                return "open"
            return row["attention_state"]

    def set_attention(
        self, message_id: int, state: str, *, snoozed_until: datetime | None = None
    ) -> sqlite3.Row | None:
        """Set open, snoozed, or done state and return the affected message."""
        if state not in {"open", "snoozed", "done"}:
            raise ValueError(f"Unsupported attention state: {state}")
        with self.connect() as db:
            row = db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
            if not row:
                return None
            db.execute(
                """
                UPDATE messages
                SET attention_state=?, snoozed_until=?,
                    done_at=CASE WHEN ?='done' THEN CURRENT_TIMESTAMP ELSE NULL END
                WHERE id=?
                """,
                (
                    state,
                    snoozed_until.astimezone(UTC).isoformat() if snoozed_until else None,
                    state,
                    message_id,
                ),
            )
        return row

    def delete_generated_drafts(self, message_id: int) -> int:
        """Delete untouched model-generated drafts for one local message."""
        with self.connect() as db:
            cursor = db.execute(
                "DELETE FROM drafts WHERE message_id=? AND status='generated'", (message_id,)
            )
        return cursor.rowcount

    def has_draft(self, message_id: int) -> bool:
        """Return whether a non-rejected local draft exists for a message."""
        with self.connect() as db:
            row = db.execute(
                "SELECT 1 FROM drafts WHERE message_id=? AND status!='rejected' LIMIT 1",
                (message_id,),
            ).fetchone()
        return bool(row)

    def list_categorized_messages(self, account_id: str, limit: int = 100) -> list[sqlite3.Row]:
        """Return recent locally classified messages eligible for provider sync."""
        with self.connect() as db:
            return db.execute(
                """
                SELECT m.*, c.payload AS classification
                FROM messages AS m
                JOIN classifications AS c ON c.message_id=m.id
                WHERE m.account_id=?
                ORDER BY m.received_at DESC
                LIMIT ?
                """,
                (account_id, limit),
            ).fetchall()

    def category_was_synced(self, message_id: int, destination: str) -> bool:
        """Return whether this exact provider organization action already succeeded."""
        with self.connect() as db:
            row = db.execute(
                "SELECT 1 FROM category_syncs WHERE message_id=? AND destination=?",
                (message_id, destination),
            ).fetchone()
        return bool(row)

    def mark_category_synced(self, message_id: int, destination: str) -> None:
        """Record a successful category sync for idempotent future runs."""
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO category_syncs(message_id,destination) VALUES(?,?)",
                (message_id, destination),
            )

    def approve(self, message_id: int) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE drafts SET status='approved' WHERE message_id=? AND status!='sent'",
                (message_id,),
            )
        return cursor.rowcount > 0
