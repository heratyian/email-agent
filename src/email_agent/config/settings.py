import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from email_agent.config.models import AccountConfig

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings:
    """Load and validate project configuration from a chosen project root."""

    def __init__(self, root: Path = PROJECT_ROOT):
        self.root = root.resolve()
        load_dotenv(self.root / ".env")
        raw = yaml.safe_load((self.root / "accounts.yaml").read_text()) or {}
        if not isinstance(raw.get("accounts"), dict):
            raise TypeError("accounts.yaml must contain an 'accounts' mapping")
        self.accounts = {}
        for email, account in raw["accounts"].items():
            if not isinstance(account, dict):
                raise TypeError("Each account must be a mapping")
            self.accounts[email] = AccountConfig.model_validate({"email": email, **account})
        configured_path = Path(os.getenv("EMAIL_AGENT_DATABASE", "data/email_agent.db"))
        self.database_path = (
            configured_path if configured_path.is_absolute() else self.root / configured_path
        )

    def account(self, email: str) -> AccountConfig:
        """Return an account by its canonical email-address key."""
        try:
            return self.accounts[email]
        except KeyError as exc:
            raise ValueError(f"Unknown account: {email}") from exc
