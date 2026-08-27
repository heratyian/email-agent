from datetime import UTC, datetime, timedelta

from email_agent.ai.outputs import ClassificationOutput
from email_agent.db import Classification, Message, initialize_database
from email_agent.providers.models import EmailMessage
from email_agent.search.graph import ground_answer, merge_results
from email_agent.search.models import InboxSearchAnswer, InboxSearchAnswerItem, InboxSearchPlan
from email_agent.search.tools import search_classified_messages


def store_message(account_id, subject, summary, *, priority="normal", requires_reply=False):
    message = Message.upsert_email(
        EmailMessage(
            provider_id=subject,
            thread_id=subject,
            account_id=account_id,
            from_address="sender@example.com",
            subject=subject,
            text_body="Body",
            received_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    Classification.save_for(
        message,
        ClassificationOutput(
            category="action",
            requires_reply=requires_reply,
            priority=priority,
            summary=summary,
            confidence=0.9,
            requires_escalation=False,
        ),
    )
    return message


def test_structured_search_filters_classified_messages(tmp_path):
    initialize_database(tmp_path / "email.db")
    store_message(
        "person@example.com",
        "Interview availability",
        "A recruiter asked for interview availability.",
        requires_reply=True,
    )
    store_message("person@example.com", "Newsletter", "A product newsletter.")

    results = search_classified_messages(
        "person@example.com",
        InboxSearchPlan(
            query="what needs reply",
            requires_reply=True,
            recent_days=14,
            rationale="Find replies.",
        ),
    )

    assert [result.subject for result in results] == ["Interview availability"]


def test_merge_results_combines_scores_for_same_message():
    from email_agent.search.models import InboxSearchResult

    base = InboxSearchResult(
        message_id=1,
        from_address="sender@example.com",
        subject="Interview availability",
        received_at=datetime.now(UTC),
        summary="Recruiter asked for availability.",
        reason="Structured.",
        score=2,
    )

    merged = merge_results([base], [base.model_copy(update={"reason": "Vector.", "score": 3})])

    assert len(merged) == 1
    assert merged[0].score == 5
    assert "Structured" in merged[0].reason
    assert "Vector" in merged[0].reason


def test_ground_answer_discards_unknown_ids_and_restores_subjects():
    from email_agent.search.models import InboxSearchResult

    result = InboxSearchResult(
        message_id=7,
        from_address="sender@example.com",
        subject="Authoritative subject",
        received_at=datetime.now(UTC),
        summary="A grounded summary.",
        reason="Structured.",
    )
    answer = InboxSearchAnswer(
        summary="Two possible messages.",
        messages=[
            InboxSearchAnswerItem(
                message_id=7,
                subject="Model-controlled subject",
                explanation="This one matches.",
            ),
            InboxSearchAnswerItem(
                message_id=7,
                subject="Duplicate",
                explanation="Duplicate reference.",
            ),
            InboxSearchAnswerItem(
                message_id=99,
                subject="Invented",
                explanation="Unknown reference.",
            ),
        ],
    )

    grounded = ground_answer(answer, [result])

    assert [item.message_id for item in grounded.messages] == [7]
    assert grounded.messages[0].subject == "Authoritative subject"
