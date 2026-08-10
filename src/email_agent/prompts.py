from __future__ import annotations

import re
from pathlib import Path

from email_agent.config import AgentProfile
from email_agent.models import EmailMessage, EmailThread


def load_prompt(root: Path, relative_path: str) -> str:
    path = (root / relative_path).resolve()
    if root.resolve() not in path.parents:
        raise ValueError("Prompt path escapes the project directory")
    return path.read_text().strip()


def strip_quoted_text(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith(">") or re.match(r"^On .+ wrote:$", line.strip()):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def format_thread(thread: EmailThread, current: EmailMessage) -> str:
    messages = thread.messages[-8:] if thread.messages else [current]
    chunks = []
    for message in messages:
        body = strip_quoted_text(message.content)[:6000]
        chunks.append(f"From: {message.from_address}\nSubject: {message.subject}\n\n{body}")
    return "\n\n---\n\n".join(chunks)


def system_prompt(root: Path, profile: AgentProfile, task: str) -> str:
    shared = load_prompt(root, "prompts/shared/safety.md")
    identity = load_prompt(root, profile.prompts.system)
    task_prompt = load_prompt(root, getattr(profile.prompts, task))
    behavior = profile.behavior.model_dump_json(indent=2)
    return f"{shared}\n\n{identity}\n\nProfile behavior:\n{behavior}\n\n{task_prompt}"
