from __future__ import annotations

from pathlib import Path

from langchain.agents import create_agent

from email_agent.config import AgentProfile
from email_agent.models import DraftReply, EmailClassification, EmailMessage, EmailThread
from email_agent.prompts import format_thread, system_prompt


class EmailAgents:
    def __init__(self, root: Path, profile: AgentProfile, model):
        self.profile = profile
        self.classifier = create_agent(
            model=model,
            tools=[],
            system_prompt=system_prompt(root, profile, "classify"),
            response_format=EmailClassification,
        )
        self.drafter = create_agent(
            model=model,
            tools=[],
            system_prompt=system_prompt(root, profile, "reply"),
            response_format=DraftReply,
        )

    def classify(self, message: EmailMessage, thread: EmailThread) -> EmailClassification:
        response = self.classifier.invoke(
            {"messages": [{"role": "user", "content": format_thread(thread, message)}]}
        )
        return EmailClassification.model_validate(response["structured_response"])

    def draft(
        self, message: EmailMessage, thread: EmailThread, classification: EmailClassification
    ) -> DraftReply:
        content = (
            f"Classification:\n{classification.model_dump_json(indent=2)}\n\n"
            f"Conversation:\n{format_thread(thread, message)}"
        )
        response = self.drafter.invoke({"messages": [{"role": "user", "content": content}]})
        draft = DraftReply.model_validate(response["structured_response"])
        draft.requires_escalation |= classification.requires_escalation
        draft.escalation_reason = draft.escalation_reason or classification.escalation_reason
        return draft
