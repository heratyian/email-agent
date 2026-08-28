from __future__ import annotations

from uuid import uuid4

from peewee import BooleanField, DateTimeField, FloatField, ForeignKeyField, TextField

from email_agent.drafting.models import DraftOutput
from email_agent.persistence.connection import database
from email_agent.persistence.models.base import BaseModel, utc_now
from email_agent.persistence.models.message import Message


class Draft(BaseModel):
    """Persist one locally generated reply suggestion and its review status."""

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
        """Return generated drafts, optionally limited to one mailbox account."""
        query = cls.select().where(cls.status == "generated")
        if account_id:
            query = query.join(Message).where(Message.account_id == account_id)
        return query.order_by(cls.created_at.desc())

    @classmethod
    def replace_generated(cls, message: Message, reply: DraftOutput) -> Draft:
        """Replace an untouched generated draft with a new model suggestion."""
        with database.atomic():
            cls.delete().where((cls.message == message) & (cls.status == "generated")).execute()
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
        """Return the newest draft record associated with a message."""
        return cls.select().where(cls.message == message_id).order_by(cls.created_at.desc()).first()

    @classmethod
    def has_reviewable(cls, message_id: int) -> bool:
        """Return whether a message has a draft that was not rejected."""
        return cls.select().where((cls.message == message_id) & (cls.status != "rejected")).exists()

    @classmethod
    def change_generated_status(cls, message_id: int, status: str) -> bool:
        """Change the status of generated drafts for one message."""
        changed = (
            cls.update(status=status)
            .where((cls.message == message_id) & (cls.status == "generated"))
            .execute()
        )
        return changed > 0
