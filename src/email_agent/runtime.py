from __future__ import annotations

from dataclasses import dataclass

from email_agent.agents import EmailAgents
from email_agent.config import AccountConfig, Settings
from email_agent.llm import get_model
from email_agent.mail import MailProvider, create_mail_provider
from email_agent.storage import Database


@dataclass(frozen=True)
class AccountRuntime:
    """Ready-to-use dependencies for one configured mailbox account."""

    settings: Settings
    account_id: str
    account: AccountConfig
    provider: MailProvider
    database: Database
    agents: EmailAgents | None


class RuntimeFactory:
    """Build account-scoped application dependencies in one place."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    def for_account(self, account_id: str, *, with_agents: bool = True) -> AccountRuntime:
        account = self.settings.account(account_id)
        agents = (
            EmailAgents(self.settings.root, account.agent, get_model(account.model))
            if with_agents
            else None
        )
        return AccountRuntime(
            settings=self.settings,
            account_id=account_id,
            account=account,
            provider=create_mail_provider(account_id, account, self.settings.root),
            database=Database(self.settings.database_path),
            agents=agents,
        )
