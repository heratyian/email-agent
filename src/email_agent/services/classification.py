from __future__ import annotations

import logging
from dataclasses import dataclass

from email_agent.ai.agents import EmailAgents
from email_agent.ai.models import EmailClassification
from email_agent.config import AgentConfig
from email_agent.db import Database
from email_agent.models import EmailMessage
from email_agent.providers import MailProvider
from email_agent.services.category_routing import category_destination

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClassifiedEmail:
    """One successfully classified and synchronized message."""

    local_id: int
    message: EmailMessage
    classification: EmailClassification
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
        database: Database,
    ):
        self.agent = agent
        self.provider = provider
        self.agents = agents
        self.database = database

    def classify_recent(
        self, limit: int = 20, *, reclassify: bool = False
    ) -> list[ClassifiedEmail | ClassificationFailure]:
        """Classify recent unclassified messages, or all recent messages when requested."""
        if limit < 1:
            return []
        results: list[ClassifiedEmail | ClassificationFailure] = []
        for message in self.provider.get_messages(limit, unread_only=False):
            if not reclassify and self.database.classification_completed(
                message.account_id, message.provider_id
            ):
                continue
            saved = self.database.get_triage(message.account_id, message.provider_id)
            results.append(self._classify(message, saved[0] if saved else None))
        return results

    def classify_message(self, local_id: int) -> ClassifiedEmail | ClassificationFailure:
        """Classify one locally synchronized message."""
        stored_message = self.database.show_message(local_id)
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
            if local_id is None:
                local_id = self.database.save_triage(message, classification)
            elif not self.database.update_classification(local_id, classification):
                raise LookupError("message classification could not be saved")
            previous = self.database.current_category_sync(local_id)
            synchronization = self.provider.sync_category(
                message.provider_id, destination, message.mailbox, previous
            )
            self.database.complete_classification(
                local_id,
                self.provider.category_sync_key(destination) if destination is not None else None,
                synchronization,
            )
            if not classification.requires_reply:
                self.database.delete_generated_drafts(local_id)
            logger.info("Classified local message %s as %s", local_id, classification.category)
            return ClassifiedEmail(
                local_id, message, classification, self.database.has_draft(local_id)
            )
        except Exception as exc:  # noqa: BLE001 - isolate failures within a batch
            logger.info("Classification failed for local message %s: %s", local_id or "new", exc)
            return ClassificationFailure(message, str(exc), local_id)
