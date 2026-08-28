from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from email_agent.cli import app
from email_agent.cli.shell import InteractiveShell, ShellSession


class FakeHandlers:
    def __init__(self, accounts=None):
        self._accounts = accounts or {
            "person@example.com": SimpleNamespace(provider="gmail")
        }

    def accounts(self):
        return self._accounts


@pytest.mark.parametrize(
    ("line", "method", "arguments"),
    [
        ("/inbox 5", "_inbox", ["5"]),
        ("/search recent important messages", "_search", ["recent important messages"]),
        (
            "/search What's the most important message?",
            "_search",
            ["What's the most important message?"],
        ),
        ("/classify 12", "_classify", ["12"]),
        ("/show 12", "_show", ["12"]),
        ("/draft 12 keep it short", "_draft", ["12", "keep", "it", "short"]),
        ("/drafts", "_drafts", []),
        ("/review", "_review", []),
        ("/upload 12", "_upload", ["12"]),
        ("/delete-draft 12", "_delete_draft", ["12"]),
        ("/account person@example.com", "_account", ["person@example.com"]),
        ("/verbose debug", "_verbose", ["debug"]),
        ("/trace-model on", "_trace_model", ["on"]),
        ("/help", "_help", []),
    ],
)
def test_every_slash_command_dispatches_without_a_router(monkeypatch, line, method, arguments):
    shell = InteractiveShell(ShellSession("person@example.com"), FakeHandlers())
    calls = []
    monkeypatch.setattr(shell, method, calls.append)

    shell.dispatch(line)

    assert calls == [arguments]


def test_unknown_and_malformed_commands_do_not_raise(capsys):
    shell = InteractiveShell(ShellSession("person@example.com"), FakeHandlers())

    shell.dispatch("/unknown")
    shell.dispatch("/show")

    output = capsys.readouterr().out
    assert "Unknown command" in output
    assert "Usage: /show LOCAL_ID" in output


def test_multiple_accounts_are_selected_before_the_prompt(capsys):
    handlers = FakeHandlers(
        {
            "one@example.com": SimpleNamespace(provider="gmail"),
            "two@example.com": SimpleNamespace(provider="imap"),
        }
    )
    answers = iter(["2", "/quit"])
    shell = InteractiveShell(
        ShellSession(None), handlers, prompt=lambda *args, **kwargs: next(answers)
    )

    shell.run()

    assert shell.session.account_id == "two@example.com"
    assert "Choose an account:" in capsys.readouterr().out


def test_service_failure_returns_to_prompt(capsys):
    answers = iter(["/drafts", "/quit"])
    handlers = FakeHandlers()
    handlers.list_drafts = lambda account: (_ for _ in ()).throw(RuntimeError("provider down"))
    shell = InteractiveShell(
        ShellSession(None), handlers, prompt=lambda *args, **kwargs: next(answers)
    )

    shell.run()

    assert "Error: provider down" in capsys.readouterr().out


def test_eof_exits_cleanly():
    shell = InteractiveShell(
        ShellSession(None), FakeHandlers(), prompt=lambda *args, **kwargs: (_ for _ in ()).throw(EOFError)
    )

    shell.run()


def test_no_command_starts_shell_and_help_does_not(monkeypatch):
    calls = []
    monkeypatch.setattr("email_agent.cli.shell.run_shell", lambda **kwargs: calls.append(kwargs))
    runner = CliRunner()

    result = runner.invoke(app, ["-vv", "--trace-model"])
    help_result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert calls == [{"verbosity": 2, "trace_model": True}]
    assert help_result.exit_code == 0
    assert "Usage:" in help_result.output


def test_draft_guidance_is_one_call_data():
    class Handlers(FakeHandlers):
        def message_account(self, message_id):
            return "person@example.com"

        def generate_draft(self, message_id, instruction):
            self.generated = (message_id, instruction)

    handlers = Handlers()
    shell = InteractiveShell(ShellSession("person@example.com"), handlers)

    shell.dispatch('/draft 203 "politely decline"')

    assert handlers.generated == (203, "politely decline")
