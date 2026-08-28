from pydantic import BaseModel, Field


class DraftOutput(BaseModel):
    """Validated reply output produced by the drafting agent."""

    recipient: str
    subject: str
    body: str
    reasoning_summary: str
    confidence: float = Field(ge=0, le=1)
    requires_escalation: bool = False
    escalation_reason: str | None = None
