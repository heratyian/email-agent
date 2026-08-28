from __future__ import annotations

from peewee import JOIN, AutoField, DateTimeField, TextField

from email_agent.persistence.models.base import BaseModel
from email_agent.providers.base import CategorySyncState
from email_agent.providers.models import EmailMessage
from email_agent.triage.models import TriageOutput


class Message(BaseModel):
    """Persist provider identifiers and metadata for one mailbox message."""

    id = AutoField()
    account_id = TextField()
    provider_message_id = TextField()
    thread_id = TextField(null=True)
    from_address = TextField()
    from_name = TextField(null=True)
    subject = TextField()
    text_body = TextField(null=True)
    received_at = DateTimeField()
    provider_mailbox = TextField(default="INBOX")
    provider_uid = TextField()

    class Meta:
        table_name = "messages"
        indexes = ((("account_id", "provider_message_id"), True),)

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
                "text_body": email.text_body,
                "received_at": email.received_at,
            },
        )
        message.provider_uid = email.provider_id
        message.provider_mailbox = email.mailbox
        message.thread_id = email.thread_id
        message.from_address = email.from_address
        message.from_name = email.from_name
        message.subject = email.subject
        message.text_body = email.text_body
        message.received_at = email.received_at
        message.save()
        return message

    @classmethod
    def find_email(cls, account_id: str, provider_message_id: str) -> Message | None:
        """Find a local message by its stable provider identity."""
        return cls.get_or_none(
            (cls.account_id == account_id) & (cls.provider_message_id == provider_message_id)
        )

    @classmethod
    def untriaged(cls, account_id: str) -> list[Message]:
        """Return stored messages that do not have a triage row."""
        from email_agent.persistence.models.triage import Triage

        return list(
            cls.select()
            .join(Triage, join_type=JOIN.LEFT_OUTER)
            .where((cls.account_id == account_id) & Triage.id.is_null())
            .order_by(cls.received_at.desc())
        )

    def to_email(self) -> EmailMessage:
        """Convert stored message content to the provider-neutral value object."""
        return EmailMessage(
            provider_id=self.provider_message_id,
            thread_id=self.thread_id,
            account_id=self.account_id,
            mailbox=self.provider_mailbox,
            from_address=self.from_address,
            from_name=self.from_name,
            subject=self.subject,
            text_body=self.text_body,
            received_at=self.received_at,
        )

    @classmethod
    def organization_candidates(cls, account_id: str, limit: int) -> list[Message]:
        """Return recent triaged messages eligible for category synchronization."""
        from email_agent.persistence.models.triage import Triage

        return list(
            cls.select()
            .join(Triage)
            .where(cls.account_id == account_id)
            .order_by(cls.received_at.desc())
            .limit(limit)
        )

    @classmethod
    def pending_category_syncs(cls, account_id: str, limit: int = 500) -> list[Message]:
        """Return triaged messages awaiting provider category synchronization."""
        from email_agent.persistence.models.triage import Triage

        return list(
            cls.select()
            .join(Triage)
            .where((cls.account_id == account_id) & Triage.category_sync_pending)
            .order_by(cls.received_at.desc())
            .limit(limit)
        )

    def triage_value(self) -> TriageOutput | None:
        """Return this message's triage as the AI-facing value object."""
        from email_agent.persistence.models.triage import Triage

        triage = Triage.get_or_none(Triage.message == self)
        return triage.to_ai() if triage else None

    def current_category_sync(self) -> CategorySyncState | None:
        """Return the active provider category state for this message."""
        from email_agent.persistence.models.category_sync import CategorySync

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
