from __future__ import annotations

import logging
from dataclasses import dataclass

from email_agent.ai.models import EmailClassification
from email_agent.db import Draft, Message
from email_agent.providers import MailProvider
from email_agent.providers.models import EmailMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InboxItem:
    """A mailbox message with any existing local assistant state."""

    local_id: int
    message: EmailMessage
    classification: EmailClassification | None
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
            stored = Message.find_email(message.account_id, message.provider_id)
            if stored is None:
                stored = Message.upsert_email(message)
            results.append(
                InboxItem(
                    local_id=stored.id,
                    message=message,
                    classification=stored.classification_value(),
                    draft_ready=Draft.has_reviewable(stored.id),
                )
            )
        logger.info("Returning %d inbox messages", len(results))
        return results
