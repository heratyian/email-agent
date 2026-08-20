from email_agent.db.records import StoredMessage, stored_message
from email_agent.db.repositories.base import ConnectionContext


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
