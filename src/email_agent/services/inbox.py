from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from email_agent.models import EmailClassification, EmailMessage


class PriorityGroup(StrEnum):
    """Familiar priority sections used to order the assistant's inbox."""

    URGENT = "Urgent"
    NORMAL = "Normal"
    LOW = "Low Priority"


PRIORITY_GROUP_ORDER = (PriorityGroup.URGENT, PriorityGroup.NORMAL, PriorityGroup.LOW)


@dataclass(frozen=True)
class TriagedEmail:
    """A mailbox message with its classification and workflow state."""

    local_id: int
    message: EmailMessage
    classification: EmailClassification
    group: PriorityGroup
    attention_state: str
    draft_ready: bool


def inbox_group(classification: EmailClassification) -> PriorityGroup:
    """Collapse model priority into three recognizable inbox sections."""
    if classification.priority in {"urgent", "high"}:
        return PriorityGroup.URGENT
    if classification.priority == "low":
        return PriorityGroup.LOW
    return PriorityGroup.NORMAL


class InboxService:
    """Fetch, classify, and filter the assistant's inbox view."""

    def __init__(self, provider, agents, database):
        self.provider = provider
        self.agents = agents
        self.database = database

    def list(
        self,
        limit: int = 20,
        *,
        unread_only: bool = False,
        attention: str = "open",
    ) -> list[TriagedEmail]:
        if limit < 1:
            return []
        results = []
        messages = self.provider.get_messages(limit, unread_only=unread_only)
        for message in sorted(messages, key=lambda item: item.received_at, reverse=True):
            saved = self.database.get_triage(message.account_id, message.provider_id)
            if saved:
                local_id, classification = saved
            else:
                thread = self.provider.get_thread(message.provider_id)
                classification = self.agents.classify(message, thread)
                local_id = self.database.save_triage(message, classification)
            state = self.database.attention_state(local_id)
            if attention != "all" and state != attention:
                continue
            results.append(
                TriagedEmail(
                    local_id=local_id,
                    message=message,
                    classification=classification,
                    group=inbox_group(classification),
                    attention_state=state,
                    draft_ready=self.database.has_draft(local_id),
                )
            )
        return results
