from __future__ import annotations

import logging
from dataclasses import dataclass

from email_agent.ai.agents import EmailAgents
from email_agent.ai.llm import get_model
from email_agent.config import AccountConfig, Settings
from email_agent.db import initialize_database
from email_agent.providers import MailProvider, create_mail_provider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountRuntime:
    """Ready-to-use dependencies for one configured mailbox account."""

    settings: Settings
    account_id: str
    account: AccountConfig
    provider: MailProvider
    agents: EmailAgents | None

    def require_agents(self) -> EmailAgents:
        """Return configured model operations for workflows that require them."""
        if self.agents is None:
            raise RuntimeError("This workflow requires configured model agents")
        return self.agents


class RuntimeFactory:
    """Build account-scoped application dependencies in one place."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        initialize_database(self.settings.database_path)

    def for_account(self, account_id: str, *, with_agents: bool = True) -> AccountRuntime:
        logger.info("Loading account runtime for %s", account_id)
        account = self.settings.account(account_id)
        agents = (
            EmailAgents(self.settings.root, account.agent, get_model(account.model))
            if with_agents
            else None
        )
        runtime = AccountRuntime(
            settings=self.settings,
            account_id=account_id,
            account=account,
            provider=create_mail_provider(account_id, account, self.settings.root),
            agents=agents,
        )
        logger.debug(
            "Runtime ready: provider=%s model=%s agents=%s database=%s",
            account.provider,
            account.model.model,
            with_agents,
            self.settings.database_path,
        )
        return runtime
