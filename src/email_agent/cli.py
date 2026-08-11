from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from typing import Annotated

import typer

from email_agent.agents import EmailAgents
from email_agent.config import PROJECT_ROOT, Settings
from email_agent.llm import get_model
from email_agent.mail import create_mail_provider
from email_agent.models import EmailClassification
from email_agent.pipeline import (
    PRIORITY_GROUP_ORDER,
    EmailPipeline,
    PriorityGroup,
    category_destination,
    triage_inbox,
)
from email_agent.scaffolding import (
    AccountProvider,
    AgentTemplate,
    ModelProvider,
    generate_account,
)
from email_agent.storage import Database

app = typer.Typer(
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

GROUP_COLORS = {
    PriorityGroup.URGENT: typer.colors.BRIGHT_RED,
    PriorityGroup.NORMAL: typer.colors.CYAN,
    PriorityGroup.LOW: typer.colors.BRIGHT_BLACK,
}


def _message_id(value: int, *, prefix: str = "") -> None:
    """Print a styled local message ID without ending the line."""
    typer.secho(f"{prefix}{value}", fg=typer.colors.CYAN, bold=True, nl=False)


def _components(account_id: str, with_agents: bool = True):
    settings = Settings()
    account = settings.account(account_id)
    provider = create_mail_provider(account_id, account, settings.root)
    database = Database(settings.database_path)
    agents = (
        EmailAgents(settings.root, account.agent, get_model(account.agent.model))
        if with_agents
        else None
    )
    return settings, account, provider, database, agents


@app.command()
def accounts():
    """List configured mailbox accounts without connecting to them."""
    settings = Settings()
    for account_id, account in settings.accounts.items():
        typer.echo(f"{account_id}: {account.provider} ({account.agent.name})")


@account_app.command("init")
def init_account(
    email: Annotated[str, typer.Argument(help="Mailbox email address.")],
    provider: Annotated[AccountProvider, typer.Option(help="Mailbox provider.")],
    template: Annotated[AgentTemplate, typer.Option(help="Agent system-prompt template.")],
    model_provider: Annotated[ModelProvider, typer.Option(help="Model provider.")],
    model: Annotated[str, typer.Option(help="Model name, such as 'gpt-5.4-mini' or 'qwen3'.")],
    display_name: Annotated[str | None, typer.Option(help="Human-readable agent name.")] = None,
    imap_host: Annotated[str | None, typer.Option(help="IMAP server hostname.")] = None,
    imap_port: Annotated[int, typer.Option(help="IMAP SSL port.")] = 993,
    smtp_host: Annotated[
        str | None, typer.Option(help="Optional SMTP hostname for future use.")
    ] = None,
    smtp_port: Annotated[int, typer.Option(help="SMTP SSL port.")] = 465,
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
    force: Annotated[bool, typer.Option(help="Replace an existing account entry.")] = False,
):
    """Create or add a mailbox account in the private accounts.yaml file."""
    try:
        generated = generate_account(
            PROJECT_ROOT,
            email,
            provider,
            template,
            model_provider=model_provider,
            model=model,
            display_name=display_name,
            imap_host=imap_host,
            imap_port=imap_port,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            username_env=username_env,
            password_env=password_env,
            credentials_file=credentials_file,
            token_file=token_file,
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
    """Validate accounts, nested agents, system prompts, and draft-only safety."""
    settings = Settings()
    for account_id, account in settings.accounts.items():
        agent = account.agent
        if not (settings.root / agent.system_prompt).is_file():
            raise typer.BadParameter(f"Missing system prompt: {agent.system_prompt}")
        typer.secho(f"✓ {account_id} ({agent.name}) v{agent.version}", fg=typer.colors.GREEN)
    typer.secho(
        f"Validated {len(settings.accounts)} accounts; sending is disabled.",
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
    _, configured, provider, database, agents = _components(account)
    typer.echo(f"Checking {configured.email}...")
    items = triage_inbox(
        provider,
        agents,
        database,
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
            _message_id(item.local_id)
            typer.echo(f"  {sender} — {item.message.subject}")
            details = [item.classification.category.replace("_", " ").title()]
            if item.draft_ready:
                details.append("Draft ready")
            if attention == "all":
                details.append(item.attention_state.title())
            typer.secho(f"    {' · '.join(details)}", fg=GROUP_COLORS[group])


def _render(result):
    c = result.classification
    typer.echo()
    _message_id(result.local_id, prefix="#")
    typer.echo(
        f"\n{result.message.from_name or result.message.from_address}\n{result.message.subject}"
    )
    typer.echo(
        f"\nCategory: {c.category.replace('_', ' ').title()}\nIntent: {c.intent or '-'}\nPriority: {c.priority.upper()}\nReply recommended: {'YES' if c.requires_reply else 'NO'}"
    )
    if c.requires_escalation:
        typer.secho("\n⚠ Human attention required", fg=typer.colors.BRIGHT_RED, bold=True)
        typer.echo(c.escalation_reason)
    if result.reply:
        typer.secho("\nSuggested response:", fg=typer.colors.GREEN, bold=True)
        typer.echo(f"\n{result.reply.body}")
        typer.secho("\nSaved to local review queue.", fg=typer.colors.GREEN)


@app.command()
def process(account: Annotated[str, typer.Option(help="Mailbox email address.")], limit: int = 20):
    """Complete pending message processing and save suggested replies for review."""
    _, configured, provider, database, agents = _components(account)
    typer.echo(f"Connecting to {configured.email}...")
    results = EmailPipeline(account, configured.agent, provider, agents, database).process(limit)
    typer.echo(f"Found {len(results)} new messages.")
    for result in results:
        _render(result)


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
    _, configured, provider, database, agents = _components(account, with_agents=should_reclassify)
    if not configured.agent.organization.enabled:
        raise typer.BadParameter("organization is disabled for this account")

    rows = database.list_categorized_messages(account, limit)
    changed = skipped = failed = 0
    typer.secho(f"Organizing {configured.email}...", fg=typer.colors.CYAN, bold=True)
    if dry_run:
        typer.secho("DRY RUN — no mailbox changes will be made", fg=typer.colors.YELLOW)
    for row in rows:
        classification = EmailClassification.model_validate_json(row["classification"])
        try:
            destination = category_destination(configured.agent, classification)
        except KeyError as exc:
            if reclassify_unknown:
                destination = None
            else:
                failed += 1
                typer.secho(f"{row['id']}: {exc.args[0]}", fg=typer.colors.BRIGHT_RED)
                continue
        if reclassify_all or (reclassify_unknown and destination is None):
            try:
                message = provider.get_message(row["provider_message_id"])
                thread = provider.get_thread(row["provider_message_id"])
                classification = agents.classify(message, thread)
                destination = category_destination(configured.agent, classification)
            except Exception as exc:  # noqa: BLE001 - continue the remaining batch
                failed += 1
                typer.secho(f"{row['id']}: reclassification failed: {exc}", fg=typer.colors.RED)
                continue
            typer.secho(
                f"{row['id']}: reclassified as {classification.category}",
                fg=typer.colors.YELLOW,
            )
            if not dry_run:
                database.update_classification(row["id"], classification)
        if destination is None:
            failed += 1
            typer.secho(f"{row['id']}: no category destination", fg=typer.colors.RED)
            continue
        if not force and database.category_was_synced(row["id"], destination):
            skipped += 1
            continue
        if dry_run:
            changed += 1
            _message_id(row["id"])
            typer.echo(f"  {row['subject']} → ", nl=False)
            typer.secho(destination, fg=typer.colors.MAGENTA, bold=True)
            continue
        try:
            provider.sync_category(row["provider_message_id"], destination)
        except Exception as exc:  # noqa: BLE001 - one provider failure must not stop the batch
            failed += 1
            typer.secho(f"{row['id']}: {exc}", fg=typer.colors.BRIGHT_RED)
            continue
        database.mark_category_synced(row["id"], destination)
        changed += 1
        _message_id(row["id"])
        typer.secho(f"  ✓ {destination}", fg=typer.colors.GREEN, bold=True)

    action = "would sync" if dry_run else "synced"
    typer.echo()
    typer.secho(f"{changed} {action}", fg=typer.colors.GREEN, bold=True, nl=False)
    typer.echo(", ", nl=False)
    typer.secho(f"{skipped} already synced", fg=typer.colors.BRIGHT_BLACK, nl=False)
    typer.echo(", ", nl=False)
    typer.secho(
        f"{failed} failed.",
        fg=typer.colors.RED if failed else typer.colors.BRIGHT_BLACK,
        bold=bool(failed),
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
    _, configured, provider, database, agents = _components(account)
    pipeline = EmailPipeline(account, configured.agent, provider, agents, database)
    typer.echo(f"Monitoring {configured.email} every {interval}s. Ctrl-C to stop.")
    try:
        while True:
            for result in pipeline.process(limit):
                _render(result)
            time.sleep(interval)
    except KeyboardInterrupt:
        typer.echo("Stopped.")


@app.command()
def drafts(account: Annotated[str | None, typer.Option()] = None):
    """List locally saved draft suggestions."""
    settings = Settings()
    if account:
        settings.account(account)
    for row in Database(settings.database_path).list_drafts(account):
        typer.echo(
            f"{row['message_id']}: [{row['status']}] To {row['recipient']} — {row['subject']}"
        )


@app.command("show")
def show_message(message_id: int):
    """Retrieve and show a mailbox message using its local database ID."""
    settings = Settings()
    row = Database(settings.database_path).show_message(message_id)
    if not row:
        raise typer.BadParameter("message not found")
    account = settings.accounts[row["account_id"]]
    provider = create_mail_provider(row["account_id"], account, settings.root)
    message = provider.get_message(row["provider_message_id"])
    classification = json.loads(row["classification"]) if row["classification"] else None

    typer.echo(f"From: {message.from_name or message.from_address}")
    typer.echo(f"Subject: {message.subject}\n")
    typer.echo(message.content or "(No plain-text body)")
    if classification:
        typer.echo(f"\nCategory: {classification['category'].replace('_', ' ').title()}")
        typer.echo(f"Priority: {classification['priority'].upper()}")
        typer.echo(f"Attention: {row['attention_state'].title()}")
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
    rows = [
        row
        for row in Database(settings.database_path).list_drafts()
        if row["message_id"] == message_id
    ]
    if not rows:
        raise typer.BadParameter("draft not found")
    row = rows[0]
    typer.echo(
        f"To: {row['recipient']}\nSubject: {row['subject']}\n\n{row['body']}\n\nStatus: {row['status']}"
    )


@app.command()
def approve(message_id: int):
    """Mark a local draft approved without sending it."""
    settings = Settings()
    if not Database(settings.database_path).approve(message_id):
        raise typer.BadParameter("draft not found")
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
    settings = Settings()
    database = Database(settings.database_path)
    row = database.set_attention(message_id, "done")
    if not row:
        raise typer.BadParameter("message not found")
    deleted = database.delete_generated_drafts(message_id) if delete_draft else 0
    typer.secho(f"✓ Marked “{row['subject']}” done.", fg=typer.colors.GREEN, bold=True)
    typer.echo("The email remains in your mailbox.")
    if deleted:
        typer.echo("Deleted the untouched generated draft.")


def _parse_snooze(value: str) -> datetime:
    """Parse `tomorrow`, an ISO date, or an ISO datetime in the local timezone."""
    local_tz = datetime.now().astimezone().tzinfo
    if value.lower() == "tomorrow":
        tomorrow = datetime.now(local_tz).date() + timedelta(days=1)
        return datetime.combine(tomorrow, datetime_time(hour=9), tzinfo=local_tz)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(value), datetime_time(hour=9))
        except ValueError as exc:
            raise typer.BadParameter(
                "--until must be 'tomorrow', YYYY-MM-DD, or an ISO datetime"
            ) from exc
    return parsed.replace(tzinfo=local_tz) if parsed.tzinfo is None else parsed


@app.command()
def snooze(
    message_id: Annotated[int, typer.Argument(help="Local message ID.")],
    until: Annotated[
        str, typer.Option(help="When to reopen: tomorrow, YYYY-MM-DD, or ISO datetime.")
    ],
):
    """Hide a message from the open inbox until a later time."""
    wake_at = _parse_snooze(until)
    if wake_at.astimezone(UTC) <= datetime.now(UTC):
        raise typer.BadParameter("--until must be in the future")
    settings = Settings()
    row = Database(settings.database_path).set_attention(
        message_id, "snoozed", snoozed_until=wake_at
    )
    if not row:
        raise typer.BadParameter("message not found")
    typer.secho(f"✓ Snoozed “{row['subject']}”.", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"Returns to Open at {wake_at.astimezone().strftime('%Y-%m-%d %H:%M %Z')}.")


@app.command()
def reopen(message_id: Annotated[int, typer.Argument(help="Local message ID.")]):
    """Return a done or snoozed message to the open inbox."""
    settings = Settings()
    row = Database(settings.database_path).set_attention(message_id, "open")
    if not row:
        raise typer.BadParameter("message not found")
    typer.secho(f"✓ Reopened “{row['subject']}”.", fg=typer.colors.GREEN, bold=True)


if __name__ == "__main__":
    app()
