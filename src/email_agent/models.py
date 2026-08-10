from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EmailMessage(BaseModel):
    provider_id: str
    thread_id: str | None = None
    account_id: str
    from_address: str
    from_name: str | None = None
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    subject: str = "(no subject)"
    text_body: str | None = None
    html_body: str | None = None
    received_at: datetime
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)

    @property
    def content(self) -> str:
        return (self.text_body or "").strip()


class EmailThread(BaseModel):
    messages: list[EmailMessage]


class EmailClassification(BaseModel):
    category: Literal[
        "spam",
        "newsletter",
        "automated",
        "informational",
        "needs_reply",
        "support_request",
        "urgent",
        "unknown",
    ]
    requires_reply: bool
    priority: Literal["low", "normal", "high", "urgent"]
    intent: str | None = None
    summary: str
    confidence: float = Field(ge=0, le=1)
    requires_escalation: bool = False
    escalation_reason: str | None = None


class DraftReply(BaseModel):
    recipient: str
    subject: str
    body: str
    reasoning_summary: str
    confidence: float = Field(ge=0, le=1)
    requires_escalation: bool = False
    escalation_reason: str | None = None


class Draft(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    account_id: str
    source_message_id: str
    to: list[str]
    subject: str
    body: str
    status: Literal["generated", "reviewed", "approved", "rejected", "sent"] = "generated"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
