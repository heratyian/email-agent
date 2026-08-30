from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from email_agent.search.models import InboxSearchPlanOutput, InboxSearchResponse, InboxSearchResult
from email_agent.search.retrieval import retrieve_similar_summaries, search_triaged_messages

SEARCH_PLANNER_PROMPT = """Convert the user's inbox search request into a structured search plan.

Rules:
- Search only locally synchronized, triaged email.
- Do not plan write actions.
- Interpret "recent" as the last 14 days.
- Interpret "important" as high priority, escalation, security, finance, legal, deadlines, or messages needing a reply.
- If the user asks for messages that need attention, set requires_reply true when appropriate.
- If the user asks for a topic, include useful synonyms in topic.
- Leave recent_days empty unless the user asks for a time range.
- Keep limit between 1 and 20.
- Return only the required schema.
"""


def rank_results(
    eligible_results: list[InboxSearchResult],
    vector_results: list[InboxSearchResult],
    *,
    has_topic: bool,
) -> list[InboxSearchResult]:
    """Rank only messages that satisfy the planner's structured constraints.

    Structured fields are hard filters. Semantic similarity ranks the remaining
    candidates when the request contains a topic. Filter-only searches use inbox
    recency, which is predictable and matches the normal inbox ordering.
    """
    if not has_topic:
        return sorted(eligible_results, key=lambda result: result.received_at, reverse=True)

    eligible_by_id = {result.message_id: result for result in eligible_results}
    ranked = []
    for vector_result in vector_results:
        eligible = eligible_by_id.get(vector_result.message_id)
        if eligible is None:
            continue
        ranked.append(
            eligible.model_copy(
                update={
                    "score": vector_result.score,
                    "reason": "Matched the search constraints and semantic query.",
                }
            )
        )
    return ranked


def build_search_response(results: list[InboxSearchResult]) -> InboxSearchResponse:
    """Build a grounded response without asking a model to reselect results."""
    if not results:
        return InboxSearchResponse(
            summary=(
                "No matching local triaged messages were found. "
                "Run triage first for the best search results."
            )
        )
    return InboxSearchResponse(
        summary=f"Found {len(results)} matching messages.",
        results=results,
    )


def run_inbox_search(
    model,
    account_id: str,
    persist_directory: Path,
    embeddings,
    query: str,
    *,
    config: dict | None = None,
) -> dict:
    """Plan once, apply hard filters, then rank eligible messages semantically."""
    planner = model.with_structured_output(InboxSearchPlanOutput)
    today = datetime.now(UTC).date().isoformat()
    plan_prompt = f"{SEARCH_PLANNER_PROMPT}\n\nToday: {today}\nUser query: {query}"
    plan = InboxSearchPlanOutput.model_validate(planner.invoke(plan_prompt, config=config))

    vector_results = []
    if plan.topic:
        # Retrieve extra semantic candidates before applying hard filters. This
        # avoids a sender or status constraint consuming the whole result limit.
        candidate_limit = min(max(plan.limit * 5, 20), 100)
        vector_results = retrieve_similar_summaries(
            account_id,
            plan.topic,
            persist_directory=persist_directory,
            embeddings=embeddings,
            limit=candidate_limit,
        )
    eligible_results = search_triaged_messages(
        account_id,
        plan,
        candidate_message_ids=(
            [result.message_id for result in vector_results] if plan.topic else None
        ),
    )
    ranked = rank_results(
        eligible_results,
        vector_results,
        has_topic=bool(plan.topic),
    )[: plan.limit]
    response = build_search_response(ranked)
    return {
        "plan": plan,
        "eligible_results": eligible_results,
        "vector_results": vector_results,
        "ranked_results": ranked,
        "response": response,
    }
