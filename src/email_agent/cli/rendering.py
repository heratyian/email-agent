import typer
from wcwidth import wcswidth, wcwidth

from email_agent.inbox.messages import MessageDetails
from email_agent.persistence import Draft
from email_agent.providers.models import EmailMessage
from email_agent.search.models import InboxSearchResponse
from email_agent.triage.workflow import TriageFailure

INBOX_COLUMNS = (
    ("ID", 6),
    ("PRIORITY", 8),
    ("FROM", 22),
    ("SUBJECT", 42),
    ("CATEGORY", 24),
    ("TRIAGE", 9),
    ("REPLY?", 6),
    ("DRAFT?", 7),
)

SEARCH_COLUMNS = (
    ("ID", 6),
    ("PRIORITY", 8),
    ("FROM", 22),
    ("SUBJECT", 36),
    ("CATEGORY", 18),
    ("REPLY?", 6),
    ("MATCH", 42),
)


def category_name(category: str | None) -> str:
    """Render an optional category for human-facing CLI output."""
    return category.replace("_", " ") if category else ""


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
    text = ("—" if value is None else str(value)).replace("\n", " ").strip()
    # Python counts Unicode code points, but terminals align by display cells.
    # Emoji and East Asian characters often occupy two cells, so len() misaligns later columns.
    if wcswidth(text) > width:
        truncated = []
        available_width = width - 1
        current_width = 0
        for character in text:
            character_width = max(wcwidth(character), 0)
            if current_width + character_width > available_width:
                break
            truncated.append(character)
            current_width += character_width
        text = f"{''.join(truncated)}…"
    return text + " " * max(width - wcswidth(text), 0)


def _table_header(columns: tuple[tuple[str, int], ...]) -> None:
    """Render labels and a divider with shared terminal table styling."""
    typer.secho("  ".join(_cell(label, width) for label, width in columns), bold=True)
    typer.secho("  ".join("─" * width for _, width in columns), dim=True)


def inbox_table_header() -> None:
    """Render labels and a divider for inbox-shaped rows."""
    _table_header(INBOX_COLUMNS)


def inbox_table_row(
    *,
    local_id: int | str,
    priority: str,
    sender: str,
    subject: str,
    category: str | None,
    needs_triage: bool,
    requires_reply: bool | None,
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
        "PENDING" if needs_triage else "DONE",
        "YES" if requires_reply else "NO" if requires_reply is False else "—",
        "READY" if draft_ready else "—",
    )
    typer.secho(
        "  ".join(_cell(value, width) for value, (_, width) in zip(values, INBOX_COLUMNS)),
        fg=color,
    )


def render_inbox_items(items) -> None:
    """Render a newest-first inbox with any existing assistant state."""
    typer.echo(f"\nInbox · {len(items)} messages")
    if items:
        inbox_table_header()
    for item in items:
        triage = item.triage
        priority = triage.priority if triage else "—"
        inbox_table_row(
            local_id=item.local_id,
            priority=priority,
            sender=item.message.from_name or item.message.from_address,
            subject=item.message.subject,
            category=triage.category if triage else None,
            needs_triage=triage is None,
            requires_reply=triage.requires_reply if triage else None,
            draft_ready=item.draft_ready,
            color=priority_color(priority) if triage else None,
        )


def render_inbox_search_response(response: InboxSearchResponse) -> None:
    """Render grounded search results using the inbox table conventions."""
    typer.echo(response.summary)
    typer.echo(f"\nSearch · {len(response.results)} messages")
    if response.results:
        _table_header(SEARCH_COLUMNS)
    for result in response.results:
        priority = result.priority or "—"
        values = (
            f"#{result.message_id}",
            priority.upper(),
            result.from_name or result.from_address,
            result.subject,
            category_name(result.category),
            "YES" if result.requires_reply else "NO" if result.requires_reply is False else "—",
            result.match_explanation or result.summary,
        )
        typer.secho(
            "  ".join(_cell(value, width) for value, (_, width) in zip(values, SEARCH_COLUMNS)),
            fg=priority_color(priority),
        )


def render_triage_results(results) -> int:
    """Render triage successes and isolated failures."""
    if not results:
        typer.echo("No untriaged messages.")
        return 0
    inbox_table_header()
    succeeded = 0
    for result in results:
        if isinstance(result, TriageFailure):
            triage = result.triage
            inbox_table_row(
                local_id=result.local_id or "?",
                priority=triage.priority if triage else "error",
                sender=result.message.from_name or result.message.from_address,
                subject=f"{result.message.subject}: {result.error}",
                category=triage.category if triage else None,
                needs_triage=triage is None,
                requires_reply=triage.requires_reply if triage else None,
                draft_ready=False,
                color=typer.colors.RED,
            )
            continue
        succeeded += 1
        inbox_table_row(
            local_id=result.local_id,
            priority=result.triage.priority,
            sender=result.message.from_name or result.message.from_address,
            subject=result.message.subject,
            category=result.triage.category,
            needs_triage=False,
            requires_reply=result.triage.requires_reply,
            draft_ready=result.draft_ready,
            color=priority_color(result.triage.priority),
        )
    failures = len(results) - succeeded
    typer.secho(
        f"Triaged {succeeded} · {failures} failed",
        fg=typer.colors.RED if failures else typer.colors.GREEN,
        bold=True,
    )
    return succeeded


def render_message_details(details: MessageDetails, *, show_confidence: bool = True) -> None:
    """Render a provider message and its typed triage."""
    message = details.message
    typer.echo(f"From: {message.from_name or message.from_address}")
    typer.echo(f"Subject: {message.subject}\n")
    typer.echo(message.content or "(No plain-text body)")
    triage = details.triage
    if triage is None:
        return
    typer.echo(f"\nCategory: {category_name(triage.category) or '(none)'}")
    typer.echo(f"Priority: {triage.priority.upper()}")
    if show_confidence:
        typer.echo(f"Confidence: {triage.confidence:.2f}")
    typer.echo(f"Summary: {triage.summary}")
    if triage.requires_escalation:
        typer.secho("\n⚠ Human attention required", fg=typer.colors.BRIGHT_RED, bold=True)
        typer.echo(triage.escalation_reason or "Review required.")


def render_draft_list(drafts: list[Draft]) -> None:
    """Render pending draft summaries."""
    for draft in drafts:
        typer.echo(f"{draft.message_id}: To {draft.recipient} — {draft.subject}")


def render_draft(draft: Draft) -> None:
    """Render one complete persisted draft."""
    typer.echo(
        f"To: {draft.recipient}\nSubject: {draft.subject}\n\n{draft.body}\n\nStatus: {draft.status}"
    )


def render_review_item(draft: Draft, source: EmailMessage | None, error: str | None) -> None:
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
