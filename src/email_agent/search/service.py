from __future__ import annotations

from pathlib import Path

from email_agent.config import AccountConfig, Settings
from email_agent.llm.embeddings import get_embedding_model
from email_agent.search.models import InboxSearchPlanOutput, InboxSearchResponse
from email_agent.search.retrieval import filter_search_candidates, retrieve_similar_summaries

SEARCH_PLANNER_PROMPT = """Plan a search over locally triaged email.

semantic_query contains words useful for vector similarity search.
The remaining fields are exact database filters. Set an exact filter only when
the user explicitly requests that constraint. Do not infer filters from the
message topic. Use only a configured category.

Examples:
- "Find the exposed credentials message"
  semantic_query="exposed production credentials"
- "Show urgent messages about credentials"
  semantic_query="credentials", priority="urgent"
- "Show my newsletters"
  semantic_query="newsletter", category="newsletters"
- "Find the API documentation update"
  semantic_query="API documentation update"
"""


def run_inbox_search(
    model,
    account_id: str,
    persist_directory: Path,
    embeddings,
    query: str,
    *,
    categories: dict[str, str] | None = None,
    config: dict | None = None,
) -> dict:
    """Plan, retrieve semantic candidates, then apply exact filters."""
    category_names = ", ".join(categories or {}) or "none"
    prompt = "\n\n".join(
        [
            SEARCH_PLANNER_PROMPT,
            f"Configured categories: {category_names}",
            f"User query: {query}",
        ]
    )
    planner = model.with_structured_output(InboxSearchPlanOutput)
    plan = InboxSearchPlanOutput.model_validate(planner.invoke(prompt, config=config))

    candidate_limit = min(max(plan.limit * 5, 20), 100)
    candidates = retrieve_similar_summaries(
        account_id,
        plan.semantic_query,
        persist_directory=persist_directory,
        embeddings=embeddings,
        limit=candidate_limit,
    )
    results = filter_search_candidates(account_id, plan, candidates)
    summary = (
        f"Found {len(results)} matching messages."
        if results
        else "No matching triaged messages were found."
    )
    response = InboxSearchResponse(summary=summary, results=results)
    return {
        "plan": plan,
        "candidate_results": candidates,
        "ranked_results": results,
        "response": response,
    }


class InboxSearchService:
    """Search triaged local email with natural language queries."""

    def __init__(self, settings: Settings, account_id: str, account: AccountConfig, model):
        self.settings = settings
        self.account_id = account_id
        self.account = account
        self.model = model

    def search(self, query: str) -> InboxSearchResponse:
        """Plan and run a filtered vector search over triaged messages."""
        embeddings = get_embedding_model(self.account.model)
        result = run_inbox_search(
            self.model,
            self.account_id,
            self.settings.root / "data" / "chroma",
            embeddings,
            query,
            categories=self.account.categories,
            config={
                "tags": ["email-agent", "inbox-search"],
                "metadata": {
                    "workflow": "inbox-search",
                    "account_id": self.account_id,
                },
            },
        )
        return result["response"]
