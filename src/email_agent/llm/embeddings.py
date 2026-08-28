from __future__ import annotations

import os

from email_agent.config import ModelConfig

DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_OLLAMA_EMBEDDING_MODEL = "nomic-embed-text"


def get_embedding_model(config: ModelConfig):
    """Return the embedding model for local inbox summary retrieval."""
    if config.provider == "ollama":
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(
            model=os.getenv("OLLAMA_EMBEDDING_MODEL", DEFAULT_OLLAMA_EMBEDDING_MODEL),
            base_url=config.base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )
    if config.provider == "compatible":
        from langchain_openai import OpenAIEmbeddings

        if not config.base_url:
            raise ValueError("compatible model provider requires model.base_url")
        return OpenAIEmbeddings(
            model=os.getenv("OPENAI_EMBEDDING_MODEL", DEFAULT_OPENAI_EMBEDDING_MODEL),
            base_url=config.base_url,
        )
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=os.getenv("OPENAI_EMBEDDING_MODEL", DEFAULT_OPENAI_EMBEDDING_MODEL)
    )
