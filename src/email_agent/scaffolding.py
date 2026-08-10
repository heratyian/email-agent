from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from pathlib import Path

import yaml


class ProfileTemplate(StrEnum):
    """Built-in starting points supported by the profile generator."""

    PERSONAL = "personal"
    CUSTOMER_SUPPORT = "customer_support"


class AccountProvider(StrEnum):
    """Mailbox providers supported by the account generator."""

    GMAIL = "gmail"
    IMAP = "imap"


class ModelProvider(StrEnum):
    """Model providers supported by the model factory and profile generator."""

    OPENAI = "openai"
    OLLAMA = "ollama"
    COMPATIBLE = "compatible"


@dataclass(frozen=True)
class GeneratedProfile:
    """Paths created by a profile generation operation."""

    profile: Path
    prompts: tuple[Path, ...]


@dataclass(frozen=True)
class GeneratedAccount:
    """Result of an account generation operation."""

    path: Path
    account_id: str


def _validate_identifier(name: str, kind: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
        raise ValueError(
            f"{kind} name must start with a lowercase letter and contain only "
            "lowercase letters, numbers, underscores, or hyphens"
        )


def _validate_account(root: Path, account: str) -> None:
    accounts_path = root / "accounts.yaml"
    if not accounts_path.is_file():
        raise ValueError(
            "accounts.yaml was not found; create an account first with 'email-agent account init'"
        )
    raw = yaml.safe_load(accounts_path.read_text()) or {}
    if account not in raw.get("accounts", {}):
        raise ValueError(f"Account '{account}' is not defined in accounts.yaml")


def generate_profile(
    root: Path,
    name: str,
    account: str,
    template: ProfileTemplate,
    *,
    display_name: str | None = None,
    model_provider: ModelProvider,
    model: str,
    force: bool = False,
) -> GeneratedProfile:
    """Generate a private profile and its prompts from a built-in template."""
    root = root.resolve()
    _validate_identifier(name, "Profile")
    _validate_account(root, account)

    profile_path = root / "profiles" / f"{name}.yaml"
    prompt_dir = root / "prompts" / name
    prompt_paths = tuple(
        prompt_dir / filename for filename in ("system.md", "classify.md", "reply.md")
    )
    destinations = (profile_path, *prompt_paths)
    existing = [path for path in destinations if path.exists()]
    if existing and not force:
        rendered = ", ".join(str(path.relative_to(root)) for path in existing)
        raise FileExistsError(f"Refusing to overwrite existing files: {rendered}")

    template_root = files("email_agent").joinpath("templates", template.value)
    profile_text = template_root.joinpath("profile.yaml").read_text()
    replacements = {
        "PROFILE_ID": name,
        "PROFILE_NAME": display_name or name.replace("_", " ").replace("-", " ").title(),
        "ACCOUNT_ID": account,
        "MODEL_PROVIDER": model_provider.value,
        "MODEL_NAME": model,
    }
    for placeholder, value in replacements.items():
        profile_text = profile_text.replace(f"{{{{{placeholder}}}}}", value)

    profile_data = yaml.safe_load(profile_text)

    profile_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_dir.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(yaml.safe_dump(profile_data, sort_keys=False))
    for destination in prompt_paths:
        destination.write_text(template_root.joinpath(destination.name).read_text())

    return GeneratedProfile(profile=profile_path, prompts=prompt_paths)


def generate_account(
    root: Path,
    name: str,
    provider: AccountProvider,
    *,
    email: str | None = None,
    imap_host: str | None = None,
    imap_port: int = 993,
    smtp_host: str | None = None,
    smtp_port: int = 465,
    username_env: str | None = None,
    password_env: str | None = None,
    credentials_file: str | None = None,
    token_file: str | None = None,
    force: bool = False,
) -> GeneratedAccount:
    """Create or add an account entry without placing secrets in YAML."""
    root = root.resolve()
    _validate_identifier(name, "Account")
    path = root / "accounts.yaml"

    raw = yaml.safe_load(path.read_text()) if path.is_file() else None
    if raw is None:
        raw = {"accounts": {}}
    if not isinstance(raw, dict) or not isinstance(raw.get("accounts"), dict):
        raise TypeError("accounts.yaml must contain an 'accounts' mapping")
    if name in raw["accounts"] and not force:
        raise FileExistsError(f"Account '{name}' already exists in accounts.yaml")

    if provider is AccountProvider.GMAIL:
        account = {
            "provider": "gmail",
            "credentials_file": credentials_file or f"secrets/{name}_credentials.json",
            "token_file": token_file or f"secrets/{name}_token.json",
        }
    else:
        if not email or not imap_host:
            raise ValueError("IMAP accounts require --email and --imap-host")
        env_prefix = re.sub(r"[^A-Z0-9]", "_", name.upper())
        account = {
            "provider": "imap",
            "email": email,
            "username_env": username_env or f"{env_prefix}_EMAIL_USERNAME",
            "password_env": password_env or f"{env_prefix}_EMAIL_PASSWORD",
            "imap_host": imap_host,
            "imap_port": imap_port,
        }
        if smtp_host:
            account.update({"smtp_host": smtp_host, "smtp_port": smtp_port})

    raw["accounts"][name] = account
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return GeneratedAccount(path=path, account_id=name)
