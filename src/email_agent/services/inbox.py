from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from email_agent.models import EmailClassification, EmailMessage

logger = logging.getLogger(__name__)


class PriorityGroup(StrEnum):
    """Familiar priority sections used to order the assistant's inbox."""

    URGENT = "Urgent"
    NORMAL = "Normal"
    LOW = "Low Priority"


PRIORITY_GROUP_ORDER = (PriorityGroup.URGENT, PriorityGroup.NORMAL, PriorityGroup.LOW)


@dataclass(frozen=True)
class TriagedEmail:
    """A mailbox message with its classification and draft state."""

    local_id: int
    message: EmailMessage
    classification: EmailClassification
    group: PriorityGroup
    draft_ready: bool


def inbox_group(classification: EmailClassification) -> PriorityGroup:
    """Collapse model priority into three recognizable inbox sections."""
    if classification.priority in {"urgent", "high"}:
        return PriorityGroup.URGENT
    if classification.priority == "low":
        return PriorityGroup.LOW
    return PriorityGroup.NORMAL


class InboxService:
    """Fetch and classify the assistant's prioritized inbox view."""

    def __init__(self, provider, agents, database):
        self.provider = provider
        self.agents = agents
        self.database = database

    def list(
        self,
        limit: int = 20,
        *,
        unread_only: bool = False,
    ) -> list[TriagedEmail]:
        if limit < 1:
            return []
        results = []
        messages = self.provider.get_messages(limit, unread_only=unread_only)
        logger.info("Examining %d recent inbox messages", len(messages))
        for message in sorted(messages, key=lambda item: item.received_at, reverse=True):
            saved = self.database.get_triage(message.account_id, message.provider_id)
            if saved:
                local_id, classification = saved
                logger.debug("Reusing classification for local message %s", local_id)
            else:
                thread = self.provider.get_thread(message.provider_id)
                classification = self.agents.classify(message, thread)
                local_id = self.database.save_triage(message, classification)
                logger.info("Classified local message %s as %s", local_id, classification.category)
            results.append(
                TriagedEmail(
                    local_id=local_id,
                    message=message,
                    classification=classification,
                    group=inbox_group(classification),
                    draft_ready=self.database.has_draft(local_id),
                )
            )
        logger.info("Returning %d prioritized inbox messages", len(results))
        return results
