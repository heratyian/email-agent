import importlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from email_agent.cli import app

runner = CliRunner()
cli = importlib.import_module("email_agent.cli.app")


def test_cli_loads_project_env_before_running_a_command(monkeypatch):
    loaded = []
    monkeypatch.setattr(cli, "load_dotenv", lambda path, override: loaded.append((path, override)))
    monkeypatch.setattr(cli.CommandHandlers, "accounts", lambda self: {})

    result = runner.invoke(app, ["account"])

    assert result.exit_code == 0
    assert loaded == [(cli.PROJECT_ROOT / ".env", True)]


def test_top_level_help_presents_the_user_workflows():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert all(
        command in result.output
        for command in ("inbox", "classify", "drafts", "message", "account", "evaluate")
    )
    assert all(
        command not in result.output
        for command in ("process  ", "organize  ", "monitor  ", "accounts  ", "config  ")
    )
    assert "account add me@example.com" in result.output


@pytest.mark.parametrize(
    ("arguments", "level"),
    [
        (["-v", "account"], 1),
        (["account", "-v"], 1),
        (["account", "--verbose"], 1),
        (["account", "-vv"], 2),
    ],
)
def test_verbose_flag_is_accepted_anywhere(monkeypatch, arguments, level):
    configured = []
    monkeypatch.setattr(cli, "configure_logging", configured.append)
    monkeypatch.setattr(cli.CommandHandlers, "accounts", lambda self: {})

    result = runner.invoke(app, arguments)

    assert result.exit_code == 0
    assert configured[-1] == level


@pytest.mark.parametrize(
    "arguments", [["--trace-model", "account"], ["account", "--trace-model"]]
)
def test_trace_model_flag_is_accepted_anywhere(monkeypatch, arguments):
    configured = []
    monkeypatch.setattr(cli, "configure_model_tracing", configured.append)
    monkeypatch.setattr(cli.CommandHandlers, "accounts", lambda self: {})

    result = runner.invoke(app, arguments)

    assert result.exit_code == 0
    assert configured[-1] is True


@pytest.mark.parametrize(
    "command",
    [
        ["inbox"],
        ["classify"],
        ["drafts"],
        ["drafts", "show"],
        ["drafts", "generate"],
        ["drafts", "review"],
        ["drafts", "upload"],
        ["drafts", "delete"],
        ["message"],
        ["message", "show"],
        ["account"],
        ["account", "add"],
        ["account", "validate"],
        ["evaluate"],
        ["evaluate", "classification"],
        ["evaluate", "drafting"],
    ],
)
@pytest.mark.parametrize("flag", ["-v", "-vv", "--trace-model"])
def test_diagnostic_flags_are_global_for_every_command(command, flag):
    result = runner.invoke(app, [*command, "--help", flag])

    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_account_without_subcommand_lists_accounts(monkeypatch):
    monkeypatch.setattr(
        cli.CommandHandlers,
        "accounts",
        lambda self: {"person@example.com": SimpleNamespace(provider="gmail")},
    )

    result = runner.invoke(app, ["account"])

    assert result.exit_code == 0
    assert "person@example.com: gmail" in result.output


def test_single_account_can_be_used_without_account_option(monkeypatch):
    monkeypatch.setattr(
        cli.CommandHandlers,
        "accounts",
        lambda self: {"person@example.com": SimpleNamespace(provider="gmail")},
    )

    assert cli._account_id(None) == "person@example.com"


def test_multiple_accounts_require_an_explicit_account(monkeypatch):
    monkeypatch.setattr(
        cli.CommandHandlers,
        "accounts",
        lambda self: {
            "one@example.com": SimpleNamespace(provider="gmail"),
            "two@example.com": SimpleNamespace(provider="imap"),
        },
    )

    with pytest.raises(Exception, match="Multiple accounts configured"):
        cli._account_id(None)


def test_inbox_help_describes_a_non_ai_mailbox_view():
    result = runner.invoke(app, ["inbox", "--help"])

    assert result.exit_code == 0
    assert "--watch" in result.output
    assert all(option not in result.output for option in ("--dry-run", "--reorganize", "--all"))
    assert "without using AI" in result.output


def test_classify_help_describes_stored_unclassified_messages():
    result = runner.invoke(app, ["classify", "--help"])

    assert result.exit_code == 0
    assert "--all" not in result.output
    assert "unclassified" in result.output
    assert "managed mailbox labels" in result.output


def test_nested_commands_are_discoverable():
    expectations = {
        "account": ("add", "validate"),
        "drafts": ("show", "generate", "review", "upload", "delete"),
        "evaluate": ("classification", "drafting"),
        "message": ("show",),
    }
    for group, commands in expectations.items():
        result = runner.invoke(app, [group, "--help"])
        assert result.exit_code == 0
        assert all(command in result.output for command in commands)


def test_draft_review_shows_original_message_and_suggested_reply(monkeypatch):
    from email_agent.db import Draft

    class Handlers:
        def list_drafts(self, account):
            return [
                Draft(
                    message_id=175,
                    recipient="sender@example.com",
                    subject="Re: A question",
                    body="Suggested answer.",
                    status="generated",
                )
            ]

        def source_message(self, message_id):
            return SimpleNamespace(
                from_name="Karen Hall",
                from_address="sender@example.com",
                subject="A question",
                received_at=datetime(2026, 8, 12, 12, tzinfo=UTC),
                content="Original email body.",
            )

    monkeypatch.setattr(cli, "CommandHandlers", Handlers)

    result = runner.invoke(app, ["drafts", "review"], input="q\n")

    assert result.exit_code == 0
    assert "Original message" in result.output
    assert "Karen Hall" in result.output
    assert "Original email body." in result.output
    assert "Suggested reply" in result.output
    assert "Suggested answer." in result.output
