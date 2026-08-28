from __future__ import annotations

import logging
from dataclasses import dataclass

from email_agent.ai.outputs import TriageOutput
from email_agent.ai.triager import EmailTriager
from email_agent.config import AgentConfig
from email_agent.db import CategorySync, Draft, Message, Triage, database
from email_agent.providers import MailProvider
from email_agent.providers.models import EmailMessage
from email_agent.services.category_routing import category_destination

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TriagedEmail:
    """One successfully triaged and synchronized message."""

    local_id: int
    message: EmailMessage
    triage: TriageOutput
    draft_ready: bool


@dataclass(frozen=True)
class TriageFailure:
    """One model or provider synchronization failure isolated from a batch."""

    message: EmailMessage
    error: str
    local_id: int | None = None
    triage: TriageOutput | None = None


class TriageService:
    """Triage messages and synchronize their configured mailbox category."""

    def __init__(
        self,
        agent: AgentConfig,
        provider: MailProvider,
        triager: EmailTriager,
    ):
        self.agent = agent
        self.provider = provider
        self.triager = triager

    def triage_pending(self, account_id: str) -> list[TriagedEmail | TriageFailure]:
        """Triage new messages and retry incomplete provider category synchronization."""
        results = self._retry_pending_category_syncs(account_id)
        for stored in Message.untriaged(account_id):
            results.append(self._triage(stored.to_email(), stored.id))
        return results

    def _retry_pending_category_syncs(
        self, account_id: str
    ) -> list[TriagedEmail | TriageFailure]:
        """Retry category synchronization without invoking the model again."""
        results = []
        for stored in Message.pending_category_syncs(account_id):
            triage = stored.triage_value()
            if triage is None:
                continue
            results.append(self._synchronize(stored, stored.to_email(), triage))
        return results

    def triage_message(self, local_id: int) -> TriagedEmail | TriageFailure:
        """Triage one locally synchronized message."""
        stored_message = Message.get_or_none(Message.id == local_id)
        if not stored_message:
            raise LookupError("message not found")
        message = self.provider.get_message(
            stored_message.provider_uid, stored_message.provider_mailbox
        )
        return self._triage(message, local_id)

    def _triage(
        self, message: EmailMessage, local_id: int | None
    ) -> TriagedEmail | TriageFailure:
        try:
            thread = self.provider.get_thread(message.provider_id, message.mailbox)
            triage = self.triager.triage(message, thread)
            with database.atomic():
                stored = (
                    Message.upsert_email(message)
                    if local_id is None
                    else Message.get_by_id(local_id)
                )
                Triage.save_for(stored, triage)
                local_id = stored.id
            return self._synchronize(stored, message, triage)
        except Exception as exc:  # noqa: BLE001 - isolate failures within a batch
            logger.info("Triage failed for local message %s: %s", local_id or "new", exc)
            return TriageFailure(message, str(exc), local_id)

    def _synchronize(
        self, stored: Message, message: EmailMessage, triage: TriageOutput
    ) -> TriagedEmail | TriageFailure:
        """Synchronize one persisted triage with its provider category."""
        try:
            destination = category_destination(self.agent, triage)
            previous = stored.current_category_sync()
            synchronization = self.provider.sync_category(
                message.provider_id, destination, message.mailbox, previous
            )
            with database.atomic():
                if synchronization is not None and synchronization.source_moved:
                    stored.provider_uid = synchronization.provider_id
                    stored.provider_mailbox = synchronization.mailbox
                CategorySync.replace_active(
                    stored.id,
                    self.provider.category_sync_key(destination)
                    if destination is not None
                    else None,
                    synchronization,
                )
                Triage.mark_category_sync_complete(stored)
                stored.save()
                if not triage.requires_reply:
                    Draft.delete().where(
                        (Draft.message == stored.id) & (Draft.status == "generated")
                    ).execute()
            logger.info("Triaged local message %s as %s", stored.id, triage.category)
            return TriagedEmail(
                stored.id, message, triage, Draft.has_reviewable(stored.id)
            )
        except Exception as exc:  # noqa: BLE001 - isolate failures within a batch
            logger.info("Category sync failed for local message %s: %s", stored.id, exc)
            return TriageFailure(message, str(exc), stored.id, triage)
