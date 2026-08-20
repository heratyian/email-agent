import typer

from email_agent.db import StoredDraft
from email_agent.models import EmailMessage
from email_agent.services import PRIORITY_GROUP_ORDER, PriorityGroup, ProcessingFailure
from email_agent.services.messages import MessageDetails

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


def render_processing_results(results) -> int:
    """Render isolated processing successes and failures; return success count."""
    if results:
        typer.secho("\nProcessed mail", bold=True)
        inbox_table_header()
    for result in results:
        if isinstance(result, ProcessingFailure):
            inbox_table_row(
                local_id=result.local_id or "?",
                priority="error",
                sender=result.message.from_name or result.message.from_address,
                subject=f"{result.message.subject}: {result.error}",
                category=None,
                draft_ready=False,
                color=typer.colors.RED,
            )
        else:
            render_processed(result)
    succeeded = [item for item in results if not isinstance(item, ProcessingFailure)]
    if results:
        drafts = sum(item.draft is not None for item in succeeded)
        failures = len(results) - len(succeeded)
        typer.secho(
            f"Processed {len(succeeded)} · {drafts} drafts ready · {failures} failed",
            fg=typer.colors.RED if failures else typer.colors.GREEN,
            bold=True,
        )
    return len(succeeded)


def render_processing_summary(results) -> int:
    """Summarize one refresh while keeping isolated failures visible."""
    succeeded = [item for item in results if not isinstance(item, ProcessingFailure)]
    failures = [item for item in results if isinstance(item, ProcessingFailure)]
    drafts = sum(item.draft is not None for item in succeeded)
    message_label = "message" if len(succeeded) == 1 else "messages"
    draft_label = "draft" if drafts == 1 else "drafts"
    typer.secho(
        f"Processed {len(succeeded)} new {message_label} · {drafts} {draft_label} ready · "
        f"{len(failures)} failed",
        fg=typer.colors.RED if failures else typer.colors.GREEN,
        bold=True,
    )
    for failure in failures:
        local_id = failure.local_id or "?"
        typer.secho(
            f"  Message #{local_id} ({failure.message.subject}): {failure.error}",
            fg=typer.colors.RED,
        )
    return len(succeeded)


def render_inbox_items(items) -> None:
    """Render an already-prioritized collection of inbox items."""
    typer.echo(f"\nPrioritized inbox · {len(items)} messages")
    if items:
        inbox_table_header()
    for group in PRIORITY_GROUP_ORDER:
        for item in (entry for entry in items if entry.group is group):
            inbox_table_row(
                local_id=item.local_id,
                priority=item.classification.priority,
                sender=item.message.from_name or item.message.from_address,
                subject=item.message.subject,
                category=item.classification.category,
                draft_ready=item.draft_ready,
                color=GROUP_COLORS[group],
            )


def render_message_details(details: MessageDetails, *, show_confidence: bool = True) -> None:
    """Render a provider message and its typed classification."""
    message = details.message
    typer.echo(f"From: {message.from_name or message.from_address}")
    typer.echo(f"Subject: {message.subject}\n")
    typer.echo(message.content or "(No plain-text body)")
    classification = details.classification
    if classification is None:
        return
    typer.echo(f"\nCategory: {category_name(classification.category)}")
    typer.echo(f"Priority: {classification.priority.upper()}")
    if show_confidence:
        typer.echo(f"Confidence: {classification.confidence:.2f}")
    typer.echo(f"Summary: {classification.summary}")
    if classification.requires_escalation:
        typer.secho("\n⚠ Human attention required", fg=typer.colors.BRIGHT_RED, bold=True)
        typer.echo(classification.escalation_reason or "Review required.")


def render_draft_list(drafts: list[StoredDraft]) -> None:
    """Render pending draft summaries."""
    for draft in drafts:
        typer.echo(f"{draft.message_id}: To {draft.recipient} — {draft.subject}")


def render_draft(draft: StoredDraft) -> None:
    """Render one complete persisted draft."""
    typer.echo(
        f"To: {draft.recipient}\nSubject: {draft.subject}\n\n{draft.body}\n\nStatus: {draft.status}"
    )


def render_review_item(draft: StoredDraft, source: EmailMessage | None, error: str | None) -> None:
    """Render one draft beside its source message when available."""
    typer.secho(f"\nDraft #{draft.message_id}", fg=typer.colors.CYAN, bold=True)
    if error:
        typer.secho(f"Original message unavailable: {error}", fg=typer.colors.RED)
    elif source:
        typer.secho("\nOriginal message", bold=True)
        typer.echo(f"From: {source.from_name or source.from_address}")
        typer.echo(f"Subject: {source.subject}")
        typer.echo(f"Received: {source.received_at.astimezone().strftime('%Y-%m-%d %H:%M %Z')}")
        typer.echo(f"\n{source.content or '(No plain-text body)'}")
    typer.secho("\nSuggested reply", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"To: {draft.recipient}")
    typer.echo(f"Subject: {draft.subject}\n\n{draft.body}\n")
