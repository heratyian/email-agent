"""Application workflows used by the CLI and other front ends."""

from email_agent.services.accounts import AccountService
from email_agent.services.drafts import DraftService
from email_agent.services.inbox import InboxItem, InboxService
from email_agent.services.messages import MessageDetails, MessageService
from email_agent.services.organization import (
    OrganizationReport,
    OrganizationService,
    OrganizationStatus,
)
from email_agent.services.triage import (
    TriagedEmail,
    TriageFailure,
    TriageService,
)

__all__ = [
    "AccountService",
    "DraftService",
    "InboxItem",
    "InboxService",
    "MessageDetails",
    "MessageService",
    "OrganizationReport",
    "OrganizationService",
    "OrganizationStatus",
    "TriageFailure",
    "TriageService",
    "TriagedEmail",
]
