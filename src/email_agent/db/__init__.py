"""Peewee connection and persistence models."""

from email_agent.db.connection import database, initialize_database
from email_agent.db.models import CategorySync, Classification, Draft, Message

__all__ = [
    "CategorySync",
    "Classification",
    "Draft",
    "Message",
    "database",
    "initialize_database",
]
