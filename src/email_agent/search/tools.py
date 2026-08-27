from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.tools import tool
from peewee import JOIN

from email_agent.db import Classification, Message
from email_agent.search.models import InboxSearchPlan, InboxSearchResult

logger = logging.getLogger(__name__)


def summary_document_text(message: Message, classification: Classification) -> str:
    """Return the PII-reduced text embedded for one classified message."""
    return "\n".join(
        [
            f"Subject: {message.subject}",
            f"Category: {classification.category or 'none'}",
            f"Priority: {classification.priority}",
            f"Requires reply: {classification.requires_reply}",
            f"Requires escalation: {classification.requires_escalation}",
            f"Summary: {classification.summary}",
        ]
    )


def summary_document(message: Message, classification: Classification) -> Document:
    """Build the searchable document for one classified message."""
    return Document(
        page_content=summary_document_text(message, classification),
        metadata={
            "message_id": message.id,
            "account_id": message.account_id,
            "from_address": message.from_address,
            "from_name": message.from_name or "",
            "subject": message.subject,
            "received_at": message.received_at.isoformat(),
            "category": classification.category or "",
            "priority": classification.priority,
            "requires_reply": classification.requires_reply,
            "requires_escalation": classification.requires_escalation,
            "summary": classification.summary,
        },
    )


def classified_messages(account_id: str, *, limit: int = 500) -> list[tuple[Message, Classification]]:
    """Return recent classified messages for one account."""
    rows = (
        Message.select(Message, Classification)
            .join(Classification, JOIN.INNER)
            .where(
                (Message.account_id == account_id)
                & Message.classified_at.is_null(False)
            )
            .order_by(Message.received_at.desc())
            .limit(limit)
    )
    return [(message, Classification.get(Classification.message == message)) for message in rows]


def result_from_message(
    message: Message,
    classification: Classification,
    *,
    reason: str,
    score: float = 0,
) -> InboxSearchResult:
    """Build a search result from persisted message and classification rows."""
    return InboxSearchResult(
        message_id=message.id,
        from_address=message.from_address,
        from_name=message.from_name,
        subject=message.subject,
        received_at=message.received_at,
        category=classification.category,
        priority=classification.priority,
        requires_reply=classification.requires_reply,
        requires_escalation=classification.requires_escalation,
        summary=classification.summary,
        reason=reason,
        score=score,
    )


def search_classified_messages(account_id: str, plan: InboxSearchPlan) -> list[InboxSearchResult]:
    """Search classified local messages with deterministic structured filters."""
    cutoff = None
    if plan.recent_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=plan.recent_days)
    results = []
    sender = plan.sender.casefold() if plan.sender else None
    topic = plan.topic.casefold() if plan.topic else None
    for message, classification in classified_messages(account_id):
        if cutoff and message.received_at < cutoff:
            continue
        if sender and sender not in f"{message.from_name or ''} {message.from_address}".casefold():
            continue
        if plan.category and classification.category != plan.category:
            continue
        if plan.priority and classification.priority != plan.priority:
            continue
        if plan.requires_reply is not None and bool(classification.requires_reply) != plan.requires_reply:
            continue
        if (
            plan.requires_escalation is not None
            and bool(classification.requires_escalation) != plan.requires_escalation
        ):
            continue
        score = 2.0
        haystack = f"{message.subject} {classification.summary} {classification.intent or ''}".casefold()
        if topic and any(term in haystack for term in topic.split()):
            score += 1.0
        if classification.priority == "high":
            score += 1.0
        if classification.requires_escalation:
            score += 1.0
        if classification.requires_reply:
            score += 0.5
        results.append(
            result_from_message(
                message,
                classification,
                reason="Matched structured inbox filters.",
                score=score,
            )
        )
    return sorted(results, key=lambda result: result.score, reverse=True)[: plan.limit]


def chroma_collection_name(account_id: str) -> str:
    """Return a Chroma-safe collection name for one account."""
    safe = "".join(character if character.isalnum() else "-" for character in account_id.lower())
    return f"email-agent-{safe}"[:63].strip("-")


