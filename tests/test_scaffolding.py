from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner

from email_agent import cli
from email_agent.cli import app
from email_agent.config import AgentConfig
from email_agent.models import EmailClassification, EmailMessage, EmailThread
from email_agent.scaffolding import (
    AccountProvider,
    AgentTemplate,
    CategoryAction,
    ModelProvider,
    generate_account,
)

runner = CliRunner()


@pytest.mark.parametrize("template", list(AgentTemplate))
def test_generates_flat_account_with_system_prompt(tmp_path, template):
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
    assert account["system_prompt"].startswith("prompts/person-example-com/")
    assert result.system_prompt.is_file()


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


def test_top_level_help_shows_combined_account_initialization():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "account init me@example.com" in result.output
    assert "profile init" not in result.output
    assert "smtp" not in result.output.lower()
    assert "--verbose" in result.output


@pytest.mark.parametrize(
    ("arguments", "level"),
    [
        (["-v", "accounts"], 1),
        (["accounts", "-v"], 1),
        (["accounts", "--verbose"], 1),
        (["accounts", "-vv"], 2),
    ],
)
def test_verbose_flag_is_accepted_anywhere(monkeypatch, arguments, level):
    configured = []
    monkeypatch.setattr(cli, "configure_logging", configured.append)
    monkeypatch.setattr(cli.AccountService, "list", lambda self: {})

    result = runner.invoke(app, arguments)

    assert result.exit_code == 0
    assert configured[-1] == level


@pytest.mark.parametrize(
    "arguments",
    [
        ["--trace-model", "accounts"],
        ["accounts", "--trace-model"],
    ],
)
def test_trace_model_flag_is_accepted_anywhere(monkeypatch, arguments):
    configured = []
    monkeypatch.setattr(cli, "configure_model_tracing", configured.append)
    monkeypatch.setattr(cli.AccountService, "list", lambda self: {})

    result = runner.invoke(app, arguments)

    assert result.exit_code == 0
    assert configured[-1] is True


@pytest.mark.parametrize(
    "command",
    [
        ["accounts"],
        ["inbox"],
        ["process"],
        ["organize"],
        ["monitor"],
        ["drafts"],
        ["show"],
        ["draft"],
        ["approve"],
        ["done"],
        ["snooze"],
        ["reopen"],
        ["config"],
        ["config", "validate"],
        ["account"],
        ["account", "init"],
    ],
)
@pytest.mark.parametrize("flag", ["-v", "-vv", "--trace-model"])
def test_diagnostic_flags_are_global_for_every_command(command, flag):
    result = runner.invoke(app, [*command, "--help", flag])

    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_verbose_and_model_trace_can_be_combined_after_command(monkeypatch):
    verbosity = []
    tracing = []
    monkeypatch.setattr(cli, "configure_logging", verbosity.append)
    monkeypatch.setattr(cli, "configure_model_tracing", tracing.append)
    monkeypatch.setattr(cli.AccountService, "list", lambda self: {})

    result = runner.invoke(app, ["accounts", "-v", "--trace-model", "-v"])

    assert result.exit_code == 0
    assert verbosity[-1] == 2
    assert tracing[-1] is True


def test_inbox_help_uses_account_and_attention_views():
    result = runner.invoke(app, ["inbox", "--help"])
    assert result.exit_code == 0
    assert "--account" in result.output
    assert "--profile" not in result.output
    assert all(option in result.output for option in ("--snoozed", "--done", "--all"))


@pytest.mark.parametrize("command", ["done", "snooze", "reopen", "organize"])
def test_attention_commands_are_in_top_level_help(command):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert command in result.output


def test_organize_help_includes_reclassification_options():
    result = runner.invoke(app, ["organize", "--help"])
    assert result.exit_code == 0
    assert "--reclassify-unknown" in result.output
    assert "--reclassify-all" in result.output


class ReclassificationDatabase:
    def __init__(self, classification):
        self.classification = classification

    def list_categorized_messages(self, account, limit):
        return [
            {
                "id": 77,
                "provider_message_id": "provider-77",
                "provider_uid": "provider-77",
                "provider_mailbox": "INBOX",
                "subject": "Old classification",
                "classification": self.classification.model_dump_json(),
            }
        ]

    def category_was_synced(self, message_id, destination):
        return False


class ReclassificationProvider:
    def get_message(self, message_id, mailbox="INBOX"):
        return EmailMessage.model_construct(provider_id=message_id)

    def get_thread(self, message_id, mailbox="INBOX"):
        return EmailThread(messages=[])

    @staticmethod
    def category_sync_key(destination):
        return destination


class ReclassificationAgents:
    def classify(self, message, thread):
        return EmailClassification(
            category="action",
            requires_reply=True,
            priority="normal",
            summary="Needs a reply",
            confidence=0.9,
        )


def test_reclassify_all_accepts_unknown_stored_category(monkeypatch):
    agent = AgentConfig.model_validate(
        {
            "model": {"provider": "openai", "model": "test"},
            "system_prompt": "prompts/test/system.md",
            "categories": {"action": "Requires my response."},
        }
    )
    configured = SimpleNamespace(email="person@example.com", agent=agent)
    old = EmailClassification(
        category="informational",
        requires_reply=False,
        priority="normal",
        summary="Old taxonomy",
        confidence=0.9,
    )
    monkeypatch.setattr(
        cli,
        "_runtime",
        lambda account, with_agents: SimpleNamespace(
            account=configured,
            provider=ReclassificationProvider(),
            database=ReclassificationDatabase(old),
            agents=ReclassificationAgents(),
        ),
    )

    result = runner.invoke(
        app,
        [
            "organize",
            "--account",
            "person@example.com",
            "--dry-run",
            "--reclassify-all",
        ],
    )

    assert result.exit_code == 0
    assert "reclassified as action" in result.output
    assert "unknown category" not in result.output
