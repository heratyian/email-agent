"""Domain-focused SQLite repositories."""

from email_agent.db.repositories.drafts import DraftRepository
from email_agent.db.repositories.messages import MessageRepository
from email_agent.db.repositories.organization import (
    OrganizationRepository,
    mark_category_synced,
)
from email_agent.db.repositories.processing_runs import ProcessingRunRepository

__all__ = [
    "DraftRepository",
    "MessageRepository",
    "OrganizationRepository",
    "ProcessingRunRepository",
    "mark_category_synced",
]
