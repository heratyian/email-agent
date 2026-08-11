from datetime import UTC, datetime

import pytest

from email_agent.config import Settings
from email_agent.models import DraftReply, EmailClassification, EmailMessage, EmailThread
from email_agent.pipeline import (
    EmailPipeline,
    InboxGroup,
    LocalMessageStatus,
    inbox_group,
    triage_inbox,
)
from email_agent.storage import Database


class FakeProvider:
    def __init__(self, message):
        self.message = message

    def get_new_messages(self, limit=20):
        return [self.message]

    def get_messages(self, limit=20, *, unread_only=False):
        return [self.message]

    def get_thread(self, message_id):
        return EmailThread(messages=[self.message])

    def mark_processed(self, message_id):
        pass


class FakeAgents:
    def __init__(self):
        self.classification_calls = 0

    def classify(self, message, thread):
        self.classification_calls += 1
        return EmailClassification(
            category="support_request",
            requires_reply=True,
            priority="normal",
            intent="login_problem",
            summary="Cannot log in",
            confidence=0.95,
        )

    def draft(self, message, thread, classification):
        return DraftReply(
            recipient=message.from_address,
            subject="Re: Login",
            body="Please share the error message.\n\nThanks,\nReceipt AI Support",
            reasoning_summary="More diagnostic detail is needed.",
            confidence=0.9,
        )


def test_pipeline_classifies_and_stores_local_draft(tmp_path):
    message = EmailMessage(
        provider_id="abc",
        account_id="receipt_ai_support",
        from_address="customer@example.com",
        subject="Login",
        text_body="I cannot log in",
        received_at=datetime.now(UTC),
    )
    profile = Settings().profile("receipt_ai_support")
    db = Database(tmp_path / "test.db")
    results = EmailPipeline(profile, FakeProvider(message), FakeAgents(), db).process()
    assert results[0].classification.intent == "login_problem"
    assert results[0].draft.status == "generated"
    assert len(db.list_drafts()) == 1
    assert EmailPipeline(profile, FakeProvider(message), FakeAgents(), db).process() == []


@pytest.mark.parametrize(
    ("classification", "expected"),
    [
        (
            EmailClassification(
                category="needs_reply",
                requires_reply=True,
                priority="normal",
                summary="Question",
                confidence=0.9,
            ),
            InboxGroup.NEEDS_REPLY,
        ),
        (
            EmailClassification(
                category="urgent",
                requires_reply=False,
                priority="urgent",
                summary="Security alert",
                confidence=0.9,
            ),
            InboxGroup.IMPORTANT,
        ),
        (
            EmailClassification(
                category="automated",
                requires_reply=False,
                priority="low",
                summary="Order shipped",
                confidence=0.9,
            ),
            InboxGroup.INFORMATIONAL,
        ),
        (
            EmailClassification(
                category="newsletter",
                requires_reply=False,
                priority="low",
                summary="Newsletter",
                confidence=0.9,
            ),
            InboxGroup.IGNORED,
        ),
        (
            EmailClassification(
                category="unknown",
                requires_reply=False,
                priority="normal",
                summary="Uncertain",
                confidence=0.4,
            ),
            InboxGroup.IMPORTANT,
        ),
    ],
)
def test_inbox_grouping(classification, expected):
    assert inbox_group(classification) is expected


def test_inbox_triage_assigns_local_id_without_completing_processing(tmp_path):
    message = EmailMessage(
        provider_id="triage-only",
        account_id="receipt_ai_support",
        from_address="customer@example.com",
        subject="Login",
        text_body="I cannot log in",
        received_at=datetime.now(UTC),
    )
    db = Database(tmp_path / "test.db")
    agents = FakeAgents()
    results = triage_inbox(FakeProvider(message), agents, db)
    assert results[0].group is InboxGroup.NEEDS_REPLY
    assert results[0].status is LocalMessageStatus.NEW
    assert results[0].local_id > 0
    assert db.show_message(results[0].local_id)["provider_message_id"] == "triage-only"
    assert db.is_processed(message.account_id, message.provider_id) is False
    assert db.list_drafts() == []

    repeated = triage_inbox(FakeProvider(message), agents, db)
    assert repeated[0].local_id == results[0].local_id
    assert repeated[0].status is LocalMessageStatus.TRIAGED
    assert agents.classification_calls == 1

    processed = EmailPipeline(
        Settings().profile("receipt_ai_support"), FakeProvider(message), agents, db
    ).process()
    assert processed[0].local_id == results[0].local_id
    assert processed[0].draft is not None
    assert db.is_processed(message.account_id, message.provider_id) is True

    browsed = triage_inbox(FakeProvider(message), agents, db)
    assert browsed[0].local_id == results[0].local_id
    assert browsed[0].status is LocalMessageStatus.PROCESSED
    assert triage_inbox(FakeProvider(message), agents, db, unprocessed_only=True) == []
