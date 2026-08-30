from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class InboxSearchPlanOutput(BaseModel):
    """Model-produced semantic query and explicit database filters."""

    semantic_query: str
    sender: str | None = None
    category: str | None = None
    priority: Literal["urgent", "high", "normal", "low"] | None = None
    requires_reply: bool | None = None
    requires_escalation: bool | None = None
    recent_days: int | None = Field(default=None, ge=1, le=365)
    limit: int = Field(default=8, ge=1, le=20)


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
