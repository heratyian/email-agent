from __future__ import annotations

import json
import time
from typing import Annotated

import typer

from email_agent.agents import EmailAgents
from email_agent.config import PROJECT_ROOT, Settings
from email_agent.llm import get_model
from email_agent.mail import create_mail_provider
from email_agent.pipeline import (
    INBOX_GROUP_ORDER,
    EmailPipeline,
    InboxGroup,
    LocalMessageStatus,
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
    InboxGroup.NEEDS_REPLY: typer.colors.YELLOW,
    InboxGroup.IMPORTANT: typer.colors.BRIGHT_RED,
    InboxGroup.INFORMATIONAL: typer.colors.CYAN,
    InboxGroup.IGNORED: typer.colors.BRIGHT_BLACK,
}
STATUS_COLORS = {
    LocalMessageStatus.NEW: typer.colors.BRIGHT_MAGENTA,
    LocalMessageStatus.TRIAGED: typer.colors.YELLOW,
    LocalMessageStatus.PROCESSED: typer.colors.GREEN,
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
    template: Annotated[AgentTemplate, typer.Option(help="Agent behavior template.")],
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
    typer.secho(f"Created prompts: {generated.prompts[0].parent.relative_to(PROJECT_ROOT)}/")
    typer.echo(f"\nNext: email-agent inbox --account {email}")


@config_app.command("validate")
def validate_config():
    """Validate accounts, nested agents, prompts, and draft-only safety."""
    settings = Settings()
    for account_id, account in settings.accounts.items():
        agent = account.agent
        for prompt in (agent.prompts.system, agent.prompts.classify, agent.prompts.reply):
            if not (settings.root / prompt).is_file():
                raise typer.BadParameter(f"Missing prompt: {prompt}")
        typer.secho(f"✓ {account_id} ({agent.name}) v{agent.version}", fg=typer.colors.GREEN)
    typer.secho(
        f"Validated {len(settings.accounts)} accounts; sending is disabled.",
        fg=typer.colors.GREEN,
        bold=True,
    )


@app.command(
    epilog="""
Message states are local to email-agent and are separate from read/unread status:

  NEW        Classified for the first time during this inbox run.
  TRIAGED    Classified previously, but not handled by process or monitor.
  PROCESSED  Full processing completed; a draft was saved when required.
"""
)
def inbox(
    account: Annotated[str, typer.Option(help="Mailbox email address.")],
    limit: int = 20,
    unread: Annotated[
        bool, typer.Option("--unread", help="Show only provider-unread messages.")
    ] = False,
    unprocessed: Annotated[
        bool, typer.Option("--unprocessed", help="Show only locally unprocessed messages.")
    ] = False,
):
    """Display recent Inbox messages grouped by classification.

    By default this behaves like a normal inbox and includes messages regardless
    of provider read state or local workflow state. Use the optional filters for
    operational views. This command may classify and store metadata, but it never
    generates drafts or marks full processing complete.
    """
    _, configured, provider, database, agents = _components(account)
    typer.echo(f"Checking {configured.email}...")
    items = triage_inbox(
        provider,
        agents,
        database,
        limit,
        unread_only=unread,
        unprocessed_only=unprocessed,
    )
    typer.echo(f"\n{len(items)} recent messages")

    for group in INBOX_GROUP_ORDER:
        grouped = [item for item in items if item.group is group]
        if not grouped:
            continue
        typer.secho(f"\n{group.value}", fg=GROUP_COLORS[group], bold=True)
        typer.secho("─" * len(group.value), fg=GROUP_COLORS[group])
        for item in grouped:
            sender = item.message.from_name or item.message.from_address
            _message_id(item.local_id)
            typer.echo(f". {sender} — {item.message.subject}  ", nl=False)
            typer.secho(
                item.status.value,
                fg=STATUS_COLORS[item.status],
                bold=item.status is LocalMessageStatus.NEW,
            )


def _render(result):
    c = result.classification
    typer.echo()
    _message_id(result.local_id, prefix="#")
    typer.echo(
        f"\n{result.message.from_name or result.message.from_address}\n{result.message.subject}"
    )
    typer.echo(
        f"\nClassification: {c.category.upper()}\nIntent: {c.intent or '-'}\nPriority: {c.priority.upper()}\nReply required: {'YES' if c.requires_reply else 'NO'}"
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
        typer.echo(f"\nClassification: {classification['category'].upper()}")
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


if __name__ == "__main__":
    app()
