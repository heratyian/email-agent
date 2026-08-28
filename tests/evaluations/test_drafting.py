from types import SimpleNamespace

from email_agent.drafting.models import DraftOutput
from email_agent.evaluations.drafting import (
    DraftQualityScore,
    draft_quality_evaluator,
    draft_quality_prompt,
    drafting_target,
    escalation_accuracy,
    recipient_accuracy,
    run_drafting_evaluation,
    word_limit,
)


class FakeDrafter:
    def __init__(self):
        self.calls = []

    def draft(self, message, thread, triage, instruction=None):
        self.calls.append((message, thread, triage, instruction))
        return DraftOutput(
            recipient=message.from_address,
            subject=f"Re: {message.subject}",
            body="Wednesday works best. What time would you prefer?",
            reasoning_summary="Followed the scheduling instruction.",
            confidence=0.9,
        )


class FakeJudge:
    def __init__(self):
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return DraftQualityScore(
            required_points_covered=True,
            grounded_in_thread=True,
            instruction_followed=True,
            tone_appropriate=True,
            safe_to_send=True,
            rationale="The draft follows every criterion.",
        )


class FakeClient:
    def __init__(self, exists=False):
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


def example_inputs():
    return {
        "message": {
            "from_address": "alex@example.test",
            "subject": "Meeting",
            "text_body": "Could you meet Tuesday or Wednesday?",
        },
        "thread": [
            {
                "from_address": "evaluation@example.com",
                "subject": "Meeting",
                "text_body": "I am available next week.",
            }
        ],
        "triage": {
            "category": "action",
            "requires_reply": True,
            "priority": "normal",
            "summary": "Alex wants to schedule a meeting.",
            "confidence": 0.95,
            "requires_escalation": False,
        },
        "instruction": "Prefer Wednesday.",
    }


def reference_outputs():
    return {
        "recipient": "alex@example.test",
        "requires_escalation": False,
        "required_points": ["prefers Wednesday"],
        "forbidden_points": ["claims a time is confirmed"],
        "tone": "friendly and concise",
        "max_words": 20,
    }


def test_drafting_target_uses_production_inputs():
    drafter = FakeDrafter()

    output = drafting_target(drafter)(example_inputs())

    message, thread, triage, instruction = drafter.calls[0]
    assert message.from_address == "alex@example.test"
    assert len(thread.messages) == 1
    assert triage.requires_reply is True
    assert instruction == "Prefer Wednesday."
    assert output["recipient"] == "alex@example.test"


def test_deterministic_drafting_evaluators_score_independently():
    output = {
        "recipient": "alex@example.test",
        "requires_escalation": False,
        "body": "A short reply.",
    }
    reference = reference_outputs()

    assert recipient_accuracy(output, reference) is True
    assert escalation_accuracy(output, reference) is True
    assert word_limit(output, reference) is True


def test_quality_prompt_includes_full_reference_criteria():
    prompt = draft_quality_prompt(
        example_inputs(),
        {"body": "Wednesday works best."},
        reference_outputs(),
    )

    assert '"recipient": "alex@example.test"' in prompt
    assert '"requires_escalation": false' in prompt
    assert '"max_words": 20' in prompt


def test_quality_judge_returns_separate_scores_from_one_call():
    judge = FakeJudge()

    results = draft_quality_evaluator(judge)(
        example_inputs(),
        {"body": "Wednesday works best."},
        reference_outputs(),
    )

    assert len(judge.prompts) == 1
    assert [result["key"] for result in results] == [
        "required_points_covered",
        "grounded_in_thread",
        "instruction_followed",
        "tone_appropriate",
        "safe_to_send",
    ]
    assert all(result["score"] is True for result in results)


def test_drafting_evaluation_uses_profile_and_application_tag(monkeypatch):
    client = FakeClient()
    drafter = FakeDrafter()
    judge = FakeJudge()
    model = SimpleNamespace(with_structured_output=lambda schema: judge)
    monkeypatch.setattr("email_agent.evaluations.drafting.get_model", lambda config: model)
    monkeypatch.setattr(
        "email_agent.evaluations.drafting.EmailDrafter",
        lambda root, agent, configured_model: drafter,
    )
    monkeypatch.setenv("LANGSMITH_APPLICATION_TAG_VALUE_ID", "application-tag-value-id")

    result = run_drafting_evaluation("personal", client=client)

    assert result == "results"
    assert client.created[0]["dataset_name"] == "drafting-personal"
    assert client.created[0]["tag_value_ids"] == ["application-tag-value-id"]
    _, values = client.evaluations[0]
    assert values["data"] == "drafting-personal"
    assert values["experiment_prefix"] == "drafting-personal"
    assert len(values["evaluators"]) == 4
