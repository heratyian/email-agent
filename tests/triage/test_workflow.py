from datetime import UTC, datetime

import pytest

from email_agent.config import AgentConfig
from email_agent.inbox.workflow import InboxService
from email_agent.persistence import CategorySync, Draft, Message, Triage, initialize_database
from email_agent.providers.base import CategorySyncResult
from email_agent.providers.models import EmailMessage, EmailThread
from email_agent.triage.category_routing import category_destination
from email_agent.triage.models import TriageOutput
from email_agent.triage.workflow import TriageFailure, TriageService


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
        self.triage_calls = 0

    def triage(self, message, thread):
        self.triage_calls += 1
        return TriageOutput(
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
            "triage_prompt": "prompts/test/triage.md",
            "draft_prompt": "prompts/test/draft.md",
        }
    )


def test_inbox_assigns_local_ids_without_triaging_or_changing_mailbox(tmp_path):
    message = make_message()
    initialize_database(tmp_path / "test.db")
    provider = FakeProvider(message)

    items = InboxService(provider).list(unread_only=True)

    assert items[0].local_id > 0
    assert items[0].triage is None
    assert items[0].draft_status is None
    assert Message.get_by_id(items[0].local_id).provider_message_id == "abc"
    assert Message.get_by_id(items[0].local_id).text_body == "I cannot log in"
    assert provider.message_queries == [(20, True)]
    assert provider.synced == []

    repeated = InboxService(provider).list()
    assert repeated[0].local_id == items[0].local_id

    provider.messages[0].text_body = "Updated body"
    InboxService(provider).list()
    assert Message.get_by_id(items[0].local_id).text_body == "Updated body"


def test_inbox_displays_an_existing_triage_without_model_access(tmp_path):
    message = make_message()
    initialize_database(tmp_path / "test.db")
    triage = FakeAgents().triage(message, EmailThread(messages=[message]))
    stored = Message.upsert_email(message)
    Triage.save_for(stored, triage)

    item = InboxService(FakeProvider(message)).list()[0]

    assert item.local_id == stored.id
    assert item.triage == triage


def test_triage_saves_result_and_synchronizes_category_without_drafting(tmp_path):
    message = make_message()
    initialize_database(tmp_path / "test.db")
    provider = FakeProvider(message)
    agents = FakeAgents()
    service = TriageService(make_agent(), provider, agents)
    InboxService(provider).list()
    provider.message_queries.clear()

    result = service.triage_pending(message.account_id)[0]

    assert result.triage.intent == "login_problem"
    assert Message.find_email(message.account_id, message.provider_id).id == result.local_id
    assert list(Draft.pending()) == []
    assert provider.synced == [("abc", "action")]
    assert service.triage_pending(message.account_id) == []
    assert agents.triage_calls == 1
    assert provider.message_queries == []


def test_triage_can_retriage_one_local_message(tmp_path):
    message = make_message()
    initialize_database(tmp_path / "test.db")
    stored = Message.upsert_email(message)
    service = TriageService(make_agent(), FakeProvider(message), FakeAgents())

    result = service.triage_message(stored.id)

    assert result.local_id == stored.id
    assert Message.get_by_id(stored.id).triage_value().requires_reply is True


def test_triage_tracks_an_imap_move(tmp_path):
    class MovingProvider(FakeProvider):
        def sync_category(self, message_id, destination, source_mailbox="INBOX", previous=None):
            return CategorySyncResult(provider_id="900", mailbox="action", source_moved=True)

    message = make_message()
    initialize_database(tmp_path / "test.db")
    provider = MovingProvider(message)
    InboxService(provider).list()
    result = TriageService(make_agent(), provider, FakeAgents()).triage_pending(message.account_id)[
        0
    ]

    stored = Message.get_by_id(result.local_id)
    assert stored.provider_message_id == "abc"
    assert stored.provider_uid == "900"
    assert stored.provider_mailbox == "action"


def test_triage_isolates_one_failure_from_the_batch(tmp_path):
    initialize_database(tmp_path / "test.db")
    first = make_message("fails")
    second = make_message("succeeds")

    class MixedProvider(FakeProvider):
        def sync_category(self, message_id, destination, source_mailbox="INBOX", previous=None):
            if message_id == "fails":
                raise RuntimeError("mailbox unavailable")

    provider = MixedProvider([first, second])
    InboxService(provider).list()
    results = TriageService(make_agent(), provider, FakeAgents()).triage_pending(first.account_id)

    results_by_id = {result.message.provider_id: result for result in results}
    assert isinstance(results_by_id["fails"], TriageFailure)
    assert not isinstance(results_by_id["succeeds"], TriageFailure)


def test_failed_category_sync_remains_eligible_for_default_retry(tmp_path):
    message = make_message("retry")
    initialize_database(tmp_path / "test.db")

    class FailingProvider(FakeProvider):
        def sync_category(self, message_id, destination, source_mailbox="INBOX", previous=None):
            raise RuntimeError("mailbox unavailable")

    failing_provider = FailingProvider(message)
    InboxService(failing_provider).list()
    first_agents = FakeAgents()
    retry_agents = FakeAgents()
    failed = TriageService(make_agent(), failing_provider, first_agents).triage_pending(
        message.account_id
    )
    assert Triage.get().category_sync_pending is True
    retried = TriageService(make_agent(), FakeProvider(message), retry_agents).triage_pending(
        message.account_id
    )

    assert isinstance(failed[0], TriageFailure)
    assert failed[0].triage is not None
    assert not isinstance(retried[0], TriageFailure)
    assert first_agents.triage_calls == 1
    assert retry_agents.triage_calls == 0
    assert Triage.get().category_sync_pending is False


def test_category_sync_audit_is_idempotent(tmp_path):
    message = make_message("categorized")
    initialize_database(tmp_path / "test.db")
    stored = Message.upsert_email(message)
    Triage.save_for(stored, FakeAgents().triage(message, EmailThread(messages=[])))

    assert CategorySync.is_active(stored.id, "Email Agent/Action") is False
    CategorySync.replace_active(stored.id, "Email Agent/Action")
    CategorySync.replace_active(stored.id, "Email Agent/Action")
    assert CategorySync.is_active(stored.id, "Email Agent/Action") is True


def test_unconfigured_category_is_rejected_instead_of_implicitly_mapped():
    triage = TriageOutput(
        category="needs_reply",
        requires_reply=True,
        priority="normal",
        summary="Question",
        confidence=0.9,
    )
    with pytest.raises(KeyError, match="unknown category 'needs_reply'"):
        category_destination(make_agent(), triage)


def test_existing_category_maps_to_unique_nested_destination():
    agent = make_agent()
    agent.categories = {
        "agent/action": "Requires my response.",
        "agent/travel": "Reservations and itinerary changes.",
    }
    triage = TriageOutput(
        category="action",
        requires_reply=True,
        priority="normal",
        summary="Question",
        confidence=0.9,
    )
    assert category_destination(agent, triage) == "agent/action"


def test_uncategorized_message_has_no_provider_destination():
    triage = TriageOutput(
        category=None,
        requires_reply=False,
        priority="normal",
        summary="Does not fit the configured taxonomy",
        confidence=0.8,
    )
    assert category_destination(make_agent(), triage) is None
