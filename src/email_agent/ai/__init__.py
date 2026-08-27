"""Model construction, prompting, and LangChain agent interactions."""

from email_agent.ai.chat_models import get_model
from email_agent.ai.classifier import EmailClassifier
from email_agent.ai.drafter import EmailDrafter
from email_agent.ai.outputs import ClassificationOutput, DraftOutput

__all__ = ["ClassificationOutput", "DraftOutput", "EmailClassifier", "EmailDrafter", "get_model"]
