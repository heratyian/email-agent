from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

from email_agent.config import AccountConfig
from email_agent.persistence import CategorySync, Draft, Message, Triage
from email_agent.providers import MailProvider
from email_agent.triage.category_routing import category_destination
from email_agent.triage.triager import EmailTriager

logger = logging.getLogger(__name__)


class OrganizationStatus(StrEnum):
    """Outcome of organizing one locally stored message."""

    SYNCED = "synced"
    PREVIEW = "preview"
    SKIPPED = "skipped"
    UNCATEGORIZED = "uncategorized"
    FAILED = "failed"


@dataclass(frozen=True)
class OrganizationItem:
    """Provider-independent result for one organization candidate."""

    local_id: int
    subject: str
    status: OrganizationStatus
    destination: str | None = None
    retriaged_as: str | None = None
    error: str | None = None


@dataclass
class OrganizationReport:
    """Complete organization batch with convenient status totals."""

    dry_run: bool
    items: list[OrganizationItem] = field(default_factory=list)

    def count(self, status: OrganizationStatus) -> int:
        return sum(item.status is status for item in self.items)

    @property
    def changed(self) -> int:
        return self.count(OrganizationStatus.PREVIEW if self.dry_run else OrganizationStatus.SYNCED)

    @property
    def skipped(self) -> int:
        return self.count(OrganizationStatus.SKIPPED)

    @property
    def uncategorized(self) -> int:
        return self.count(OrganizationStatus.UNCATEGORIZED)

    @property
    def failed(self) -> int:
        return self.count(OrganizationStatus.FAILED)


class OrganizationService:
    """Retriage and synchronize stored categories without CLI concerns."""

    def __init__(
        self,
        account_id: str,
        account: AccountConfig,
        provider: MailProvider,
        triager: EmailTriager | None = None,
    ):
        self.account_id = account_id
        self.account = account
        self.provider = provider
        self.triager = triager

    def run(
        self,
        *,
        limit: int = 100,
        dry_run: bool = False,
        force: bool = False,
        retriage_unknown: bool = False,
        retriage_all: bool = False,
    ) -> OrganizationReport:
        """Organize recent local messages and isolate failures per message."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if retriage_unknown and retriage_all:
            raise ValueError("Use only one retriage option")
        should_retriage = retriage_unknown or retriage_all
        if should_retriage and self.triager is None:
            raise ValueError("Retriage requires a configured triager")

        report = OrganizationReport(dry_run=dry_run)
        rows = Message.organization_candidates(self.account_id, limit)
        logger.info("Examining %d local messages for organization", len(rows))
        for row in rows:
            report.items.append(
                self._organize_one(
                    row,
                    dry_run=dry_run,
                    force=force,
                    retriage_unknown=retriage_unknown,
                    retriage_all=retriage_all,
                )
            )
        logger.info(
            "Organization finished: changed=%d skipped=%d uncategorized=%d failed=%d",
            report.changed,
            report.skipped,
            report.uncategorized,
            report.failed,
        )
        return report

    def _organize_one(
        self,
        row: Message,
        *,
        dry_run: bool,
        force: bool,
        retriage_unknown: bool,
        retriage_all: bool,
    ) -> OrganizationItem:
        local_id, subject = row.id, row.subject
        triage = row.triage_value()
        missing_category = False
        try:
            destination = category_destination(self.account.agent, triage)
        except KeyError as exc:
            missing_category = True
            if not (retriage_unknown or retriage_all):
                return OrganizationItem(
                    local_id, subject, OrganizationStatus.FAILED, error=exc.args[0]
                )
            destination = None

        retriaged_as = None
        if retriage_all or (retriage_unknown and missing_category):
            try:
                message = self.provider.get_message(row.provider_uid, row.provider_mailbox)
                thread = self.provider.get_thread(row.provider_uid, row.provider_mailbox)
                triage = self.triager.triage(message, thread)
                destination = category_destination(self.account.agent, triage)
                retriaged_as = triage.category or "uncategorized"
                if not dry_run:
                    Triage.save_for(row, triage)
                    if not triage.requires_reply:
                        Draft.delete().where(
                            (Draft.message == local_id) & (Draft.status == "generated")
                        ).execute()
            except Exception as exc:  # noqa: BLE001 - isolate failures within the batch
                return OrganizationItem(
                    local_id,
                    subject,
                    OrganizationStatus.FAILED,
                    error=f"retriage failed: {exc}",
                )

        if destination is None:
            previous = row.current_category_sync()
            if not (retriage_unknown or retriage_all) or previous is None:
                return OrganizationItem(
                    local_id,
                    subject,
                    OrganizationStatus.UNCATEGORIZED,
                    retriaged_as=retriaged_as,
                )
            if dry_run:
                return OrganizationItem(
                    local_id,
                    subject,
                    OrganizationStatus.PREVIEW,
                    retriaged_as=retriaged_as,
                )
            try:
                self.provider.sync_category(row.provider_uid, None, row.provider_mailbox, previous)
                CategorySync.replace_active(local_id, None)
            except Exception as exc:  # noqa: BLE001 - isolate failures within the batch
                return OrganizationItem(
                    local_id,
                    subject,
                    OrganizationStatus.FAILED,
                    retriaged_as=retriaged_as,
                    error=str(exc),
                )
            return OrganizationItem(
                local_id,
                subject,
                OrganizationStatus.SYNCED,
                retriaged_as=retriaged_as,
            )

        sync_key = self.provider.category_sync_key(destination)
        if not force and CategorySync.is_active(local_id, sync_key):
            return OrganizationItem(
                local_id,
                subject,
                OrganizationStatus.SKIPPED,
                destination=destination,
                retriaged_as=retriaged_as,
            )
        if dry_run:
            return OrganizationItem(
                local_id,
                subject,
                OrganizationStatus.PREVIEW,
                destination=destination,
                retriaged_as=retriaged_as,
            )
        try:
            previous = row.current_category_sync()
            sync = self.provider.sync_category(
                row.provider_uid, destination, row.provider_mailbox, previous
            )
            if sync is not None and sync.source_moved:
                row.provider_uid = sync.provider_id
                row.provider_mailbox = sync.mailbox
                row.save()
            CategorySync.replace_active(local_id, sync_key, sync)
        except Exception as exc:  # noqa: BLE001 - isolate failures within the batch
            return OrganizationItem(
                local_id,
                subject,
                OrganizationStatus.FAILED,
                destination=destination,
                retriaged_as=retriaged_as,
                error=str(exc),
            )
        return OrganizationItem(
            local_id,
            subject,
            OrganizationStatus.SYNCED,
            destination=destination,
            retriaged_as=retriaged_as,
        )
