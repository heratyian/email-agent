from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from email_agent.evaluations.triage import (
    category_accuracy,
    ensure_dataset,
    escalation_accuracy,
    load_profile,
    priority_accuracy,
    reply_accuracy,
    run_triage_evaluation,
    triage_target,
    validate_reference_categories,
)
from email_agent.triage.models import TriageOutput


class FakeAgents:
    def __init__(self):
        self.messages = []

    def triage(self, message, thread):
        self.messages.append((message, thread))
        return TriageOutput(
            category="action",
            requires_reply=True,
            priority="normal",
            summary="A response is needed.",
            confidence=0.9,
        )


def test_triage_target_uses_production_message_shape():
    triager = FakeAgents()

    output = triage_target(triager)(
        {
            "from_address": "customer@example.test",
            "subject": "Question",
            "text_body": "Can you help?",
        }
    )

    message, thread = triager.messages[0]
    assert message.received_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert message.text_body == "Can you help?"
    assert thread.messages == [message]
    assert output["category"] == "action"


def test_field_evaluators_score_independently():
    reference = {
        "category": "action",
        "requires_reply": True,
        "priority": "high",
        "requires_escalation": False,
    }
    output = {
        "category": "action",
        "requires_reply": False,
        "priority": "normal",
        "requires_escalation": False,
    }

    assert category_accuracy(output, reference) is True
    assert reply_accuracy(output, reference) is False
    assert priority_accuracy(output, reference) is False
    assert escalation_accuracy(output, reference) is True


def test_checked_in_examples_use_supported_categories():
    profile = load_profile("personal")

    validate_reference_categories(profile.examples, profile.agent.categories)
    assert profile.agent.model.model == "gpt-5.4-nano"
    assert profile.agent.triage_prompt == "triage.md"


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError, match="unknown evaluation profile"):
        load_profile("missing")


def test_profile_name_cannot_escape_profiles_directory():
    with pytest.raises(ValueError, match="invalid evaluation profile"):
        load_profile("../accounts")


def test_unknown_reference_category_is_rejected():
    examples = [{"outputs": {"category": "missing"}}]

    with pytest.raises(ValueError, match="missing"):
        validate_reference_categories(examples, {"action": ""})


class FakeClient:
    def __init__(self, exists):
        self.exists = exists
        self.created = []
        self.examples = []
        self.evaluations = []

    def has_dataset(self, *, dataset_name):
        return self.exists

    def create_dataset(self, **values):
        self.created.append(values)
        return SimpleNamespace(id="dataset-1")

    def create_examples(self, **values):
        self.examples.append(values)

    def evaluate(self, target, **values):
        self.evaluations.append((target, values))
        return "results"


def test_dataset_is_seeded_only_when_it_does_not_exist():
    client = FakeClient(exists=False)

    ensure_dataset(client, "triage", [{"inputs": {}, "outputs": {}}])

    assert client.created[0]["dataset_name"] == "triage"
    assert client.examples[0]["dataset_id"] == "dataset-1"

    existing = FakeClient(exists=True)
    ensure_dataset(existing, "triage", [])
    assert existing.created == []


def test_new_dataset_is_assigned_to_application():
    client = FakeClient(exists=False)

    ensure_dataset(
        client,
        "triage",
        [],
        application_tag_value_id="application-tag-value-id",
    )

    assert client.created[0]["tag_value_ids"] == ["application-tag-value-id"]


def test_evaluation_uses_profile_without_account_settings(monkeypatch):
    client = FakeClient(exists=False)
    triager = FakeAgents()
    monkeypatch.setattr("email_agent.evaluations.triage.get_model", lambda model: "model")
    monkeypatch.setattr(
        "email_agent.evaluations.triage.EmailTriager",
        lambda root, agent, model: triager,
    )
    monkeypatch.setenv("LANGSMITH_APPLICATION_TAG_VALUE_ID", "application-tag-value-id")

    result = run_triage_evaluation("personal", client=client)

    assert result == "results"
    _, values = client.evaluations[0]
    assert values["data"] == "triage-personal"
    assert values["metadata"]["evaluation_profile"] == "personal"
    assert client.created[0]["tag_value_ids"] == ["application-tag-value-id"]
