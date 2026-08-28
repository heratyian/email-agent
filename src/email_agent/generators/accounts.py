from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from pathlib import Path

import yaml

from email_agent.config import AccountConfig


class AgentTemplate(StrEnum):
    """Built-in prompt templates available during account creation."""

    PERSONAL = "personal"
    SUPPORT = "support"


class AccountProvider(StrEnum):
    """Mailbox providers supported by the account generator."""

    GMAIL = "gmail"
    IMAP = "imap"


class ModelProvider(StrEnum):
    """Model providers supported by the model factory."""

    OPENAI = "openai"
    OLLAMA = "ollama"
    COMPATIBLE = "compatible"


class CategoryAction(StrEnum):
    """How an IMAP account places messages into category folders."""

    COPY = "copy"
    MOVE = "move"


@dataclass(frozen=True)
class GeneratedAccount:
    """Configuration and prompts created for one account."""

    path: Path
    account_id: str
    triage_prompt: Path
    draft_prompt: Path


def _validate_email(value: str) -> None:
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError("Account ID must be a valid email address")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def generate_account(
    root: Path,
    email: str,
    provider: AccountProvider,
    template: AgentTemplate,
    *,
    model_provider: ModelProvider,
    model: str,
    imap_host: str | None = None,
    imap_port: int = 993,
    username_env: str | None = None,
    password_env: str | None = None,
    credentials_file: str | None = None,
    token_file: str | None = None,
    category_action: CategoryAction | None = None,
    force: bool = False,
) -> GeneratedAccount:
    """Create one flat email-address account and its prompts."""
    root = root.resolve()
    _validate_email(email)
    path = root / "accounts.yaml"
    slug = _slug(email)
    prompt_dir = root / "prompts" / slug
    triage_prompt = prompt_dir / "triage.md"
    draft_prompt = prompt_dir / "draft.md"

    raw = yaml.safe_load(path.read_text()) if path.is_file() else None
    if raw is None:
        raw = {"accounts": {}}
    if not isinstance(raw, dict) or not isinstance(raw.get("accounts"), dict):
        raise TypeError("accounts.yaml must contain an 'accounts' mapping")
    if email in raw["accounts"] and not force:
        raise FileExistsError(f"Account '{email}' already exists in accounts.yaml")
    for prompt in (triage_prompt, draft_prompt):
        if prompt.exists() and not force:
            raise FileExistsError(
                f"Refusing to overwrite existing file: {prompt.relative_to(root)}"
            )

    template_directory = "support" if template is AgentTemplate.SUPPORT else template.value
    template_root = files("email_agent.generators").joinpath("templates", template_directory)
    account_text = template_root.joinpath("account.yaml").read_text()
    replacements = {
        "MODEL_PROVIDER": model_provider.value,
        "MODEL_NAME": model,
        "PROMPT_DIR": f"prompts/{slug}",
    }
    for placeholder, value in replacements.items():
        account_text = account_text.replace(f"{{{{{placeholder}}}}}", value)

    env_prefix = re.sub(r"[^A-Z0-9]", "_", email.upper())
    account: dict = {"provider": provider.value}
    if provider is AccountProvider.GMAIL:
        if category_action is not None:
            raise ValueError("--category-action is only supported for IMAP accounts")
        account.update(
            {
                "credentials_file": credentials_file or f"secrets/{slug}_credentials.json",
                "token_file": token_file or f"secrets/{slug}_token.json",
            }
        )
    else:
        if not imap_host:
            raise ValueError("IMAP accounts require --imap-host")
        account.update(
            {
                "username_env": username_env or f"{env_prefix}_USERNAME",
                "password_env": password_env or f"{env_prefix}_PASSWORD",
                "imap_host": imap_host,
                "imap_port": imap_port,
            }
        )
        if category_action is not None:
            account["category_action"] = category_action.value
    account.update(yaml.safe_load(account_text))
    AccountConfig.model_validate({"email": email, **account})

    raw["accounts"][email] = account
    prompt_dir.mkdir(parents=True, exist_ok=True)
    triage_prompt.write_text(
        template_root.joinpath("triage.md").read_text()
    )
    draft_prompt.write_text(template_root.joinpath("draft.md").read_text())
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return GeneratedAccount(
        path=path,
        account_id=email,
        triage_prompt=triage_prompt,
        draft_prompt=draft_prompt,
    )
