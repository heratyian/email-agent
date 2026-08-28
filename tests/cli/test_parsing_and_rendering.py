from datetime import UTC, datetime

from email_agent.cli.rendering import (
    _cell,
    category_name,
    inbox_table_header,
    inbox_table_row,
    render_inbox_search_response,
)
from email_agent.search.models import InboxSearchResponse, InboxSearchResult


def test_category_name_formats_optional_category():
    assert category_name("follow_up") == "follow up"
    assert category_name(None) == "Uncategorized"


def test_inbox_table_has_labeled_aligned_columns(capsys):
    inbox_table_header()
    inbox_table_row(
        local_id=175,
        priority="low",
        sender="Karen Hall",
        subject="40 hours for Big Green Company",
        category="agent/solicitations",
        requires_reply=True,
        draft_ready=True,
    )

    lines = capsys.readouterr().out.splitlines()
    assert all(label in lines[0] for label in ("ID", "PRIORITY", "FROM", "SUBJECT", "CATEGORY"))
    assert "REPLY" in lines[0]
    assert "DRAFT" in lines[0]
    assert "#175" in lines[2]
    assert "Karen Hall" in lines[2]
    assert "agent/solicitations" in lines[2]
    assert "YES" in lines[2]
    assert "READY" in lines[2]


def test_inbox_cell_uses_terminal_width_for_emojis():
    assert _cell("Hello 👋", 10) == "Hello 👋  "
    assert _cell("One two three 🚀", 12) == "One two thr…"


def test_inbox_search_response_uses_inbox_table_format(capsys):
    render_inbox_search_response(
        InboxSearchResponse(
            summary="Two messages need attention.",
            results=[
                InboxSearchResult(
                    message_id=12,
                    from_address="legal@example.test",
                    from_name="Legal Team",
                    subject="Contract approval",
                    received_at=datetime.now(UTC),
                    category="action",
                    priority="high",
                    requires_reply=True,
                    summary="A contract decision is due.",
                    reason="Matched structured filters.",
                    match_explanation="A decision is due tomorrow.",
                )
            ],
        )
    )

    output = capsys.readouterr().out
    assert "Two messages need attention." in output
    assert "Search · 1 messages" in output
    assert all(label in output for label in ("ID", "PRIORITY", "FROM", "MATCH"))
    assert all(
        value in output
        for value in ("#12", "HIGH", "Legal Team", "Contract approval", "YES")
    )
    assert "A decision is due tomorrow." in output
