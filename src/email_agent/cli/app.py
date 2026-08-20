from __future__ import annotations

import time
from typing import Annotated

import typer
from typer.core import TyperGroup

from email_agent.cli.commands import CommandHandlers
from email_agent.cli.logging import configure_logging, warn_model_tracing
from email_agent.cli.rendering import (
    render_draft,
    render_draft_list,
    render_inbox_items,
    render_message_details,
    render_processing_results,
    render_review_item,
)
from email_agent.config import PROJECT_ROOT
from email_agent.diagnostics import configure_model_tracing
from email_agent.generators import (
    AccountProvider,
    AgentTemplate,
    CategoryAction,
    ModelProvider,
)
from email_agent.services import OrganizationStatus


class GlobalOptionsAnywhereGroup(TyperGroup):
    """Allow diagnostic global flags anywhere before the argument separator."""

    @staticmethod
    def _normalize_verbose_args(args: list[str]) -> list[str]:
        before_separator, separator, after_separator = args, [], []
        if "--" in args:
            index = args.index("--")
            before_separator, separator, after_separator = args[:index], ["--"], args[index + 1 :]
        global_options = [
            value
            for value in before_separator
            if value in {"--verbose", "--trace-model"}
            or (value.startswith("-") and len(value) > 1 and set(value[1:]) == {"v"})
        ]
        remaining = [value for value in before_separator if value not in global_options]
        return [*global_options, *remaining, *separator, *after_separator]

    def parse_args(self, typer_context, args: list[str]) -> list[str]:
        return super().parse_args(typer_context, self._normalize_verbose_args(args))


app = typer.Typer(
    cls=GlobalOptionsAnywhereGroup,
    invoke_without_command=True,
    help="Safe, account-configured email triage and drafting.",
    epilog="""
Getting started:

  email-agent account add me@example.com --provider gmail --template personal --model-provider openai --model gpt-5.4-mini

Then run: email-agent inbox
""",
)
account_app = typer.Typer(
    help="Add, list, and validate mailbox accounts.", invoke_without_command=True
)
drafts_app = typer.Typer(help="Review and upload suggested replies.", invoke_without_command=True)
message_app = typer.Typer(help="View or update an individual message.")
app.add_typer(account_app, name="account")
app.add_typer(drafts_app, name="drafts")
app.add_typer(message_app, name="message")


@app.callback()
def main(
    typer_context: typer.Context,
    verbose: Annotated[
        int,
        typer.Option(
            "--verbose",
            "-v",
            count=True,
            help="Show workflow details; repeat (-vv) for diagnostics.",
        ),
    ] = 0,
    trace_model: Annotated[
        bool,
        typer.Option(
            "--trace-model",
            help="Log exact model prompts and responses; may expose email content.",
        ),
    ] = False,
):
    """Configure diagnostics shared by every command."""
    configure_logging(verbose)
    configure_model_tracing(trace_model)
    if trace_model:
        warn_model_tracing()
    if typer_context.invoked_subcommand is None:
        from email_agent.cli.shell import run_shell

        run_shell(verbosity=verbose, trace_model=trace_model)

def _account_id(requested: str | None) -> str:
    """Resolve an optional account when exactly one mailbox is configured."""
    accounts = CommandHandlers().accounts()
    if requested:
        if requested not in accounts:
            raise typer.BadParameter(f"Unknown account '{requested}'")
        return requested
    if len(accounts) == 1:
        return next(iter(accounts))
    if not accounts:
        raise typer.BadParameter("No accounts configured; run 'email-agent account add'")
    raise typer.BadParameter("Multiple accounts configured; use --account EMAIL")


@account_app.callback()
def account(typer_context: typer.Context):
    """Add, list, and validate mailbox accounts."""
    if typer_context.invoked_subcommand is None:
        list_accounts()


def list_accounts():
    """Render configured accounts without connecting to them."""
    for account_id, account in CommandHandlers().accounts().items():
        typer.echo(f"{account_id}: {account.provider}")


