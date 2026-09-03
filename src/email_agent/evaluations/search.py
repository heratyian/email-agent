from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from langsmith import Client

from email_agent.evaluations.triage import ensure_dataset, load_examples, load_profile
from email_agent.llm.chat import get_model
from email_agent.llm.embeddings import get_embedding_model
from email_agent.persistence import Message, Triage, initialize_database
from email_agent.providers.models import EmailMessage
from email_agent.search.retrieval import sync_summary_vector_store
from email_agent.search.service import run_inbox_search
from email_agent.triage.models import TriageOutput

EVALUATION_ACCOUNT_ID = "search-evaluation@example.test"


def seed_search_corpus(path: Path, account_id: str = EVALUATION_ACCOUNT_ID) -> dict[int, str]:
    """Store a checked-in triaged corpus and return local IDs mapped to stable keys."""
    corpus = load_examples(path)
    now = datetime.now(UTC)
    keys_by_id = {}
    for entry in corpus:
        values = entry["message"]
        message = Message.upsert_email(
            EmailMessage(
                provider_id=entry["key"],
                account_id=account_id,
                from_address=values["from_address"],
                from_name=values.get("from_name"),
                subject=values["subject"],
                text_body=values["text_body"],
                received_at=now - timedelta(days=values["received_days_ago"]),
            )
        )
        Triage.save_for(
            message,
            TriageOutput.model_validate(entry["triage"]),
        )
        keys_by_id[message.id] = entry["key"]
    return keys_by_id


def search_target(pipeline, keys_by_id: dict[int, str]) -> Callable[[dict], dict]:
    """Build a LangSmith target around the production inbox search pipeline."""

    def search(inputs: dict) -> dict:
        result = pipeline(inputs["query"])
        response = result["response"]
        return {
            "plan": result["plan"].model_dump(mode="json"),
            "retrieved_keys": [
                keys_by_id[item.message_id] for item in result.get("ranked_results", [])
            ],
            "summary": response.summary,
        }

    return search


def planner_accuracy(outputs: dict, reference_outputs: dict) -> bool:
    """Score only planner fields specified by the evaluation example."""
    expected = reference_outputs.get("plan", {})
    return all(outputs["plan"].get(field) == value for field, value in expected.items())


def retrieval_recall(outputs: dict, reference_outputs: dict) -> float:
    """Score the fraction of relevant messages present in ranked retrieval."""
    relevant = set(reference_outputs.get("relevant_keys", []))
    if not relevant:
        return float(not outputs["retrieved_keys"])
    return len(relevant & set(outputs["retrieved_keys"])) / len(relevant)


def retrieval_precision(outputs: dict, reference_outputs: dict) -> float:
    """Score the fraction of retrieved messages marked relevant."""
    retrieved = set(outputs["retrieved_keys"])
    if not retrieved:
        return float(not reference_outputs.get("relevant_keys"))
    relevant = set(reference_outputs.get("relevant_keys", []))
    return len(relevant & retrieved) / len(retrieved)


def top_result_accuracy(outputs: dict, reference_outputs: dict) -> bool:
    """Score whether the expected first result is ranked first."""
    expected = reference_outputs.get("top_key")
    if expected is None:
        return True
    return bool(outputs["retrieved_keys"] and outputs["retrieved_keys"][0] == expected)


def exclusion_accuracy(outputs: dict, reference_outputs: dict) -> bool:
    """Score whether explicitly excluded messages stay out of retrieval."""
    excluded = set(reference_outputs.get("excluded_keys", []))
    return excluded.isdisjoint(outputs["retrieved_keys"])


EVALUATORS = [
    planner_accuracy,
    retrieval_recall,
    retrieval_precision,
    top_result_accuracy,
    exclusion_accuracy,
]


def search_metadata(profile) -> dict[str, Any]:
    """Return version details needed to compare search experiments."""
    return {
        "evaluation_profile": profile.name,
        "model_provider": profile.agent.model.provider,
        "model": profile.agent.model.model,
        "pipeline": "planned-filtered-vector-search-v3",
        "retrieval": "chroma-triage-summaries-v1",
        "corpus": "search-corpus-v1",
    }


def run_search_evaluation(
    profile_name: str = "personal",
    *,
    dataset_name: str | None = None,
    client: Client | None = None,
):
    """Run the production inbox search pipeline against a synthetic fixed corpus."""
    profile = load_profile(profile_name)
    examples = load_examples(profile.root / "search_examples.json")
    dataset_name = dataset_name or f"search-{profile.name}"
    client = client or Client()
    ensure_dataset(
        client,
        dataset_name,
        examples,
        application_tag_value_id=os.getenv("LANGSMITH_APPLICATION_TAG_VALUE_ID"),
        description="Synthetic inbox search examples for RAG regression testing.",
    )

    with TemporaryDirectory(prefix="email-agent-search-evaluation-") as directory:
        root = Path(directory)
        initialize_database(root / "email.db")
        keys_by_id = seed_search_corpus(profile.root / "search_corpus.json")
        model = get_model(profile.agent.model)
        embeddings = get_embedding_model(profile.agent.model)
        vector_directory = root / "chroma"
        sync_summary_vector_store(EVALUATION_ACCOUNT_ID, vector_directory, embeddings)

        def pipeline(query: str):
            return run_inbox_search(
                model,
                EVALUATION_ACCOUNT_ID,
                vector_directory,
                embeddings,
                query,
                categories=profile.agent.categories,
            )

        return client.evaluate(
            search_target(pipeline, keys_by_id),
            data=dataset_name,
            evaluators=EVALUATORS,
            experiment_prefix=f"search-{profile.name}",
            metadata=search_metadata(profile),
            max_concurrency=1,
            blocking=True,
        )
