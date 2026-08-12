from email_agent.storage import Database


class DraftService:
    """List, retrieve, and approve locally stored draft suggestions."""

    def __init__(self, database: Database):
        self.database = database

    def list(self, account_id: str | None = None):
        return self.database.list_drafts(account_id)

    def get(self, message_id: int):
        row = self.database.get_draft(message_id)
        if not row:
            raise LookupError("draft not found")
        return row

    def approve(self, message_id: int) -> None:
        if not self.database.approve(message_id):
            raise LookupError("draft not found")
