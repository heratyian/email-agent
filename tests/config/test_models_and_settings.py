from pathlib import Path

import pytest

from email_agent.config import AccountConfig, Settings


def write_account_config(root: Path) -> None:
    (root / "accounts.yaml").write_text(
        """
accounts:
  person@example.com:
    provider: gmail
    credentials_file: secrets/credentials.json
    token_file: secrets/token.json
    model: {provider: openai, model: test-model}
    classification_prompt: prompts/person/classification.md
    draft_prompt: prompts/person/draft.md
"""
    )


def test_account_uses_mapping_key_as_email_and_always_supports_drafts(tmp_path):
    write_account_config(tmp_path)
    settings = Settings(tmp_path)
    account = settings.account("person@example.com")
    assert account.email == "person@example.com"
    assert account.agent.categories["action"].startswith("Requires")


def test_category_action_is_imap_only():
    with pytest.raises(ValueError, match="only supported for IMAP"):
        AccountConfig.model_validate(
            {
                "provider": "gmail",
                "category_action": "move",
                "email": "person@example.com",
                "model": {"provider": "openai", "model": "test"},
                "classification_prompt": "prompts/classification.md",
                "draft_prompt": "prompts/draft.md",
            }
        )


def test_nested_category_paths_are_validated(tmp_path):
    write_account_config(tmp_path)
    raw = (tmp_path / "accounts.yaml").read_text()
    (tmp_path / "accounts.yaml").write_text(
        raw.replace(
            "    classification_prompt:",
            "    categories:\n      agent/follow_up: Needs my response.\n    classification_prompt:",
        )
    )
    agent = Settings(tmp_path).account("person@example.com").agent
    assert agent.categories["agent/follow_up"] == "Needs my response."


def test_unknown_account_is_rejected(tmp_path):
    write_account_config(tmp_path)
    with pytest.raises(ValueError, match="Unknown account"):
        Settings(tmp_path).account("missing@example.com")


def test_environment_configures_database_path(tmp_path, monkeypatch):
    write_account_config(tmp_path)
    monkeypatch.setenv("EMAIL_AGENT_DATABASE", "state/custom.db")
    settings = Settings(tmp_path)
    assert settings.database_path == Path(tmp_path, "state/custom.db")
