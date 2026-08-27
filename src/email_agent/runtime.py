from __future__ import annotations

import logging
from dataclasses import dataclass

from email_agent.ai.chat_models import get_model
from email_agent.ai.classifier import EmailClassifier
from email_agent.ai.drafter import EmailDrafter
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
    classifier: EmailClassifier | None
    drafter: EmailDrafter | None
    model: object | None

    def require_classifier(self) -> EmailClassifier:
        """Return the configured classifier when the runtime includes AI."""
        if self.classifier is None:
            raise RuntimeError("This workflow requires a configured classifier")
        return self.classifier

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

    def for_classification(self, account_id: str) -> AccountRuntime:
        """Build a runtime for classifying messages."""
        account = self.settings.account(account_id)
        model = get_model(account.model)
        classifier = EmailClassifier(self.settings.root, account.agent, model)
        return self._build(account_id, account, model=model, classifier=classifier)

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

    def _build(
        self,
        account_id: str,
        account: AccountConfig,
        *,
        model: object | None = None,
        classifier: EmailClassifier | None = None,
        drafter: EmailDrafter | None = None,
    ) -> AccountRuntime:
        logger.info("Loading account runtime for %s", account_id)
        runtime = AccountRuntime(
            settings=self.settings,
            account_id=account_id,
            account=account,
            provider=create_mail_provider(account_id, account, self.settings.root),
            classifier=classifier,
            drafter=drafter,
            model=model,
        )
        logger.debug(
            "Runtime ready: provider=%s model=%s agents=%s database=%s",
            account.provider,
            account.model.model,
            {
                "classifier": classifier is not None,
                "drafter": drafter is not None,
                "model": model is not None,
            },
            self.settings.database_path,
        )
        return runtime
