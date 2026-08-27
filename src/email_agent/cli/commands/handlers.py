from __future__ import annotations

from dataclasses import dataclass

from email_agent.config import AccountConfig, Settings
from email_agent.db import Draft, Message
from email_agent.generators import GeneratedAccount
from email_agent.providers.models import EmailMessage
from email_agent.runtime import AccountRuntime, RuntimeFactory
from email_agent.search import InboxSearchService
from email_agent.services import (
    AccountService,
    ClassificationFailure,
    ClassificationService,
    ClassifiedEmail,
    DraftService,
    InboxItem,
    InboxService,
    MessageDetails,
    MessageService,
)


@dataclass(frozen=True)
class InboxResult:
    runtime: AccountRuntime
    items: list[InboxItem]


@dataclass
class CommandHandlers:
    """Deterministic application operations with no terminal dependencies."""

    settings: Settings | None = None
    runtime_factory: RuntimeFactory | None = None

    def __post_init__(self) -> None:
        self.settings = self.settings or Settings()
        self.runtime_factory = self.runtime_factory or RuntimeFactory(self.settings)

    def accounts(self) -> dict[str, AccountConfig]:
        return AccountService(self.settings.root).list()

    def create_account(self, *args, **kwargs) -> GeneratedAccount:
        return AccountService(self.settings.root).create(*args, **kwargs)

    def validate_accounts(self) -> list[str]:
        return AccountService(self.settings.root).validate()

    def validate_account(self, account_id: str) -> AccountConfig:
        return self.settings.account(account_id)

    def show_message(self, message_id: int) -> MessageDetails:
        return MessageService(self.settings).show(message_id)

    def message_account(self, message_id: int) -> str:
        row = Message.get_or_none(Message.id == message_id)
        if not row:
            raise LookupError("message not found")
        return row.account_id

    def list_drafts(self, account_id: str | None = None) -> list[Draft]:
        return list(Draft.pending(account_id))

    def show_draft(self, message_id: int) -> Draft:
        draft = Draft.latest_for_message(message_id)
        if draft is None:
            raise LookupError("draft not found")
        return draft

    def generate_draft(self, message_id: int, instruction: str | None = None) -> Draft:
        row = Message.get_or_none(Message.id == message_id)
        if not row:
            raise LookupError("message not found")
        runtime = self.runtime_factory.for_drafting(row.account_id)
        return DraftService().generate(
            message_id, runtime.provider, runtime.require_drafter(), instruction=instruction
        )

    def upload_draft(self, message_id: int) -> str:
        return DraftService().upload(message_id, self.settings)

    def delete_draft(self, message_id: int) -> None:
        if not Draft.change_generated_status(message_id, "rejected"):
            raise LookupError("draft not found")

    def source_message(self, message_id: int) -> EmailMessage:
        return DraftService().source_message(message_id, self.settings)

    def inbox_items(
        self, runtime: AccountRuntime, limit: int, *, unread: bool = False
    ) -> list[InboxItem]:
        return InboxService(runtime.provider).list(limit, unread_only=unread)

    def run_inbox(
        self,
        account_id: str,
        limit: int,
        *,
        unread: bool = False,
    ) -> InboxResult:
        runtime = self.runtime_factory.for_inbox(account_id)
        items = self.inbox_items(runtime, limit, unread=unread)
        return InboxResult(runtime, items)

    def ask_inbox(self, account_id: str, query: str) -> str:
        """Answer a read-only natural language question about local email."""
        runtime = self.runtime_factory.for_search(account_id)
        if runtime.model is None:
            raise RuntimeError("This workflow requires a configured model")
        return InboxSearchService(
            runtime.settings,
            runtime.account_id,
            runtime.account,
            runtime.model,
        ).ask(query)

    def classify(
        self,
        account_id: str,
        *,
        message_id: int | None = None,
    ) -> list[ClassifiedEmail | ClassificationFailure]:
        runtime = self.runtime_factory.for_classification(account_id)
        service = ClassificationService(
            runtime.account.agent,
            runtime.provider,
            runtime.require_classifier(),
        )
        if message_id is not None:
            if self.message_account(message_id) != account_id:
                raise LookupError(f"message {message_id} does not belong to account {account_id}")
            return [service.classify_message(message_id)]
        return service.classify_unclassified(account_id)
