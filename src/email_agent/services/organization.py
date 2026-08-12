from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from email_agent.models import EmailClassification
from email_agent.services.category_routing import category_destination

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
    reclassified_as: str | None = None
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
    """Reclassify and synchronize stored categories without CLI concerns."""

    def __init__(self, account_id: str, account, provider, database, agents=None):
        self.account_id = account_id
        self.account = account
        self.provider = provider
        self.database = database
        self.agents = agents

    def run(
        self,
        *,
        limit: int = 100,
        dry_run: bool = False,
        force: bool = False,
        reclassify_unknown: bool = False,
        reclassify_all: bool = False,
    ) -> OrganizationReport:
        """Organize recent local messages and isolate failures per message."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if reclassify_unknown and reclassify_all:
            raise ValueError("Use only one reclassification option")
        should_reclassify = reclassify_unknown or reclassify_all
        if should_reclassify and self.agents is None:
            raise ValueError("Reclassification requires configured model agents")

        report = OrganizationReport(dry_run=dry_run)
        rows = self.database.list_categorized_messages(self.account_id, limit)
        logger.info("Examining %d local messages for organization", len(rows))
        for row in rows:
            report.items.append(
                self._organize_one(
                    row,
                    dry_run=dry_run,
                    force=force,
                    reclassify_unknown=reclassify_unknown,
                    reclassify_all=reclassify_all,
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
        row: Any,
        *,
        dry_run: bool,
        force: bool,
        reclassify_unknown: bool,
        reclassify_all: bool,
    ) -> OrganizationItem:
        local_id, subject = row["id"], row["subject"]
        classification = EmailClassification.model_validate_json(row["classification"])
        missing_category = False
        try:
            destination = category_destination(self.account.agent, classification)
        except KeyError as exc:
            missing_category = True
            if not (reclassify_unknown or reclassify_all):
                return OrganizationItem(
                    local_id, subject, OrganizationStatus.FAILED, error=exc.args[0]
                )
            destination = None

        reclassified_as = None
        if reclassify_all or (reclassify_unknown and missing_category):
            try:
                message = self.provider.get_message(
                    row["provider_uid"], row["provider_mailbox"]
                )
                thread = self.provider.get_thread(
                    row["provider_uid"], row["provider_mailbox"]
                )
                classification = self.agents.classify(message, thread)
                destination = category_destination(self.account.agent, classification)
                reclassified_as = classification.category or "uncategorized"
                if not dry_run:
                    self.database.update_classification(local_id, classification)
                    if not classification.requires_reply:
                        self.database.delete_generated_drafts(local_id)
            except Exception as exc:  # noqa: BLE001 - isolate failures within the batch
                return OrganizationItem(
                    local_id,
                    subject,
                    OrganizationStatus.FAILED,
                    error=f"reclassification failed: {exc}",
                )

        if destination is None:
            previous = self.database.current_category_sync(local_id)
            if not (reclassify_unknown or reclassify_all) or previous is None:
                return OrganizationItem(
                    local_id,
                    subject,
                    OrganizationStatus.UNCATEGORIZED,
                    reclassified_as=reclassified_as,
                )
            if dry_run:
                return OrganizationItem(
                    local_id,
                    subject,
                    OrganizationStatus.PREVIEW,
                    reclassified_as=reclassified_as,
                )
            try:
                self.provider.sync_category(
                    row["provider_uid"], None, row["provider_mailbox"], previous
                )
                self.database.mark_category_synced(local_id, None)
            except Exception as exc:  # noqa: BLE001 - isolate failures within the batch
                return OrganizationItem(
                    local_id,
                    subject,
                    OrganizationStatus.FAILED,
                    reclassified_as=reclassified_as,
                    error=str(exc),
                )
            return OrganizationItem(
                local_id,
                subject,
                OrganizationStatus.SYNCED,
                reclassified_as=reclassified_as,
            )

        sync_key = self.provider.category_sync_key(destination)
        if not force and self.database.category_was_synced(local_id, sync_key):
            return OrganizationItem(
                local_id,
                subject,
                OrganizationStatus.SKIPPED,
                destination=destination,
                reclassified_as=reclassified_as,
            )
        if dry_run:
            return OrganizationItem(
                local_id,
                subject,
                OrganizationStatus.PREVIEW,
                destination=destination,
                reclassified_as=reclassified_as,
            )
        try:
            previous = self.database.current_category_sync(local_id)
            sync = self.provider.sync_category(
                row["provider_uid"], destination, row["provider_mailbox"], previous
            )
            if sync is not None and sync.source_moved:
                self.database.update_provider_location(local_id, sync.provider_id, sync.mailbox)
            self.database.mark_category_synced(local_id, sync_key, sync)
        except Exception as exc:  # noqa: BLE001 - isolate failures within the batch
            return OrganizationItem(
                local_id,
                subject,
                OrganizationStatus.FAILED,
                destination=destination,
                reclassified_as=reclassified_as,
                error=str(exc),
            )
        return OrganizationItem(
            local_id,
            subject,
            OrganizationStatus.SYNCED,
            destination=destination,
            reclassified_as=reclassified_as,
        )
