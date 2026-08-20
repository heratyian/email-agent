from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from sqlite3 import Connection

from email_agent.config import AgentConfig
from email_agent.db.records import (
    OrganizationCandidate,
    StoredDraft,
    StoredMessage,
    organization_candidate,
    stored_draft,
    stored_message,
)
from email_agent.models import Draft, DraftReply
from email_agent.providers.base import CategorySyncResult, CategorySyncState

ConnectionContext = Callable[[], AbstractContextManager[Connection]]


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
    ) -> Draft:
        draft = Draft(
            account_id=account_id,
            source_message_id=source_message_id,
            to=[reply.recipient],
            subject=reply.subject,
            body=reply.body,
        )
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
                    str(draft.id),
                    message_id,
                    account_id,
                    source_message_id,
                    reply.recipient,
                    reply.subject,
                    reply.body,
                    draft.status,
                    reply.model_dump_json(),
                    draft.created_at.isoformat(),
                ),
            )
        return draft

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


class OrganizationRepository:
    """Persist provider-managed category locations."""

    def __init__(self, connect: ConnectionContext):
        self.connect = connect

    def list_candidates(self, account_id: str, limit: int) -> list[OrganizationCandidate]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT m.*, c.payload AS classification
                   FROM messages AS m
                   JOIN classifications AS c ON c.message_id=m.id
                   WHERE m.account_id=?
                   ORDER BY m.received_at DESC
                   LIMIT ?""",
                (account_id, limit),
            ).fetchall()
        return [organization_candidate(row) for row in rows]

    def was_synced(self, message_id: int, destination: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM category_syncs WHERE message_id=? AND destination=? AND active=1",
                (message_id, destination),
            ).fetchone()
        return bool(row)

    def current(self, message_id: int) -> CategorySyncState | None:
        with self.connect() as connection:
            row = connection.execute(
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

    def mark(
        self,
        message_id: int,
        destination: str | None,
        result: CategorySyncResult | None = None,
    ) -> None:
        with self.connect() as connection:
            mark_category_synced(connection, message_id, destination, result)


def mark_category_synced(
    connection: Connection,
    message_id: int,
    destination: str | None,
    result: CategorySyncResult | None,
) -> None:
    connection.execute("UPDATE category_syncs SET active=0 WHERE message_id=?", (message_id,))
    if destination is not None:
        connection.execute(
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


class MessageRepository:
    """Retrieve stored message metadata and update provider locations."""

    def __init__(self, connect: ConnectionContext):
        self.connect = connect

    def get(self, message_id: int) -> StoredMessage | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT m.*, c.payload classification
                   FROM messages AS m
                   LEFT JOIN classifications AS c ON c.message_id=m.id
                   WHERE m.id=?""",
                (message_id,),
            ).fetchone()
        return stored_message(row) if row else None

    def update_provider_location(self, message_id: int, provider_id: str, mailbox: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE messages SET provider_uid=?, provider_mailbox=? WHERE id=?",
                (provider_id, mailbox, message_id),
            )


class ProcessingRunRepository:
    """Record model runs for processing diagnostics and audit history."""

    def __init__(self, connect: ConnectionContext):
        self.connect = connect

    def record(
        self,
        message_id: int,
        account_id: str,
        agent: AgentConfig,
        latency_ms: int,
        drafted: bool,
        error: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO agent_runs(
                       message_id,account_id,model,latency_ms,draft_generated,error
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    message_id,
                    account_id,
                    f"{agent.model.provider}:{agent.model.model}",
                    latency_ms,
                    drafted,
                    error,
                ),
            )
