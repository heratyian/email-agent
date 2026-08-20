from __future__ import annotations

from dataclasses import dataclass

from email_agent.config import AccountConfig, Settings
from email_agent.db import Database, StoredDraft
from email_agent.generators import GeneratedAccount
from email_agent.models import Draft, EmailMessage
from email_agent.runtime import AccountRuntime, RuntimeFactory
from email_agent.services import (
    AccountService,
    DraftService,
    InboxService,
    MessageDetails,
    MessageService,
    OrganizationReport,
    OrganizationService,
    ProcessedEmail,
    ProcessingFailure,
    ProcessingService,
    TriagedEmail,
)


@dataclass(frozen=True)
class InboxResult:
    runtime: AccountRuntime
    processed: list[ProcessedEmail | ProcessingFailure]
    items: list[TriagedEmail]
    organization: OrganizationReport | None = None
    dry_run: bool = False


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

    def runtime(self, account_id: str, *, with_agents: bool = True) -> AccountRuntime:
        return self.runtime_factory.for_account(account_id, with_agents=with_agents)

    def show_message(self, message_id: int) -> MessageDetails:
        return MessageService(self.settings).show(message_id)

    def message_account(self, message_id: int) -> str:
        row = Database(self.settings.database_path).show_message(message_id)
        if not row:
            raise LookupError("message not found")
        return row.account_id

    def list_drafts(self, account_id: str | None = None) -> list[StoredDraft]:
        return DraftService(Database(self.settings.database_path)).list(account_id)

    def show_draft(self, message_id: int) -> StoredDraft:
        return DraftService(Database(self.settings.database_path)).get(message_id)

    def generate_draft(self, message_id: int, instruction: str | None = None) -> Draft:
        database = Database(self.settings.database_path)
        row = database.show_message(message_id)
        if not row:
            raise LookupError("message not found")
        runtime = self.runtime(row.account_id)
        return DraftService(database).generate(
            message_id, runtime.provider, runtime.require_agents(), instruction=instruction
        )

    def upload_draft(self, message_id: int) -> str:
        return DraftService(Database(self.settings.database_path)).upload(message_id, self.settings)

    def delete_draft(self, message_id: int) -> None:
        DraftService(Database(self.settings.database_path)).delete(message_id)

    def source_message(self, message_id: int) -> EmailMessage:
        return DraftService(Database(self.settings.database_path)).source_message(
            message_id, self.settings
        )

    def inbox_items(
        self, runtime: AccountRuntime, limit: int, *, unread: bool = False
    ) -> list[TriagedEmail]:
        return InboxService(runtime.provider, runtime.require_agents(), runtime.database).list(
            limit, unread_only=unread
        )

    def run_inbox(
        self,
        account_id: str,
        limit: int,
        *,
        unread: bool = False,
        dry_run: bool = False,
        reorganize: bool = False,
    ) -> InboxResult:
        runtime = self.runtime(account_id)
        processed = []
        if not dry_run:
            processed = ProcessingService(
                account_id,
                runtime.account.agent,
                runtime.provider,
                runtime.require_agents(),
                runtime.database,
            ).process(limit)
        organization = None
        if reorganize and not dry_run:
            organization = OrganizationService(
                account_id,
                runtime.account,
                runtime.provider,
                runtime.database,
                runtime.require_agents(),
            ).run(limit=limit, force=True, reclassify_all=True)
        items = self.inbox_items(runtime, limit, unread=unread)
        return InboxResult(runtime, processed, items, organization, dry_run)