@account_app.command("add")
def add_account(
    email: Annotated[str, typer.Argument(help="Mailbox email address.")],
    provider: Annotated[AccountProvider, typer.Option(help="Mailbox provider.")],
    template: Annotated[AgentTemplate, typer.Option(help="Agent system-prompt template.")],
    model_provider: Annotated[ModelProvider, typer.Option(help="Model provider.")],
    model: Annotated[str, typer.Option(help="Model name, such as 'gpt-5.4-mini' or 'qwen3'.")],
    imap_host: Annotated[str | None, typer.Option(help="IMAP server hostname.")] = None,
    imap_port: Annotated[int, typer.Option(help="IMAP SSL port.")] = 993,
    username_env: Annotated[
        str | None, typer.Option(help="Environment variable containing the IMAP username.")
    ] = None,
    password_env: Annotated[
        str | None, typer.Option(help="Environment variable containing the IMAP password.")
    ] = None,
    credentials_file: Annotated[
        str | None, typer.Option(help="Gmail OAuth client JSON path.")
    ] = None,
    token_file: Annotated[str | None, typer.Option(help="Gmail OAuth token path.")] = None,
    category_action: Annotated[
        CategoryAction | None,
        typer.Option(help="IMAP category behavior: copy or move."),
    ] = None,
    force: Annotated[bool, typer.Option(help="Replace an existing account entry.")] = False,
):
    """Create or add a mailbox account in the private accounts.yaml file."""
    try:
        generated = CommandHandlers().create_account(
            email,
            provider,
            template,
            model_provider=model_provider,
            model=model,
            imap_host=imap_host,
            imap_port=imap_port,
            username_env=username_env,
            password_env=password_env,
            credentials_file=credentials_file,
            token_file=token_file,
            category_action=category_action,
            force=force,
        )
    except (TypeError, ValueError, FileExistsError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.secho(
        f"Created account '{generated.account_id}' in {generated.path.name}.",
        fg=typer.colors.GREEN,
        bold=True,
    )
    if provider is AccountProvider.GMAIL:
        typer.echo("Place the OAuth client JSON at the generated credentials_file path.")
    else:
        typer.echo("Set the generated username and password environment variables in .env.")
    typer.secho(f"Created system prompt: {generated.system_prompt.relative_to(PROJECT_ROOT)}")
    typer.echo(f"\nNext: email-agent inbox --account {email}")


@account_app.command("validate")
def validate_config():
    """Validate mailbox accounts, model settings, categories, and system prompts."""
    try:
        account_ids = CommandHandlers().validate_accounts()
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    for account_id in account_ids:
        typer.secho(f"✓ {account_id}", fg=typer.colors.GREEN)
    typer.secho(
        f"Validated {len(account_ids)} accounts; sending is disabled.",
        fg=typer.colors.GREEN,
        bold=True,
    )


@app.command()
def inbox(
    account: Annotated[str | None, typer.Option(help="Mailbox email address.")] = None,
    limit: int = 20,
    unread: Annotated[
        bool, typer.Option("--unread", help="Show only provider-unread messages.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Classify without changing the mailbox or drafting.")
    ] = False,
    reorganize: Annotated[
        bool,
        typer.Option("--reorganize", help="Reclassify and resync recent locally stored messages."),
    ] = False,
    watch: Annotated[
        bool, typer.Option("--watch", help="Keep checking for new messages.")
    ] = False,
    interval: Annotated[int, typer.Option(help="Seconds between checks when watching.")] = 300,
):
    """Prioritize new mail, organize it, and prepare replies.

    Category says what a message is, priority controls its position, and Draft
    ready means the assistant prepared a reply.
    """
    account_id = _account_id(account)
    if interval < 30:
        raise typer.BadParameter("interval must be at least 30 seconds")
    try:
        while True:
            result = CommandHandlers().run_inbox(
                account_id,
                limit,
                unread=unread,
                dry_run=dry_run,
                reorganize=reorganize,
            )
            if result.dry_run:
                typer.secho(
                    "DRY RUN — mailbox labels and drafts will not change",
                    fg=typer.colors.YELLOW,
                )
            render_processing_results(result.processed)
            if result.organization:
                for item in result.organization.items:
                    if item.status is OrganizationStatus.FAILED:
                        typer.secho(f"{item.local_id}: {item.error}", fg=typer.colors.RED)
                typer.secho(
                    f"Reorganized {result.organization.changed}; "
                    f"{result.organization.failed} failed.",
                    fg=(
                        typer.colors.RED
                        if result.organization.failed
                        else typer.colors.GREEN
                    ),
                )
            render_inbox_items(result.items)
            if not watch:
                break
            typer.echo(f"\nWatching every {interval}s. Ctrl-C to stop.")
            time.sleep(interval)
    except KeyboardInterrupt:
        typer.echo("Stopped.")


@drafts_app.callback()
def drafts(typer_context: typer.Context, account: Annotated[str | None, typer.Option()] = None):
    """Review and upload suggested replies."""
    if typer_context.invoked_subcommand is not None:
        return
    handlers = CommandHandlers()
    if account:
        handlers.validate_account(account)
    rows = handlers.list_drafts(account)
    if not rows:
        typer.echo("No draft suggestions to review.")
        return
    typer.echo(f"{len(rows)} draft suggestions. Run 'email-agent drafts review' to review them.")
    render_draft_list(rows)


@message_app.command("show")
def show_message(message_id: int):
    """Retrieve and show a mailbox message using its local database ID."""
    try:
        details = CommandHandlers().show_message(message_id)
    except LookupError as exc:
        raise typer.BadParameter(str(exc)) from exc
    render_message_details(details)


@drafts_app.command("show")
def show_draft(message_id: int):
    """Show the local draft associated with a processed message."""
    try:
        row = CommandHandlers().show_draft(message_id)
    except LookupError as exc:
        raise typer.BadParameter(str(exc)) from exc
    render_draft(row)


@drafts_app.command()
def generate(
    message_id: Annotated[int, typer.Argument(help="Local message ID.")],
    instruction: Annotated[
        str | None, typer.Option(help="One-time guidance for this draft only.")
    ] = None,
):
    """Generate or regenerate a reply suggestion for one message."""
    try:
        draft = CommandHandlers().generate_draft(message_id, instruction)
    except (LookupError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.secho(f"✓ Draft ready for message #{message_id}.", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"To: {draft.to[0]}\nSubject: {draft.subject}")
    typer.echo("Review it with: email-agent drafts review")


@drafts_app.command()
def upload(message_id: int):
    """Upload a suggestion to the mailbox Drafts folder without sending."""
    try:
        CommandHandlers().upload_draft(message_id)
    except (LookupError, RuntimeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.secho("✓ Uploaded to mailbox drafts. No email was sent.", fg=typer.colors.GREEN, bold=True)


@drafts_app.command("delete")
def delete_draft(message_id: int):
    """Delete a local draft suggestion without changing the mailbox."""
    try:
        CommandHandlers().delete_draft(message_id)
    except LookupError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.secho("✓ Deleted draft suggestion.", fg=typer.colors.GREEN, bold=True)


@drafts_app.command()
def review(account: Annotated[str | None, typer.Option()] = None):
    """Cycle through draft suggestions and upload, delete, keep, or quit."""
    handlers = CommandHandlers()
    if account:
        handlers.validate_account(account)
    rows = handlers.list_drafts(account)
    if not rows:
        typer.echo("No draft suggestions to review.")
        return
    for row in rows:
        try:
            source = handlers.source_message(row.message_id)
        except Exception as exc:  # noqa: BLE001 - keep the review queue usable
            render_review_item(row, None, str(exc))
        else:
            render_review_item(row, source, None)
        choice = typer.prompt(
            "[u] Upload  [d] Delete  [k] Keep  [q] Quit",
            default="k",
            show_default=False,
        ).strip().lower()
        if choice in {"q", "quit"}:
            break
        if choice in {"u", "upload"}:
            try:
                handlers.upload_draft(row.message_id)
            except (LookupError, RuntimeError) as exc:
                typer.secho(f"Upload failed: {exc}", fg=typer.colors.RED)
            else:
                typer.secho("✓ Uploaded to mailbox drafts. No email was sent.", fg=typer.colors.GREEN)
        elif choice in {"d", "delete"}:
            handlers.delete_draft(row.message_id)
            typer.secho("✓ Deleted suggestion.", fg=typer.colors.GREEN)
        else:
            typer.echo("Kept for later.")
