import logging

from email_agent.storage import Database

logger = logging.getLogger(__name__)


class DraftService:
    """List, retrieve, and approve locally stored draft suggestions."""

    def __init__(self, database: Database):
        self.database = database

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

    def approve(self, message_id: int) -> None:
        if not self.database.approve(message_id):
            raise LookupError("draft not found")
        logger.info("Approved draft for local message %s", message_id)
