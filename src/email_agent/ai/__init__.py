"""Model construction, prompting, and LangChain agent interactions."""

from email_agent.ai.agents import EmailAgents
from email_agent.ai.llm import get_model
from email_agent.ai.outputs import ClassificationOutput, DraftOutput

__all__ = ["ClassificationOutput", "DraftOutput", "EmailAgents", "get_model"]
