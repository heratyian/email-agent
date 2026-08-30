from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from email_agent.application import EmailApplication
from email_agent.persistence import Message, Triage, initialize_database
from email_agent.providers.models import EmailMessage
from email_agent.search.models import InboxSearchPlanOutput, InboxSearchResult
from email_agent.search.pipeline import build_search_response, rank_results
from email_agent.search.retrieval import (
    retrieve_similar_summaries,
    search_triaged_messages,
    summary_document,
    sync_summary_vector_store,
)
from email_agent.triage.models import TriageOutput


def store_message(account_id, subject, summary, *, priority="normal", requires_reply=False):
    message = Message.upsert_email(
        EmailMessage(
            provider_id=subject,
            thread_id=subject,
            account_id=account_id,
            from_address="sender@example.com",
            subject=subject,
            text_body="Body",
            received_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    Triage.save_for(
        message,
        TriageOutput(
            category="action",
            requires_reply=requires_reply,
            priority=priority,
            summary=summary,
            confidence=0.9,
            requires_escalation=False,
        ),
    )
    return message


def test_structured_search_filters_triaged_messages(tmp_path):
    initialize_database(tmp_path / "email.db")
    store_message(
        "person@example.com",
        "Interview availability",
        "A recruiter asked for interview availability.",
        requires_reply=True,
    )
    store_message("person@example.com", "Newsletter", "A product newsletter.")

    results = search_triaged_messages(
        "person@example.com",
        InboxSearchPlanOutput(
            query="what needs reply",
            requires_reply=True,
            recent_days=14,
            rationale="Find replies.",
        ),
    )

    assert [result.subject for result in results] == ["Interview availability"]


def test_structured_search_filters_before_applying_the_result_limit(tmp_path):
    initialize_database(tmp_path / "email.db")
    matching = store_message(
        "person@example.com",
        "Old reply request",
        "An older message still needs a reply.",
        requires_reply=True,
    )
    matching.received_at = datetime.now(UTC) - timedelta(days=30)
    matching.save()
    for index in range(500):
        store_message(
            "person@example.com",
            f"Newsletter {index}",
            "A newer message that does not need a reply.",
        )

    results = search_triaged_messages(
        "person@example.com",
        InboxSearchPlanOutput(
            query="what needs a reply",
            requires_reply=True,
            limit=1,
            rationale="Find reply requests.",
        ),
    )

    assert [result.subject for result in results] == ["Old reply request"]


def test_semantic_ranking_only_includes_eligible_messages():
    eligible = InboxSearchResult(
        message_id=1,
        from_address="sender@example.com",
        subject="Interview availability",
        received_at=datetime.now(UTC),
        summary="Recruiter asked for availability.",
        reason="Matched filters.",
    )
    ineligible = eligible.model_copy(update={"message_id": 2, "subject": "Newsletter"})

    ranked = rank_results(
        [eligible],
        [
            ineligible.model_copy(update={"score": 4}),
            eligible.model_copy(update={"score": 3}),
        ],
        has_topic=True,
    )

    assert [result.message_id for result in ranked] == [1]
    assert ranked[0].score == 3


def test_filter_only_ranking_uses_received_date_descending():
    older = InboxSearchResult(
        message_id=1,
        from_address="sender@example.com",
        subject="Older",
        received_at=datetime.now(UTC) - timedelta(days=2),
        summary="Older message.",
        reason="Matched filters.",
    )
    newer = older.model_copy(
        update={"message_id": 2, "subject": "Newer", "received_at": datetime.now(UTC)}
    )

    ranked = rank_results([older, newer], [], has_topic=False)

    assert [result.message_id for result in ranked] == [2, 1]


def test_search_response_returns_all_ranked_results():
    result = InboxSearchResult(
        message_id=7,
        from_address="legal@example.test",
        from_name="Legal Team",
        subject="Contract approval",
        received_at=datetime.now(UTC),
        priority="high",
        summary="A contract decision is due.",
        reason="Matched.",
    )
    response = build_search_response([result])

    assert response.summary == "Found 1 matching messages."
    assert response.results[0].from_name == "Legal Team"
    assert response.results[0].priority == "high"


def test_summary_vector_store_only_changes_outdated_documents(tmp_path, monkeypatch):
    initialize_database(tmp_path / "email.db")
    unchanged_message = store_message("person@example.com", "Unchanged", "Same summary.")
    changed_message = store_message("person@example.com", "Changed", "New summary.")
    new_message = store_message("person@example.com", "New", "New document.")
    unchanged_triage = Triage.get(Triage.message == unchanged_message)
    unchanged_document = summary_document(unchanged_message, unchanged_triage)

    class FakeChroma:
        def __init__(self, **kwargs):
            self.deleted = []
            self.added = []
            self.updated = []

        def get(self, *, include):
            assert include == ["documents", "metadatas"]
            return {
                "ids": [str(unchanged_message.id), str(changed_message.id), "99"],
                "documents": [unchanged_document.page_content, "Old summary", "Stale"],
                "metadatas": [unchanged_document.metadata, {"old": True}, {"stale": True}],
            }

        def delete(self, *, ids):
            self.deleted.extend(ids)

        def add_documents(self, documents, *, ids):
            self.added.extend(zip(ids, documents))

        def update_documents(self, ids, documents):
            self.updated.extend(zip(ids, documents))

    store = FakeChroma()
    monkeypatch.setattr("email_agent.search.retrieval.Chroma", lambda **kwargs: store)

    result = sync_summary_vector_store("person@example.com", tmp_path / "chroma", object())

    assert result is store
    assert store.deleted == ["99"]
    assert [document_id for document_id, _ in store.added] == [str(new_message.id)]
    assert [document_id for document_id, _ in store.updated] == [str(changed_message.id)]
    changed_ids = {*store.deleted}
    changed_ids.update(document_id for document_id, _ in store.added)
    changed_ids.update(document_id for document_id, _ in store.updated)
    assert str(unchanged_message.id) not in changed_ids


def test_vector_retrieval_only_searches_the_existing_index(tmp_path, monkeypatch):
    class ReadOnlyStore:
        def similarity_search_with_score(self, query, *, k):
            assert query == "important messages"
            assert k == 5
            return []

        def __getattr__(self, name):
            raise AssertionError(f"retrieval attempted index mutation: {name}")

    monkeypatch.setattr(
        "email_agent.search.retrieval.open_summary_vector_store",
        lambda account_id, persist_directory, embeddings: ReadOnlyStore(),
    )

    results = retrieve_similar_summaries(
        "person@example.com",
        "important messages",
        persist_directory=tmp_path / "chroma",
        embeddings=object(),
        limit=5,
    )

    assert results == []


def test_triage_synchronizes_the_summary_index_even_without_new_messages(tmp_path, monkeypatch):
    runtime = SimpleNamespace(
        settings=SimpleNamespace(root=tmp_path),
        account=SimpleNamespace(agent=object(), model=object()),
        provider=object(),
        require_triager=lambda: object(),
    )
    runtime_factory = SimpleNamespace(for_triage=lambda account_id: runtime)

    class EmptyTriageService:
        def __init__(self, agent, provider, triager):
            pass

        def triage_pending(self, account_id):
            return []

    synchronized = []
    monkeypatch.setattr(
        "email_agent.application.TriageService",
        EmptyTriageService,
    )
    monkeypatch.setattr(
        "email_agent.application.get_embedding_model",
        lambda model: "embeddings",
    )
    monkeypatch.setattr(
        "email_agent.application.sync_summary_vector_store",
        lambda *args: synchronized.append(args),
    )
    handlers = EmailApplication(
        settings=SimpleNamespace(root=tmp_path), runtime_factory=runtime_factory
    )

    assert handlers.triage("person@example.com") == []
    assert synchronized == [("person@example.com", tmp_path / "data" / "chroma", "embeddings")]
