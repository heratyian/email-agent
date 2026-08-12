import logging

from email_agent.config import Settings
from email_agent.db import Database
from email_agent.providers import create_mail_provider

logger = logging.getLogger(__name__)


class DraftService:
    """List, retrieve, upload, and discard local draft suggestions."""

    def __init__(self, database: Database, settings: Settings | None = None):
        self.database = database
        self.settings = settings

    def list(self, account_id: str | None = None):
        rows = self.database.list_drafts(account_id)
        logger.info("Found %d local draft(s)", len(rows))
        logger.debug("Draft list filter: account=%s", account_id or "all")
        return rows

    def get(self, message_id: int):
        row = self.database.get_draft(message_id)
        if not row:
            raise LookupError("draft not found")
        logger.info("Loaded draft for local message %s", message_id)
        logger.debug("Draft status for local message %s: %s", message_id, row["status"])
        return row

    def source_message(self, message_id: int):
        """Retrieve the original mailbox message for one local draft."""
        if self.settings is None:
            raise RuntimeError("Reading the source message requires account settings")
        message_row = self.database.show_message(message_id)
        if not message_row:
            raise LookupError("message not found")
        account_id = message_row["account_id"]
        account = self.settings.account(account_id)
        provider = create_mail_provider(account_id, account, self.settings.root)
        return provider.get_message(
            message_row["provider_uid"], message_row["provider_mailbox"]
        )

    def upload(self, message_id: int) -> str:
        """Upload one suggestion to its mailbox Drafts folder without sending."""
        if self.settings is None:
            raise RuntimeError("Draft upload requires account settings")
        draft = self.get(message_id)
        source = self.source_message(message_id)
        account = self.settings.account(source.account_id)
        provider = create_mail_provider(source.account_id, account, self.settings.root)
        provider_id = provider.upload_draft(
            source,
            recipient=draft["recipient"],
            subject=draft["subject"],
            body=draft["body"],
        )
        if not self.database.mark_draft_uploaded(message_id):
            raise LookupError("draft not found")
        logger.info("Uploaded draft for local message %s", message_id)
        return provider_id

    def delete(self, message_id: int) -> None:
        """Remove one generated suggestion from the review queue."""
        if not self.database.reject_draft(message_id):
            raise LookupError("draft not found")
        logger.info("Deleted draft suggestion for local message %s", message_id)
