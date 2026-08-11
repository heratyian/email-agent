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
      prompts:
        system: prompts/person/system.md
        classify: prompts/person/classify.md
        reply: prompts/person/reply.md
      safety: {allow_drafts: true, allow_send: false}
"""
    )


def test_account_contains_valid_draft_only_agent(tmp_path):
    write_account_config(tmp_path)
    settings = Settings(tmp_path)
    account = settings.account("person@example.com")
    assert account.email == "person@example.com"
    assert account.agent.safety.allow_send is False


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
