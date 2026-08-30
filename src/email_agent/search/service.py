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
        """Run hybrid local retrieval and return grounded search results."""
        embeddings = get_embedding_model(self.account.model)
        result = run_inbox_search(
            self.model,
            self.account_id,
            self.settings.root / "data" / "chroma",
            embeddings,
            query,
            config={
                "tags": ["email-agent", "inbox-search"],
                "metadata": {
                    "workflow": "natural-language-inbox-search",
                    "account_id": self.account_id,
                    "model_provider": self.account.model.provider,
                    "model": self.account.model.model,
                    "retrieval": "chroma-triage-summaries",
                },
            },
        )
        return result["response"]
