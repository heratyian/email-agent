import typer

from email_agent.services import PriorityGroup

GROUP_COLORS = {
    PriorityGroup.URGENT: typer.colors.BRIGHT_RED,
    PriorityGroup.NORMAL: typer.colors.CYAN,
    PriorityGroup.LOW: typer.colors.BRIGHT_BLACK,
}


def category_name(category: str | None) -> str:
    """Render an optional category for human-facing CLI output."""
    return category.replace("_", " ") if category else "Uncategorized"


def message_id(value: int, *, prefix: str = "") -> None:
    """Print a styled local message ID without ending the line."""
    typer.secho(f"{prefix}{value}", fg=typer.colors.CYAN, bold=True, nl=False)


def render_processed(result) -> None:
    """Render one successfully processed message and optional draft."""
    classification = result.classification
    typer.echo()
    message_id(result.local_id, prefix="#")
    typer.echo(
        f"\n{result.message.from_name or result.message.from_address}\n{result.message.subject}"
    )
    typer.echo(
        f"\nCategory: {category_name(classification.category)}"
        f"\nIntent: {classification.intent or '-'}"
        f"\nPriority: {classification.priority.upper()}"
        f"\nReply recommended: {'YES' if classification.requires_reply else 'NO'}"
    )
    if classification.requires_escalation:
        typer.secho("\n⚠ Human attention required", fg=typer.colors.BRIGHT_RED, bold=True)
        typer.echo(classification.escalation_reason)
    if result.reply:
        typer.secho("\nSuggested response:", fg=typer.colors.GREEN, bold=True)
        typer.echo(f"\n{result.reply.body}")
        typer.secho("\nSaved to local review queue.", fg=typer.colors.GREEN)
