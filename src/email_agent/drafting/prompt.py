from pathlib import Path

from email_agent.config import AgentConfig
from email_agent.llm.prompts import SAFETY_INSTRUCTIONS, format_thread, load_prompt

DRAFT_INSTRUCTIONS = """Create a useful reply draft using the required schema.
Address only the latest relevant request. Do not invent facts, commitments, or
authorization. Ask a focused question when essential information is missing.
Preserve an existing Re: subject prefix or add it exactly once."""


def draft_system_prompt(root: Path, agent: AgentConfig) -> str:
    """Build the drafting prompt from application and user instructions."""
    if agent.draft_prompt is None:
        raise ValueError("draft_prompt is required to create an email drafter")
    custom_instructions = load_prompt(root, agent.draft_prompt)
    return f"{SAFETY_INSTRUCTIONS}\n\n{DRAFT_INSTRUCTIONS}\n\n{custom_instructions}"


__all__ = ["draft_system_prompt", "format_thread"]
