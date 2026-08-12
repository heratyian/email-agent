from dataclasses import dataclass
from typing import Protocol

from email_agent.models import EmailMessage, EmailThread


@dataclass(frozen=True)
class CategorySyncResult:
    """Provider location created by category synchronization."""

    provider_id: str
    mailbox: str
    source_moved: bool = True


@dataclass(frozen=True)
class CategorySyncState:
    """The currently active provider-managed category for a local message."""

    destination: str
    provider_id: str | None = None
    mailbox: str | None = None


class MailProvider(Protocol):
    """Mailbox operations required by the provider-independent pipeline."""

    def get_messages(self, limit: int = 20, *, unread_only: bool = False) -> list[EmailMessage]: ...
    def get_message(self, message_id: str, mailbox: str = "INBOX") -> EmailMessage: ...
    def get_thread(self, message_id: str, mailbox: str = "INBOX") -> EmailThread: ...
    def upload_draft(
        self,
        source: EmailMessage,
        *,
        recipient: str,
        subject: str,
        body: str,
    ) -> str: ...
    def mark_processed(self, message_id: str) -> None: ...
    def sync_category(
        self,
        message_id: str,
        destination: str | None,
        source_mailbox: str = "INBOX",
        previous: CategorySyncState | None = None,
    ) -> CategorySyncResult | None: ...
    def category_sync_key(self, destination: str) -> str: ...
