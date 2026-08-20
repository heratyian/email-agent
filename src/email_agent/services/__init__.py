"""Application workflows used by the CLI and other front ends."""

from email_agent.services.accounts import AccountService
from email_agent.services.classification import (
    ClassificationFailure,
    ClassificationService,
    ClassifiedEmail,
)
from email_agent.services.drafts import DraftService
from email_agent.services.inbox import InboxItem, InboxService
from email_agent.services.messages import MessageDetails, MessageService
from email_agent.services.organization import (
    OrganizationReport,
    OrganizationService,
    OrganizationStatus,
)

__all__ = [
    "AccountService",
    "ClassificationFailure",
    "ClassificationService",
    "ClassifiedEmail",
    "DraftService",
    "InboxItem",
    "InboxService",
    "MessageDetails",
    "MessageService",
    "OrganizationReport",
    "OrganizationService",
    "OrganizationStatus",
]
