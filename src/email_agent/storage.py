from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from email_agent.models import Draft, DraftReply, EmailClassification, EmailMessage


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self):
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY, account_id TEXT NOT NULL,
                    provider_message_id TEXT NOT NULL, thread_id TEXT,
                    from_address TEXT NOT NULL, from_name TEXT, subject TEXT NOT NULL,
                    received_at TEXT NOT NULL, processed_at TEXT DEFAULT CURRENT_TIMESTAMP,
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

    def is_processed(self, account_id: str, provider_id: str) -> bool:
        with self.connect() as db:
            row = db.execute(
                "SELECT 1 FROM messages WHERE account_id=? AND provider_message_id=?",
                (account_id, provider_id),
            ).fetchone()
        return bool(row)

    def save_result(
        self,
        message: EmailMessage,
        classification: EmailClassification,
        draft_reply: DraftReply | None,
    ) -> tuple[int, Draft | None]:
        with self.connect() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO messages(account_id,provider_message_id,thread_id,from_address,from_name,subject,received_at) VALUES(?,?,?,?,?,?,?)",
                (
                    message.account_id,
                    message.provider_id,
                    message.thread_id,
                    message.from_address,
                    message.from_name,
                    message.subject,
                    message.received_at.isoformat(),
                ),
            )
            message_id = (
                cursor.lastrowid
                or db.execute(
                    "SELECT id FROM messages WHERE account_id=? AND provider_message_id=?",
                    (message.account_id, message.provider_id),
                ).fetchone()[0]
            )
            db.execute(
                "INSERT OR REPLACE INTO classifications(message_id,payload) VALUES(?,?)",
                (message_id, classification.model_dump_json()),
            )
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
                    "INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?,?,?)",
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

    def record_run(self, message_id: int, profile, latency_ms: int, drafted: bool, error=None):
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

    def list_drafts(self, account_id: str | None = None):
        query, params = "SELECT * FROM drafts", ()
        if account_id:
            query, params = query + " WHERE account_id=?", (account_id,)
        with self.connect() as db:
            return db.execute(query + " ORDER BY created_at DESC", params).fetchall()

    def show_message(self, message_id: int):
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
