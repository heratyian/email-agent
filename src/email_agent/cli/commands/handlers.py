from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from email_agent.config import Settings
from email_agent.db import Database
from email_agent.runtime import AccountRuntime, RuntimeFactory
from email_agent.services import (
    AccountService,
    DraftService,
    InboxService,
    MessageService,
    ProcessingService,
)


@dataclass(frozen=True)
class InboxResult:
    runtime: AccountRuntime
    processed: list[Any]
    items: list[Any]


@dataclass
class CommandHandlers:
    """Deterministic application operations with no terminal dependencies."""

    settings: Settings | None = None
    runtime_factory: RuntimeFactory | None = None

    def __post_init__(self) -> None:
        self.settings = self.settings or Settings()
        self.runtime_factory = self.runtime_factory or RuntimeFactory(self.settings)

    def accounts(self) -> dict[str, Any]:
        return AccountService(self.settings.root).list()

    def runtime(self, account_id: str, *, with_agents: bool = True) -> AccountRuntime:
        return self.runtime_factory.for_account(account_id, with_agents=with_agents)

    def show_message(self, message_id: int):
        return MessageService(self.settings).show(message_id)

    def message_account(self, message_id: int) -> str:
        row = Database(self.settings.database_path).show_message(message_id)
        if not row:
            raise LookupError("message not found")
        return row["account_id"]

    def list_drafts(self, account_id: str | None = None):
        return DraftService(Database(self.settings.database_path)).list(account_id)

    def show_draft(self, message_id: int):
        return DraftService(Database(self.settings.database_path)).get(message_id)

    def generate_draft(self, message_id: int, instruction: str | None = None):
        database = Database(self.settings.database_path)
        row = database.show_message(message_id)
        if not row:
            raise LookupError("message not found")
        runtime = self.runtime(row["account_id"])
        return DraftService(database).generate(
            message_id, runtime.provider, runtime.agents, instruction=instruction
        )

    def upload_draft(self, message_id: int) -> str:
        return DraftService(Database(self.settings.database_path), self.settings).upload(message_id)

    def delete_draft(self, message_id: int) -> None:
        DraftService(Database(self.settings.database_path)).delete(message_id)

    def draft_service(self, *, mailbox_access: bool = False) -> DraftService:
        return DraftService(
            Database(self.settings.database_path), self.settings if mailbox_access else None
        )

    def inbox_items(self, runtime: AccountRuntime, limit: int, *, unread: bool = False):
        return InboxService(runtime.provider, runtime.agents, runtime.database).list(
            limit, unread_only=unread
        )

    def run_inbox(self, account_id: str, limit: int) -> InboxResult:
        runtime = self.runtime(account_id)
        processed = ProcessingService(
            account_id,
            runtime.account.agent,
            runtime.provider,
            runtime.agents,
            runtime.database,
        ).process(limit)
        items = self.inbox_items(runtime, limit)
        return InboxResult(runtime, processed, items)
