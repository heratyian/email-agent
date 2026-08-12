from __future__ import annotations

from pathlib import Path

from email_agent.config import AccountConfig, Settings
from email_agent.scaffolding import GeneratedAccount, generate_account


class AccountService:
    """Create, list, and validate mailbox account configuration."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def list(self) -> dict[str, AccountConfig]:
        return Settings(self.root).accounts

    def validate(self) -> list[str]:
        settings = Settings(self.root)
        for account in settings.accounts.values():
            prompt = settings.root / account.system_prompt
            if not prompt.is_file():
                raise ValueError(f"Missing system prompt: {account.system_prompt}")
        return list(settings.accounts)

    def create(self, *args, **kwargs) -> GeneratedAccount:
        return generate_account(self.root, *args, **kwargs)
