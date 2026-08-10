from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AccountConfig(BaseModel):
    """Connection settings for one mailbox; secret values are environment-only."""

    provider: Literal["gmail", "imap"]
    email: str | None = None
    credentials_file: str | None = None
    token_file: str | None = None
    username_env: str | None = None
    password_env: str | None = None
    imap_host: str | None = None
    imap_port: int = 993
    smtp_host: str | None = None
    smtp_port: int = 465

    @model_validator(mode="after")
    def provider_fields(self) -> AccountConfig:
        if self.provider == "imap" and not all(
            [self.email, self.username_env, self.password_env, self.imap_host]
        ):
            raise ValueError("IMAP accounts require email, credential env names, and imap_host")
        return self


class ModelConfig(BaseModel):
    """Provider-independent chat model configuration."""

    provider: Literal["openai", "ollama", "compatible"] = "ollama"
    model: str = "qwen3"
    temperature: float = 0
    base_url: str | None = None


class PromptConfig(BaseModel):
    version: int = 1
    system: str
    classify: str
    reply: str


class BehaviorConfig(BaseModel):
    default_tone: str = "friendly"
    max_reply_words: int = 150
    intents: list[str] = Field(default_factory=list)
    escalation_rules: list[str] = Field(default_factory=list)
    ignored_rules: list[str] = Field(default_factory=list)
    company_context: str = ""


class SafetyConfig(BaseModel):
    allow_drafts: bool = True
    allow_send: bool = False

    @model_validator(mode="after")
    def sending_is_forbidden(self):
        if self.allow_send:
            raise ValueError("allow_send must remain false in this release")
        return self


class AgentProfile(BaseModel):
    """All mailbox-specific behavior consumed by the shared agent engine."""

    id: str
    name: str
    version: int = 1
    account: str
    model: ModelConfig
    prompts: PromptConfig
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)


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

    def profile(self, name: str) -> AgentProfile:
        if not name or Path(name).name != name:
            raise ValueError(f"Invalid profile name: {name}")
        path = self.root / "profiles" / f"{name}.yaml"
        if not path.is_file():
            raise ValueError(f"Unknown profile: {name}")
        return AgentProfile.model_validate(yaml.safe_load(path.read_text()))

    def account_for(self, profile: AgentProfile) -> AccountConfig:
        try:
            return self.accounts[profile.account]
        except KeyError as exc:
            raise ValueError(f"Profile references unknown account: {profile.account}") from exc
