from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter

from email_agent.models import Draft, DraftReply, EmailClassification, EmailMessage

logger = logging.getLogger(__name__)

LEGACY_CATEGORY_MAP = {
    "needs_reply": "action",
    "support_request": "action",
    "urgent": "important",
    "newsletter": "newsletters",
    "spam": "noise",
    "automated": "reference",
    "informational": "reference",
    "unknown": "important",
}


def category_destination(agent, classification: EmailClassification) -> str | None:
    """Return the provider-neutral label/folder path for a configured category."""
    key = classification.category
    if key is None:
        return None
    if key not in agent.categories:
        key = LEGACY_CATEGORY_MAP.get(key, key)
    if key not in agent.categories:
        nested_matches = [
            candidate for candidate in agent.categories if candidate.rsplit("/", 1)[-1] == key
        ]
        if len(nested_matches) == 1:
            key = nested_matches[0]
    if key not in agent.categories:
        raise KeyError(f"unknown category {classification.category!r}")
    return key


@dataclass
class ProcessedEmail:
    """One successfully processed message and its persisted outputs."""

    local_id: int
    message: EmailMessage
    classification: EmailClassification
    reply: DraftReply | None
    draft: Draft | None


@dataclass
class ProcessingFailure:
    """A message-level failure that remains eligible for a later retry."""

    message: EmailMessage
    error: str
    local_id: int | None = None


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

    def process(self, limit: int = 20) -> list[ProcessedEmail | ProcessingFailure]:
        """Process recent messages that have not already been processed locally.

        Provider read/unread state is deliberately ignored. A message may have
        been read in another mail client without having been handled by the
        agent, so the local database is the source of truth for this workflow.
        """
        if limit < 1:
            return []
        results: list[ProcessedEmail | ProcessingFailure] = []
        for message in self.provider.get_messages(limit, unread_only=False):
            if self.database.is_processed(message.account_id, message.provider_id):
                continue
            started = perf_counter()
            local_id = None
            drafted = False
            try:
                thread = self.provider.get_thread(message.provider_id)
                classification = self.agents.classify(message, thread)
                reply = None
                if classification.requires_reply and self.agent.safety.allow_drafts:
                    reply = self.agents.draft(message, thread, classification)
                    drafted = True
                destination = category_destination(self.agent, classification)
                local_id, draft = self.database.save_result(message, classification, reply)
                sync = None
                if destination is not None:
                    previous = self.database.current_category_sync(local_id)
                    sync = self.provider.sync_category(
                        message.provider_id, destination, message.mailbox, previous
                    )
                self.provider.mark_processed(message.provider_id)
                self.database.complete_result(
                    local_id,
                    self.account_id,
                    self.agent,
                    round((perf_counter() - started) * 1000),
                    drafted,
                    destination=(
                        self.provider.category_sync_key(destination)
                        if destination is not None
                        else None
                    ),
                    sync_result=sync,
                )
                results.append(ProcessedEmail(local_id, message, classification, reply, draft))
            except Exception as exc:  # noqa: BLE001 - isolate failures within the batch
                if local_id is not None:
                    try:
                        self.database.record_run(
                            local_id,
                            self.account_id,
                            self.agent,
                            round((perf_counter() - started) * 1000),
                            drafted,
                            error=str(exc),
                        )
                    except Exception as audit_error:  # noqa: BLE001
                        logger.warning("Could not record processing failure: %s", audit_error)
                results.append(
                    ProcessingFailure(message=message, local_id=local_id, error=str(exc))
                )
        return results
