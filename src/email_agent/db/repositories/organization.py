from sqlite3 import Connection

from email_agent.db.records import OrganizationCandidate, organization_candidate
from email_agent.db.repositories.base import ConnectionContext
from email_agent.providers.base import CategorySyncResult, CategorySyncState


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
