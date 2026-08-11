from datetime import UTC, datetime

import pytest

from email_agent.config import AgentConfig
from email_agent.models import DraftReply, EmailClassification, EmailMessage, EmailThread
from email_agent.pipeline import (
    EmailPipeline,
    PriorityGroup,
    category_destination,
    inbox_group,
    triage_inbox,
)
from email_agent.storage import Database


class FakeProvider:
    def __init__(self, message):
        self.message = message
        self.synced = []

    def get_new_messages(self, limit=20):
        return [self.message]

    def get_messages(self, limit=20, *, unread_only=False):
        return [self.message]

    def get_thread(self, message_id):
        return EmailThread(messages=[self.message])

    def mark_processed(self, message_id):
        pass

    def sync_category(self, message_id, destination):
        self.synced.append((message_id, destination))


class FakeAgents:
    def __init__(self):
        self.classification_calls = 0

    def classify(self, message, thread):
        self.classification_calls += 1
        return EmailClassification(
            category="action",
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


def make_agent() -> AgentConfig:
    return AgentConfig.model_validate(
        {
            "name": "Test Agent",
            "model": {"provider": "openai", "model": "test-model"},
            "system_prompt": "prompts/test/system.md",
        }
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
    agent = make_agent()
    db = Database(tmp_path / "test.db")
    provider = FakeProvider(message)
    results = EmailPipeline("support@example.com", agent, provider, FakeAgents(), db).process()
    assert results[0].classification.intent == "login_problem"
    assert results[0].draft.status == "generated"
    assert len(db.list_drafts()) == 1
    assert provider.synced == [("abc", "email agent/action")]
    assert db.category_was_synced(results[0].local_id, "email agent/action") is True
    assert (
        EmailPipeline(
            "support@example.com", agent, FakeProvider(message), FakeAgents(), db
        ).process()
        == []
    )


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
            PriorityGroup.NORMAL,
        ),
        (
            EmailClassification(
                category="urgent",
                requires_reply=False,
                priority="urgent",
                summary="Security alert",
                confidence=0.9,
            ),
            PriorityGroup.URGENT,
        ),
        (
            EmailClassification(
                category="automated",
                requires_reply=False,
                priority="low",
                summary="Order shipped",
                confidence=0.9,
            ),
            PriorityGroup.LOW,
        ),
        (
            EmailClassification(
                category="newsletter",
                requires_reply=False,
                priority="low",
                summary="Newsletter",
                confidence=0.9,
            ),
            PriorityGroup.LOW,
        ),
        (
            EmailClassification(
                category="unknown",
                requires_reply=False,
                priority="normal",
                summary="Uncertain",
                confidence=0.4,
            ),
            PriorityGroup.NORMAL,
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
    assert results[0].group is PriorityGroup.NORMAL
    assert results[0].attention_state == "open"
    assert results[0].local_id > 0
    assert db.show_message(results[0].local_id)["provider_message_id"] == "triage-only"
    assert db.is_processed(message.account_id, message.provider_id) is False
    assert db.list_drafts() == []

    repeated = triage_inbox(FakeProvider(message), agents, db)
    assert repeated[0].local_id == results[0].local_id
    assert repeated[0].attention_state == "open"
    assert agents.classification_calls == 1

    processed = EmailPipeline(
        "support@example.com", make_agent(), FakeProvider(message), agents, db
    ).process()
    assert processed[0].local_id == results[0].local_id
    assert processed[0].draft is not None
    assert db.is_processed(message.account_id, message.provider_id) is True

    browsed = triage_inbox(FakeProvider(message), agents, db)
    assert browsed[0].local_id == results[0].local_id
    assert browsed[0].attention_state == "open"


def test_attention_workflow_and_expired_snooze(tmp_path):
    message = EmailMessage(
        provider_id="attention",
        account_id="support@example.com",
        from_address="customer@example.com",
        subject="Handled on Slack",
        text_body="Can you help?",
        received_at=datetime.now(UTC),
    )
    db = Database(tmp_path / "test.db")
    local_id = db.save_triage(message, FakeAgents().classify(message, EmailThread(messages=[])))

    assert db.attention_state(local_id) == "open"
    assert db.set_attention(local_id, "done") is not None
    assert db.attention_state(local_id) == "done"
    assert (
        db.set_attention(
            local_id,
            "snoozed",
            snoozed_until=datetime(2000, 1, 1, tzinfo=UTC),
        )
        is not None
    )
    assert db.attention_state(local_id) == "open"


def test_category_sync_audit_is_idempotent(tmp_path):
    message = EmailMessage(
        provider_id="categorized",
        account_id="support@example.com",
        from_address="customer@example.com",
        subject="Question",
        received_at=datetime.now(UTC),
    )
    db = Database(tmp_path / "test.db")
    local_id = db.save_triage(message, FakeAgents().classify(message, EmailThread(messages=[])))

    assert db.category_was_synced(local_id, "Email Agent/Action") is False
    db.mark_category_synced(local_id, "Email Agent/Action")
    db.mark_category_synced(local_id, "Email Agent/Action")
    assert db.category_was_synced(local_id, "Email Agent/Action") is True
    assert len(db.list_categorized_messages("support@example.com")) == 1

    db.set_attention(local_id, "done")
    replacement = EmailClassification(
        category="reference",
        requires_reply=False,
        priority="low",
        summary="Updated taxonomy",
        confidence=0.9,
    )
    assert db.update_classification(local_id, replacement) is True
    assert db.attention_state(local_id) == "done"
    assert db.get_triage("support@example.com", "categorized")[1].category == "reference"


def test_legacy_category_maps_to_new_provider_destination():
    classification = EmailClassification(
        category="needs_reply",
        requires_reply=True,
        priority="normal",
        summary="Question",
        confidence=0.9,
    )
    assert category_destination(make_agent(), classification) == "email agent/action"
