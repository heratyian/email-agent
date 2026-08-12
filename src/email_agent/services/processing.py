from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter

from email_agent.categories import category_destination
from email_agent.models import Draft, DraftReply, EmailClassification, EmailMessage

logger = logging.getLogger(__name__)


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


class ProcessingService:
    """Classify, draft, synchronize, and persist recent messages."""

    def __init__(self, account_id, agent, provider, agents, database):
        self.account_id, self.agent, self.provider, self.agents, self.database = (
            account_id,
            agent,
            provider,
            agents,
            database,
        )

    def process(self, limit: int = 20) -> list[ProcessedEmail | ProcessingFailure]:
        """Process messages not already completed in the local database."""
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
                if classification.requires_reply:
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
