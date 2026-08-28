from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ModelConfig(BaseModel):
    """Provider-independent chat model configuration."""

    provider: Literal["openai", "ollama", "compatible"] = "ollama"
    model: str = "qwen3"
    temperature: float = 0
    base_url: str | None = None


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
    """Internal model, prompt, and category view of an account."""

    model_config = ConfigDict(extra="forbid")

    model: ModelConfig
    triage_prompt: str
    draft_prompt: str | None = None
    categories: dict[str, str] = Field(default_factory=_default_categories)

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

    model_config = ConfigDict(extra="forbid")

    provider: Literal["gmail", "imap", "demo"]
    email: str = Field(exclude=True)
    credentials_file: str | None = None
    token_file: str | None = None
    username_env: str | None = None
    password_env: str | None = None
    imap_host: str | None = None
    imap_port: int = 993
    category_action: Literal["copy", "move"] | None = None
    model: ModelConfig
    triage_prompt: str
    draft_prompt: str
    categories: dict[str, str] = Field(default_factory=_default_categories)

    @field_validator("categories")
    @classmethod
    def valid_categories(cls, value: dict[str, str]) -> dict[str, str]:
        return AgentConfig.valid_categories(value)

    @property
    def agent(self) -> AgentConfig:
        """Return the internal agent view used by triage and drafting."""
        return AgentConfig(
            model=self.model,
            triage_prompt=self.triage_prompt,
            draft_prompt=self.draft_prompt,
            categories=self.categories,
        )

    @model_validator(mode="after")
    def provider_fields(self) -> AccountConfig:
        if self.provider == "imap" and not all(
            [self.username_env, self.password_env, self.imap_host]
        ):
            raise ValueError("IMAP accounts require credential env names and imap_host")
        if self.provider == "gmail" and self.category_action is not None:
            raise ValueError("category_action is only supported for IMAP accounts")
        return self
