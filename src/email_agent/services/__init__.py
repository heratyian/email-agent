"""Application workflows used by the CLI and other front ends."""

from email_agent.services.accounts import AccountService
from email_agent.services.drafts import DraftService
from email_agent.services.inbox import PRIORITY_GROUP_ORDER, InboxService, PriorityGroup
from email_agent.services.messages import MessageService
from email_agent.services.organization import OrganizationService, OrganizationStatus
from email_agent.services.processing import ProcessingFailure, ProcessingService

__all__ = [
    "PRIORITY_GROUP_ORDER",
    "AccountService",
    "DraftService",
    "InboxService",
    "MessageService",
    "OrganizationService",
    "OrganizationStatus",
    "PriorityGroup",
    "ProcessingFailure",
    "ProcessingService",
]
