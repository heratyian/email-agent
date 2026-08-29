"""Peewee connection and persistence models."""

from email_agent.persistence.connection import database, initialize_database
from email_agent.persistence.models import CategorySync, Draft, DraftStatus, Message, Triage

__all__ = [
    "CategorySync",
    "Draft",
    "DraftStatus",
    "Message",
    "Triage",
    "database",
    "initialize_database",
]
