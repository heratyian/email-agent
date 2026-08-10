from __future__ import annotations

import time
from typing import Annotated

import typer

from email_agent.agents import EmailAgents
from email_agent.config import Settings
from email_agent.llm import get_model
from email_agent.mail import create_mail_provider
from email_agent.pipeline import EmailPipeline
from email_agent.storage import Database

app = typer.Typer(no_args_is_help=True, help="Safe, profile-driven email triage and drafting.")
config_app = typer.Typer(help="Configuration utilities.")
app.add_typer(config_app, name="config")


def _components(profile_name: str, with_agents: bool = True):
    settings = Settings()
    profile = settings.profile(profile_name)
    provider = create_mail_provider(profile.account, settings.account_for(profile), settings.root)
    database = Database(settings.database_path)
    agents = EmailAgents(settings.root, profile, get_model(profile.model)) if with_agents else None
    return settings, profile, provider, database, agents


@app.command()
def accounts():
    settings = Settings()
    for account_id, account in settings.accounts.items():
        typer.echo(f"{account_id}: {account.provider} ({account.email or 'OAuth account'})")


@config_app.command("validate")
def validate_config():
    settings = Settings()
    profiles = sorted((settings.root / "profiles").glob("*.yaml"))
    for path in profiles:
        profile = settings.profile(path.stem)
        settings.account_for(profile)
        for prompt in (profile.prompts.system, profile.prompts.classify, profile.prompts.reply):
            if not (settings.root / prompt).is_file():
                raise typer.BadParameter(f"Missing prompt: {prompt}")
        typer.echo(f"✓ {profile.id} v{profile.version}")
    typer.echo(f"Validated {len(profiles)} profiles; sending is disabled.")


@app.command()
def inbox(profile: Annotated[str, typer.Option()], limit: int = 20):
    _, selected, provider, database, _ = _components(profile, with_agents=False)
    messages = [
        m
        for m in provider.get_new_messages(limit)
        if not database.is_processed(m.account_id, m.provider_id)
    ]
    typer.echo(f"Checking {selected.name}...\n\n{len(messages)} new messages")
    for index, message in enumerate(messages, 1):
        typer.echo(f"{index}. {message.from_name or message.from_address} — {message.subject}")


def _render(result):
    c = result.classification
    typer.echo(
        f"\n#{result.local_id}\n{result.message.from_name or result.message.from_address}\n{result.message.subject}"
    )
    typer.echo(
        f"\nClassification: {c.category.upper()}\nIntent: {c.intent or '-'}\nPriority: {c.priority.upper()}\nReply required: {'YES' if c.requires_reply else 'NO'}"
    )
    if c.requires_escalation:
        typer.echo(f"\n⚠ Human attention required\n{c.escalation_reason}")
    if result.reply:
        typer.echo(f"\nSuggested response:\n\n{result.reply.body}\n\nSaved to local review queue.")


@app.command()
def process(profile: Annotated[str, typer.Option()], limit: int = 20):
    _, selected, provider, database, agents = _components(profile)
    typer.echo(f"Connecting to {selected.name}...")
    results = EmailPipeline(selected, provider, agents, database).process(limit)
    typer.echo(f"Found {len(results)} new messages.")
    for result in results:
        _render(result)


@app.command()
def monitor(profile: Annotated[str, typer.Option()], interval: int = 300, limit: int = 20):
    if interval < 30:
        raise typer.BadParameter("interval must be at least 30 seconds")
    _, selected, provider, database, agents = _components(profile)
    pipeline = EmailPipeline(selected, provider, agents, database)
    typer.echo(f"Monitoring {selected.name} every {interval}s. Ctrl-C to stop.")
    try:
        while True:
            for result in pipeline.process(limit):
                _render(result)
            time.sleep(interval)
    except KeyboardInterrupt:
        typer.echo("Stopped.")


@app.command()
def drafts(profile: Annotated[str | None, typer.Option()] = None):
    settings = Settings()
    account_id = settings.profile(profile).account if profile else None
    for row in Database(settings.database_path).list_drafts(account_id):
        typer.echo(
            f"{row['message_id']}: [{row['status']}] To {row['recipient']} — {row['subject']}"
        )


@app.command("show")
def show_message(message_id: int):
    settings = Settings()
    row = Database(settings.database_path).show_message(message_id)
    if not row:
        raise typer.BadParameter("message not found")
    typer.echo(
        f"From: {row['from_name'] or row['from_address']}\nSubject: {row['subject']}\nClassification: {row['classification']}"
    )
    typer.echo("\nRaw body is not persisted for privacy.")


@app.command("draft")
def show_draft(message_id: int):
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
    settings = Settings()
    if not Database(settings.database_path).approve(message_id):
        raise typer.BadParameter("draft not found")
    typer.echo("Draft approved locally. No email was sent.")


if __name__ == "__main__":
    app()
