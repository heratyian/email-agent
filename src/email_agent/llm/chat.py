from __future__ import annotations

import os

from langchain.chat_models import init_chat_model

from email_agent.config import ModelConfig


def get_model(config: ModelConfig):
    if config.provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=config.model,
            temperature=config.temperature,
            base_url=config.base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )
    if config.provider == "compatible":
        from langchain_openai import ChatOpenAI

        if not config.base_url:
            raise ValueError("compatible model provider requires model.base_url")
        return ChatOpenAI(
            model=config.model, temperature=config.temperature, base_url=config.base_url
        )
    return init_chat_model(
        config.model, model_provider=config.provider, temperature=config.temperature
    )
