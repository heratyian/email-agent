from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from email_agent.ai.agents import EmailAgents
from email_agent.ai.outputs import ClassificationOutput
from email_agent.config import AgentConfig
from email_agent.db import CategorySync, Classification, Draft, Message, database
from email_agent.providers import MailProvider
from email_agent.providers.models import EmailMessage
from email_agent.services.category_routing import category_destination

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClassifiedEmail:
    """One successfully classified and synchronized message."""

    local_id: int
    message: EmailMessage
    classification: ClassificationOutput
    draft_ready: bool


@dataclass(frozen=True)
class ClassificationFailure:
    """One classification failure isolated from the rest of a batch."""

    message: EmailMessage
    error: str
    local_id: int | None = None


class ClassificationService:
    """Classify messages and synchronize their configured mailbox category."""

    def __init__(
        self,
        agent: AgentConfig,
        provider: MailProvider,
        agents: EmailAgents,
    ):
        self.agent = agent
        self.provider = provider
        self.agents = agents

    def classify_recent(
        self, limit: int = 20, *, reclassify: bool = False
    ) -> list[ClassifiedEmail | ClassificationFailure]:
        """Classify recent unclassified messages, or all recent messages when requested."""
        if limit < 1:
            return []
        results: list[ClassifiedEmail | ClassificationFailure] = []
        for message in self.provider.get_messages(limit, unread_only=False):
            stored = Message.find_email(message.account_id, message.provider_id)
            if not reclassify and stored is not None and stored.classified_at is not None:
                continue
            results.append(self._classify(message, stored.id if stored else None))
        return results

    def classify_message(self, local_id: int) -> ClassifiedEmail | ClassificationFailure:
        """Classify one locally synchronized message."""
        stored_message = Message.get_or_none(Message.id == local_id)
        if not stored_message:
            raise LookupError("message not found")
        message = self.provider.get_message(
            stored_message.provider_uid, stored_message.provider_mailbox
        )
        return self._classify(message, local_id)

    def _classify(
        self, message: EmailMessage, local_id: int | None
    ) -> ClassifiedEmail | ClassificationFailure:
        try:
            thread = self.provider.get_thread(message.provider_id, message.mailbox)
            classification = self.agents.classify(message, thread)
            destination = category_destination(self.agent, classification)
            with database.atomic():
                stored = (
                    Message.upsert_email(message)
                    if local_id is None
                    else Message.get_by_id(local_id)
                )
                Classification.save_for(stored, classification)
                local_id = stored.id
            previous = stored.current_category_sync()
            synchronization = self.provider.sync_category(
                message.provider_id, destination, message.mailbox, previous
            )
            with database.atomic():
                if synchronization is not None and synchronization.source_moved:
                    stored.provider_uid = synchronization.provider_id
                    stored.provider_mailbox = synchronization.mailbox
                CategorySync.replace_active(
                    local_id,
                    self.provider.category_sync_key(destination)
                    if destination is not None
                    else None,
                    synchronization,
                )
                stored.classified_at = datetime.now(UTC)
                stored.save()
                if not classification.requires_reply:
                    Draft.delete().where(
                        (Draft.message == local_id) & (Draft.status == "generated")
                    ).execute()
            logger.info("Classified local message %s as %s", local_id, classification.category)
            return ClassifiedEmail(
                local_id, message, classification, Draft.has_reviewable(local_id)
            )
        except Exception as exc:  # noqa: BLE001 - isolate failures within a batch
            logger.info("Classification failed for local message %s: %s", local_id or "new", exc)
            return ClassificationFailure(message, str(exc), local_id)
