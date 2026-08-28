from __future__ import annotations

import logging
from dataclasses import dataclass

from email_agent.persistence import Draft, Message
from email_agent.providers import MailProvider
from email_agent.providers.models import EmailMessage
from email_agent.triage.models import TriageOutput

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InboxItem:
    """A mailbox message with any existing local assistant state."""

    local_id: int
    message: EmailMessage
    triage: TriageOutput | None
    draft_ready: bool


class InboxService:
    """Synchronize and list an ordinary inbox without invoking a model."""

    def __init__(self, provider: MailProvider):
        self.provider = provider

    def list(
        self,
        limit: int = 20,
        *,
        unread_only: bool = False,
    ) -> list[InboxItem]:
        if limit < 1:
            return []
        results = []
        messages = self.provider.get_messages(limit, unread_only=unread_only)
        logger.info("Synchronizing %d recent inbox messages", len(messages))
        for message in sorted(messages, key=lambda item: item.received_at, reverse=True):
            stored = Message.upsert_email(message)
            results.append(
                InboxItem(
                    local_id=stored.id,
                    message=message,
                    triage=stored.triage_value(),
                    draft_ready=Draft.has_reviewable(stored.id),
                )
            )
        logger.info("Returning %d inbox messages", len(results))
        return results
