from __future__ import annotations

from email_agent.ai.embeddings import get_embedding_model
from email_agent.config import AccountConfig, Settings
from email_agent.search.graph import build_inbox_search_graph
from email_agent.search.models import InboxSearchAnswer
from email_agent.search.tools import make_search_tools


class InboxSearchService:
    """Answer read-only natural language questions about classified local email."""

    def __init__(self, settings: Settings, account_id: str, account: AccountConfig, model):
        self.settings = settings
        self.account_id = account_id
        self.account = account
        self.model = model

    def ask(self, query: str) -> InboxSearchAnswer:
        """Run the inbox search graph and return a grounded answer."""
        embeddings = get_embedding_model(self.account.model)
        tools = make_search_tools(
            self.account_id,
            self.settings.root / "data" / "chroma",
            embeddings,
        )
        graph = build_inbox_search_graph(self.model, *tools)
        result = graph.invoke(
            {"account_id": self.account_id, "user_query": query},
            config={
                "tags": ["email-agent", "inbox-search"],
                "metadata": {
                    "workflow": "natural-language-inbox-search",
                    "account_id": self.account_id,
                    "model_provider": self.account.model.provider,
                    "model": self.account.model.model,
                    "retrieval": "chroma-classification-summaries",
                },
            },
        )
        return result["answer"]
