from __future__ import annotations

from dataclasses import dataclass

from email_agent.ai.models import EmailClassification


@dataclass(frozen=True)
class StoredMessage:
    """Message metadata required to retrieve one provider message."""

    id: int
    account_id: str
    provider_message_id: str
    provider_uid: str
    provider_mailbox: str
    subject: str
    classification: EmailClassification | None


@dataclass(frozen=True)
class StoredDraft:
    """One persisted draft suggestion exposed outside the database layer."""

    message_id: int
    account_id: str
    source_message_id: str
    recipient: str
    subject: str
    body: str
    status: str


@dataclass(frozen=True)
class OrganizationCandidate:
    """Stored message data required by category organization."""

    id: int
    provider_uid: str
    provider_mailbox: str
    subject: str
    classification: EmailClassification


def stored_message(row) -> StoredMessage:
    payload = row["classification"]
    return StoredMessage(
        id=row["id"],
        account_id=row["account_id"],
        provider_message_id=row["provider_message_id"],
        provider_uid=row["provider_uid"],
        provider_mailbox=row["provider_mailbox"],
        subject=row["subject"],
        classification=EmailClassification.model_validate_json(payload) if payload else None,
    )


def stored_draft(row) -> StoredDraft:
    return StoredDraft(
        message_id=row["message_id"],
        account_id=row["account_id"],
        source_message_id=row["source_message_id"],
        recipient=row["recipient"],
        subject=row["subject"],
        body=row["body"],
        status=row["status"],
    )


def organization_candidate(row) -> OrganizationCandidate:
    return OrganizationCandidate(
        id=row["id"],
        provider_uid=row["provider_uid"],
        provider_mailbox=row["provider_mailbox"],
        subject=row["subject"],
        classification=EmailClassification.model_validate_json(row["classification"]),
    )
