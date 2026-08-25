"""Peewee persistence models and their table creation order."""

from email_agent.db.models.category_sync import CategorySync
from email_agent.db.models.classification import Classification
from email_agent.db.models.draft import Draft
from email_agent.db.models.message import Message

MODELS = (Message, Classification, Draft, CategorySync)

__all__ = ["MODELS", "CategorySync", "Classification", "Draft", "Message"]
