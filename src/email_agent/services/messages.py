from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from email_agent.config import Settings
from email_agent.db import Database
from email_agent.models import EmailMessage
from email_agent.providers import create_mail_provider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MessageDetails:
    """A provider message combined with its local workflow metadata."""

    message: EmailMessage
    classification: dict[str, Any] | None
    attention_state: str


@dataclass(frozen=True)
class AttentionResult:
    """Result of changing a message's attention state."""

    subject: str
    deleted_drafts: int = 0


class MessageService:
    """Retrieve messages and manage open, snoozed, and done state."""

    def __init__(self, settings: Settings, database: Database | None = None):
        self.settings = settings
        self.database = database or Database(settings.database_path)

    def show(self, message_id: int) -> MessageDetails:
        logger.info("Loading local message %s", message_id)
        row = self.database.show_message(message_id)
        if not row:
            raise LookupError("message not found")
        account = self.settings.account(row["account_id"])
        provider = create_mail_provider(row["account_id"], account, self.settings.root)
        logger.debug(
            "Retrieving local message %s from provider=%s mailbox=%s",
            message_id,
            account.provider,
            row["provider_mailbox"],
        )
        message = provider.get_message(row["provider_uid"], row["provider_mailbox"])
        classification = json.loads(row["classification"]) if row["classification"] else None
        return MessageDetails(message, classification, row["attention_state"])

    def done(self, message_id: int, *, delete_draft: bool = False) -> AttentionResult:
        row = self.database.set_attention(message_id, "done")
        if not row:
            raise LookupError("message not found")
        deleted = self.database.delete_generated_drafts(message_id) if delete_draft else 0
        logger.info("Marked local message %s done", message_id)
        logger.debug("Deleted %d untouched draft(s)", deleted)
        return AttentionResult(row["subject"], deleted)

    def snooze(self, message_id: int, until: datetime) -> AttentionResult:
        if until.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("--until must be in the future")
        row = self.database.set_attention(message_id, "snoozed", snoozed_until=until)
        if not row:
            raise LookupError("message not found")
        logger.info("Snoozed local message %s", message_id)
        logger.debug("Local message %s snoozed until %s", message_id, until.isoformat())
        return AttentionResult(row["subject"])

    def reopen(self, message_id: int) -> AttentionResult:
        row = self.database.set_attention(message_id, "open")
        if not row:
            raise LookupError("message not found")
        logger.info("Reopened local message %s", message_id)
        return AttentionResult(row["subject"])
