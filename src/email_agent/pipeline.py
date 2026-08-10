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


INBOX_GROUP_ORDER = (
    InboxGroup.NEEDS_REPLY,
    InboxGroup.IMPORTANT,
    InboxGroup.INFORMATIONAL,
    InboxGroup.IGNORED,
)


@dataclass(frozen=True)
class TriagedEmail:
    """A message paired with its read-only inbox classification."""

    message: EmailMessage
    classification: EmailClassification
    group: InboxGroup


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


def triage_inbox(provider, agents, database, limit: int = 20) -> list[TriagedEmail]:
    """Classify unprocessed mail without persisting results or generating drafts."""
    if limit < 1:
        return []
    results: list[TriagedEmail] = []
    for message in provider.get_new_messages(limit):
        if database.is_processed(message.account_id, message.provider_id):
            continue
        thread = provider.get_thread(message.provider_id)
        classification = agents.classify(message, thread)
        results.append(
            TriagedEmail(
                message=message,
                classification=classification,
                group=inbox_group(classification),
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
