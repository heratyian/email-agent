"""Peewee persistence models and their table creation order."""

from email_agent.persistence.models.category_sync import CategorySync
from email_agent.persistence.models.draft import Draft
from email_agent.persistence.models.message import Message
from email_agent.persistence.models.triage import Triage

MODELS = (Message, Triage, Draft, CategorySync)

__all__ = ["MODELS", "CategorySync", "Draft", "Message", "Triage"]
