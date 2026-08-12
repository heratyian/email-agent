from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from email_agent.db.migrations import migrate
from email_agent.models import Draft, DraftReply, EmailClassification, EmailMessage
from email_agent.providers.base import CategorySyncResult, CategorySyncState


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
            migrate(db)

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
    ) -> int:
        db.execute(
            """
            INSERT INTO messages(
                account_id, provider_message_id, provider_uid, provider_mailbox, thread_id,
                from_address, from_name, subject, received_at, triaged_at, processed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP,
                      CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END)
            ON CONFLICT(account_id, provider_message_id) DO UPDATE SET
                thread_id=excluded.thread_id,
                provider_uid=excluded.provider_uid,
                provider_mailbox=excluded.provider_mailbox,
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
                message.provider_id,
                message.mailbox,
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

    def update_classification(self, message_id: int, classification: EmailClassification) -> bool:
        """Replace a stored classification."""
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE classifications SET payload=? WHERE message_id=?",
                (classification.model_dump_json(), message_id),
            )
        return cursor.rowcount > 0

    def save_result(
        self,
        message: EmailMessage,
        classification: EmailClassification,
        draft_reply: DraftReply | None,
    ) -> tuple[int, Draft | None]:
        """Persist a pending result before any external mailbox changes."""
        with self.connect() as db:
            message_id = self._upsert_message(db, message, processed=False)
            self._save_classification(db, message_id, classification)
            draft = None
            if draft_reply:
                existing_draft = db.execute(
                    "SELECT 1 FROM drafts WHERE message_id=? LIMIT 1", (message_id,)
                ).fetchone()
                if not existing_draft:
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

    def complete_result(
        self,
        message_id: int,
        account_id: str,
        agent,
        latency_ms: int,
        drafted: bool,
        *,
        destination: str | None = None,
        sync_result: CategorySyncResult | None = None,
    ) -> None:
        """Atomically finalize local state after mailbox synchronization succeeds."""
        with self.connect() as db:
            if sync_result is not None and sync_result.source_moved:
                db.execute(
                    "UPDATE messages SET provider_uid=?, provider_mailbox=? WHERE id=?",
                    (sync_result.provider_id, sync_result.mailbox, message_id),
                )
            if destination is not None:
                self._mark_category_synced(db, message_id, destination, sync_result)
            db.execute(
                "UPDATE messages SET processed_at=CURRENT_TIMESTAMP WHERE id=?", (message_id,)
            )
            db.execute(
                "INSERT INTO agent_runs(message_id,account_id,model,latency_ms,draft_generated,error) VALUES(?,?,?,?,?,NULL)",
                (
                    message_id,
                    account_id,
                    f"{agent.model.provider}:{agent.model.model}",
                    latency_ms,
                    drafted,
                ),
            )

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
                "INSERT INTO agent_runs(message_id,account_id,model,latency_ms,draft_generated,error) VALUES(?,?,?,?,?,?)",
                (
                    message_id,
                    account_id,
                    f"{agent.model.provider}:{agent.model.model}",
                    latency_ms,
                    drafted,
                    error,
                ),
            )

    def list_drafts(self, account_id: str | None = None) -> list[sqlite3.Row]:
        query, params = "SELECT * FROM drafts WHERE status='generated'", ()
        if account_id:
            query, params = query + " AND account_id=?", (account_id,)
        with self.connect() as db:
            return db.execute(query + " ORDER BY created_at DESC", params).fetchall()

    def get_draft(self, message_id: int) -> sqlite3.Row | None:
        """Return the newest local draft for one message."""
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM drafts WHERE message_id=? ORDER BY created_at DESC LIMIT 1",
                (message_id,),
            ).fetchone()

    def show_message(self, message_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT m.*, c.payload classification FROM messages m LEFT JOIN classifications c ON c.message_id=m.id WHERE m.id=?",
                (message_id,),
            ).fetchone()

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
        """Return whether this is the message's current managed category."""
        with self.connect() as db:
            row = db.execute(
                "SELECT 1 FROM category_syncs WHERE message_id=? AND destination=? AND active=1",
                (message_id, destination),
            ).fetchone()
        return bool(row)

    def current_category_sync(self, message_id: int) -> CategorySyncState | None:
        """Return the most recently active managed category and provider location."""
        with self.connect() as db:
            row = db.execute(
                """SELECT destination, provider_uid AS provider_id,
                          provider_mailbox AS mailbox
                   FROM category_syncs WHERE message_id=? AND active=1
                   ORDER BY id DESC LIMIT 1""",
                (message_id,),
            ).fetchone()
        if not row:
            return None
        values = dict(row)
        values["destination"] = values["destination"].removeprefix("move:")
        return CategorySyncState(**values)

    def mark_category_synced(
        self,
        message_id: int,
        destination: str | None,
        result: CategorySyncResult | None = None,
    ) -> None:
        """Make ``destination`` the sole active managed category for a message."""
        with self.connect() as db:
            self._mark_category_synced(db, message_id, destination, result)

    @staticmethod
    def _mark_category_synced(
        db,
        message_id: int,
        destination: str | None,
        result: CategorySyncResult | None,
    ) -> None:
        db.execute("UPDATE category_syncs SET active=0 WHERE message_id=?", (message_id,))
        if destination is not None:
            db.execute(
                """INSERT INTO category_syncs(
                       message_id, destination, provider_uid, provider_mailbox, active
                   ) VALUES(?,?,?,?,1)
                   ON CONFLICT(message_id,destination) DO UPDATE SET
                       provider_uid=excluded.provider_uid,
                       provider_mailbox=excluded.provider_mailbox,
                       active=1,
                       synced_at=CURRENT_TIMESTAMP""",
                (
                    message_id,
                    destination,
                    result.provider_id if result else None,
                    result.mailbox if result else None,
                ),
            )

    def update_provider_location(self, message_id: int, provider_id: str, mailbox: str) -> None:
        """Store the UID and folder assigned by an IMAP move."""
        with self.connect() as db:
            db.execute(
                "UPDATE messages SET provider_uid=?, provider_mailbox=? WHERE id=?",
                (provider_id, mailbox, message_id),
            )

    def mark_draft_uploaded(self, message_id: int) -> bool:
        """Remove a successfully uploaded suggestion from the local review queue."""
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE drafts SET status='uploaded' WHERE message_id=? AND status='generated'",
                (message_id,),
            )
        return cursor.rowcount > 0

    def reject_draft(self, message_id: int) -> bool:
        """Remove a suggestion from review while retaining an audit record."""
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE drafts SET status='rejected' WHERE message_id=? AND status='generated'",
                (message_id,),
            )
        return cursor.rowcount > 0
