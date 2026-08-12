import importlib
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from email_agent.cli import app

runner = CliRunner()
cli = importlib.import_module("email_agent.cli.app")


def test_top_level_help_presents_four_user_concepts():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert all(command in result.output for command in ("inbox", "drafts", "message", "account"))
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
    monkeypatch.setattr(cli.AccountService, "list", lambda self: {})

    result = runner.invoke(app, arguments)

    assert result.exit_code == 0
    assert configured[-1] == level


@pytest.mark.parametrize(
    "arguments", [["--trace-model", "account"], ["account", "--trace-model"]]
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
        ["inbox"],
        ["drafts"],
        ["drafts", "show"],
        ["drafts", "review"],
        ["drafts", "upload"],
        ["drafts", "delete"],
        ["message"],
        ["message", "show"],
        ["message", "done"],
        ["message", "snooze"],
        ["message", "reopen"],
        ["account"],
        ["account", "add"],
        ["account", "validate"],
    ],
)
@pytest.mark.parametrize("flag", ["-v", "-vv", "--trace-model"])
def test_diagnostic_flags_are_global_for_every_command(command, flag):
    result = runner.invoke(app, [*command, "--help", flag])

    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_account_without_subcommand_lists_accounts(monkeypatch):
    monkeypatch.setattr(
        cli.AccountService,
        "list",
        lambda self: {"person@example.com": SimpleNamespace(provider="gmail")},
    )

    result = runner.invoke(app, ["account"])

    assert result.exit_code == 0
    assert "person@example.com: gmail" in result.output


def test_single_account_can_be_used_without_account_option(monkeypatch):
    monkeypatch.setattr(
        cli.AccountService,
        "list",
        lambda self: {"person@example.com": SimpleNamespace(provider="gmail")},
    )

    assert cli._account_id(None) == "person@example.com"


def test_multiple_accounts_require_an_explicit_account(monkeypatch):
    monkeypatch.setattr(
        cli.AccountService,
        "list",
        lambda self: {
            "one@example.com": SimpleNamespace(provider="gmail"),
            "two@example.com": SimpleNamespace(provider="imap"),
        },
    )

    with pytest.raises(Exception, match="Multiple accounts configured"):
        cli._account_id(None)


def test_inbox_help_describes_the_combined_workflow():
    result = runner.invoke(app, ["inbox", "--help"])

    assert result.exit_code == 0
    assert all(option in result.output for option in ("--watch", "--dry-run", "--reorganize"))
    assert all(option in result.output for option in ("--snoozed", "--done", "--all"))


def test_nested_commands_are_discoverable():
    expectations = {
        "account": ("add", "validate"),
        "drafts": ("show", "review", "upload", "delete"),
        "message": ("show", "done", "snooze", "reopen"),
    }
    for group, commands in expectations.items():
        result = runner.invoke(app, [group, "--help"])
        assert result.exit_code == 0
        assert all(command in result.output for command in commands)
