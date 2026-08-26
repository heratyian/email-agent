from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter

from langchain.agents import create_agent

from email_agent.ai.outputs import ClassificationOutput
from email_agent.ai.prompts import classification_system_prompt, format_thread
from email_agent.ai.tracing import trace_payload, trace_response
from email_agent.config import AgentConfig
from email_agent.privacy import redact
from email_agent.providers.models import EmailMessage, EmailThread

logger = logging.getLogger(__name__)


class EmailClassifier:
    """Classify email with one configured structured-output model."""

    def __init__(self, root: Path, agent: AgentConfig, model):
        self.agent = agent
        self.system_prompt = redact(
            classification_system_prompt(root, agent)
        ).sanitized_text
        self.model_agent = create_agent(
            model=model,
            tools=[],
            system_prompt=self.system_prompt,
            response_format=ClassificationOutput,
        )

    def classify(self, message: EmailMessage, thread: EmailThread) -> ClassificationOutput:
        """Classify one message using recent thread context."""
        messages = [*thread.messages, message]
        known_names = [item.from_name for item in messages if item.from_name]
        content = redact(
            format_thread(thread, message), known_names=known_names
        ).sanitized_text
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
        trace_payload("classification", self.system_prompt, content)
        started = perf_counter()
        response = self.model_agent.invoke(
            {"messages": [{"role": "user", "content": content}]}
        )
        classification = ClassificationOutput.model_validate(response["structured_response"])
        logger.info("Classification completed in %.2fs", perf_counter() - started)
        logger.debug("Classification result: %s", classification.model_dump_json())
        trace_response("classification", classification.model_dump())
        if (
            classification.category is not None
            and classification.category not in self.agent.categories
        ):
            allowed = ", ".join(self.agent.categories)
            raise ValueError(
                f"Model returned unknown category {classification.category!r}; expected {allowed}"
            )
        return classification
