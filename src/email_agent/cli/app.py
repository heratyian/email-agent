from __future__ import annotations

import time
from typing import Annotated

import typer
from typer.core import TyperGroup

from email_agent.cli.logging import configure_logging, warn_model_tracing
from email_agent.cli.parsing import parse_snooze
from email_agent.cli.rendering import (
    GROUP_COLORS,
    category_name,
    message_id,
    render_processed,
)
from email_agent.config import PROJECT_ROOT, Settings
from email_agent.db import Database
from email_agent.diagnostics import configure_model_tracing
from email_agent.generators import (
    AccountProvider,
    AgentTemplate,
    CategoryAction,
    ModelProvider,
)
from email_agent.runtime import AccountRuntime, RuntimeFactory
from email_agent.services import (
    PRIORITY_GROUP_ORDER,
    AccountService,
    DraftService,
    InboxService,
    MessageService,
    OrganizationService,
    OrganizationStatus,
    ProcessingFailure,
    ProcessingService,
)


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

    def parse_args(self, ctx, args: list[str]) -> list[str]:
        return super().parse_args(ctx, self._normalize_verbose_args(args))


app = typer.Typer(
    cls=GlobalOptionsAnywhereGroup,
    no_args_is_help=True,
    help="Safe, account-configured email triage and drafting.",
    epilog="""
Getting started:

  email-agent account init me@example.com --provider gmail --template personal --model-provider openai --model gpt-5.4-mini

Then validate with: email-agent config validate
""",
)
config_app = typer.Typer(help="Configuration utilities.")
account_app = typer.Typer(help="Create and manage mailbox accounts.")
app.add_typer(config_app, name="config")
app.add_typer(account_app, name="account")


