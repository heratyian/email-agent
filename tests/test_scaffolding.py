import pytest
import yaml
from typer.testing import CliRunner

from email_agent.cli import app
from email_agent.scaffolding import (
    AccountProvider,
    AgentTemplate,
    ModelProvider,
    generate_account,
)

runner = CliRunner()


@pytest.mark.parametrize("template", list(AgentTemplate))
def test_generates_account_with_nested_agent_and_prompts(tmp_path, template):
    result = generate_account(
        tmp_path,
        "person@example.com",
        AccountProvider.GMAIL,
        template,
        model_provider=ModelProvider.OPENAI,
        model="test-model",
    )
    account = yaml.safe_load(result.path.read_text())["accounts"]["person@example.com"]
    assert account["email"] == "person@example.com"
    assert account["agent"]["model"]["model"] == "test-model"
    assert account["agent"]["prompts"]["system"].startswith("prompts/person-example-com/")
    assert all(path.is_file() for path in result.prompts)


def test_generates_imap_credentials_as_environment_references(tmp_path):
    result = generate_account(
        tmp_path,
        "support@example.com",
        AccountProvider.IMAP,
        AgentTemplate.SUPPORT,
        model_provider=ModelProvider.OLLAMA,
        model="qwen3",
        imap_host="imap.example.com",
    )
    account = yaml.safe_load(result.path.read_text())["accounts"][result.account_id]
    assert account["username_env"] == "SUPPORT_EXAMPLE_COM_USERNAME"
    assert account["password_env"] == "SUPPORT_EXAMPLE_COM_PASSWORD"
    assert account["agent"]["model"]["provider"] == "ollama"


def test_generator_refuses_duplicates_and_invalid_email(tmp_path):
    kwargs = {
        "model_provider": ModelProvider.OPENAI,
        "model": "test-model",
    }
    generate_account(
        tmp_path,
        "person@example.com",
        AccountProvider.GMAIL,
        AgentTemplate.PERSONAL,
        **kwargs,
    )
    with pytest.raises(FileExistsError, match="already exists"):
        generate_account(
            tmp_path,
            "person@example.com",
            AccountProvider.GMAIL,
            AgentTemplate.PERSONAL,
            **kwargs,
        )
    with pytest.raises(ValueError, match="valid email"):
        generate_account(
            tmp_path,
            "not-an-email",
            AccountProvider.GMAIL,
            AgentTemplate.PERSONAL,
            **kwargs,
        )


def test_top_level_help_shows_combined_account_initialization():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "account init me@example.com" in result.output
    assert "profile init" not in result.output


def test_inbox_help_uses_account_and_explains_states():
    result = runner.invoke(app, ["inbox", "--help"])
    assert result.exit_code == 0
    assert "--account" in result.output
    assert "--profile" not in result.output
    assert all(state in result.output for state in ("NEW", "TRIAGED", "PROCESSED"))
