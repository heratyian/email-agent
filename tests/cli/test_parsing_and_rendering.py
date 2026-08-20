from email_agent.cli.rendering import (
    category_name,
    inbox_table_header,
    inbox_table_row,
)


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
