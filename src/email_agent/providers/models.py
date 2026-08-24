from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class EmailMessage(BaseModel):
    """Provider-neutral representation of an email message."""

    provider_id: str
    thread_id: str | None = None
    account_id: str
    mailbox: str = "INBOX"
    from_address: str
    from_name: str | None = None
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    subject: str = "(no subject)"
    text_body: str | None = None
    html_body: str | None = None
    received_at: datetime
    message_id: str | None = None
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)

    @property
    def content(self) -> str:
        return (self.text_body or "").strip()


class EmailThread(BaseModel):
    messages: list[EmailMessage]
