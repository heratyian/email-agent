from __future__ import annotations

import logging
from dataclasses import dataclass

from email_agent.config import AccountConfig, Settings
from email_agent.drafting.drafter import EmailDrafter
from email_agent.llm.chat import get_model
from email_agent.persistence import initialize_database
from email_agent.providers import MailProvider, create_mail_provider
from email_agent.triage.triager import EmailTriager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountRuntime:
    """Ready-to-use dependencies for one configured mailbox account."""

    settings: Settings
    account_id: str
    account: AccountConfig
    provider: MailProvider
    triager: EmailTriager | None
    drafter: EmailDrafter | None
    model: object | None

    def require_triager(self) -> EmailTriager:
        """Return the configured triager when the runtime includes AI."""
        if self.triager is None:
            raise RuntimeError("This workflow requires a configured triager")
        return self.triager

    def require_drafter(self) -> EmailDrafter:
        """Return the configured drafter when the runtime includes AI."""
        if self.drafter is None:
            raise RuntimeError("This workflow requires a configured drafter")
        return self.drafter


class RuntimeFactory:
    """Account-scoped abstract factory that serves as the application's composition root."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        initialize_database(self.settings.database_path)

    def for_inbox(self, account_id: str) -> AccountRuntime:
        """Build a runtime for provider-only inbox operations."""
        account = self.settings.account(account_id)
        return self._build(account_id, account)

    def for_triage(self, account_id: str) -> AccountRuntime:
        """Build a runtime for triaging messages."""
        account = self.settings.account(account_id)
        model = get_model(account.model)
        triager = EmailTriager(self.settings.root, account.agent, model)
        return self._build(account_id, account, model=model, triager=triager)

    def for_drafting(self, account_id: str) -> AccountRuntime:
        """Build a runtime for drafting replies."""
        account = self.settings.account(account_id)
        model = get_model(account.model)
        drafter = EmailDrafter(self.settings.root, account.agent, model)
        return self._build(account_id, account, model=model, drafter=drafter)

    def for_search(self, account_id: str) -> AccountRuntime:
        """Build a runtime for model-assisted inbox search."""
        account = self.settings.account(account_id)
        return self._build(account_id, account, model=get_model(account.model))

    def for_assistant(self, account_id: str) -> AccountRuntime:
        """Build a runtime for natural-language orchestration."""
        account = self.settings.account(account_id)
        return self._build(account_id, account, model=get_model(account.model))

    def _build(
        self,
        account_id: str,
        account: AccountConfig,
        *,
        model: object | None = None,
        triager: EmailTriager | None = None,
        drafter: EmailDrafter | None = None,
    ) -> AccountRuntime:
        logger.info("Loading account runtime for %s", account_id)
        runtime = AccountRuntime(
            settings=self.settings,
            account_id=account_id,
            account=account,
            provider=create_mail_provider(account_id, account, self.settings.root),
            triager=triager,
            drafter=drafter,
            model=model,
        )
        logger.debug(
            "Runtime ready: provider=%s model=%s agents=%s database=%s",
            account.provider,
            account.model.model,
            {
                "triager": triager is not None,
                "drafter": drafter is not None,
                "model": model is not None,
            },
            self.settings.database_path,
        )
        return runtime
