"""Peewee connection and persistence models."""

from email_agent.db.connection import database, initialize_database
from email_agent.db.models import CategorySync, Draft, Message, Triage

__all__ = [
    "CategorySync",
    "Draft",
    "Message",
    "Triage",
    "database",
    "initialize_database",
]
