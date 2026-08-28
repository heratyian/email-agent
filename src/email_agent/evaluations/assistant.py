from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from langsmith import Client

from email_agent.assistant.interpreter import (
    assistant_route,
    interpret_assistant_request,
)
from email_agent.assistant.models import AssistantIntentOutput, PendingAction
from email_agent.evaluations.triage import ensure_dataset, load_examples, load_profile
from email_agent.llm.chat import get_model


def assistant_target(model) -> Callable[[dict], dict]:
    """Build a LangSmith target around the production assistant interpreter."""
    planner = model.with_structured_output(AssistantIntentOutput)

    def interpret(inputs: dict) -> dict:
        pending_values = inputs.get("pending_action")
        state = {
            "account_id": "assistant-evaluation@example.test",
            "user_input": inputs["user_input"],
            "pending_action": (
                PendingAction.model_validate(pending_values) if pending_values else None
            ),
            "last_message_ids": inputs.get("last_message_ids", []),
            "last_draft_message_id": inputs.get("last_draft_message_id"),
        }
        intent = interpret_assistant_request(planner, state)
        route = assistant_route(intent)
        return {
            **intent.model_dump(mode="json"),
            "route": route,
            "requires_confirmation": route in {"prepare_triage", "prepare_upload"},
            "query_present": bool(intent.query),
            "instruction_present": bool(intent.instruction),
        }

    return interpret


def _expected_value(outputs: dict, reference_outputs: dict, field: str) -> bool:
    """Compare one field only when the example specifies an expectation."""
    return field not in reference_outputs or outputs.get(field) == reference_outputs[field]


def action_accuracy(outputs: dict, reference_outputs: dict) -> bool:
    """Score the selected assistant action when specified."""
    return _expected_value(outputs, reference_outputs, "action")


def route_accuracy(outputs: dict, reference_outputs: dict) -> bool:
    """Score the graph route, including confirmation and cancellation routes."""
    return _expected_value(outputs, reference_outputs, "route")


def reference_accuracy(outputs: dict, reference_outputs: dict) -> bool:
    """Score explicit or context-resolved local message references."""
    return _expected_value(outputs, reference_outputs, "message_id")


def argument_accuracy(outputs: dict, reference_outputs: dict) -> bool:
    """Score limits and required free-text argument presence."""
    return all(
        _expected_value(outputs, reference_outputs, field)
        for field in ("limit", "query_present", "instruction_present")
    )


def confirmation_accuracy(outputs: dict, reference_outputs: dict) -> bool:
    """Score whether the interpreted operation requires confirmation."""
    return _expected_value(outputs, reference_outputs, "requires_confirmation")


EVALUATORS = [
    action_accuracy,
    route_accuracy,
    reference_accuracy,
    argument_accuracy,
    confirmation_accuracy,
]


def assistant_metadata(profile) -> dict[str, Any]:
    """Return version details needed to compare assistant experiments."""
    return {
        "evaluation_profile": profile.name,
        "model_provider": profile.agent.model.provider,
        "model": profile.agent.model.model,
        "workflow": "typed-intent-assistant-v1",
        "confirmation_policy": "triage-and-upload-v1",
    }


def run_assistant_evaluation(
    profile_name: str = "personal",
    *,
    dataset_name: str | None = None,
    client: Client | None = None,
):
    """Evaluate natural-language assistant routing as a LangSmith experiment."""
    profile = load_profile(profile_name)
    examples = load_examples(profile.root / "assistant_examples.json")
    dataset_name = dataset_name or f"assistant-{profile.name}"
    client = client or Client()
    ensure_dataset(
        client,
        dataset_name,
        examples,
        application_tag_value_id=os.getenv("LANGSMITH_APPLICATION_TAG_VALUE_ID"),
        description=(
            "Synthetic natural-language assistant routing, reference, and safety examples."
        ),
    )
    return client.evaluate(
        assistant_target(get_model(profile.agent.model)),
        data=dataset_name,
        evaluators=EVALUATORS,
        experiment_prefix=f"assistant-{profile.name}",
        metadata=assistant_metadata(profile),
        max_concurrency=1,
        blocking=True,
    )
