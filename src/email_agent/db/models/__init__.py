"""Peewee persistence models and their table creation order."""

from email_agent.db.models.category_sync import CategorySync
from email_agent.db.models.draft import Draft
from email_agent.db.models.message import Message
from email_agent.db.models.triage import Triage

MODELS = (Message, Triage, Draft, CategorySync)

__all__ = ["MODELS", "CategorySync", "Draft", "Message", "Triage"]
