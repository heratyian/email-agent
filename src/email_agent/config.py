from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ModelConfig(BaseModel):
    """Provider-independent chat model configuration."""

    provider: Literal["openai", "ollama", "compatible"] = "ollama"
    model: str = "qwen3"
    temperature: float = 0
    base_url: str | None = None


class SafetyConfig(BaseModel):
    allow_drafts: bool = True
    allow_send: bool = False

    @model_validator(mode="after")
    def sending_is_forbidden(self):
        if self.allow_send:
            raise ValueError("allow_send must remain false in this release")
        return self


def _default_categories() -> dict[str, str]:
    return {
        "action": "Requires a reply, decision, or other action.",
        "important": "Important information that deserves attention.",
        "receipts": "Purchases, invoices, and payment confirmations.",
        "newsletters": "Subscriptions and recurring publications.",
        "reference": "Useful information requiring no action.",
        "noise": "Spam or low-value automated mail.",
    }


class AgentConfig(BaseModel):
    """Model, system prompt, categories, and enforced safety policy."""

    name: str
    version: int = 1
    model: ModelConfig
    system_prompt: str
    categories: dict[str, str] = Field(default_factory=_default_categories)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)

    @field_validator("categories")
    @classmethod
    def valid_categories(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("categories must be a non-empty mapping")
        for key, description in value.items():
            segments = key.split("/")
            if any(
                not segment
                or not segment.replace("_", "").isalnum()
                or not segment.isascii()
                or segment != segment.lower()
                for segment in segments
            ):
                raise ValueError(f"Invalid category key: {key!r}")
            if not description.strip():
                raise ValueError(f"Category {key!r} must have a description")
        return value


class AccountConfig(BaseModel):
    """One mailbox connection and its email assistant configuration."""

    provider: Literal["gmail", "imap"]
    email: str
    credentials_file: str | None = None
    token_file: str | None = None
    username_env: str | None = None
    password_env: str | None = None
    imap_host: str | None = None
    imap_port: int = 993
    category_action: Literal["copy", "move"] | None = None
    smtp_host: str | None = None
    smtp_port: int = 465
    agent: AgentConfig

    @model_validator(mode="after")
    def provider_fields(self) -> AccountConfig:
        if self.provider == "imap" and not all(
            [self.username_env, self.password_env, self.imap_host]
        ):
            raise ValueError("IMAP accounts require credential env names and imap_host")
        if self.provider == "gmail" and self.category_action is not None:
            raise ValueError("category_action is only supported for IMAP accounts")
        return self


class Settings:
    """Load and validate project configuration from a chosen project root."""

    def __init__(self, root: Path = PROJECT_ROOT):
        self.root = root.resolve()
        load_dotenv(self.root / ".env")
        raw = yaml.safe_load((self.root / "accounts.yaml").read_text()) or {}
        if not isinstance(raw.get("accounts"), dict):
            raise TypeError("accounts.yaml must contain an 'accounts' mapping")
        self.accounts = {
            key: AccountConfig.model_validate(value) for key, value in raw["accounts"].items()
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
