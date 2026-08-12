import typer

from email_agent.services import PriorityGroup

GROUP_COLORS = {
    PriorityGroup.URGENT: typer.colors.BRIGHT_RED,
    PriorityGroup.NORMAL: typer.colors.CYAN,
    PriorityGroup.LOW: typer.colors.BRIGHT_BLACK,
}

INBOX_COLUMNS = (
    ("ID", 6),
    ("PRIORITY", 8),
    ("FROM", 22),
    ("SUBJECT", 42),
    ("CATEGORY", 24),
    ("DRAFT", 7),
)


def category_name(category: str | None) -> str:
    """Render an optional category for human-facing CLI output."""
    return category.replace("_", " ") if category else "Uncategorized"


def priority_color(priority: str) -> str:
    """Map model priority to the same colors used by the prioritized inbox."""
    if priority in {"urgent", "high"}:
        return typer.colors.BRIGHT_RED
    if priority == "low":
        return typer.colors.BRIGHT_BLACK
    return typer.colors.CYAN


def message_id(value: int, *, prefix: str = "") -> None:
    """Print a styled local message ID without ending the line."""
    typer.secho(f"{prefix}{value}", fg=typer.colors.CYAN, bold=True, nl=False)


def _cell(value: object, width: int) -> str:
    """Fit one value into a stable terminal column."""
    text = str(value or "—").replace("\n", " ").strip()
    if len(text) > width:
        text = f"{text[: width - 1]}…"
    return text.ljust(width)


def inbox_table_header() -> None:
    """Render labels and a divider for inbox-shaped rows."""
    typer.secho("  ".join(_cell(label, width) for label, width in INBOX_COLUMNS), bold=True)
    typer.secho("  ".join("─" * width for _, width in INBOX_COLUMNS), dim=True)


def inbox_table_row(
    *,
    local_id: int | str,
    priority: str,
    sender: str,
    subject: str,
    category: str | None,
    draft_ready: bool,
    color: str | None = None,
) -> None:
    """Render one aligned inbox row with predictable user-facing fields."""
    values = (
        f"#{local_id}",
        priority.upper(),
        sender,
        subject,
        category_name(category),
        "READY" if draft_ready else "—",
    )
    typer.secho(
        "  ".join(_cell(value, width) for value, (_, width) in zip(values, INBOX_COLUMNS)),
        fg=color,
    )


def render_processed(result) -> None:
    """Render one successfully processed message as an inbox table row."""
    inbox_table_row(
        local_id=result.local_id,
        priority=result.classification.priority,
        sender=result.message.from_name or result.message.from_address,
        subject=result.message.subject,
        category=result.classification.category,
        draft_ready=result.draft is not None,
        color=priority_color(result.classification.priority),
    )
