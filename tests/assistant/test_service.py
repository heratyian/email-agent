from types import SimpleNamespace

from email_agent.assistant.models import AssistantIntentOutput
from email_agent.assistant.service import AssistantConversation


class FakePlanner:
    def __init__(self, intents):
        self.intents = iter(intents)

    def invoke(self, prompt):
        return next(self.intents)


class FakeModel:
    def __init__(self, intents):
        self.planner = FakePlanner(intents)

    def with_structured_output(self, schema):
        assert schema is AssistantIntentOutput
        return self.planner


class FakeHandlers:
    def __init__(self):
        self.calls = []

    def message_account(self, message_id):
        return "person@example.com"

    def run_inbox(self, account_id, limit):
        self.calls.append(("inbox", account_id, limit))
        return SimpleNamespace(items=[SimpleNamespace(local_id=12)])

    def triage(self, account_id, *, message_id=None):
        self.calls.append(("triage", account_id, message_id))
        return ["triaged"]

    def upload_draft(self, message_id):
        self.calls.append(("upload", message_id))
        return "provider-id"


def test_inbox_tool_updates_reference_context():
    handlers = FakeHandlers()
    conversation = AssistantConversation(
        "person@example.com",
        FakeModel([AssistantIntentOutput(action="inbox", limit=5)]),
        handlers,
    )

    turn = conversation.invoke("fetch my five newest messages")

    assert turn.kind == "inbox"
    assert conversation.state["last_message_ids"] == [12]
    assert handlers.calls == [("inbox", "person@example.com", 5)]


def test_triage_requires_confirmation_before_tool_execution():
    handlers = FakeHandlers()
    conversation = AssistantConversation(
        "person@example.com",
        FakeModel([AssistantIntentOutput(action="triage", message_id=12)]),
        handlers,
    )

    first_turn = conversation.invoke("triage message 12")
    confirmed_turn = conversation.invoke("yes")

    assert first_turn.kind == "text"
    assert "synchronize mailbox labels" in first_turn.message
    assert confirmed_turn.kind == "triage"
    assert handlers.calls == [("triage", "person@example.com", 12)]
    assert conversation.state["pending_action"] is None


def test_pending_provider_action_can_be_cancelled():
    handlers = FakeHandlers()
    conversation = AssistantConversation(
        "person@example.com",
        FakeModel([AssistantIntentOutput(action="upload", message_id=12)]),
        handlers,
    )

    conversation.invoke("upload draft 12")
    turn = conversation.invoke("no")

    assert turn.message == "Cancelled."
    assert handlers.calls == []


def test_pending_action_blocks_unrelated_requests():
    handlers = FakeHandlers()
    conversation = AssistantConversation(
        "person@example.com",
        FakeModel([AssistantIntentOutput(action="triage", message_id=12)]),
        handlers,
    )

    conversation.invoke("triage message 12")
    turn = conversation.invoke("fetch my inbox instead")

    assert turn.message == ("Confirm or cancel the pending action before starting another request.")
    assert handlers.calls == []


def test_graph_exposes_explicit_safety_and_tool_nodes():
    conversation = AssistantConversation("person@example.com", FakeModel([]), FakeHandlers())

    assert set(conversation.graph.get_graph().nodes) >= {
        "interpret",
        "inbox",
        "search",
        "show",
        "prepare_triage",
        "draft",
        "drafts",
        "prepare_upload",
        "confirm",
        "cancel",
        "unsupported",
    }
