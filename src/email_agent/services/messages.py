from __future__ import annotations

import logging
from dataclasses import dataclass

from email_agent.config import Settings
from email_agent.db import Database
from email_agent.models import EmailClassification, EmailMessage
from email_agent.providers import create_mail_provider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MessageDetails:
    """A provider message combined with its local workflow metadata."""

    message: EmailMessage
    classification: EmailClassification | None


class MessageService:
    """Retrieve locally tracked messages from their mailbox provider."""

    def __init__(self, settings: Settings, database: Database | None = None):
        self.settings = settings
        self.database = database or Database(settings.database_path)

    def show(self, message_id: int) -> MessageDetails:
        logger.info("Loading local message %s", message_id)
        row = self.database.show_message(message_id)
        if not row:
            raise LookupError("message not found")
        account = self.settings.account(row.account_id)
        provider = create_mail_provider(row.account_id, account, self.settings.root)
        logger.debug(
            "Retrieving local message %s from provider=%s mailbox=%s",
            message_id,
            account.provider,
            row.provider_mailbox,
        )
        message = provider.get_message(row.provider_uid, row.provider_mailbox)
        return MessageDetails(message, row.classification)
