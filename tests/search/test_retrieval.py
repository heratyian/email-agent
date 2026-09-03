from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from email_agent.application import EmailApplication
from email_agent.persistence import Message, Triage, initialize_database
from email_agent.providers.models import EmailMessage
from email_agent.search.models import InboxSearchPlanOutput, InboxSearchResult
from email_agent.search.retrieval import (
    retrieve_similar_summaries,
    summary_document,
    summary_document_text,
    sync_summary_vector_store,
)
from email_agent.search.service import run_inbox_search
from email_agent.triage.models import TriageOutput


def store_message(
    account_id,
    subject,
    summary,
    *,
    priority="normal",
    requires_reply=False,
    received_at=None,
):
    message = Message.upsert_email(
        EmailMessage(
            provider_id=subject,
            thread_id=subject,
            account_id=account_id,
            from_address="sender@example.com",
            subject=subject,
            text_body="Body",
            received_at=received_at or datetime.now(UTC) - timedelta(days=1),
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


def test_search_filters_vector_candidates_with_the_model_plan(tmp_path, monkeypatch):
    initialize_database(tmp_path / "email.db")
    matching = store_message(
        "person@example.com",
        "Reply requested",
        "The sender needs a reply.",
        requires_reply=True,
    )
    second_matching = store_message(
        "person@example.com",
        "Another reply request",
        "Another sender needs a reply.",
        requires_reply=True,
    )
    excluded = store_message(
        "person@example.com",
        "Newsletter",
        "A general newsletter.",
    )
    candidates = [
        InboxSearchResult(
            message_id=message.id,
            from_address=message.from_address,
            subject=message.subject,
            received_at=message.received_at,
            summary="Candidate summary.",
            reason="Vector match.",
        )
        for message in (second_matching, matching, excluded)
    ]
    monkeypatch.setattr(
        "email_agent.search.service.retrieve_similar_summaries",
        lambda *args, **kwargs: candidates,
    )

    class Planner:
        def invoke(self, prompt, *, config):
            assert "exact database filters" in prompt
            return InboxSearchPlanOutput(
                semantic_query="reply requested",
                requires_reply=True,
                limit=1,
            )

    class Model:
        def with_structured_output(self, output_type):
            assert output_type is InboxSearchPlanOutput
            return Planner()

    search = run_inbox_search(
        Model(),
        "person@example.com",
        tmp_path / "chroma",
        object(),
        "Which messages need a reply?",
    )

    assert search["response"].summary == "Found 1 matching messages."
    assert [result.message_id for result in search["ranked_results"]] == [second_matching.id]


def test_search_results_are_ordered_newest_first(tmp_path, monkeypatch):
    initialize_database(tmp_path / "email.db")
    now = datetime.now(UTC)
    older = store_message(
        "person@example.com",
        "Older high priority message",
        "An older important message.",
        priority="high",
        received_at=now - timedelta(days=2),
    )
    newer = store_message(
        "person@example.com",
        "Newer high priority message",
        "A newer important message.",
        priority="high",
        received_at=now - timedelta(hours=1),
    )
    candidates = [
        InboxSearchResult(
            message_id=message.id,
            from_address=message.from_address,
            subject=message.subject,
            received_at=message.received_at,
            summary="Candidate summary.",
            reason="Vector match.",
        )
        for message in (older, newer)
    ]
    monkeypatch.setattr(
        "email_agent.search.service.retrieve_similar_summaries",
        lambda *args, **kwargs: candidates,
    )

    class Planner:
        def invoke(self, prompt, *, config):
            return InboxSearchPlanOutput(
                semantic_query="important",
                priority="high",
            )

    class Model:
        def with_structured_output(self, output_type):
            return Planner()

    search = run_inbox_search(
        Model(),
        "person@example.com",
        tmp_path / "chroma",
        object(),
        "Get my latest high priority messages",
    )

    assert [result.message_id for result in search["ranked_results"]] == [newer.id, older.id]


def test_embedded_summary_contains_searchable_sender(tmp_path):
    initialize_database(tmp_path / "email.db")
    message = store_message("person@example.com", "Update", "A project update.")
    triage = Triage.get(Triage.message == message)

    assert "From: sender@example.com" in summary_document_text(message, triage)


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
        def similarity_search(self, query, *, k):
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
