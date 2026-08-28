"""Model construction, prompting, and LangChain agent interactions."""

from email_agent.ai.chat_models import get_model
from email_agent.ai.drafter import EmailDrafter
from email_agent.ai.outputs import DraftOutput, TriageOutput
from email_agent.ai.triager import EmailTriager

__all__ = ["DraftOutput", "EmailDrafter", "EmailTriager", "TriageOutput", "get_model"]
