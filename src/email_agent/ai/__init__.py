"""Model construction, prompting, and LangChain agent interactions."""

from email_agent.ai.agents import EmailAgents
from email_agent.ai.llm import get_model

__all__ = ["EmailAgents", "get_model"]
