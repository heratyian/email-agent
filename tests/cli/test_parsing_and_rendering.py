from datetime import UTC, datetime
from types import SimpleNamespace

from email_agent.cli.rendering import (
    category_name,
    inbox_table_header,
    inbox_table_row,
    render_processing_summary,
)
from email_agent.models import EmailMessage
from email_agent.services import ProcessingFailure


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
        draft_ready=True,
    )

    lines = capsys.readouterr().out.splitlines()
    assert all(label in lines[0] for label in ("ID", "PRIORITY", "FROM", "SUBJECT", "CATEGORY"))
    assert "DRAFT" in lines[0]
    assert "#175" in lines[2]
    assert "Karen Hall" in lines[2]
    assert "agent/solicitations" in lines[2]
    assert "READY" in lines[2]


def test_shell_processing_summary_replaces_the_second_message_table(capsys):
    message = EmailMessage(
        provider_id="provider-1",
        account_id="person@example.com",
        from_address="sender@example.com",
        subject="Could not process this",
        received_at=datetime.now(UTC),
    )
    results = [
        SimpleNamespace(draft=object()),
        SimpleNamespace(draft=None),
        ProcessingFailure(message=message, error="provider unavailable", local_id=17),
    ]

    count = render_processing_summary(results)

    output = capsys.readouterr().out
    assert count == 2
    assert "Processed 2 new messages · 1 draft ready · 1 failed" in output
    assert "Message #17 (Could not process this): provider unavailable" in output
    assert "PRIORITY" not in output