@app.callback()
def main(
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

def _runtime(account_id: str, *, with_agents: bool = True) -> AccountRuntime:
    """Build typed dependencies for one CLI account command."""
    return RuntimeFactory().for_account(account_id, with_agents=with_agents)


@app.command()
def accounts():
    """List configured mailbox accounts without connecting to them."""
    for account_id, account in AccountService(PROJECT_ROOT).list().items():
        typer.echo(f"{account_id}: {account.provider}")


@account_app.command("init")
def init_account(
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
        generated = AccountService(PROJECT_ROOT).create(
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


@config_app.command("validate")
def validate_config():
    """Validate mailbox accounts, model settings, categories, and system prompts."""
    try:
        account_ids = AccountService(PROJECT_ROOT).validate()
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
    account: Annotated[str, typer.Option(help="Mailbox email address.")],
    limit: int = 20,
    unread: Annotated[
        bool, typer.Option("--unread", help="Show only provider-unread messages.")
    ] = False,
    snoozed: Annotated[
        bool, typer.Option("--snoozed", help="Show messages deferred until later.")
    ] = False,
    done: Annotated[bool, typer.Option("--done", help="Show handled messages.")] = False,
    all_messages: Annotated[
        bool, typer.Option("--all", help="Show open, snoozed, and done messages.")
    ] = False,
):
    """Display the assistant's prioritized view of recent Inbox messages.

    The default view contains messages that still need attention. Category says
    what a message is, priority controls its position, and Draft ready means the
    assistant prepared a reply. Use --done, --snoozed, or --all for other views.
    """
    selected = sum((snoozed, done, all_messages))
    if selected > 1:
        raise typer.BadParameter("Use only one of --snoozed, --done, or --all")
    attention = "all" if all_messages else "snoozed" if snoozed else "done" if done else "open"
    runtime = _runtime(account)
    typer.echo(f"Checking {runtime.account.email}...")
    items = InboxService(runtime.provider, runtime.agents, runtime.database).list(
        limit,
        unread_only=unread,
        attention=attention,
    )
    typer.echo(f"\n{len(items)} recent messages")

    for group in PRIORITY_GROUP_ORDER:
        grouped = [item for item in items if item.group is group]
        if not grouped:
            continue
        typer.secho(f"\n{group.value}", fg=GROUP_COLORS[group], bold=True)
        typer.secho("─" * len(group.value), fg=GROUP_COLORS[group])
        for item in grouped:
            sender = item.message.from_name or item.message.from_address
            message_id(item.local_id)
            typer.echo(f"  {sender} — {item.message.subject}")
            details = [category_name(item.classification.category)]
            if item.draft_ready:
                details.append("Draft ready")
            if attention == "all":
                details.append(item.attention_state.title())
            typer.secho(f"    {' · '.join(details)}", fg=GROUP_COLORS[group])


@app.command()
def process(account: Annotated[str, typer.Option(help="Mailbox email address.")], limit: int = 20):
    """Complete pending message processing and save suggested replies for review."""
    runtime = _runtime(account)
    typer.echo(f"Connecting to {runtime.account.email}...")
    results = ProcessingService(
        account, runtime.account.agent, runtime.provider, runtime.agents, runtime.database
    ).process(limit)
    for result in results:
        if isinstance(result, ProcessingFailure):
            label = f"{result.local_id}: " if result.local_id is not None else ""
            typer.secho(
                f"{label}{result.message.subject}: {result.error}", fg=typer.colors.BRIGHT_RED
            )
        else:
            render_processed(result)
    succeeded = sum(not isinstance(result, ProcessingFailure) for result in results)
    failed = len(results) - succeeded
    typer.echo()
    typer.secho(f"{succeeded} processed", fg=typer.colors.GREEN, bold=True, nl=False)
    typer.echo(", ", nl=False)
    typer.secho(
        f"{failed} failed.",
        fg=typer.colors.RED if failed else typer.colors.BRIGHT_BLACK,
        bold=bool(failed),
    )
    if failed:
        raise typer.Exit(1)


@app.command()
def organize(
    account: Annotated[str, typer.Option(help="Mailbox email address.")],
    limit: Annotated[int, typer.Option(help="Maximum recent local messages to examine.")] = 100,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview changes without modifying the mailbox.")
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Repeat previously successful syncs; may duplicate IMAP messages.",
        ),
    ] = False,
    reclassify_unknown: Annotated[
        bool,
        typer.Option(
            "--reclassify-unknown",
            help="Reclassify stored categories that no longer exist in the configuration.",
        ),
    ] = False,
    reclassify_all: Annotated[
        bool,
        typer.Option(
            "--reclassify-all",
            help="Reclassify every examined message using the current categories.",
        ),
    ] = False,
):
    """Apply existing local categories as Gmail labels or IMAP folders."""
    if limit < 1:
        raise typer.BadParameter("limit must be at least 1")
    if reclassify_unknown and reclassify_all:
        raise typer.BadParameter("Use only one reclassification option")
    should_reclassify = reclassify_unknown or reclassify_all
    runtime = _runtime(account, with_agents=should_reclassify)
    typer.secho(f"Organizing {runtime.account.email}...", fg=typer.colors.CYAN, bold=True)
    if dry_run:
        typer.secho("DRY RUN — no mailbox changes will be made", fg=typer.colors.YELLOW)
    report = OrganizationService(
        account, runtime.account, runtime.provider, runtime.database, runtime.agents
    ).run(
        limit=limit,
        dry_run=dry_run,
        force=force,
        reclassify_unknown=reclassify_unknown,
        reclassify_all=reclassify_all,
    )
    for item in report.items:
        if item.reclassified_as is not None:
            typer.secho(
                f"{item.local_id}: reclassified as {item.reclassified_as}",
                fg=typer.colors.YELLOW,
            )
        if item.status is OrganizationStatus.FAILED:
            typer.secho(
                f"{item.local_id}: {item.error}", fg=typer.colors.BRIGHT_RED
            )
        elif item.status is OrganizationStatus.UNCATEGORIZED:
            typer.secho(
                f"{item.local_id}: uncategorized", fg=typer.colors.BRIGHT_BLACK
            )
        elif item.status in {OrganizationStatus.PREVIEW, OrganizationStatus.SYNCED}:
            message_id(item.local_id)
            if item.status is OrganizationStatus.PREVIEW:
                typer.echo(f"  {item.subject} → ", nl=False)
                typer.secho(
                    item.destination or "uncategorized",
                    fg=typer.colors.MAGENTA,
                    bold=True,
                )
            else:
                typer.secho(
                    f"  ✓ {item.destination or 'uncategorized'}",
                    fg=typer.colors.GREEN,
                    bold=True,
                )

    action = "would sync" if dry_run else "synced"
    typer.echo()
    typer.secho(f"{report.changed} {action}", fg=typer.colors.GREEN, bold=True, nl=False)
    typer.echo(", ", nl=False)
    typer.secho(
        f"{report.skipped} already synced", fg=typer.colors.BRIGHT_BLACK, nl=False
    )
    typer.echo(", ", nl=False)
    typer.secho(
        f"{report.uncategorized} uncategorized", fg=typer.colors.BRIGHT_BLACK, nl=False
    )
    typer.echo(", ", nl=False)
    typer.secho(
        f"{report.failed} failed.",
        fg=typer.colors.RED if report.failed else typer.colors.BRIGHT_BLACK,
        bold=bool(report.failed),
    )


