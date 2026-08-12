from __future__ import annotations

import json
import logging
from pathlib import Path
from time import perf_counter

from langchain.agents import create_agent

from email_agent.ai.prompts import format_thread, system_prompt
from email_agent.config import AgentConfig
from email_agent.diagnostics import model_tracing_enabled
from email_agent.models import DraftReply, EmailClassification, EmailMessage, EmailThread

logger = logging.getLogger(__name__)


class EmailAgents:
    """LangChain agents for the two bounded LLM tasks in the workflow."""

    def __init__(self, root: Path, agent: AgentConfig, model):
        self.agent = agent
        self.classification_prompt = system_prompt(root, agent, "classify")
        self.draft_prompt = system_prompt(root, agent, "reply")
        self.classifier = create_agent(
            model=model,
            tools=[],
            system_prompt=self.classification_prompt,
            response_format=EmailClassification,
        )
        self.drafter = create_agent(
            model=model,
            tools=[],
            system_prompt=self.draft_prompt,
            response_format=DraftReply,
        )

    def classify(self, message: EmailMessage, thread: EmailThread) -> EmailClassification:
        content = format_thread(thread, message)
        logger.info(
            "Starting classification with %s:%s",
            self.agent.model.provider,
            self.agent.model.model,
        )
        logger.debug(
            "Classification input: thread_messages=%d characters=%d",
            len(thread.messages),
            len(content),
        )
        self._trace_payload("classification", self.classification_prompt, content)
        started = perf_counter()
        response = self.classifier.invoke({"messages": [{"role": "user", "content": content}]})
        classification = EmailClassification.model_validate(response["structured_response"])
        logger.info("Classification completed in %.2fs", perf_counter() - started)
        logger.debug("Classification result: %s", classification.model_dump_json())
        self._trace_response("classification", classification.model_dump())
        if (
            classification.category is not None
            and classification.category not in self.agent.categories
        ):
            allowed = ", ".join(self.agent.categories)
            raise ValueError(
                f"Model returned unknown category {classification.category!r}; expected {allowed}"
            )
        return classification

    def draft(
        self, message: EmailMessage, thread: EmailThread, classification: EmailClassification
    ) -> DraftReply:
        content = (
            f"Classification:\n{classification.model_dump_json(indent=2)}\n\n"
            f"Conversation:\n{format_thread(thread, message)}"
        )
        logger.info(
            "Starting draft generation with %s:%s",
            self.agent.model.provider,
            self.agent.model.model,
        )
        logger.debug(
            "Draft input: thread_messages=%d characters=%d", len(thread.messages), len(content)
        )
        self._trace_payload("draft", self.draft_prompt, content)
        started = perf_counter()
        response = self.drafter.invoke({"messages": [{"role": "user", "content": content}]})
        draft = DraftReply.model_validate(response["structured_response"])
        logger.info("Draft generation completed in %.2fs", perf_counter() - started)
        logger.debug(
            "Draft result: confidence=%.2f escalation=%s characters=%d",
            draft.confidence,
            draft.requires_escalation,
            len(draft.body),
        )
        self._trace_response("draft", draft.model_dump())
        draft.requires_escalation |= classification.requires_escalation
        draft.escalation_reason = draft.escalation_reason or classification.escalation_reason
        return draft

    @staticmethod
    def _trace_payload(task: str, system: str, user: str) -> None:
        if model_tracing_enabled():
            logger.info("MODEL TRACE %s system prompt:\n%s", task, system)
            logger.info("MODEL TRACE %s user prompt:\n%s", task, user)

    @staticmethod
    def _trace_response(task: str, response: dict) -> None:
        if model_tracing_enabled():
            logger.info("MODEL TRACE %s structured response:\n%s", task, json.dumps(response, indent=2))
