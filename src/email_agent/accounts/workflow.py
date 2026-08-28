from __future__ import annotations

import logging
from pathlib import Path

from email_agent.accounts.generator import GeneratedAccount, generate_account
from email_agent.config import AccountConfig, Settings

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
            for prompt_path in (account.triage_prompt, account.draft_prompt):
                prompt = settings.root / prompt_path
                logger.debug("Checking prompt path: %s", prompt)
                if not prompt.is_file():
                    raise ValueError(f"Missing prompt: {prompt_path}")
        logger.info("Account configuration is valid")
        return list(settings.accounts)

    def create(self, *args, **kwargs) -> GeneratedAccount:
        logger.info("Generating account configuration")
        generated = generate_account(self.root, *args, **kwargs)
        logger.info("Created account configuration for %s", generated.account_id)
        logger.debug("Generated triage prompt: %s", generated.triage_prompt)
        logger.debug("Generated draft prompt: %s", generated.draft_prompt)
        return generated