@app.command()
def monitor(
    account: Annotated[str, typer.Option(help="Mailbox email address.")],
    interval: int = 300,
    limit: int = 20,
):
    """Poll a mailbox until interrupted."""
    if interval < 30:
        raise typer.BadParameter("interval must be at least 30 seconds")
    runtime = _runtime(account)
    processing = ProcessingService(
        account, runtime.account.agent, runtime.provider, runtime.agents, runtime.database
    )
    typer.echo(f"Monitoring {runtime.account.email} every {interval}s. Ctrl-C to stop.")
    try:
        while True:
            for result in processing.process(limit):
                if isinstance(result, ProcessingFailure):
                    typer.secho(
                        f"{result.message.subject}: {result.error}",
                        fg=typer.colors.BRIGHT_RED,
                    )
                else:
                    render_processed(result)
            time.sleep(interval)
    except KeyboardInterrupt:
        typer.echo("Stopped.")


@app.command()
def drafts(account: Annotated[str | None, typer.Option()] = None):
    """List locally saved draft suggestions."""
    settings = Settings()
    if account:
        settings.account(account)
    service = DraftService(Database(settings.database_path))
    for row in service.list(account):
        typer.echo(
            f"{row['message_id']}: [{row['status']}] To {row['recipient']} — {row['subject']}"
        )


@app.command("show")
def show_message(message_id: int):
    """Retrieve and show a mailbox message using its local database ID."""
    try:
        details = MessageService(Settings()).show(message_id)
    except LookupError as exc:
        raise typer.BadParameter(str(exc)) from exc
    message, classification = details.message, details.classification

    typer.echo(f"From: {message.from_name or message.from_address}")
    typer.echo(f"Subject: {message.subject}\n")
    typer.echo(message.content or "(No plain-text body)")
    if classification:
        typer.echo(f"\nCategory: {category_name(classification['category'])}")
        typer.echo(f"Priority: {classification['priority'].upper()}")
        typer.echo(f"Attention: {details.attention_state.title()}")
        typer.echo(f"Confidence: {classification['confidence']:.2f}")
        typer.echo(f"Summary: {classification['summary']}")
        if classification.get("requires_escalation"):
            typer.secho(
                "\n⚠ Human attention required",
                fg=typer.colors.BRIGHT_RED,
                bold=True,
            )
            typer.echo(classification.get("escalation_reason") or "Review required.")


@app.command("draft")
def show_draft(message_id: int):
    """Show the local draft associated with a processed message."""
    settings = Settings()
    try:
        row = DraftService(Database(settings.database_path)).get(message_id)
    except LookupError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"To: {row['recipient']}\nSubject: {row['subject']}\n\n{row['body']}\n\nStatus: {row['status']}"
    )


@app.command()
def approve(message_id: int):
    """Mark a local draft approved without sending it."""
    settings = Settings()
    try:
        DraftService(Database(settings.database_path)).approve(message_id)
    except LookupError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.secho("Draft approved locally. No email was sent.", fg=typer.colors.GREEN, bold=True)


@app.command()
def done(
    message_id: Annotated[int, typer.Argument(help="Local message ID.")],
    delete_draft: Annotated[
        bool,
        typer.Option(
            "--delete-draft",
            help="Also delete an untouched generated draft; reviewed drafts are preserved.",
        ),
    ] = False,
):
    """Mark a message handled here or in another channel."""
    try:
        result = MessageService(Settings()).done(message_id, delete_draft=delete_draft)
    except LookupError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.secho(f"✓ Marked “{result.subject}” done.", fg=typer.colors.GREEN, bold=True)
    typer.echo("The email remains in your mailbox.")
    if result.deleted_drafts:
        typer.echo("Deleted the untouched generated draft.")


@app.command()
def snooze(
    message_id: Annotated[int, typer.Argument(help="Local message ID.")],
    until: Annotated[
        str, typer.Option(help="When to reopen: tomorrow, YYYY-MM-DD, or ISO datetime.")
    ],
):
    """Hide a message from the open inbox until a later time."""
    try:
        wake_at = parse_snooze(until)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    try:
        result = MessageService(Settings()).snooze(message_id, wake_at)
    except (LookupError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.secho(f"✓ Snoozed “{result.subject}”.", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"Returns to Open at {wake_at.astimezone().strftime('%Y-%m-%d %H:%M %Z')}.")


@app.command()
def reopen(message_id: Annotated[int, typer.Argument(help="Local message ID.")]):
    """Return a done or snoozed message to the open inbox."""
    try:
        result = MessageService(Settings()).reopen(message_id)
    except LookupError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.secho(f"✓ Reopened “{result.subject}”.", fg=typer.colors.GREEN, bold=True)
