import importlib
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from email_agent.cli import app
from email_agent.config import AgentConfig
from email_agent.models import EmailClassification, EmailMessage, EmailThread

runner = CliRunner()
cli = importlib.import_module("email_agent.cli.app")


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
