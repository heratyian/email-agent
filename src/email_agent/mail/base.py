from dataclasses import dataclass
from typing import Protocol

from email_agent.models import Draft, EmailMessage, EmailThread


@dataclass(frozen=True)
class CategorySyncResult:
    """A new provider location assigned by a category move."""

    provider_id: str
    mailbox: str


class MailProvider(Protocol):
    """Mailbox operations required by the provider-independent pipeline."""

    def get_messages(self, limit: int = 20, *, unread_only: bool = False) -> list[EmailMessage]: ...
    def get_new_messages(self, limit: int = 20) -> list[EmailMessage]: ...
    def get_message(self, message_id: str, mailbox: str = "INBOX") -> EmailMessage: ...
    def get_thread(self, message_id: str, mailbox: str = "INBOX") -> EmailThread: ...
    def create_draft(self, message_id: str, body: str) -> Draft: ...
    def mark_processed(self, message_id: str) -> None: ...
    def sync_category(
        self, message_id: str, destination: str, source_mailbox: str = "INBOX"
    ) -> CategorySyncResult | None: ...
    def category_sync_key(self, destination: str) -> str: ...
