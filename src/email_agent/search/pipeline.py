from __future__ import annotations

import json
from datetime import UTC, datetime

from email_agent.search.models import (
    InboxSearchItemOutput,
    InboxSearchOutput,
    InboxSearchPlanOutput,
    InboxSearchResponse,
    InboxSearchResult,
)

SEARCH_PLANNER_PROMPT = """Convert the user's inbox search request into a structured search plan.

Rules:
- Search only locally synchronized, triaged email.
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
- If there are no results, return an empty messages list and say that no matching local triaged messages were found.
- Mention that /search only searches synchronized and triaged local mail when useful.
"""


def default_plan(query: str) -> InboxSearchPlanOutput:
    """Return a safe search plan when model planning is unavailable."""
    lowered = query.casefold()
    return InboxSearchPlanOutput(
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


def fallback_output(
    query: str, plan: InboxSearchPlanOutput, results: list[InboxSearchResult]
) -> InboxSearchOutput:
    """Return deterministic model-shaped output when synthesis is unavailable."""
    if not results:
        return InboxSearchOutput(
            summary=(
                "I did not find matching local triaged messages. "
                "Run triage first for best /search results."
            )
        )
    return InboxSearchOutput(
        summary=f"Found {len(results)} messages. {plan.rationale}",
        messages=[
            InboxSearchItemOutput(
                message_id=result.message_id,
                subject=result.subject,
                explanation=result.summary,
            )
            for result in results
        ],
    )


def ground_output(output: InboxSearchOutput, results: list[InboxSearchResult]) -> InboxSearchOutput:
    """Discard unknown IDs and restore subjects from retrieved messages."""
    results_by_id = {result.message_id: result for result in results}
    grounded = []
    seen = set()
    for item in output.messages:
        result = results_by_id.get(item.message_id)
        if result is None or item.message_id in seen:
            continue
        seen.add(item.message_id)
        grounded.append(item.model_copy(update={"subject": result.subject}))
    return output.model_copy(update={"messages": grounded})


def build_search_response(
    output: InboxSearchOutput, results: list[InboxSearchResult]
) -> InboxSearchResponse:
    """Attach model explanations to authoritative ranked result metadata."""
    results_by_id = {result.message_id: result for result in results}
    grounded_results = [
        results_by_id[item.message_id].model_copy(update={"match_explanation": item.explanation})
        for item in output.messages
        if item.message_id in results_by_id
    ]
    return InboxSearchResponse(summary=output.summary, results=grounded_results)


def run_inbox_search(
    model,
    structured_search_tool,
    vector_search_tool,
    query: str,
    *,
    config: dict | None = None,
) -> dict:
    """Run the read-only hybrid retrieval pipeline in explicit sequence."""
    planner = model.with_structured_output(InboxSearchPlanOutput)
    synthesizer = model.with_structured_output(InboxSearchOutput)
    today = datetime.now(UTC).date().isoformat()
    plan_prompt = f"{SEARCH_PLANNER_PROMPT}\n\nToday: {today}\nUser query: {query}"
    plan = InboxSearchPlanOutput.model_validate(planner.invoke(plan_prompt, config=config))

    raw_structured = structured_search_tool.invoke(plan.model_dump_json(), config=config)
    structured_results = [
        InboxSearchResult.model_validate(result) for result in json.loads(raw_structured)
    ]
    raw_vector = vector_search_tool.invoke(
        {"query": plan.topic or query, "limit": plan.limit}, config=config
    )
    vector_results = [InboxSearchResult.model_validate(result) for result in json.loads(raw_vector)]
    ranked = merge_results(structured_results, vector_results)[: plan.limit]

    answer_prompt = "\n\n".join(
        [
            SEARCH_ANSWER_PROMPT,
            f"User query:\n{query}",
            f"Interpreted search:\n{plan.rationale}",
            f"Results:\n{results_context(ranked) if ranked else 'No results.'}",
        ]
    )
    output = InboxSearchOutput.model_validate(synthesizer.invoke(answer_prompt, config=config))
    output = ground_output(output, ranked)
    return {
        "plan": plan,
        "structured_results": structured_results,
        "vector_results": vector_results,
        "ranked_results": ranked,
        "output": output,
        "response": build_search_response(output, ranked),
    }
