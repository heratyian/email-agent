from __future__ import annotations

import logging
from dataclasses import dataclass

from email_agent.ai.models import EmailClassification
from email_agent.db import Database
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

    def __init__(self, provider: MailProvider, database: Database):
        self.provider = provider
        self.database = database

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
            saved = self.database.get_triage(message.account_id, message.provider_id)
            if saved:
                local_id, classification = saved
            else:
                local_id = self.database.save_message(message)
                classification = None
            results.append(
                InboxItem(
                    local_id=local_id,
                    message=message,
                    classification=classification,
                    draft_ready=self.database.has_draft(local_id),
                )
            )
        logger.info("Returning %d inbox messages", len(results))
        return results
