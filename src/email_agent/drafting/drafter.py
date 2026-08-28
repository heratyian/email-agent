from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter

from langchain.agents import create_agent

from email_agent.config import AgentConfig
from email_agent.drafting.models import DraftOutput
from email_agent.drafting.prompt import draft_system_prompt, format_thread
from email_agent.llm.tracing import trace_payload, trace_response
from email_agent.privacy import redact
from email_agent.providers.models import EmailMessage, EmailThread
from email_agent.triage.models import TriageOutput

logger = logging.getLogger(__name__)


class EmailDrafter:
    """Draft email replies with one configured structured-output model."""

    def __init__(self, root: Path, agent: AgentConfig, model):
        self.agent = agent
        self.system_prompt = redact(draft_system_prompt(root, agent)).sanitized_text
        self.model_agent = create_agent(
            model=model,
            tools=[],
            system_prompt=self.system_prompt,
            response_format=DraftOutput,
        )

    def draft(
        self,
        message: EmailMessage,
        thread: EmailThread,
        triage: TriageOutput,
        instruction: str | None = None,
    ) -> DraftOutput:
        """Draft one suggested reply using triage and thread context."""
        content = (
            f"Triage:\n{triage.model_dump_json(indent=2)}\n\n"
            f"Conversation:\n{format_thread(thread, message)}"
        )
        if instruction:
            content += f"\n\nOne-time drafting guidance:\n{instruction.strip()}"
        messages = [*thread.messages, message]
        known_names = [item.from_name for item in messages if item.from_name]
        redaction = redact(content, known_names=known_names)
        content = redaction.sanitized_text
        logger.info(
            "Starting draft generation with %s:%s",
            self.agent.model.provider,
            self.agent.model.model,
        )
        logger.debug(
            "Draft input: thread_messages=%d characters=%d", len(thread.messages), len(content)
        )
        trace_payload("draft", self.system_prompt, content)
        started = perf_counter()
        response = self.model_agent.invoke({"messages": [{"role": "user", "content": content}]})
        draft = DraftOutput.model_validate(response["structured_response"])
        logger.info("Draft generation completed in %.2fs", perf_counter() - started)
        logger.debug(
            "Draft result: confidence=%.2f escalation=%s characters=%d",
            draft.confidence,
            draft.requires_escalation,
            len(draft.body),
        )
        trace_response("draft", draft.model_dump())
        draft = draft.model_copy(
            update={
                "recipient": message.from_address,
                "subject": redaction.placeholder_map.restore(draft.subject),
                "body": redaction.placeholder_map.restore(draft.body),
                "reasoning_summary": redaction.placeholder_map.restore(draft.reasoning_summary),
                "escalation_reason": (
                    redaction.placeholder_map.restore(draft.escalation_reason)
                    if draft.escalation_reason
                    else None
                ),
            }
        )
        draft.requires_escalation |= triage.requires_escalation
        draft.escalation_reason = draft.escalation_reason or triage.escalation_reason
        return draft
