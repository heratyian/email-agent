from __future__ import annotations

from peewee import AutoField, BooleanField, FloatField, ForeignKeyField, TextField

from email_agent.ai.outputs import ClassificationOutput
from email_agent.db.models.base import BaseModel
from email_agent.db.models.message import Message


class Classification(BaseModel):
    """Persist one structured AI classification for a message."""

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
    def save_for(cls, message: Message | int, value: ClassificationOutput) -> Classification:
        """Insert or replace the classification associated with a message."""
        fields = value.model_dump()
        classification, created = cls.get_or_create(message=message, defaults=fields)
        if not created:
            cls.update(**fields).where(cls.id == classification.id).execute()
            classification = cls.get_by_id(classification.id)
        Message.update(classified_at=None).where(Message.id == classification.message_id).execute()
        return classification

    def to_ai(self) -> ClassificationOutput:
        """Convert persisted columns into the AI-facing classification model."""
        return ClassificationOutput(
            category=self.category,
            requires_reply=self.requires_reply,
            priority=self.priority,
            intent=self.intent,
            summary=self.summary,
            confidence=self.confidence,
            requires_escalation=self.requires_escalation,
            escalation_reason=self.escalation_reason,
        )
