from datetime import UTC, datetime

import pytest

from email_agent.config import AgentConfig
from email_agent.db import Database
from email_agent.models import EmailClassification, EmailMessage, EmailThread
from email_agent.providers.base import CategorySyncResult
from email_agent.services.category_routing import category_destination
from email_agent.services.classification import ClassificationFailure, ClassificationService
from email_agent.services.inbox import InboxService


class FakeProvider:
    def __init__(self, messages):
        self.messages = messages if isinstance(messages, list) else [messages]
        self.message_queries = []
        self.synced = []

    def get_messages(self, limit=20, *, unread_only=False):
        self.message_queries.append((limit, unread_only))
        return self.messages[:limit]

    def get_message(self, message_id, mailbox="INBOX"):
        return next(message for message in self.messages if message.provider_id == message_id)

    def get_thread(self, message_id, mailbox="INBOX"):
        return EmailThread(messages=[self.get_message(message_id, mailbox)])

    def sync_category(self, message_id, destination, source_mailbox="INBOX", previous=None):
        self.synced.append((message_id, destination))

    @staticmethod
    def category_sync_key(destination):
        return destination


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


def make_message(provider_id="abc"):
    return EmailMessage(
        provider_id=provider_id,
        account_id="support@example.com",
        from_address="customer@example.com",
        subject="Login",
        text_body="I cannot log in",
        received_at=datetime.now(UTC),
    )


def make_agent() -> AgentConfig:
    return AgentConfig.model_validate(
        {
            "model": {"provider": "openai", "model": "test-model"},
            "system_prompt": "prompts/test/system.md",
        }
    )


def test_inbox_assigns_local_ids_without_classifying_or_changing_mailbox(tmp_path):
    message = make_message()
    database = Database(tmp_path / "test.db")
    provider = FakeProvider(message)

    items = InboxService(provider, database).list(unread_only=True)

    assert items[0].local_id > 0
    assert items[0].classification is None
    assert items[0].draft_ready is False
    assert database.show_message(items[0].local_id).provider_message_id == "abc"
    assert provider.message_queries == [(20, True)]
    assert provider.synced == []

    repeated = InboxService(provider, database).list()
    assert repeated[0].local_id == items[0].local_id


def test_inbox_displays_an_existing_classification_without_model_access(tmp_path):
    message = make_message()
    database = Database(tmp_path / "test.db")
    classification = FakeAgents().classify(message, EmailThread(messages=[message]))
    local_id = database.save_triage(message, classification)

    item = InboxService(FakeProvider(message), database).list()[0]

    assert item.local_id == local_id
    assert item.classification == classification


def test_classification_saves_result_and_synchronizes_category_without_drafting(tmp_path):
    message = make_message()
    database = Database(tmp_path / "test.db")
    provider = FakeProvider(message)
    agents = FakeAgents()
    service = ClassificationService(make_agent(), provider, agents, database)

    result = service.classify_recent()[0]

    assert result.classification.intent == "login_problem"
    assert database.get_triage(message.account_id, message.provider_id)[0] == result.local_id
    assert database.list_drafts() == []
    assert provider.synced == [("abc", "action")]
    assert service.classify_recent() == []
    assert agents.classification_calls == 1


def test_classification_can_reclassify_one_local_message(tmp_path):
    message = make_message()
    database = Database(tmp_path / "test.db")
    local_id = database.save_message(message)
    service = ClassificationService(make_agent(), FakeProvider(message), FakeAgents(), database)

    result = service.classify_message(local_id)

    assert result.local_id == local_id
    assert database.show_message(local_id).classification.requires_reply is True


def test_classification_tracks_an_imap_move(tmp_path):
    class MovingProvider(FakeProvider):
        def sync_category(self, message_id, destination, source_mailbox="INBOX", previous=None):
            return CategorySyncResult(provider_id="900", mailbox="action", source_moved=True)

    message = make_message()
    database = Database(tmp_path / "test.db")
    result = ClassificationService(
        make_agent(), MovingProvider(message), FakeAgents(), database
    ).classify_recent()[0]

    stored = database.show_message(result.local_id)
    assert stored.provider_message_id == "abc"
    assert stored.provider_uid == "900"
    assert stored.provider_mailbox == "action"


def test_classification_isolates_one_failure_from_the_batch(tmp_path):
    first = make_message("fails")
    second = make_message("succeeds")

    class MixedProvider(FakeProvider):
        def sync_category(self, message_id, destination, source_mailbox="INBOX", previous=None):
            if message_id == "fails":
                raise RuntimeError("mailbox unavailable")

    results = ClassificationService(
        make_agent(), MixedProvider([first, second]), FakeAgents(), Database(tmp_path / "test.db")
    ).classify_recent()

    assert isinstance(results[0], ClassificationFailure)
    assert not isinstance(results[1], ClassificationFailure)


def test_failed_category_sync_remains_eligible_for_default_retry(tmp_path):
    message = make_message("retry")
    database = Database(tmp_path / "test.db")

    class FailingProvider(FakeProvider):
        def sync_category(self, message_id, destination, source_mailbox="INBOX", previous=None):
            raise RuntimeError("mailbox unavailable")

    failed = ClassificationService(
        make_agent(), FailingProvider(message), FakeAgents(), database
    ).classify_recent()
    retried = ClassificationService(
        make_agent(), FakeProvider(message), FakeAgents(), database
    ).classify_recent()

    assert isinstance(failed[0], ClassificationFailure)
    assert not isinstance(retried[0], ClassificationFailure)


def test_category_sync_audit_is_idempotent(tmp_path):
    message = make_message("categorized")
    database = Database(tmp_path / "test.db")
    local_id = database.save_triage(
        message, FakeAgents().classify(message, EmailThread(messages=[]))
    )

    assert database.category_was_synced(local_id, "Email Agent/Action") is False
    database.mark_category_synced(local_id, "Email Agent/Action")
    database.mark_category_synced(local_id, "Email Agent/Action")
    assert database.category_was_synced(local_id, "Email Agent/Action") is True


def test_unconfigured_category_is_rejected_instead_of_implicitly_mapped():
    classification = EmailClassification(
        category="needs_reply",
        requires_reply=True,
        priority="normal",
        summary="Question",
        confidence=0.9,
    )
    with pytest.raises(KeyError, match="unknown category 'needs_reply'"):
        category_destination(make_agent(), classification)


def test_existing_category_maps_to_unique_nested_destination():
    agent = make_agent()
    agent.categories = {
        "agent/action": "Requires my response.",
        "agent/travel": "Reservations and itinerary changes.",
    }
    classification = EmailClassification(
        category="action",
        requires_reply=True,
        priority="normal",
        summary="Question",
        confidence=0.9,
    )
    assert category_destination(agent, classification) == "agent/action"


def test_uncategorized_message_has_no_provider_destination():
    classification = EmailClassification(
        category=None,
        requires_reply=False,
        priority="normal",
        summary="Does not fit the configured taxonomy",
        confidence=0.8,
    )
    assert category_destination(make_agent(), classification) is None
