from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class InboxSearchPlanOutput(BaseModel):
    """Structured model plan for one natural language inbox search."""

    query: str
    topic: str | None = None
    sender: str | None = None
    category: str | None = None
    priority: str | None = None
    requires_reply: bool | None = None
    requires_escalation: bool | None = None
    recent_days: int | None = Field(default=None, ge=1, le=365)
    limit: int = Field(default=8, ge=1, le=20)
    rationale: str


class InboxSearchResult(BaseModel):
    """One ranked inbox search result."""

    message_id: int
    from_address: str
    from_name: str | None = None
    subject: str
    received_at: datetime
    category: str | None = None
    priority: str | None = None
    requires_reply: bool | None = None
    requires_escalation: bool | None = None
    summary: str
    reason: str
    score: float = 0


class InboxSearchResponse(BaseModel):
    """Grounded search response returned to application interfaces."""

    summary: str
    results: list[InboxSearchResult] = Field(default_factory=list)
