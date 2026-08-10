from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from email_agent.cli import app
from email_agent.scaffolding import (
    AccountProvider,
    ModelProvider,
    ProfileTemplate,
    generate_account,
    generate_profile,
)

runner = CliRunner()


def project(tmp_path: Path) -> Path:
    (tmp_path / "accounts.yaml").write_text("accounts:\n  personal_gmail:\n    provider: gmail\n")
    return tmp_path


@pytest.mark.parametrize("template", list(ProfileTemplate))
def test_generates_each_profile_template(tmp_path, template):
    result = generate_profile(
        project(tmp_path),
        "work",
        "personal_gmail",
        template,
        model_provider=ModelProvider.OPENAI,
        model="gpt-5.4-mini",
    )
    profile = yaml.safe_load(result.profile.read_text())
    assert profile["id"] == "work"
    assert profile["account"] == "personal_gmail"
    assert profile["prompts"]["system"] == "prompts/work/system.md"
    assert all(path.is_file() for path in result.prompts)


def test_sets_selected_model_in_generated_profile(tmp_path):
    result = generate_profile(
        project(tmp_path),
        "work",
        "personal_gmail",
        ProfileTemplate.PERSONAL,
        model_provider=ModelProvider.OLLAMA,
        model="qwen3",
    )
    profile = yaml.safe_load(result.profile.read_text())
    assert profile["model"] == {"provider": "ollama", "model": "qwen3", "temperature": 0}


def test_refuses_to_overwrite_existing_profile(tmp_path):
    root = project(tmp_path)
    generate_profile(
        root,
        "work",
        "personal_gmail",
        ProfileTemplate.PERSONAL,
        model_provider=ModelProvider.OPENAI,
        model="gpt-5.4-mini",
    )
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        generate_profile(
            root,
            "work",
            "personal_gmail",
            ProfileTemplate.PERSONAL,
            model_provider=ModelProvider.OPENAI,
            model="gpt-5.4-mini",
        )


def test_rejects_unknown_account_and_unsafe_name(tmp_path):
    root = project(tmp_path)
    with pytest.raises(ValueError, match="not defined"):
        generate_profile(
            root,
            "work",
            "missing",
            ProfileTemplate.PERSONAL,
            model_provider=ModelProvider.OPENAI,
            model="gpt-5.4-mini",
        )
    with pytest.raises(ValueError, match="Profile name"):
        generate_profile(
            root,
            "../work",
            "personal_gmail",
            ProfileTemplate.PERSONAL,
            model_provider=ModelProvider.OPENAI,
            model="gpt-5.4-mini",
        )


def test_generates_gmail_account_and_creates_file(tmp_path):
    result = generate_account(tmp_path, "personal_gmail", AccountProvider.GMAIL)
    accounts = yaml.safe_load(result.path.read_text())["accounts"]
    assert accounts["personal_gmail"] == {
        "provider": "gmail",
        "credentials_file": "secrets/personal_gmail_credentials.json",
        "token_file": "secrets/personal_gmail_token.json",
    }


def test_adds_imap_account_without_removing_existing_accounts(tmp_path):
    generate_account(tmp_path, "personal_gmail", AccountProvider.GMAIL)
    generate_account(
        tmp_path,
        "support",
        AccountProvider.IMAP,
        email="support@example.com",
        imap_host="imap.example.com",
    )
    accounts = yaml.safe_load((tmp_path / "accounts.yaml").read_text())["accounts"]
    assert set(accounts) == {"personal_gmail", "support"}
    assert accounts["support"]["username_env"] == "SUPPORT_EMAIL_USERNAME"
    assert "smtp_host" not in accounts["support"]


def test_account_generator_validates_required_fields_and_overwrites(tmp_path):
    with pytest.raises(ValueError, match="require --email and --imap-host"):
        generate_account(tmp_path, "support", AccountProvider.IMAP)
    generate_account(tmp_path, "personal", AccountProvider.GMAIL)
    with pytest.raises(FileExistsError, match="already exists"):
        generate_account(tmp_path, "personal", AccountProvider.GMAIL)
    generate_account(
        tmp_path,
        "personal",
        AccountProvider.GMAIL,
        token_file="secrets/custom_token.json",
        force=True,
    )
    account = yaml.safe_load((tmp_path / "accounts.yaml").read_text())["accounts"]["personal"]
    assert account["token_file"] == "secrets/custom_token.json"


def test_top_level_help_shows_initialization_flow():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "email-agent account init personal_gmail --provider gmail" in result.output
    assert "email-agent profile init personal" in result.output
    assert "--provider openai --model gpt-5.4-mini" in result.output
