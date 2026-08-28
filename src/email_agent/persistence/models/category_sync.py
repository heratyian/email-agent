from __future__ import annotations

from peewee import AutoField, BooleanField, DateTimeField, ForeignKeyField, TextField

from email_agent.persistence.models.base import BaseModel, utc_now
from email_agent.persistence.models.message import Message
from email_agent.providers.base import CategorySyncResult


class CategorySync(BaseModel):
    """Record the active provider-managed category for a message."""

    id = AutoField()
    message = ForeignKeyField(Message, backref="category_syncs")
    destination = TextField()
    synced_at = DateTimeField(default=utc_now)
    provider_uid = TextField(null=True)
    provider_mailbox = TextField(null=True)
    active = BooleanField(default=True)

    class Meta:
        table_name = "category_syncs"
        indexes = ((("message", "destination"), True),)

    @classmethod
    def is_active(cls, message_id: int, destination: str) -> bool:
        """Return whether a destination is the message's active managed category."""
        return (
            cls.select()
            .where((cls.message == message_id) & (cls.destination == destination) & cls.active)
            .exists()
        )

    @classmethod
    def replace_active(
        cls,
        message_id: int,
        destination: str | None,
        result: CategorySyncResult | None = None,
    ) -> None:
        """Make one destination the sole active category for a message."""
        cls.update(active=False).where(cls.message == message_id).execute()
        if destination is None:
            return
        values = {
            "provider_uid": result.provider_id if result else None,
            "provider_mailbox": result.mailbox if result else None,
            "active": True,
            "synced_at": utc_now(),
        }
        sync, created = cls.get_or_create(
            message=message_id,
            destination=destination,
            defaults=values,
        )
        if not created:
            cls.update(**values).where(cls.id == sync.id).execute()
