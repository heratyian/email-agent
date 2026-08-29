from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langsmith import Client
from pydantic import BaseModel

from email_agent.drafting.drafter import EmailDrafter
from email_agent.drafting.prompt import draft_system_prompt
from email_agent.evaluations.fingerprints import prompt_hash
from email_agent.evaluations.triage import ensure_dataset, load_examples, load_profile
from email_agent.llm.chat import get_model
from email_agent.providers.models import EmailMessage, EmailThread
from email_agent.triage.models import TriageOutput


class DraftQualityScore(BaseModel):
    """Structured semantic scores for one generated draft."""

    required_points_covered: bool
    grounded_in_thread: bool
    instruction_followed: bool
    tone_appropriate: bool
    safe_to_send: bool
    rationale: str


DRAFT_QUALITY_FIELDS = (
    "required_points_covered",
    "grounded_in_thread",
    "instruction_followed",
    "tone_appropriate",
    "safe_to_send",
)


def recipient_accuracy(outputs: dict, reference_outputs: dict) -> bool:
    """Score whether the draft addresses the expected recipient."""
    return outputs["recipient"] == reference_outputs["recipient"]


def escalation_accuracy(outputs: dict, reference_outputs: dict) -> bool:
    """Score whether the draft has the expected escalation requirement."""
    return outputs["requires_escalation"] == reference_outputs["requires_escalation"]


def word_limit(outputs: dict, reference_outputs: dict) -> bool:
    """Score whether the draft stays within the example's word limit."""
    return len(outputs["body"].split()) <= reference_outputs["max_words"]


def _message(values: dict[str, Any], index: int) -> EmailMessage:
    """Build one synthetic email message from evaluation input."""
    return EmailMessage(
        provider_id=f"evaluation-{index}",
        account_id="evaluation@example.com",
        received_at=datetime(2026, 1, index + 1, tzinfo=UTC),
        **values,
    )


def drafting_target(drafter: EmailDrafter) -> Callable[[dict], dict]:
    """Build a LangSmith target around the production drafting operation."""

    def draft(inputs: dict) -> dict:
        message = _message(inputs["message"], len(inputs.get("thread", [])))
        thread = EmailThread(
            messages=[
                _message(thread_message, index)
                for index, thread_message in enumerate(inputs.get("thread", []))
            ]
        )
        triage = TriageOutput.model_validate(inputs["triage"])
        result = drafter.draft(
            message,
            thread,
            triage,
            instruction=inputs.get("instruction"),
        )
        return result.model_dump()

    return draft


def draft_quality_prompt(inputs: dict, outputs: dict, reference_outputs: dict) -> str:
    """Build the semantic draft quality judge prompt."""
    prompt = {
        "task": (
            "Judge the draft against the conversation and reference criteria. "
            "Unsupported facts, promises, or commitments make grounded_in_thread "
            "and safe_to_send false."
        ),
        "inputs": inputs,
        "draft": outputs,
        "criteria": {
            "recipient": reference_outputs["recipient"],
            "requires_escalation": reference_outputs["requires_escalation"],
            "required_points": reference_outputs["required_points"],
            "forbidden_points": reference_outputs["forbidden_points"],
            "tone": reference_outputs["tone"],
            "max_words": reference_outputs["max_words"],
        },
    }
    return json.dumps(prompt, indent=2)


def draft_quality_evaluator(judge) -> Callable[[dict, dict, dict], list[dict]]:
    """Build one model judge that returns separate semantic quality scores."""

    def evaluate(inputs: dict, outputs: dict, reference_outputs: dict) -> list[dict]:
        score = DraftQualityScore.model_validate(
            judge.invoke(draft_quality_prompt(inputs, outputs, reference_outputs))
        )
        return [
            {"key": field, "score": getattr(score, field), "comment": score.rationale}
            for field in DRAFT_QUALITY_FIELDS
        ]

    return evaluate


def drafting_evaluators(judge) -> list[Callable]:
    """Return deterministic and semantic drafting evaluators."""
    return [
        recipient_accuracy,
        escalation_accuracy,
        word_limit,
        draft_quality_evaluator(judge),
    ]


def drafting_metadata(profile) -> dict[str, Any]:
    """Return LangSmith metadata for one drafting evaluation run."""

    prompt = draft_system_prompt(profile.root, profile.agent)
    return {
        "evaluation_profile": profile.name,
        "model_provider": profile.agent.model.provider,
        "model": profile.agent.model.model,
        "draft_prompt": profile.agent.draft_prompt,
        "prompt_hash": prompt_hash(prompt),
    }

def experiment_prefix(profile) -> str:
    """Return the prompt-versioned LangSmith experiment prefix."""
    prompt = draft_system_prompt(profile.root, profile.agent)
    return f"drafting-{profile.name}-{prompt_hash(prompt)}"

def run_drafting_evaluation(
    profile_name: str = "personal",
    *,
    dataset_name: str | None = None,
    client: Client | None = None,
):
    """Run a self-contained drafting profile as a LangSmith experiment."""
    profile = load_profile(profile_name)
    if profile.agent.draft_prompt is None:
        raise ValueError(f"evaluation profile has no draft prompt: {profile.name!r}")
    examples = load_examples(profile.root / "drafting_examples.json")
    dataset_name = dataset_name or f"drafting-{profile.name}"
    client = client or Client()
    ensure_dataset(
        client,
        dataset_name,
        examples,
        application_tag_value_id=os.getenv("LANGSMITH_APPLICATION_TAG_VALUE_ID"),
        description="Synthetic email examples for drafting regression testing.",
    )
    drafter = EmailDrafter(profile.root, profile.agent, get_model(profile.agent.model))
    judge = get_model(profile.agent.model).with_structured_output(DraftQualityScore)
    return client.evaluate(
        drafting_target(drafter),
        data=dataset_name,
        evaluators=drafting_evaluators(judge),
        experiment_prefix=experiment_prefix(profile),
        metadata=drafting_metadata(profile),
    )
