from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from langsmith import Client

from email_agent.ai.chat_models import get_model
from email_agent.ai.embeddings import get_embedding_model
from email_agent.ai.outputs import ClassificationOutput
from email_agent.db import Classification, Message, initialize_database
from email_agent.evaluations.classification import ensure_dataset, load_examples, load_profile
from email_agent.providers.models import EmailMessage
from email_agent.search.graph import build_inbox_search_graph
from email_agent.search.tools import make_search_tools, sync_summary_vector_store

EVALUATION_ACCOUNT_ID = "search-evaluation@example.test"


def seed_search_corpus(path: Path, account_id: str = EVALUATION_ACCOUNT_ID) -> dict[int, str]:
    """Store a checked-in classified corpus and return local IDs mapped to stable keys."""
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
        Classification.save_for(
            message,
            ClassificationOutput.model_validate(entry["classification"]),
        )
        message.classified_at = now
        message.save()
        keys_by_id[message.id] = entry["key"]
    return keys_by_id


def search_target(graph, keys_by_id: dict[int, str]) -> Callable[[dict], dict]:
    """Build a LangSmith target around the production inbox search graph."""

    def search(inputs: dict) -> dict:
        result = graph.invoke(
            {
                "account_id": EVALUATION_ACCOUNT_ID,
                "user_query": inputs["query"],
            },
            config={
                "tags": ["email-agent", "inbox-search", "evaluation"],
                "metadata": {"workflow": "inbox-search-evaluation"},
            },
        )
        answer = result["answer"]
        return {
            "plan": result["plan"].model_dump(mode="json"),
            "retrieved_keys": [
                keys_by_id[item.message_id] for item in result.get("ranked_results", [])
            ],
            "cited_keys": [keys_by_id[item.message_id] for item in answer.messages],
            "summary": answer.summary,
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


def citation_validity(outputs: dict, reference_outputs: dict) -> bool:
    """Score whether every answer citation came from ranked retrieval."""
    return set(outputs["cited_keys"]).issubset(outputs["retrieved_keys"])


def citation_recall(outputs: dict, reference_outputs: dict) -> float:
    """Score the fraction of relevant retrieved messages cited in the answer."""
    relevant_retrieved = set(reference_outputs.get("relevant_keys", [])) & set(
        outputs["retrieved_keys"]
    )
    if not relevant_retrieved:
        return 1.0
    return len(relevant_retrieved & set(outputs["cited_keys"])) / len(relevant_retrieved)


def empty_answer_accuracy(outputs: dict, reference_outputs: dict) -> bool:
    """Score whether no-match examples return no results and no citations."""
    if reference_outputs.get("relevant_keys"):
        return True
    return not outputs["retrieved_keys"] and not outputs["cited_keys"]


EVALUATORS = [
    planner_accuracy,
    retrieval_recall,
    retrieval_precision,
    top_result_accuracy,
    exclusion_accuracy,
    citation_validity,
    citation_recall,
    empty_answer_accuracy,
]


def search_metadata(profile) -> dict[str, Any]:
    """Return version details needed to compare search experiments."""
    return {
        "evaluation_profile": profile.name,
        "model_provider": profile.agent.model.provider,
        "model": profile.agent.model.model,
        "graph": "parallel-structured-vector-search-v1",
        "retrieval": "chroma-classification-summaries-v1",
        "corpus": "search-corpus-v1",
    }


def run_search_evaluation(
    profile_name: str = "personal",
    *,
    dataset_name: str | None = None,
    client: Client | None = None,
):
    """Run the production inbox search graph against a synthetic fixed corpus."""
    profile = load_profile(profile_name)
    examples = load_examples(profile.root / "search_examples.json")
    dataset_name = dataset_name or f"search-{profile.name}"
    client = client or Client()
    ensure_dataset(
        client,
        dataset_name,
        examples,
        application_tag_value_id=os.getenv("LANGSMITH_APPLICATION_TAG_VALUE_ID"),
        description="Synthetic inbox search examples for graph and RAG regression testing.",
    )

    with TemporaryDirectory(prefix="email-agent-search-evaluation-") as directory:
        root = Path(directory)
        initialize_database(root / "email.db")
        keys_by_id = seed_search_corpus(profile.root / "search_corpus.json")
        model = get_model(profile.agent.model)
        embeddings = get_embedding_model(profile.agent.model)
        vector_directory = root / "chroma"
        sync_summary_vector_store(EVALUATION_ACCOUNT_ID, vector_directory, embeddings)
        graph = build_inbox_search_graph(
            model,
            *make_search_tools(EVALUATION_ACCOUNT_ID, vector_directory, embeddings),
        )
        return client.evaluate(
            search_target(graph, keys_by_id),
            data=dataset_name,
            evaluators=EVALUATORS,
            experiment_prefix=f"search-{profile.name}",
            metadata=search_metadata(profile),
            max_concurrency=1,
            blocking=True,
        )
