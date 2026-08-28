"""Shared language-model construction and diagnostics."""

from email_agent.llm.chat import get_model
from email_agent.llm.embeddings import get_embedding_model

__all__ = ["get_embedding_model", "get_model"]
