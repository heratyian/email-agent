from __future__ import annotations

import re
from pathlib import Path

from email_agent.config import AgentConfig
from email_agent.models import EmailMessage, EmailThread


def load_prompt(root: Path, relative_path: str) -> str:
    """Read a prompt while preventing paths outside the project root."""
    path = (root / relative_path).resolve()
    if root.resolve() not in path.parents:
        raise ValueError("Prompt path escapes the project directory")
    return path.read_text().strip()


def strip_quoted_text(text: str) -> str:
    """Remove common reply quotations to minimize model context exposure."""
    kept: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith(">") or re.match(r"^On .+ wrote:$", line.strip()):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def format_thread(thread: EmailThread, current: EmailMessage) -> str:
    """Format only the most recent relevant messages for model input."""
    messages = thread.messages[-8:] if thread.messages else [current]
    chunks = []
    for message in messages:
        body = strip_quoted_text(message.content)[:6000]
        chunks.append(f"From: {message.from_address}\nSubject: {message.subject}\n\n{body}")
    return "\n\n---\n\n".join(chunks)


def system_prompt(root: Path, agent: AgentConfig, task: str) -> str:
    shared = load_prompt(root, "prompts/shared/safety.md")
    identity = load_prompt(root, agent.prompts.system)
    task_prompt = load_prompt(root, getattr(agent.prompts, task))
    behavior = agent.behavior.model_dump_json(indent=2)
    return f"{shared}\n\n{identity}\n\nAgent behavior:\n{behavior}\n\n{task_prompt}"
