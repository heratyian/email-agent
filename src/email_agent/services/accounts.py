from __future__ import annotations

import logging
from pathlib import Path

from email_agent.config import AccountConfig, Settings
from email_agent.generators import GeneratedAccount, generate_account

logger = logging.getLogger(__name__)


class AccountService:
    """Create, list, and validate mailbox account configuration."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def list(self) -> dict[str, AccountConfig]:
        accounts = Settings(self.root).accounts
        logger.info("Loaded %d configured account(s)", len(accounts))
        logger.debug("Configured account providers: %s", [a.provider for a in accounts.values()])
        return accounts

    def validate(self) -> list[str]:
        settings = Settings(self.root)
        logger.info("Validating %d configured account(s)", len(settings.accounts))
        for account in settings.accounts.values():
            prompt = settings.root / account.system_prompt
            logger.debug("Checking system prompt path: %s", prompt)
            if not prompt.is_file():
                raise ValueError(f"Missing system prompt: {account.system_prompt}")
        logger.info("Account configuration is valid")
        return list(settings.accounts)

    def create(self, *args, **kwargs) -> GeneratedAccount:
        logger.info("Generating account configuration")
        generated = generate_account(self.root, *args, **kwargs)
        logger.info("Created account configuration for %s", generated.account_id)
        logger.debug("Generated system prompt: %s", generated.system_prompt)
        return generated
