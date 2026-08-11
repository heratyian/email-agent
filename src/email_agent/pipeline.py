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


class InboxGroup(StrEnum):
    """User-facing inbox sections from the personal Gmail user story."""

    NEEDS_REPLY = "Needs Reply"
    IMPORTANT = "Important"
    INFORMATIONAL = "Informational"
    IGNORED = "Ignored"


class LocalMessageStatus(StrEnum):
    """Local agent state, independent of the mailbox provider's read/unread flag.

    NEW means this inbox run classified the message for the first time. TRIAGED
    means a previous inbox run stored its classification but the processing
    workflow has not handled it. PROCESSED means ``process`` or ``monitor``
    completed agent handling and generated a draft when one was required.
    """

    NEW = "NEW"
    TRIAGED = "TRIAGED"
    PROCESSED = "PROCESSED"


INBOX_GROUP_ORDER = (
    InboxGroup.NEEDS_REPLY,
    InboxGroup.IMPORTANT,
    InboxGroup.INFORMATIONAL,
    InboxGroup.IGNORED,
)


@dataclass(frozen=True)
class TriagedEmail:
    """A mailbox message with its local ID, classification, group, and workflow state."""

    local_id: int
    message: EmailMessage
    classification: EmailClassification
    group: InboxGroup
    status: LocalMessageStatus


def inbox_group(classification: EmailClassification) -> InboxGroup:
    """Map the detailed classification schema to one user-facing inbox section."""
    if classification.requires_reply:
        return InboxGroup.NEEDS_REPLY
    if classification.category in {"urgent", "unknown"} or classification.priority in {
        "high",
        "urgent",
    }:
        return InboxGroup.IMPORTANT
    if classification.category in {"spam", "newsletter"}:
        return InboxGroup.IGNORED
    return InboxGroup.INFORMATIONAL


def triage_inbox(
    provider,
    agents,
    database,
    limit: int = 20,
    *,
    unread_only: bool = False,
    unprocessed_only: bool = False,
) -> list[TriagedEmail]:
    """Classify and return recent Inbox mail without generating drafts.

    Previously stored classifications are reused. A newly classified message is
    returned as NEW, an existing unprocessed classification as TRIAGED, and a
    message completed by the processing workflow as PROCESSED.
    """
    if limit < 1:
        return []
    results: list[TriagedEmail] = []
    messages = provider.get_messages(limit, unread_only=unread_only)
    for message in sorted(messages, key=lambda item: item.received_at, reverse=True):
        processed = database.is_processed(message.account_id, message.provider_id)
        if unprocessed_only and processed:
            continue
        saved = database.get_triage(message.account_id, message.provider_id)
        if saved:
            local_id, classification = saved
            status = LocalMessageStatus.PROCESSED if processed else LocalMessageStatus.TRIAGED
        else:
            thread = provider.get_thread(message.provider_id)
            classification = agents.classify(message, thread)
            local_id = database.save_triage(message, classification)
            status = LocalMessageStatus.PROCESSED if processed else LocalMessageStatus.NEW
        results.append(
            TriagedEmail(
                local_id=local_id,
                message=message,
                classification=classification,
                group=inbox_group(classification),
                status=status,
            )
        )
    return results


class EmailPipeline:
    """Deterministic orchestration around classification and optional drafting."""

    def __init__(self, profile, provider, agents, database):
        self.profile, self.provider, self.agents, self.database = (
            profile,
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
            if classification.requires_reply and self.profile.safety.allow_drafts:
                reply = self.agents.draft(message, thread, classification)
                words = reply.body.split()
                if len(words) > self.profile.behavior.max_reply_words:
                    reply.body = " ".join(words[: self.profile.behavior.max_reply_words])
            local_id, draft = self.database.save_result(message, classification, reply)
            self.database.record_run(
                local_id, self.profile, round((perf_counter() - started) * 1000), bool(reply)
            )
            self.provider.mark_processed(message.provider_id)
            results.append(ProcessedEmail(local_id, message, classification, reply, draft))
        return results
