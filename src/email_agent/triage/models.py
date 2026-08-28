from typing import Literal

from pydantic import BaseModel, Field


class TriageOutput(BaseModel):
    """Validated triage output produced by the triage agent."""

    category: str | None = Field(
        default=None, min_length=1, pattern=r"^[a-z][a-z0-9_]*(?:/[a-z][a-z0-9_]*)*$"
    )
    requires_reply: bool
    priority: Literal["low", "normal", "high", "urgent"]
    intent: str | None = None
    summary: str
    confidence: float = Field(ge=0, le=1)
    requires_escalation: bool = False
    escalation_reason: str | None = None
