from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from langsmith import Client

from email_agent.config import AgentConfig
from email_agent.evaluations.fingerprints import prompt_hash
from email_agent.llm.chat import get_model
from email_agent.providers.models import EmailMessage, EmailThread
from email_agent.triage.prompt import triage_system_prompt
from email_agent.triage.triager import EmailTriager

PROFILES_ROOT = Path(__file__).with_name("profiles")


@dataclass(frozen=True)
class EvaluationProfile:
    """Self-contained model, prompt, taxonomy, and examples for one evaluation."""

    name: str
    root: Path
    agent: AgentConfig
    examples: list[dict[str, dict[str, Any]]]


def category_accuracy(outputs: dict, reference_outputs: dict) -> bool:
    """Score whether the predicted category matches the reference category."""
    return outputs["category"] == reference_outputs["category"]


def reply_accuracy(outputs: dict, reference_outputs: dict) -> bool:
    """Score whether the predicted reply requirement matches the reference."""
    return outputs["requires_reply"] == reference_outputs["requires_reply"]


def priority_accuracy(outputs: dict, reference_outputs: dict) -> bool:
    """Score whether the predicted priority matches the reference priority."""
    return outputs["priority"] == reference_outputs["priority"]


def escalation_accuracy(outputs: dict, reference_outputs: dict) -> bool:
    """Score whether the predicted escalation requirement matches the reference."""
    return outputs["requires_escalation"] == reference_outputs["requires_escalation"]


EVALUATORS = [
    category_accuracy,
    reply_accuracy,
    priority_accuracy,
    escalation_accuracy,
]


def load_examples(path: Path) -> list[dict[str, dict[str, Any]]]:
    """Load checked-in evaluation examples."""
    examples = json.loads(path.read_text())
    if not isinstance(examples, list) or not examples:
        raise ValueError("evaluation dataset must be a non-empty list")
    return examples


def load_profile(name: str) -> EvaluationProfile:
    """Load one checked-in evaluation profile without mailbox configuration."""
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
        raise ValueError(f"invalid evaluation profile name: {name!r}")
    root = PROFILES_ROOT / name
    config_path = root / "agent.yaml"
    examples_path = root / "triage_examples.json"
    if not config_path.is_file() or not examples_path.is_file():
        raise ValueError(f"unknown evaluation profile: {name!r}")
    agent = AgentConfig.model_validate(yaml.safe_load(config_path.read_text()))
    examples = load_examples(examples_path)
    validate_reference_categories(examples, agent.categories)
    return EvaluationProfile(name=name, root=root, agent=agent, examples=examples)


def validate_reference_categories(examples: list[dict], categories: dict[str, str]) -> None:
    """Reject reference categories that the configured triager cannot return."""
    unknown = sorted(
        {
            example["outputs"]["category"]
            for example in examples
            if example["outputs"]["category"] is not None
            and example["outputs"]["category"] not in categories
        }
    )
    if unknown:
        raise ValueError(
            "evaluation dataset contains categories missing from the profile: " + ", ".join(unknown)
        )


def triage_target(triager: EmailTriager) -> Callable[[dict], dict]:
    """Build a LangSmith target around the production triage operation."""

    def triage(inputs: dict) -> dict:
        message = EmailMessage(
            provider_id="evaluation",
            account_id="evaluation@example.com",
            from_address=inputs["from_address"],
            subject=inputs["subject"],
            text_body=inputs["text_body"],
            received_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        result = triager.triage(message, EmailThread(messages=[message]))
        return result.model_dump()

    return triage


def ensure_dataset(
    client: Client,
    name: str,
    examples: list[dict],
    *,
    application_tag_value_id: str | None = None,
    description: str = "Synthetic email examples for triage regression testing.",
) -> None:
    """Create a LangSmith dataset and seed it on its first use."""
    if client.has_dataset(dataset_name=name):
        return
    dataset = client.create_dataset(
        dataset_name=name,
        description=description,
        tag_value_ids=[application_tag_value_id] if application_tag_value_id else None,
    )
    client.create_examples(dataset_id=dataset.id, examples=examples)


def run_triage_evaluation(
    profile_name: str = "personal",
    *,
    dataset_name: str | None = None,
    client: Client | None = None,
):
    """Run a self-contained triage profile as a LangSmith experiment."""
    profile = load_profile(profile_name)
    dataset_name = dataset_name or f"triage-{profile.name}"
    client = client or Client()
    ensure_dataset(
        client,
        dataset_name,
        profile.examples,
        application_tag_value_id=os.getenv("LANGSMITH_APPLICATION_TAG_VALUE_ID"),
    )
    triager = EmailTriager(profile.root, profile.agent, get_model(profile.agent.model))
    prompt = triage_system_prompt(profile.root, profile.agent)
    return client.evaluate(
        triage_target(triager),
        data=dataset_name,
        evaluators=EVALUATORS,
        experiment_prefix=f"triage-{profile.name}-{prompt_hash(prompt)}",
        metadata={
            "evaluation_profile": profile.name,
            "model_provider": profile.agent.model.provider,
            "model": profile.agent.model.model,
            "triage_prompt": profile.agent.triage_prompt,
            "prompt_hash": prompt_hash(prompt),
            "categories": sorted(profile.agent.categories),
        },
    )
