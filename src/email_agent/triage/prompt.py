from pathlib import Path

from email_agent.config import AgentConfig
from email_agent.llm.prompts import SAFETY_INSTRUCTIONS, format_thread, load_prompt

TRIAGE_INSTRUCTIONS = """Triage the email using the required schema.
Choose a category only when one configured value clearly fits. Return null when
none fit; never force a message into the closest category, invent a category, or
reuse an unlisted category. Set requires_reply when a direct response is useful.
Use priority to express urgency. Set requires_escalation for sensitive or
consequential matters that require careful human judgment, and explain why."""


def triage_system_prompt(root: Path, agent: AgentConfig) -> str:
    """Build the triage prompt from application and user instructions."""
    custom_instructions = load_prompt(root, agent.triage_prompt)
    categories = "\n".join(
        f"- {key}: {description}" for key, description in agent.categories.items()
    )
    return (
        f"{SAFETY_INSTRUCTIONS}\n\n{TRIAGE_INSTRUCTIONS}\n\n"
        f"Configured categories:\n{categories}\n\n{custom_instructions}"
    )


__all__ = ["format_thread", "triage_system_prompt"]
