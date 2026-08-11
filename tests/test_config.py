from pathlib import Path

import pytest

from email_agent.config import Settings


def write_account_config(root: Path) -> None:
    (root / "accounts.yaml").write_text(
        """
accounts:
  person@example.com:
    provider: gmail
    email: person@example.com
    credentials_file: secrets/credentials.json
    token_file: secrets/token.json
    agent:
      name: Personal Agent
      model: {provider: openai, model: test-model}
      system_prompt: prompts/person/system.md
      safety: {allow_drafts: true, allow_send: false}
"""
    )


def test_account_contains_valid_draft_only_agent(tmp_path):
    write_account_config(tmp_path)
    settings = Settings(tmp_path)
    account = settings.account("person@example.com")
    assert account.email == "person@example.com"
    assert account.agent.safety.allow_send is False
    assert account.agent.organization.enabled is True
    assert account.agent.categories["action"].startswith("Requires")


def test_category_shorthand_and_provider_names_are_validated(tmp_path):
    write_account_config(tmp_path)
    raw = (tmp_path / "accounts.yaml").read_text()
    (tmp_path / "accounts.yaml").write_text(
        raw.replace(
            "      safety:",
            "      categories:\n        follow_up: Needs my response.\n"
            "      organization: {enabled: true, prefix: Assistant}\n      safety:",
        )
    )
    agent = Settings(tmp_path).account("person@example.com").agent
    assert agent.categories["follow_up"] == "Needs my response."
    assert agent.organization.prefix == "Assistant"


def test_unknown_account_is_rejected(tmp_path):
    write_account_config(tmp_path)
    with pytest.raises(ValueError, match="Unknown account"):
        Settings(tmp_path).account("missing@example.com")


def test_env_file_configures_database_path(tmp_path, monkeypatch):
    write_account_config(tmp_path)
    (tmp_path / ".env").write_text("EMAIL_AGENT_DATABASE=state/custom.db\n")
    monkeypatch.delenv("EMAIL_AGENT_DATABASE", raising=False)
    settings = Settings(tmp_path)
    assert settings.database_path == Path(tmp_path, "state/custom.db")
