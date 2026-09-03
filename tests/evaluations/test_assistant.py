from email_agent.assistant.models import AssistantIntentOutput
from email_agent.evaluations.assistant import (
    action_accuracy,
    argument_accuracy,
    assistant_target,
    confirmation_accuracy,
    reference_accuracy,
    route_accuracy,
    run_assistant_evaluation,
)
from email_agent.evaluations.triage import load_examples, load_profile


class FakePlanner:
    def __init__(self, intent):
        self.intent = intent

    def invoke(self, prompt):
        assert "Session context" in prompt
        return self.intent


class FakeModel:
    def __init__(self, intent):
        self.intent = intent

    def with_structured_output(self, schema):
        assert schema is AssistantIntentOutput
        return FakePlanner(self.intent)


def test_assistant_target_uses_production_interpretation_and_route():
    target = assistant_target(
        FakeModel(
            AssistantIntentOutput(
                action="upload",
                message_id=42,
            )
        )
    )

    output = target({"user_input": "Upload draft 42."})

    assert output["action"] == "upload"
    assert output["message_id"] == 42
    assert output["route"] == "prepare_upload"
    assert output["requires_confirmation"] is True


def test_assistant_target_handles_pending_responses_without_calling_model():
    class ModelMustNotRun:
        def with_structured_output(self, schema):
            return FakePlanner(None)

    target = assistant_target(ModelMustNotRun())

    output = target(
        {
            "user_input": "yes",
            "pending_action": {"action": "triage", "message_id": None},
        }
    )

    assert output["action"] == "confirm"
    assert output["route"] == "confirm"
    assert output["requires_confirmation"] is False

    output = target(
        {
            "user_input": "cancel",
            "pending_action": {"action": "upload", "message_id": 42},
        }
    )

    assert output["action"] == "cancel"
    assert output["route"] == "cancel"
    assert output["requires_confirmation"] is False


def test_assistant_evaluators_score_independent_contracts():
    outputs = {
        "action": "draft",
        "route": "draft",
        "message_id": 42,
        "limit": 20,
        "query_present": False,
        "instruction_present": True,
        "requires_confirmation": False,
    }
    expected = {
        "action": "draft",
        "route": "draft",
        "message_id": 42,
        "instruction_present": True,
        "requires_confirmation": False,
    }

    assert action_accuracy(outputs, expected) is True
    assert route_accuracy(outputs, expected) is True
    assert reference_accuracy(outputs, expected) is True
    assert argument_accuracy(outputs, expected) is True
    assert confirmation_accuracy(outputs, expected) is True
    assert reference_accuracy(outputs, {"message_id": 7}) is False


def test_checked_in_assistant_dataset_covers_routes_and_safety():
    profile = load_profile("personal")
    examples = load_examples(profile.root / "assistant_examples.json")
    routes = {example["outputs"]["route"] for example in examples}

    assert {"confirm", "cancel", "prepare_triage", "prepare_upload"} <= routes
    assert sum(example["outputs"].get("action") == "unsupported" for example in examples) >= 3


class FakeClient:
    def __init__(self):
        self.evaluations = []

    def has_dataset(self, *, dataset_name):
        return True

    def evaluate(self, target, **values):
        self.evaluations.append((target, values))
        return "results"


def test_assistant_evaluation_is_serial_and_blocking(monkeypatch):
    client = FakeClient()
    model = FakeModel(AssistantIntentOutput(action="inbox"))
    monkeypatch.setattr("email_agent.evaluations.assistant.get_model", lambda config: model)

    result = run_assistant_evaluation("personal", client=client)

    assert result == "results"
    target, values = client.evaluations[0]
    assert callable(target)
    assert values["data"] == "assistant-personal"
    assert values["max_concurrency"] == 1
    assert values["blocking"] is True
    assert values["metadata"]["confirmation_policy"] == "triage-and-upload-v1"
