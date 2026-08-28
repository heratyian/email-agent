from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from email_agent.ai.outputs import TriageOutput
from email_agent.cli.commands.handlers import CommandHandlers
from email_agent.db import Message, Triage, initialize_database
from email_agent.providers.models import EmailMessage
from email_agent.search.graph import build_search_response, ground_output, merge_results
from email_agent.search.models import (
    InboxSearchItemOutput,
    InboxSearchOutput,
    InboxSearchPlanOutput,
)
from email_agent.search.tools import (
    retrieve_similar_summaries,
    search_triaged_messages,
    summary_document,
    sync_summary_vector_store,
)


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


def test_merge_results_combines_scores_for_same_message():
    from email_agent.search.models import InboxSearchResult

    base = InboxSearchResult(
        message_id=1,
        from_address="sender@example.com",
        subject="Interview availability",
        received_at=datetime.now(UTC),
        summary="Recruiter asked for availability.",
        reason="Structured.",
        score=2,
    )

    merged = merge_results([base], [base.model_copy(update={"reason": "Vector.", "score": 3})])

    assert len(merged) == 1
    assert merged[0].score == 5
    assert "Structured" in merged[0].reason
    assert "Vector" in merged[0].reason


def test_ground_output_discards_unknown_ids_and_restores_subjects():
    from email_agent.search.models import InboxSearchResult

    result = InboxSearchResult(
        message_id=7,
        from_address="sender@example.com",
        subject="Authoritative subject",
        received_at=datetime.now(UTC),
        summary="A grounded summary.",
        reason="Structured.",
    )
    output = InboxSearchOutput(
        summary="Two possible messages.",
        messages=[
            InboxSearchItemOutput(
                message_id=7,
                subject="Model-controlled subject",
                explanation="This one matches.",
            ),
            InboxSearchItemOutput(
                message_id=7,
                subject="Duplicate",
                explanation="Duplicate reference.",
            ),
            InboxSearchItemOutput(
                message_id=99,
                subject="Invented",
                explanation="Unknown reference.",
            ),
        ],
    )

    grounded = ground_output(output, [result])

    assert [item.message_id for item in grounded.messages] == [7]
    assert grounded.messages[0].subject == "Authoritative subject"


def test_search_response_combines_explanations_with_authoritative_result_metadata():
    from email_agent.search.models import InboxSearchResult

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
    output = InboxSearchOutput(
        summary="One contract needs attention.",
        messages=[
            InboxSearchItemOutput(
                message_id=7,
                subject="Contract approval",
                explanation="A decision is due tomorrow.",
            )
        ],
    )

    response = build_search_response(output, [result])

    assert response.summary == "One contract needs attention."
    assert response.results[0].from_name == "Legal Team"
    assert response.results[0].priority == "high"
    assert response.results[0].match_explanation == "A decision is due tomorrow."


def test_summary_vector_store_only_changes_outdated_documents(tmp_path, monkeypatch):
    initialize_database(tmp_path / "email.db")
    unchanged_message = store_message("person@example.com", "Unchanged", "Same summary.")
    changed_message = store_message("person@example.com", "Changed", "New summary.")
    new_message = store_message("person@example.com", "New", "New document.")
    unchanged_triage = Triage.get(
        Triage.message == unchanged_message
    )
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
    monkeypatch.setattr("email_agent.search.tools.Chroma", lambda **kwargs: store)

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
        "email_agent.search.tools.open_summary_vector_store",
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


def test_triage_synchronizes_the_summary_index_even_without_new_messages(
    tmp_path, monkeypatch
):
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
        "email_agent.cli.commands.handlers.TriageService",
        EmptyTriageService,
    )
    monkeypatch.setattr(
        "email_agent.cli.commands.handlers.get_embedding_model",
        lambda model: "embeddings",
    )
    monkeypatch.setattr(
        "email_agent.cli.commands.handlers.sync_summary_vector_store",
        lambda *args: synchronized.append(args),
    )
    handlers = CommandHandlers(
        settings=SimpleNamespace(root=tmp_path), runtime_factory=runtime_factory
    )

    assert handlers.triage("person@example.com") == []
    assert synchronized == [
        ("person@example.com", tmp_path / "data" / "chroma", "embeddings")
    ]
