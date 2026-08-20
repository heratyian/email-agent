from datetime import UTC, datetime
from uuid import uuid4

from email_agent.ai.models import DraftReply
from email_agent.db.records import StoredDraft, stored_draft
from email_agent.db.repositories.base import ConnectionContext


class DraftRepository:
    """Persist and retrieve reviewable draft suggestions."""

    def __init__(self, connect: ConnectionContext):
        self.connect = connect

    def list(self, account_id: str | None = None) -> list[StoredDraft]:
        query, parameters = "SELECT * FROM drafts WHERE status='generated'", ()
        if account_id:
            query, parameters = query + " AND account_id=?", (account_id,)
        with self.connect() as connection:
            rows = connection.execute(query + " ORDER BY created_at DESC", parameters).fetchall()
        return [stored_draft(row) for row in rows]

    def get(self, message_id: int) -> StoredDraft | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM drafts WHERE message_id=? ORDER BY created_at DESC LIMIT 1",
                (message_id,),
            ).fetchone()
        return stored_draft(row) if row else None

    def replace(
        self,
        message_id: int,
        account_id: str,
        source_message_id: str,
        reply: DraftReply,
    ) -> StoredDraft:
        draft_id = str(uuid4())
        created_at = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM drafts WHERE message_id=? AND status='generated'", (message_id,)
            )
            connection.execute(
                """INSERT INTO drafts(
                       id, message_id, account_id, source_message_id, recipient,
                       subject, body, status, metadata, created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    draft_id,
                    message_id,
                    account_id,
                    source_message_id,
                    reply.recipient,
                    reply.subject,
                    reply.body,
                    "generated",
                    reply.model_dump_json(),
                    created_at,
                ),
            )
        return StoredDraft(
            message_id=message_id,
            account_id=account_id,
            source_message_id=source_message_id,
            recipient=reply.recipient,
            subject=reply.subject,
            body=reply.body,
            status="generated",
        )

    def delete_generated(self, message_id: int) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM drafts WHERE message_id=? AND status='generated'", (message_id,)
            )
        return cursor.rowcount

    def exists(self, message_id: int) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM drafts WHERE message_id=? AND status!='rejected' LIMIT 1",
                (message_id,),
            ).fetchone()
        return bool(row)

    def mark_uploaded(self, message_id: int) -> bool:
        return self._change_status(message_id, "uploaded")

    def reject(self, message_id: int) -> bool:
        return self._change_status(message_id, "rejected")

    def _change_status(self, message_id: int, status: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE drafts SET status=? WHERE message_id=? AND status='generated'",
                (status, message_id),
            )
        return cursor.rowcount > 0
