from datetime import UTC, datetime

from email_agent.evaluations.search import (
    citation_recall,
    citation_validity,
    empty_answer_accuracy,
    exclusion_accuracy,
    planner_accuracy,
    retrieval_precision,
    retrieval_recall,
    run_search_evaluation,
    search_target,
    seed_search_corpus,
    top_result_accuracy,
)
from email_agent.search.models import (
    InboxSearchItemOutput,
    InboxSearchOutput,
    InboxSearchPlanOutput,
    InboxSearchResponse,
    InboxSearchResult,
)


def test_search_target_exposes_stable_keys_from_production_pipeline():
    def fake_pipeline(query, *, config):
        assert query == "What needs a reply?"
        assert "evaluation" in config["tags"]
        return {
            "plan": InboxSearchPlanOutput(
                query=query,
                requires_reply=True,
                rationale="Find reply requests.",
            ),
            "ranked_results": [
                InboxSearchResult(
                    message_id=7,
                    from_address="sender@example.test",
                    subject="Reply requested",
                    received_at=datetime.now(UTC),
                    summary="A reply is needed.",
                    reason="Matched.",
                )
            ],
            "output": InboxSearchOutput(
                summary="One message needs a reply.",
                messages=[
                    InboxSearchItemOutput(
                        message_id=7,
                        subject="Reply requested",
                        explanation="The sender asked a question.",
                    )
                ],
            ),
            "response": InboxSearchResponse(
                summary="One message needs a reply.",
                results=[
                    InboxSearchResult(
                        message_id=7,
                        from_address="sender@example.test",
                        subject="Reply requested",
                        received_at=datetime.now(UTC),
                        summary="A reply is needed.",
                        reason="Matched.",
                        match_explanation="The sender asked a question.",
                    )
                ],
            ),
        }

    output = search_target(fake_pipeline, {7: "reply_request"})({"query": "What needs a reply?"})

    assert output["plan"]["requires_reply"] is True
    assert output["retrieved_keys"] == ["reply_request"]
    assert output["cited_keys"] == ["reply_request"]


def test_search_evaluators_report_independent_failures():
    outputs = {
        "plan": {"requires_reply": True},
        "retrieved_keys": ["relevant", "irrelevant"],
        "cited_keys": ["relevant", "invented"],
    }
    reference = {
        "plan": {"requires_reply": True},
        "relevant_keys": ["relevant", "missed"],
        "top_key": "relevant",
        "excluded_keys": ["irrelevant"],
    }

    assert planner_accuracy(outputs, reference) is True
    assert retrieval_recall(outputs, reference) == 0.5
    assert retrieval_precision(outputs, reference) == 0.5
    assert top_result_accuracy(outputs, reference) is True
    assert exclusion_accuracy(outputs, reference) is False
    assert citation_validity(outputs, reference) is False
    assert citation_recall(outputs, reference) == 1.0
    assert empty_answer_accuracy(outputs, reference) is True


def test_empty_search_requires_no_retrieval_and_no_citations():
    reference = {"relevant_keys": []}

    assert retrieval_recall({"retrieved_keys": []}, reference) == 1.0
    assert retrieval_precision({"retrieved_keys": []}, reference) == 1.0
    assert empty_answer_accuracy({"retrieved_keys": [], "cited_keys": []}, reference) is True
    assert (
        empty_answer_accuracy({"retrieved_keys": ["unrelated"], "cited_keys": []}, reference)
        is False
    )


def test_checked_in_search_corpus_has_stable_unique_keys(tmp_path):
    from email_agent.db import initialize_database
    from email_agent.evaluations.triage import load_profile

    initialize_database(tmp_path / "email.db")
    profile = load_profile("personal")

    keys_by_id = seed_search_corpus(profile.root / "search_corpus.json")

    assert len(keys_by_id) == 8
    assert len(set(keys_by_id.values())) == 8
    assert "security_credentials" in keys_by_id.values()


class FakeClient:
    def __init__(self):
        self.evaluations = []

    def has_dataset(self, *, dataset_name):
        return True

    def evaluate(self, target, **values):
        self.evaluations.append((target, values))
        return "results"


def test_search_evaluation_uses_serial_blocking_production_pipeline(monkeypatch):
    client = FakeClient()
    graph = object()
    monkeypatch.setattr("email_agent.evaluations.search.get_model", lambda config: "model")
    monkeypatch.setattr(
        "email_agent.evaluations.search.get_embedding_model", lambda config: "embeddings"
    )
    monkeypatch.setattr(
        "email_agent.evaluations.search.seed_search_corpus", lambda path: {1: "message"}
    )
    monkeypatch.setattr(
        "email_agent.evaluations.search.sync_summary_vector_store", lambda *args: None
    )
    monkeypatch.setattr(
        "email_agent.evaluations.search.make_search_tools", lambda *args: ("structured", "vector")
    )
    monkeypatch.setattr(
        "email_agent.evaluations.search.run_inbox_search",
        lambda model, structured, vector: graph,
    )

    result = run_search_evaluation("personal", client=client)

    assert result == "results"
    target, values = client.evaluations[0]
    assert callable(target)
    assert values["data"] == "search-personal"
    assert values["max_concurrency"] == 1
    assert values["blocking"] is True
    assert values["metadata"]["corpus"] == "search-corpus-v1"
