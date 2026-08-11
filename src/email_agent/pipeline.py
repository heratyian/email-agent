from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter

from email_agent.models import Draft, DraftReply, EmailClassification, EmailMessage


@dataclass
class ProcessedEmail:
    """One successfully processed message and its persisted outputs."""

    local_id: int
    message: EmailMessage
    classification: EmailClassification
    reply: DraftReply | None
    draft: Draft | None


class PriorityGroup(StrEnum):
    """Familiar priority sections used to order the assistant's inbox."""

    URGENT = "Urgent"
    NORMAL = "Normal"
    LOW = "Low Priority"


PRIORITY_GROUP_ORDER = (PriorityGroup.URGENT, PriorityGroup.NORMAL, PriorityGroup.LOW)


@dataclass(frozen=True)
class TriagedEmail:
    """A mailbox message with its local ID, classification, group, and workflow state."""

    local_id: int
    message: EmailMessage
    classification: EmailClassification
    group: PriorityGroup
    attention_state: str
    draft_ready: bool


def inbox_group(classification: EmailClassification) -> PriorityGroup:
    """Collapse model priority into three recognizable inbox sections."""
    if classification.priority in {"urgent", "high"}:
        return PriorityGroup.URGENT
    if classification.priority == "low":
        return PriorityGroup.LOW
    return PriorityGroup.NORMAL


def triage_inbox(
    provider,
    agents,
    database,
    limit: int = 20,
    *,
    unread_only: bool = False,
    attention: str = "open",
) -> list[TriagedEmail]:
    """Classify and return recent Inbox mail without generating drafts.

    Previously stored classifications are reused. ``attention`` controls whether
    open, snoozed, done, or all recent messages are returned.
    """
    if limit < 1:
        return []
    results: list[TriagedEmail] = []
    messages = provider.get_messages(limit, unread_only=unread_only)
    for message in sorted(messages, key=lambda item: item.received_at, reverse=True):
        saved = database.get_triage(message.account_id, message.provider_id)
        if saved:
            local_id, classification = saved
        else:
            thread = provider.get_thread(message.provider_id)
            classification = agents.classify(message, thread)
            local_id = database.save_triage(message, classification)
        state = database.attention_state(local_id)
        if attention != "all" and state != attention:
            continue
        results.append(
            TriagedEmail(
                local_id=local_id,
                message=message,
                classification=classification,
                group=inbox_group(classification),
                attention_state=state,
                draft_ready=database.has_draft(local_id),
            )
        )
    return results


class EmailPipeline:
    """Deterministic orchestration around classification and optional drafting."""

    def __init__(self, account_id, agent, provider, agents, database):
        self.account_id, self.agent, self.provider, self.agents, self.database = (
            account_id,
            agent,
            provider,
            agents,
            database,
        )

    def process(self, limit: int = 20) -> list[ProcessedEmail]:
        if limit < 1:
            return []
        results: list[ProcessedEmail] = []
        for message in self.provider.get_new_messages(limit):
            if self.database.is_processed(message.account_id, message.provider_id):
                continue
            started = perf_counter()
            thread = self.provider.get_thread(message.provider_id)
            classification = self.agents.classify(message, thread)
            reply = None
            if classification.requires_reply and self.agent.safety.allow_drafts:
                reply = self.agents.draft(message, thread, classification)
                words = reply.body.split()
                if len(words) > self.agent.behavior.max_reply_words:
                    reply.body = " ".join(words[: self.agent.behavior.max_reply_words])
            local_id, draft = self.database.save_result(message, classification, reply)
            self.database.record_run(
                local_id,
                self.account_id,
                self.agent,
                round((perf_counter() - started) * 1000),
                bool(reply),
            )
            self.provider.mark_processed(message.provider_id)
            results.append(ProcessedEmail(local_id, message, classification, reply, draft))
        return results
