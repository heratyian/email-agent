from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class AssistantIntentOutput(BaseModel):
    """One constrained interpretation of a natural-language shell request."""

    action: Literal[
        "inbox",
        "search",
        "show",
        "triage",
        "draft",
        "drafts",
        "upload",
        "unsupported",
    ]
    message_id: int | None = None
    query: str | None = None
    instruction: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    explanation: str | None = None


class PendingAction(BaseModel):
    """A provider-changing operation waiting for user authorization."""

    action: Literal["triage", "upload"]
    message_id: int | None = None

    def describe(self) -> str:
        if self.action == "triage":
            target = f"message #{self.message_id}" if self.message_id else "all untriaged messages"
            return f"Triage {target} and synchronize mailbox labels?"
        return f"Upload the suggestion for message #{self.message_id} to mailbox drafts?"


class AssistantTurn(BaseModel):
    """One interface-neutral result from the conversational graph."""

    kind: Literal["text", "inbox", "search", "message", "triage", "draft", "drafts"]
    message: str | None = None
    payload: Any = None


class AssistantState(TypedDict, total=False):
    """Session state passed through one conversational graph turn."""

    account_id: str
    user_input: str
    intent: AssistantIntentOutput
    pending_action: PendingAction | None
    last_message_ids: list[int]
    last_draft_message_id: int | None
    turn: AssistantTurn
