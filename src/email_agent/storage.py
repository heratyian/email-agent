from __future__ import annotations

import sqlite3
from contextlib import contextmanager
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
                    id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL, profile_id TEXT NOT NULL,
                    profile_version INTEGER NOT NULL, prompt_version INTEGER NOT NULL,
                    model TEXT NOT NULL, latency_ms INTEGER NOT NULL, draft_generated INTEGER NOT NULL,
                    error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(messages)")}
            if "triaged_at" not in columns:
                db.execute("ALTER TABLE messages ADD COLUMN triaged_at TEXT")
                db.execute(
                    "UPDATE messages SET triaged_at=COALESCE(processed_at, CURRENT_TIMESTAMP)"
                )

    def is_processed(self, account_id: str, provider_id: str) -> bool:
        """Return whether full agent processing—not merely inbox triage—completed."""
        with self.connect() as db:
            row = db.execute(
                "SELECT 1 FROM messages WHERE account_id=? AND provider_message_id=? AND processed_at IS NOT NULL",
                (account_id, provider_id),
            ).fetchone()
        return bool(row)

    @staticmethod
    def _upsert_message(db, message: EmailMessage, *, processed: bool) -> int:
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
            message_id = self._upsert_message(db, message, processed=False)
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

    def save_result(
        self,
        message: EmailMessage,
        classification: EmailClassification,
        draft_reply: DraftReply | None,
    ) -> tuple[int, Draft | None]:
        """Persist the completed processing result and optional review draft."""
        with self.connect() as db:
            message_id = self._upsert_message(db, message, processed=True)
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
        self, message_id: int, profile, latency_ms: int, drafted: bool, error: str | None = None
    ) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO agent_runs(message_id,profile_id,profile_version,prompt_version,model,latency_ms,draft_generated,error) VALUES(?,?,?,?,?,?,?,?)",
                (
                    message_id,
                    profile.id,
                    profile.version,
                    profile.prompts.version,
                    f"{profile.model.provider}:{profile.model.model}",
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

    def approve(self, message_id: int) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE drafts SET status='approved' WHERE message_id=? AND status!='sent'",
                (message_id,),
            )
        return cursor.rowcount > 0
