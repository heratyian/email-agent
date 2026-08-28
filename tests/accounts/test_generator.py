import pytest
import yaml

from email_agent.accounts.generator import (
    AccountProvider,
    AgentTemplate,
    CategoryAction,
    ModelProvider,
    generate_account,
)


@pytest.mark.parametrize("template", list(AgentTemplate))
def test_generates_flat_account_with_separate_prompts(tmp_path, template):
    result = generate_account(
        tmp_path,
        "person@example.com",
        AccountProvider.GMAIL,
        template,
        model_provider=ModelProvider.OPENAI,
        model="test-model",
    )
    account = yaml.safe_load(result.path.read_text())["accounts"]["person@example.com"]
    assert "email" not in account
    assert "agent" not in account
    assert account["model"]["model"] == "test-model"
    assert account["triage_prompt"].endswith("/triage.md")
    assert account["draft_prompt"].endswith("/draft.md")
    assert result.triage_prompt.is_file()
    assert result.draft_prompt.is_file()


def test_generates_imap_credentials_as_environment_references(tmp_path):
    result = generate_account(
        tmp_path,
        "support@example.com",
        AccountProvider.IMAP,
        AgentTemplate.SUPPORT,
        model_provider=ModelProvider.OLLAMA,
        model="qwen3",
        imap_host="imap.example.com",
        category_action=CategoryAction.MOVE,
    )
    account = yaml.safe_load(result.path.read_text())["accounts"][result.account_id]
    assert account["username_env"] == "SUPPORT_EXAMPLE_COM_USERNAME"
    assert account["password_env"] == "SUPPORT_EXAMPLE_COM_PASSWORD"
    assert account["model"]["provider"] == "ollama"
    assert account["category_action"] == "move"


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
