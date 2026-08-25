from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from peewee import (
    AutoField,
    BooleanField,
    DateTimeField,
    FloatField,
    ForeignKeyField,
    Model,
    TextField,
)

from email_agent.ai.models import DraftReply, EmailClassification
from email_agent.db.connection import database
from email_agent.providers.base import CategorySyncResult, CategorySyncState
from email_agent.providers.models import EmailMessage


def utc_now() -> datetime:
    return datetime.now(UTC)


class BaseModel(Model):
    class Meta:
        database = database
        legacy_table_names = False


class Message(BaseModel):
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
        return cls.get_or_none(
            (cls.account_id == account_id)
            & (cls.provider_message_id == provider_message_id)
        )

    @classmethod
    def organization_candidates(cls, account_id: str, limit: int) -> list[Message]:
        return list(
            cls.select()
            .join(Classification)
            .where(cls.account_id == account_id)
            .order_by(cls.received_at.desc())
            .limit(limit)
        )

    def classification_value(self) -> EmailClassification | None:
        classification = Classification.get_or_none(Classification.message == self)
        return classification.to_ai() if classification else None

    def current_category_sync(self) -> CategorySyncState | None:
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


class Classification(BaseModel):
    id = AutoField()
    message = ForeignKeyField(Message, backref="classification", unique=True)
    category = TextField(null=True)
    requires_reply = BooleanField()
    priority = TextField()
    intent = TextField(null=True)
    summary = TextField()
    confidence = FloatField()
    requires_escalation = BooleanField(default=False)
    escalation_reason = TextField(null=True)

    class Meta:
        table_name = "classifications"

    @classmethod
    def save_for(cls, message: Message | int, value: EmailClassification) -> Classification:
        fields = value.model_dump()
        classification, created = cls.get_or_create(message=message, defaults=fields)
        if not created:
            cls.update(**fields).where(cls.id == classification.id).execute()
            classification = cls.get_by_id(classification.id)
        Message.update(classified_at=None).where(Message.id == classification.message_id).execute()
        return classification

    def to_ai(self) -> EmailClassification:
        return EmailClassification(
            category=self.category,
            requires_reply=self.requires_reply,
            priority=self.priority,
            intent=self.intent,
            summary=self.summary,
            confidence=self.confidence,
            requires_escalation=self.requires_escalation,
            escalation_reason=self.escalation_reason,
        )


class Draft(BaseModel):
    id = TextField(primary_key=True)
    message = ForeignKeyField(Message, backref="drafts")
    recipient = TextField()
    subject = TextField()
    body = TextField()
    status = TextField()
    reasoning_summary = TextField()
    confidence = FloatField()
    requires_escalation = BooleanField(default=False)
    escalation_reason = TextField(null=True)
    created_at = DateTimeField(default=utc_now)

    class Meta:
        table_name = "drafts"

    @classmethod
    def pending(cls, account_id: str | None = None):
        query = cls.select().where(cls.status == "generated")
        if account_id:
            query = query.join(Message).where(Message.account_id == account_id)
        return query.order_by(cls.created_at.desc())

    @classmethod
    def replace_generated(cls, message: Message, reply: DraftReply) -> Draft:
        with database.atomic():
            cls.delete().where(
                (cls.message == message) & (cls.status == "generated")
            ).execute()
            return cls.create(
                id=str(uuid4()),
                message=message,
                recipient=reply.recipient,
                subject=reply.subject,
                body=reply.body,
                reasoning_summary=reply.reasoning_summary,
                confidence=reply.confidence,
                requires_escalation=reply.requires_escalation,
                escalation_reason=reply.escalation_reason,
                status="generated",
            )

    @classmethod
    def latest_for_message(cls, message_id: int) -> Draft | None:
        return (
            cls.select()
            .where(cls.message == message_id)
            .order_by(cls.created_at.desc())
            .first()
        )

    @classmethod
    def has_reviewable(cls, message_id: int) -> bool:
        return cls.select().where(
            (cls.message == message_id) & (cls.status != "rejected")
        ).exists()

    @classmethod
    def change_generated_status(cls, message_id: int, status: str) -> bool:
        changed = cls.update(status=status).where(
            (cls.message == message_id) & (cls.status == "generated")
        ).execute()
        return changed > 0


class CategorySync(BaseModel):
    id = AutoField()
    message = ForeignKeyField(Message, backref="category_syncs")
    destination = TextField()
    synced_at = DateTimeField(default=utc_now)
    provider_uid = TextField(null=True)
    provider_mailbox = TextField(null=True)
    active = BooleanField(default=True)

    class Meta:
        table_name = "category_syncs"
        indexes = (
            (("message", "destination"), True),
        )

    @classmethod
    def is_active(cls, message_id: int, destination: str) -> bool:
        return cls.select().where(
            (cls.message == message_id)
            & (cls.destination == destination)
            & cls.active
        ).exists()

    @classmethod
    def replace_active(
        cls,
        message_id: int,
        destination: str | None,
        result: CategorySyncResult | None = None,
    ) -> None:
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


MODELS = (Message, Classification, Draft, CategorySync)
