from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from email_agent.db.migrations import migrate
from email_agent.db.records import (
    OrganizationCandidate,
    StoredDraft,
    StoredMessage,
)
from email_agent.db.repositories import (
    DraftRepository,
    MessageRepository,
    OrganizationRepository,
    ProcessingRunRepository,
    mark_category_synced,
)
from email_agent.models import Draft, DraftReply, EmailClassification, EmailMessage
from email_agent.providers.base import CategorySyncResult, CategorySyncState


class Database:
    """Small SQLite repository for metadata, classifications, drafts, and run records."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()
        self.drafts = DraftRepository(self.connect)
        self.messages = MessageRepository(self.connect)
        self.organization = OrganizationRepository(self.connect)
        self.processing_runs = ProcessingRunRepository(self.connect)

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

    def classification_completed(self, account_id: str, provider_id: str) -> bool:
        """Return whether classification and mailbox synchronization completed."""
        with self.connect() as db:
            row = db.execute(
                "SELECT 1 FROM messages WHERE account_id=? AND provider_message_id=? "
                "AND classified_at IS NOT NULL",
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
            db.execute("UPDATE messages SET classified_at=NULL WHERE id=?", (message_id,))
        return message_id

    def save_message(self, message: EmailMessage) -> int:
        """Assign a stable local ID without classifying or processing a message."""
        with self.connect() as db:
            return self._upsert_message(db, message, processed=False)

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
        """Save a classification for an existing local message."""
        with self.connect() as db:
            message_exists = db.execute(
                "SELECT 1 FROM messages WHERE id=?", (message_id,)
            ).fetchone()
            if not message_exists:
                return False
            cursor = db.execute(
                """INSERT INTO classifications(message_id, payload) VALUES(?, ?)
                   ON CONFLICT(message_id) DO UPDATE SET payload=excluded.payload""",
                (message_id, classification.model_dump_json()),
            )
            if cursor.rowcount:
                db.execute("UPDATE messages SET classified_at=NULL WHERE id=?", (message_id,))
        return cursor.rowcount > 0

    def complete_classification(
        self,
        message_id: int,
        destination: str | None,
        synchronization: CategorySyncResult | None,
    ) -> None:
        """Finalize classification only after mailbox category synchronization succeeds."""
        with self.connect() as db:
            if synchronization is not None and synchronization.source_moved:
                db.execute(
                    "UPDATE messages SET provider_uid=?, provider_mailbox=? WHERE id=?",
                    (synchronization.provider_id, synchronization.mailbox, message_id),
                )
            self._mark_category_synced(db, message_id, destination, synchronization)
            db.execute(
                "UPDATE messages SET classified_at=CURRENT_TIMESTAMP WHERE id=?", (message_id,)
            )

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
        self.processing_runs.record(
            message_id, account_id, agent, latency_ms, drafted, error
        )

    def list_drafts(self, account_id: str | None = None) -> list[StoredDraft]:
        return self.drafts.list(account_id)

    def get_draft(self, message_id: int) -> StoredDraft | None:
        """Return the newest local draft for one message."""
        return self.drafts.get(message_id)

    def replace_generated_draft(
        self,
        message_id: int,
        account_id: str,
        source_message_id: str,
        reply: DraftReply,
    ) -> Draft:
        """Replace the local review suggestion without touching uploaded drafts."""
        return self.drafts.replace(message_id, account_id, source_message_id, reply)

    def show_message(self, message_id: int) -> StoredMessage | None:
        return self.messages.get(message_id)

    def delete_generated_drafts(self, message_id: int) -> int:
        """Delete untouched model-generated drafts for one local message."""
        return self.drafts.delete_generated(message_id)

    def has_draft(self, message_id: int) -> bool:
        """Return whether a non-rejected local draft exists for a message."""
        return self.drafts.exists(message_id)

    def list_categorized_messages(
        self, account_id: str, limit: int = 100
    ) -> list[OrganizationCandidate]:
        """Return recent locally classified messages eligible for provider sync."""
        return self.organization.list_candidates(account_id, limit)

    def category_was_synced(self, message_id: int, destination: str) -> bool:
        """Return whether this is the message's current managed category."""
        return self.organization.was_synced(message_id, destination)

    def current_category_sync(self, message_id: int) -> CategorySyncState | None:
        """Return the most recently active managed category and provider location."""
        return self.organization.current(message_id)

    def mark_category_synced(
        self,
        message_id: int,
        destination: str | None,
        result: CategorySyncResult | None = None,
    ) -> None:
        """Make ``destination`` the sole active managed category for a message."""
        self.organization.mark(message_id, destination, result)

    @staticmethod
    def _mark_category_synced(
        db,
        message_id: int,
        destination: str | None,
        result: CategorySyncResult | None,
    ) -> None:
        mark_category_synced(db, message_id, destination, result)

    def update_provider_location(self, message_id: int, provider_id: str, mailbox: str) -> None:
        """Store the UID and folder assigned by an IMAP move."""
        self.messages.update_provider_location(message_id, provider_id, mailbox)

    def mark_draft_uploaded(self, message_id: int) -> bool:
        """Remove a successfully uploaded suggestion from the local review queue."""
        return self.drafts.mark_uploaded(message_id)

    def reject_draft(self, message_id: int) -> bool:
        """Remove a suggestion from review while retaining an audit record."""
        return self.drafts.reject(message_id)
