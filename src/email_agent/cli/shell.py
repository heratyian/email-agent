from __future__ import annotations

import logging
import shlex
from collections.abc import Callable
from dataclasses import dataclass

import typer

from email_agent.cli.commands import CommandHandlers
from email_agent.cli.logging import configure_logging, warn_model_tracing
from email_agent.cli.rendering import (
    render_draft,
    render_draft_list,
    render_inbox_items,
    render_inbox_search_response,
    render_message_details,
    render_review_item,
    render_triage_results,
)
from email_agent.diagnostics import configure_model_tracing

logger = logging.getLogger(__name__)
DEFAULT_INBOX_LIMIT = 20


@dataclass
class ShellSession:
    account_id: str | None
    verbosity: int = 0
    trace_model: bool = False


class ShellUsageError(ValueError):
    pass


class InteractiveShell:
    """Interactive shell with explicit commands and constrained natural language."""

    def __init__(
        self,
        session: ShellSession,
        handlers: CommandHandlers | None = None,
        *,
        prompt: Callable[..., str] = typer.prompt,
    ):
        self.session = session
        self.handlers = handlers or CommandHandlers()
        self.prompt = prompt
        self._interrupted_empty_prompt = False
        self._assistant = None
        self._assistant_account_id: str | None = None

    def run(self) -> None:
        typer.secho("Email Agent", bold=True)
        if not self._select_initial_account():
            return
        typer.echo(f"Account: {self.session.account_id}")
        typer.echo("Type /help for commands.\n")
        while True:
            try:
                line = self.prompt(">", prompt_suffix=" ", default="", show_default=False)
                self._interrupted_empty_prompt = False
            except EOFError:
                typer.echo()
                return
            except KeyboardInterrupt:
                typer.echo("\nPress Ctrl-C again at the prompt to quit.")
                if self._interrupted_empty_prompt:
                    return
                self._interrupted_empty_prompt = True
                continue
            if line.strip() in {"quit", "/quit", "/exit"}:
                return
            if not line.strip():
                continue
            try:
                self.dispatch(line)
            except KeyboardInterrupt:
                typer.echo("\nCancelled.")
            except (LookupError, RuntimeError, ValueError) as exc:
                typer.secho(f"Error: {exc}", fg=typer.colors.RED)
            except Exception as exc:
                logger.exception("Shell command failed")
                typer.secho(f"Error: {exc}", fg=typer.colors.RED)

    def _select_initial_account(self) -> bool:
        accounts = self.handlers.accounts()
        if self.session.account_id:
            if self.session.account_id not in accounts:
                typer.secho(f"Unknown account: {self.session.account_id}", fg=typer.colors.RED)
                return False
            return True
        if not accounts:
            typer.echo("No accounts configured; run 'email-agent account add'.")
            return False
        if len(accounts) == 1:
            self.session.account_id = next(iter(accounts))
            return True
        typer.echo("Choose an account:")
        account_ids = list(accounts)
        for index, account_id in enumerate(account_ids, 1):
            typer.echo(f"{index}. {account_id}")
        while True:
            try:
                choice = self.prompt(">", prompt_suffix=" ").strip()
            except (EOFError, KeyboardInterrupt):
                typer.echo()
                return False
            if choice.isdigit() and 1 <= int(choice) <= len(account_ids):
                self.session.account_id = account_ids[int(choice) - 1]
                return True
            if choice in accounts:
                self.session.account_id = choice
                return True
            typer.echo("Enter an account number or email address.")

    def dispatch(self, line: str) -> None:
        if not line.startswith("/"):
            self._natural_language(line)
            return
        command_text = line.split(maxsplit=1)[0]
        command = command_text.casefold()
        if command == "/search":
            # Everything after /search is treated as natural-language text
            # rather than parsed with shell quotation rules.
            # This permits apostrophes and unmatched quotation marks in queries.
            query = line[len(command_text) :].strip()
            args = [query] if query else []
        else:
            try:
                args = shlex.split(line)[1:]
            except ValueError as exc:
                raise ShellUsageError(str(exc)) from exc
        logger.info("Shell command: %s", command)
        methods = {
            "/inbox": self._inbox,
            "/search": self._search,
            "/triage": self._triage,
            "/show": self._show,
            "/draft": self._draft,
            "/drafts": self._drafts,
            "/review": self._review,
            "/upload": self._upload,
            "/delete-draft": self._delete_draft,
            "/account": self._account,
            "/verbose": self._verbose,
            "/trace-model": self._trace_model,
            "/help": self._help,
        }
        method = methods.get(command)
        if method is None:
            typer.echo(f"Unknown command: {command}. Type /help for commands.")
            return
        try:
            method(args)
        except ShellUsageError as exc:
            typer.echo(f"Usage: {exc}")

    def _active(self) -> str:
        if not self.session.account_id:
            raise RuntimeError("No active account; use /account EMAIL")
        return self.session.account_id

    def _natural_language(self, line: str) -> None:
        account_id = self._active()
        if self._assistant is None or self._assistant_account_id != account_id:
            self._assistant = self.handlers.assistant(account_id)
            self._assistant_account_id = account_id
        turn = self._assistant.invoke(line)
        if turn.kind == "inbox":
            render_inbox_items(turn.payload)
        elif turn.kind == "search":
            render_inbox_search_response(turn.payload)
        elif turn.kind == "message":
            render_message_details(turn.payload, show_confidence=False)
        elif turn.kind == "triage":
            render_triage_results(turn.payload)
        elif turn.kind == "draft":
            render_draft(turn.payload)
        elif turn.kind == "drafts":
            if turn.payload:
                render_draft_list(turn.payload)
            else:
                typer.echo("No draft suggestions to review.")
        else:
            typer.echo(turn.message or "I could not complete that request.")

    def _require_active_message(self, message_id: int) -> int:
        account_id = self.handlers.message_account(message_id)
        if account_id != self._active():
            raise LookupError(f"message {message_id} does not belong to the active account")
        return message_id

    def _inbox(self, args: list[str]) -> None:
        if len(args) > 1:
            raise ShellUsageError("/inbox [limit]")
        try:
            limit = int(args[0]) if args else DEFAULT_INBOX_LIMIT
        except ValueError as exc:
            raise ShellUsageError("/inbox [limit]") from exc
        if limit < 1:
            raise ShellUsageError("/inbox [limit]")
        account_id = self._active()
        typer.echo(f"Checking {account_id}...")
        result = self.handlers.run_inbox(account_id, limit)
        render_inbox_items(result.items)

    def _search(self, args: list[str]) -> None:
        if not args:
            raise ShellUsageError("/search QUERY")
        response = self.handlers.search_inbox(self._active(), " ".join(args))
        render_inbox_search_response(response)

    def _triage(self, args: list[str]) -> None:
        if len(args) > 1:
            raise ShellUsageError("/triage [LOCAL_ID]")
        try:
            message_id = int(args[0]) if args else None
        except ValueError as exc:
            raise ShellUsageError("/triage [LOCAL_ID]") from exc
        if message_id is not None:
            self._require_active_message(message_id)
        results = self.handlers.triage(self._active(), message_id=message_id)
        render_triage_results(results)

    @staticmethod
    def _one_id(args: list[str], usage: str) -> int:
        if len(args) != 1:
            raise ShellUsageError(usage)
        try:
            return int(args[0])
        except ValueError as exc:
            raise ShellUsageError(usage) from exc

    def _show(self, args: list[str]) -> None:
        message_id = self._require_active_message(self._one_id(args, "/show LOCAL_ID"))
        render_message_details(self.handlers.show_message(message_id), show_confidence=False)

    def _draft(self, args: list[str]) -> None:
        if not args:
            raise ShellUsageError("/draft LOCAL_ID [instruction]")
        try:
            message_id = int(args[0])
        except ValueError as exc:
            raise ShellUsageError("/draft LOCAL_ID [instruction]") from exc
        self._require_active_message(message_id)
        self.handlers.generate_draft(message_id, " ".join(args[1:]) or None)
        typer.secho(f"✓ Draft ready for message #{message_id}.", fg=typer.colors.GREEN)

    def _drafts(self, args: list[str]) -> None:
        if args:
            raise ShellUsageError("/drafts")
        rows = self.handlers.list_drafts(self._active())
        if not rows:
            typer.echo("No draft suggestions to review.")
            return
        render_draft_list(rows)

    def _review(self, args: list[str]) -> None:
        if args:
            raise ShellUsageError("/review")
        drafts = self.handlers.list_drafts(self._active())
        for draft in drafts:
            try:
                source = self.handlers.source_message(draft.message_id)
            except Exception as exc:  # noqa: BLE001 - keep the remaining review queue usable
                render_review_item(draft, None, str(exc))
            else:
                render_review_item(draft, source, None)
            choice = self.prompt("[u] Upload  [d] Delete  [k] Keep  [q] Quit", default="k", show_default=False).strip().lower()
            if choice in {"q", "quit"}:
                break
            if choice in {"u", "upload"}:
                self.handlers.upload_draft(draft.message_id)
                typer.echo("✓ Uploaded to mailbox drafts. No email was sent.")
            elif choice in {"d", "delete"}:
                self.handlers.delete_draft(draft.message_id)
                typer.echo("✓ Deleted suggestion.")
            else:
                typer.echo("Kept for later.")

    def _upload(self, args: list[str]) -> None:
        message_id = self._require_active_message(self._one_id(args, "/upload LOCAL_ID"))
        self.handlers.upload_draft(message_id)
        typer.echo("✓ Uploaded to mailbox drafts. No email was sent.")

    def _delete_draft(self, args: list[str]) -> None:
        message_id = self._require_active_message(
            self._one_id(args, "/delete-draft LOCAL_ID")
        )
        self.handlers.delete_draft(message_id)
        typer.echo("✓ Deleted draft suggestion.")

    def _account(self, args: list[str]) -> None:
        accounts = self.handlers.accounts()
        if not args:
            for account_id, account in accounts.items():
                marker = "*" if account_id == self.session.account_id else " "
                typer.echo(f"{marker} {account_id}: {account.provider}")
            return
        if len(args) != 1:
            raise ShellUsageError("/account [EMAIL]")
        if args[0] not in accounts:
            raise ValueError(f"Unknown account: {args[0]}")
        self.session.account_id = args[0]
        self._assistant = None
        self._assistant_account_id = None
        typer.echo(f"Account: {args[0]}")

    def _verbose(self, args: list[str]) -> None:
        names = {0: "off", 1: "on", 2: "debug"}
        if not args:
            typer.echo(f"Verbose: {names[self.session.verbosity]}")
            return
        if len(args) != 1 or args[0] not in {"off", "on", "debug"}:
            raise ShellUsageError("/verbose [off|on|debug]")
        self.session.verbosity = {"off": 0, "on": 1, "debug": 2}[args[0]]
        configure_logging(self.session.verbosity)
        typer.echo(f"Verbose: {args[0]}")

    def _trace_model(self, args: list[str]) -> None:
        if not args:
            typer.echo(f"Model tracing: {'on' if self.session.trace_model else 'off'}")
            return
        if len(args) != 1 or args[0] not in {"off", "on"}:
            raise ShellUsageError("/trace-model [off|on]")
        self.session.trace_model = args[0] == "on"
        configure_model_tracing(self.session.trace_model)
        if self.session.trace_model:
            warn_model_tracing()
        typer.echo(f"Model tracing: {args[0]}")

    def _help(self, args: list[str]) -> None:
        if args:
            raise ShellUsageError("/help")
        typer.echo(HELP_TEXT)


HELP_TEXT = """Commands:
  Plain text                      Ask the conversational assistant
  /inbox [limit]                 Synchronize and show recent mail
  /search QUERY                  Search triaged local mail with natural language
  /triage [LOCAL_ID]             Triage untriaged mail (or one message)
  /show LOCAL_ID                 Show a message
  /draft LOCAL_ID [instruction]  Generate or regenerate a reply suggestion
  /drafts                        List pending suggestions
  /review                        Review pending suggestions
  /upload LOCAL_ID               Upload draft to mailbox (never sends)
  /delete-draft LOCAL_ID         Delete a local suggestion
  /account [EMAIL]               List or switch accounts
  /verbose [off|on|debug]        Show or change verbosity
  /trace-model [off|on]          Show or change model tracing
  /help                          Show this help
  /quit                          Exit the shell"""


def run_shell(
    *,
    account_id: str | None = None,
    verbosity: int = 0,
    trace_model: bool = False,
    handlers: CommandHandlers | None = None,
) -> None:
    InteractiveShell(ShellSession(account_id, verbosity, trace_model), handlers).run()