def open_summary_vector_store(account_id: str, persist_directory: Path, embeddings) -> Chroma:
    """Open the account's classification-summary collection."""
    return Chroma(
        collection_name=chroma_collection_name(account_id),
        embedding_function=embeddings,
        persist_directory=str(persist_directory),
    )


def sync_summary_vector_store(account_id: str, persist_directory: Path, embeddings) -> Chroma:
    """Synchronize changed classified-message summaries with Chroma."""
    documents_by_id = {
        str(message.id): summary_document(message, classification)
        for message, classification in classified_messages(account_id)
    }
    store = open_summary_vector_store(account_id, persist_directory, embeddings)
    existing = store.get(include=["documents", "metadatas"])
    existing_by_id = {
        document_id: (document_text, metadata)
        for document_id, document_text, metadata in zip(
            existing["ids"],
            existing["documents"] or [],
            existing["metadatas"] or [],
        )
    }

    stale_ids = sorted(set(existing_by_id) - set(documents_by_id))
    new_ids = sorted(set(documents_by_id) - set(existing_by_id))
    changed_ids = sorted(
        document_id
        for document_id in set(documents_by_id) & set(existing_by_id)
        if existing_by_id[document_id]
        != (
            documents_by_id[document_id].page_content,
            documents_by_id[document_id].metadata,
        )
    )

    logger.debug(
        "Summary index sync: account=%s unchanged=%d added=%d updated=%d deleted=%d",
        account_id,
        len(documents_by_id) - len(new_ids) - len(changed_ids),
        len(new_ids),
        len(changed_ids),
        len(stale_ids),
    )

    if stale_ids:
        store.delete(ids=stale_ids)
    if new_ids:
        store.add_documents(
            [documents_by_id[document_id] for document_id in new_ids], ids=new_ids
        )
    if changed_ids:
        store.update_documents(
            changed_ids,
            [documents_by_id[document_id] for document_id in changed_ids],
        )
    return store


def retrieve_similar_summaries(
    account_id: str,
    query: str,
    *,
    persist_directory: Path,
    embeddings,
    limit: int = 8,
) -> list[InboxSearchResult]:
    """Retrieve classified message summaries with Chroma vector search."""
    store = open_summary_vector_store(account_id, persist_directory, embeddings)
    documents = store.similarity_search_with_score(query, k=limit)
    results = []
    for document, distance in documents:
        metadata = document.metadata
        results.append(
            InboxSearchResult(
                message_id=int(metadata["message_id"]),
                from_address=str(metadata["from_address"]),
                from_name=str(metadata["from_name"]) or None,
                subject=str(metadata["subject"]),
                received_at=datetime.fromisoformat(str(metadata["received_at"])),
                category=str(metadata["category"]) or None,
                priority=str(metadata["priority"]),
                requires_reply=bool(metadata["requires_reply"]),
                requires_escalation=bool(metadata["requires_escalation"]),
                summary=str(metadata["summary"]),
                reason="Matched the vector search over classified message summaries.",
                score=max(0.0, 2.0 - float(distance)),
            )
        )
    return results


def make_search_tools(account_id: str, persist_directory: Path, embeddings):
    """Return read-only LangChain tools for inbox search."""

    @tool
    def search_local_classified_messages(plan_json: str) -> str:
        """Search local classified messages with structured inbox filters."""
        plan = InboxSearchPlan.model_validate_json(plan_json)
        results = search_classified_messages(account_id, plan)
        return json.dumps([result.model_dump(mode="json") for result in results])

    @tool
    def retrieve_classified_message_summaries(query: str, limit: int = 8) -> str:
        """Retrieve local classified message summaries with Chroma vector search."""
        results = retrieve_similar_summaries(
            account_id,
            query,
            persist_directory=persist_directory,
            embeddings=embeddings,
            limit=limit,
        )
        return json.dumps([result.model_dump(mode="json") for result in results])

    return search_local_classified_messages, retrieve_classified_message_summaries
