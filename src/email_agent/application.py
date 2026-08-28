from __future__ import annotations

from dataclasses import dataclass

from email_agent.accounts.generator import GeneratedAccount
from email_agent.accounts.workflow import AccountService
from email_agent.assistant import AssistantConversation
from email_agent.config import AccountConfig, Settings
from email_agent.drafting.workflow import DraftService
from email_agent.inbox.messages import MessageDetails, MessageService
from email_agent.inbox.workflow import InboxItem, InboxService
from email_agent.llm.embeddings import get_embedding_model
from email_agent.persistence import Draft, Message
from email_agent.providers.models import EmailMessage
from email_agent.runtime import RuntimeFactory
from email_agent.search import InboxSearchService
from email_agent.search.models import InboxSearchResponse
from email_agent.search.retrieval import sync_summary_vector_store
from email_agent.triage.workflow import TriagedEmail, TriageFailure, TriageService


@dataclass
class EmailApplication:
    """Integrated application operations shared by every interface."""

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

    def run_inbox(
        self,
        account_id: str,
        limit: int,
        *,
        unread: bool = False,
    ) -> list[InboxItem]:
        runtime = self.runtime_factory.for_inbox(account_id)
        return InboxService(runtime.provider).list(limit, unread_only=unread)

    def search_inbox(self, account_id: str, query: str) -> InboxSearchResponse:
        """Search triaged local email with a natural language query."""
        runtime = self.runtime_factory.for_search(account_id)
        if runtime.model is None:
            raise RuntimeError("This workflow requires a configured model")
        return InboxSearchService(
            runtime.settings,
            runtime.account_id,
            runtime.account,
            runtime.model,
        ).search(query)

    def assistant(self, account_id: str) -> AssistantConversation:
        """Build a stateful conversational graph for one shell session."""
        runtime = self.runtime_factory.for_assistant(account_id)
        if runtime.model is None:
            raise RuntimeError("This workflow requires a configured model")
        return AssistantConversation(account_id, runtime.model, self)

    def triage(
        self,
        account_id: str,
        *,
        message_id: int | None = None,
    ) -> list[TriagedEmail | TriageFailure]:
        runtime = self.runtime_factory.for_triage(account_id)
        service = TriageService(
            runtime.account.agent,
            runtime.provider,
            runtime.require_triager(),
        )
        if message_id is not None:
            if self.message_account(message_id) != account_id:
                raise LookupError(f"message {message_id} does not belong to account {account_id}")
            results = [service.triage_message(message_id)]
        else:
            results = service.triage_pending(account_id)
        sync_summary_vector_store(
            account_id,
            runtime.settings.root / "data" / "chroma",
            get_embedding_model(runtime.account.model),
        )
        return results
