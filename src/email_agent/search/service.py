from __future__ import annotations

from email_agent.config import AccountConfig, Settings
from email_agent.llm.embeddings import get_embedding_model
from email_agent.search.models import InboxSearchResponse
from email_agent.search.pipeline import run_inbox_search


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
