from __future__ import annotations

from peewee import AutoField, DateTimeField, TextField

from email_agent.ai.models import EmailClassification
from email_agent.db.models.base import BaseModel
from email_agent.providers.base import CategorySyncState
from email_agent.providers.models import EmailMessage


class Message(BaseModel):
    """Persist provider identifiers and metadata for one mailbox message."""

    id = AutoField()
    account_id = TextField()
    provider_message_id = TextField()
    thread_id = TextField(null=True)
    from_address = TextField()
    from_name = TextField(null=True)
    subject = TextField()
    received_at = DateTimeField()
    provider_mailbox = TextField(default="INBOX")
    provider_uid = TextField()
    classified_at = DateTimeField(null=True)

    class Meta:
        table_name = "messages"
        indexes = (
            (("account_id", "provider_message_id"), True),
        )

    @classmethod
    def upsert_email(cls, email: EmailMessage) -> Message:
        """Insert or refresh local metadata for a provider message."""
        message, _ = cls.get_or_create(
            account_id=email.account_id,
            provider_message_id=email.provider_id,
            defaults={
                "provider_uid": email.provider_id,
                "provider_mailbox": email.mailbox,
                "thread_id": email.thread_id,
                "from_address": email.from_address,
                "from_name": email.from_name,
                "subject": email.subject,
                "received_at": email.received_at,
            },
        )
        message.provider_uid = email.provider_id
        message.provider_mailbox = email.mailbox
        message.thread_id = email.thread_id
        message.from_address = email.from_address
        message.from_name = email.from_name
        message.subject = email.subject
        message.received_at = email.received_at
        message.save()
        return message

    @classmethod
    def find_email(cls, account_id: str, provider_message_id: str) -> Message | None:
        """Find a local message by its stable provider identity."""
        return cls.get_or_none(
            (cls.account_id == account_id)
            & (cls.provider_message_id == provider_message_id)
        )

    @classmethod
    def organization_candidates(cls, account_id: str, limit: int) -> list[Message]:
        """Return recent classified messages eligible for category synchronization."""
        from email_agent.db.models.classification import Classification

        return list(
            cls.select()
            .join(Classification)
            .where(cls.account_id == account_id)
            .order_by(cls.received_at.desc())
            .limit(limit)
        )

    def classification_value(self) -> EmailClassification | None:
        """Return this message's classification as the AI-facing value object."""
        from email_agent.db.models.classification import Classification

        classification = Classification.get_or_none(Classification.message == self)
        return classification.to_ai() if classification else None

    def current_category_sync(self) -> CategorySyncState | None:
        """Return the active provider category state for this message."""
        from email_agent.db.models.category_sync import CategorySync

        sync = (
            CategorySync.select()
            .where((CategorySync.message == self) & CategorySync.active)
            .order_by(CategorySync.id.desc())
            .first()
        )
        if sync is None:
            return None
        return CategorySyncState(
            destination=sync.destination.removeprefix("move:"),
            provider_id=sync.provider_uid,
            mailbox=sync.provider_mailbox,
        )
