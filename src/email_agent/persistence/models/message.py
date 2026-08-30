from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from peewee import JOIN, AutoField, DateTimeField, TextField, fn

from email_agent.persistence.models.base import BaseModel
from email_agent.providers.base import CategorySyncState
from email_agent.providers.models import EmailMessage
from email_agent.triage.models import TriageOutput

if TYPE_CHECKING:
    from email_agent.persistence.models.triage import Triage


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
        indexes = (
            (("account_id", "provider_message_id"), True),
            (("account_id", "received_at"), False),
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
            .order_by(cls.received_at.desc(), cls.id.asc())
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
            .order_by(cls.received_at.desc(), cls.id.asc())
            .limit(limit)
        )

    @classmethod
    def search_triaged(
        cls,
        account_id: str,
        *,
        sender: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        requires_reply: bool | None = None,
        requires_escalation: bool | None = None,
        received_after: datetime | None = None,
        candidate_message_ids: Sequence[int] | None = None,
        limit: int | None = None,
    ) -> list[tuple[Message, Triage]]:
        """Filter vector-search candidates by exact persisted fields."""
        from email_agent.persistence.models.triage import Triage

        conditions = [cls.account_id == account_id]
        if sender:
            normalized_sender = sender.casefold()
            conditions.append(
                fn.LOWER(cls.from_name).contains(normalized_sender)
                | fn.LOWER(cls.from_address).contains(normalized_sender)
            )
        if category:
            conditions.append(Triage.category == category)
        if priority:
            conditions.append(Triage.priority == priority)
        if requires_reply is not None:
            conditions.append(Triage.requires_reply == requires_reply)
        if requires_escalation is not None:
            conditions.append(Triage.requires_escalation == requires_escalation)
        if received_after is not None:
            conditions.append(cls.received_at >= received_after)
        if candidate_message_ids is not None:
            conditions.append(cls.id.in_(candidate_message_ids))

        rows = (
            Triage.select(Triage, cls)
            .join(cls, JOIN.INNER)
            .where(*conditions)
            .order_by(cls.received_at.desc(), cls.id.asc())
        )
        if limit is not None:
            query = query.limit(limit)
        return [(triage.message, triage) for triage in rows]

    @classmethod
    def pending_category_syncs(cls, account_id: str, limit: int = 500) -> list[Message]:
        """Return triaged messages awaiting provider category synchronization."""
        from email_agent.persistence.models.triage import Triage

        return list(
            cls.select()
            .join(Triage)
            .where((cls.account_id == account_id) & Triage.category_sync_pending)
            .order_by(cls.received_at.desc(), cls.id.asc())
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
