from __future__ import annotations

import json
from datetime import UTC, datetime

from langgraph.graph import END, StateGraph

from email_agent.search.models import (
    InboxSearchAnswer,
    InboxSearchAnswerItem,
    InboxSearchPlan,
    InboxSearchResult,
    InboxSearchState,
)

SEARCH_PLANNER_PROMPT = """Convert the user's inbox search request into a structured search plan.

Rules:
- Search only locally synchronized, classified email.
- Do not plan write actions.
- Interpret "recent" as the last 14 days.
- Interpret "important" as high priority, escalation, security, finance, legal, deadlines, or messages needing a reply.
- If the user asks for messages that need attention, set requires_reply true when appropriate.
- If the user asks for a topic, include useful synonyms in topic.
- Keep limit between 1 and 20.
- Return only the required schema.
"""

SEARCH_ANSWER_PROMPT = """Answer the user's inbox search request using only the provided message results.

Rules:
- Do not invent messages.
- Return a concise plain-text summary with no Markdown.
- Return each referenced message as a structured item with its local ID, subject, and explanation.
- Use only local IDs provided in the results.
- If there are no results, return an empty messages list and say that no matching local classified messages were found.
- Mention that /search only searches synchronized and classified local mail when useful.
"""


def default_plan(query: str) -> InboxSearchPlan:
    """Return a safe search plan when model planning is unavailable."""
    lowered = query.casefold()
    return InboxSearchPlan(
        query=query,
        topic=query,
        priority="high" if "important" in lowered else None,
        requires_reply=True if "reply" in lowered or "attention" in lowered else None,
        recent_days=14 if "recent" in lowered or "this week" in lowered else None,
        limit=8,
        rationale="Used a conservative local search plan.",
    )


def merge_results(
    structured_results: list[InboxSearchResult], vector_results: list[InboxSearchResult]
) -> list[InboxSearchResult]:
    """Merge result lists and keep the best score for each message."""
    merged: dict[int, InboxSearchResult] = {}
    for result in [*structured_results, *vector_results]:
        existing = merged.get(result.message_id)
        if existing is None:
            merged[result.message_id] = result
            continue
        merged[result.message_id] = existing.model_copy(
            update={
                "score": existing.score + result.score,
                "reason": f"{existing.reason} {result.reason}",
            }
        )
    return sorted(merged.values(), key=lambda item: item.score, reverse=True)


def results_context(results: list[InboxSearchResult]) -> str:
    """Format ranked results as grounded context for answer synthesis."""
    return "\n\n".join(
        [
            "\n".join(
                [
                    f"[{result.message_id}]",
                    f"From: {result.from_name or result.from_address}",
                    f"Subject: {result.subject}",
                    f"Received: {result.received_at.isoformat()}",
                    f"Category: {result.category or 'none'}",
                    f"Priority: {result.priority or 'unknown'}",
                    f"Requires reply: {result.requires_reply}",
                    f"Requires escalation: {result.requires_escalation}",
                    f"Summary: {result.summary}",
                    f"Reason: {result.reason}",
                ]
            )
            for result in results
        ]
    )


def fallback_answer(
    query: str, plan: InboxSearchPlan, results: list[InboxSearchResult]
) -> InboxSearchAnswer:
    """Return a deterministic answer when model synthesis is unavailable."""
    if not results:
        return InboxSearchAnswer(
            summary=(
                "I did not find matching local classified messages. "
                "Run classify first for best /search results."
            )
        )
    return InboxSearchAnswer(
        summary=f"Found {len(results)} messages. {plan.rationale}",
        messages=[
            InboxSearchAnswerItem(
                message_id=result.message_id,
                subject=result.subject,
                explanation=result.summary,
            )
            for result in results
        ],
    )


def ground_answer(
    answer: InboxSearchAnswer, results: list[InboxSearchResult]
) -> InboxSearchAnswer:
    """Discard unknown IDs and restore subjects from retrieved messages."""
    results_by_id = {result.message_id: result for result in results}
    grounded = []
    seen = set()
    for item in answer.messages:
        result = results_by_id.get(item.message_id)
        if result is None or item.message_id in seen:
            continue
        seen.add(item.message_id)
        grounded.append(item.model_copy(update={"subject": result.subject}))
    return answer.model_copy(update={"messages": grounded})


def build_inbox_search_graph(model, structured_search_tool, vector_search_tool):
    """Build the read-only LangGraph inbox search workflow."""
    planner = model.with_structured_output(InboxSearchPlan)
    answerer = model.with_structured_output(InboxSearchAnswer)

    def plan_search(state: InboxSearchState) -> dict:
        today = datetime.now(UTC).date().isoformat()
        prompt = f"{SEARCH_PLANNER_PROMPT}\n\nToday: {today}\nUser query: {state['user_query']}"
        plan = InboxSearchPlan.model_validate(planner.invoke(prompt))
        return {"plan": plan}

    def structured_search(state: InboxSearchState) -> dict:
        raw_results = structured_search_tool.invoke(state["plan"].model_dump_json())
        return {
            "structured_results": [
                InboxSearchResult.model_validate(result) for result in json.loads(raw_results)
            ]
        }

    def vector_search(state: InboxSearchState) -> dict:
        plan = state["plan"]
        raw_results = vector_search_tool.invoke({"query": plan.topic or state["user_query"], "limit": plan.limit})
        return {
            "vector_results": [
                InboxSearchResult.model_validate(result) for result in json.loads(raw_results)
            ]
        }

    def rank_results(state: InboxSearchState) -> dict:
        ranked = merge_results(state.get("structured_results", []), state.get("vector_results", []))
        return {"ranked_results": ranked[: state["plan"].limit]}

    def synthesize_answer(state: InboxSearchState) -> dict:
        ranked = state.get("ranked_results", [])
        prompt = "\n\n".join(
            [
                SEARCH_ANSWER_PROMPT,
                f"User query:\n{state['user_query']}",
                f"Interpreted search:\n{state['plan'].rationale}",
                f"Results:\n{results_context(ranked) if ranked else 'No results.'}",
            ]
        )
        answer = InboxSearchAnswer.model_validate(answerer.invoke(prompt))
        answer = ground_answer(answer, ranked)
        return {"answer": answer}

    graph = StateGraph(InboxSearchState)
    graph.add_node("plan_search", plan_search)
    graph.add_node("structured_search", structured_search)
    graph.add_node("vector_search", vector_search)
    graph.add_node("rank_results", rank_results)
    graph.add_node("synthesize_answer", synthesize_answer)
    graph.set_entry_point("plan_search")
    graph.add_edge("plan_search", "structured_search")
    graph.add_edge("plan_search", "vector_search")
    graph.add_edge("structured_search", "rank_results")
    graph.add_edge("vector_search", "rank_results")
    graph.add_edge("rank_results", "synthesize_answer")
    graph.add_edge("synthesize_answer", END)
    return graph.compile()
