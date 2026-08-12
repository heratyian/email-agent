from datetime import datetime

import pytest

from email_agent.cli.parsing import parse_snooze
from email_agent.cli.rendering import category_name, inbox_table_header, inbox_table_row


def test_parse_snooze_accepts_iso_date_and_datetime():
    date_value = parse_snooze("2030-01-02")
    datetime_value = parse_snooze("2030-01-02T15:30:00+00:00")

    assert date_value.hour == 9
    assert date_value.tzinfo is not None
    assert datetime_value == datetime.fromisoformat("2030-01-02T15:30:00+00:00")


def test_parse_snooze_rejects_unrecognized_value():
    with pytest.raises(ValueError, match="tomorrow"):
        parse_snooze("next week sometime")


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
        state="new",
    )

    lines = capsys.readouterr().out.splitlines()
    assert all(label in lines[0] for label in ("ID", "PRIORITY", "FROM", "SUBJECT", "CATEGORY"))
    assert "DRAFT" in lines[0]
    assert "STATE" in lines[0]
    assert "#175" in lines[2]
    assert "Karen Hall" in lines[2]
    assert "agent/solicitations" in lines[2]
    assert "READY" in lines[2]
