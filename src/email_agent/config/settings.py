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
        self.accounts = {
            key: AccountConfig.model_validate(
                {"email": key, **self._flatten_legacy_account(value)}
            )
            for key, value in raw["accounts"].items()
        }
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

    @staticmethod
    def _flatten_legacy_account(value: object) -> dict:
        """Accept the pre-flattening v0.1 shape while users migrate their YAML."""
        if not isinstance(value, dict):
            raise TypeError("Each account must be a mapping")
        flattened = dict(value)
        flattened.pop("email", None)
        flattened.pop("smtp_host", None)
        flattened.pop("smtp_port", None)
        legacy_agent = flattened.pop("agent", None)
        if isinstance(legacy_agent, dict):
            legacy_agent = dict(legacy_agent)
            legacy_agent.pop("version", None)
            legacy_agent.pop("safety", None)
            flattened.update(legacy_agent)
        return flattened
