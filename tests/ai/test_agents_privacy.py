from datetime import UTC, datetime

import pytest

import email_agent.ai.classifier as classifier_module
import email_agent.ai.drafter as drafter_module
from email_agent.ai.classifier import EmailClassifier
from email_agent.ai.drafter import EmailDrafter
from email_agent.ai.outputs import ClassificationOutput
from email_agent.config import AgentConfig
from email_agent.privacy import SensitiveDataError
from email_agent.providers.models import EmailMessage, EmailThread


class RecordingAgent:
    def __init__(self, response: dict):
        self.response = response
        self.inputs: list[dict] = []

    def invoke(self, value: dict) -> dict:
        self.inputs.append(value)
        return {"structured_response": self.response}


def build_agents(tmp_path, monkeypatch):
    classification_prompt = tmp_path / "classification.md"
    classification_prompt.write_text("Escalate sensitive messages.")
    draft_prompt = tmp_path / "draft.md"
    draft_prompt.write_text("Write concise replies.")
    classifier_agent = RecordingAgent(
        {
            "category": "action",
            "requires_reply": True,
            "priority": "normal",
            "summary": "A reply is requested.",
            "confidence": 0.9,
        }
    )
    drafter_agent = RecordingAgent(
        {
            "recipient": "attacker@example.net",
            "subject": "Re: Hello [NAME_1]",
            "body": "Hello [NAME_1], reply to [EMAIL_1].",
            "reasoning_summary": "Answers [NAME_1].",
            "confidence": 0.8,
        }
    )
    monkeypatch.setattr(classifier_module, "create_agent", lambda **kwargs: classifier_agent)
    monkeypatch.setattr(drafter_module, "create_agent", lambda **kwargs: drafter_agent)
    config = AgentConfig.model_validate(
        {
            "model": {"provider": "openai", "model": "test"},
            "classification_prompt": "classification.md",
            "draft_prompt": "draft.md",
            "categories": {"action": "Requires a response."},
        }
    )
    return EmailClassifier(tmp_path, config, object()), EmailDrafter(
        tmp_path, config, object()
    )


def source_message(body="Contact Jordan Smith at jordan@example.com or (312) 555-0192."):
    return EmailMessage(
        provider_id="provider-1",
        account_id="me@example.com",
        from_address="jordan@example.com",
        from_name="Jordan Smith",
        to=["me@example.com"],
        subject="Hello Jordan Smith",
        text_body=body,
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_all_dynamic_draft_input_is_redacted_and_output_is_safely_restored(
    tmp_path, monkeypatch
):
    _, drafter = build_agents(tmp_path, monkeypatch)
    source = source_message()
    classification = ClassificationOutput(
        category="action",
        requires_reply=True,
        priority="normal",
        summary="Jordan Smith requested a reply at jordan@example.com.",
        confidence=0.9,
    )

    draft = drafter.draft(
        source,
        EmailThread(messages=[source]),
        classification,
        instruction="Mention jordan@example.com.",
    )

    payload = drafter.model_agent.inputs[0]["messages"][0]["content"]
    assert "Jordan Smith" not in payload
    assert "jordan@example.com" not in payload
    assert "(312) 555-0192" not in payload
    assert "[NAME_1]" in payload
    assert "[EMAIL_1]" in payload
    assert "[PHONE_1]" in payload
    assert draft.recipient == "jordan@example.com"
    assert draft.body == "Hello Jordan Smith, reply to jordan@example.com."


def test_credential_detection_stops_the_model_call(tmp_path, monkeypatch):
    classifier, _ = build_agents(tmp_path, monkeypatch)
    source = source_message("password: swordfish")

    with pytest.raises(SensitiveDataError, match="not sent"):
        classifier.classify(source, EmailThread(messages=[source]))

    assert classifier.model_agent.inputs == []
