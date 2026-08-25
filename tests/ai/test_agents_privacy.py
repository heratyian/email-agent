from datetime import UTC, datetime

import pytest

import email_agent.ai.agents as agents_module
from email_agent.ai.agents import EmailAgents
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
    created = [
        RecordingAgent(
            {
                "category": "action",
                "requires_reply": True,
                "priority": "normal",
                "summary": "A reply is requested.",
                "confidence": 0.9,
            }
        ),
        RecordingAgent(
            {
                "recipient": "attacker@example.net",
                "subject": "Re: Hello [NAME_1]",
                "body": "Hello [NAME_1], reply to [EMAIL_1].",
                "reasoning_summary": "Answers [NAME_1].",
                "confidence": 0.8,
            }
        ),
    ]
    monkeypatch.setattr(agents_module, "create_agent", lambda **kwargs: created.pop(0))
    config = AgentConfig.model_validate(
        {
            "model": {"provider": "openai", "model": "test"},
            "classification_prompt": "classification.md",
            "draft_prompt": "draft.md",
            "categories": {"action": "Requires a response."},
        }
    )
    email_agents = EmailAgents(tmp_path, config, object())
    return email_agents


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
    email_agents = build_agents(tmp_path, monkeypatch)
    source = source_message()
    classification = ClassificationOutput(
        category="action",
        requires_reply=True,
        priority="normal",
        summary="Jordan Smith requested a reply at jordan@example.com.",
        confidence=0.9,
    )

    draft = email_agents.draft(
        source,
        EmailThread(messages=[source]),
        classification,
        instruction="Mention jordan@example.com.",
    )

    payload = email_agents.drafter.inputs[0]["messages"][0]["content"]
    assert "Jordan Smith" not in payload
    assert "jordan@example.com" not in payload
    assert "(312) 555-0192" not in payload
    assert "[NAME_1]" in payload
    assert "[EMAIL_1]" in payload
    assert "[PHONE_1]" in payload
    assert draft.recipient == "jordan@example.com"
    assert draft.body == "Hello Jordan Smith, reply to jordan@example.com."


def test_credential_detection_stops_the_model_call(tmp_path, monkeypatch):
    email_agents = build_agents(tmp_path, monkeypatch)
    source = source_message("password: swordfish")

    with pytest.raises(SensitiveDataError, match="not sent"):
        email_agents.classify(source, EmailThread(messages=[source]))

    assert email_agents.classifier.inputs == []
