"""Application workflows used by the CLI and other front ends."""

from email_agent.services.accounts import AccountService
from email_agent.services.drafts import DraftService
from email_agent.services.inbox import (
    PRIORITY_GROUP_ORDER,
    InboxService,
    PriorityGroup,
    TriagedEmail,
)
from email_agent.services.messages import MessageDetails, MessageService
from email_agent.services.organization import (
    OrganizationReport,
    OrganizationService,
    OrganizationStatus,
)
from email_agent.services.processing import ProcessedEmail, ProcessingFailure, ProcessingService

__all__ = [
    "PRIORITY_GROUP_ORDER",
    "AccountService",
    "DraftService",
    "InboxService",
    "MessageDetails",
    "MessageService",
    "OrganizationReport",
    "OrganizationService",
    "OrganizationStatus",
    "PriorityGroup",
    "ProcessedEmail",
    "ProcessingFailure",
    "ProcessingService",
    "TriagedEmail",
]
