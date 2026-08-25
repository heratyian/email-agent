from datetime import UTC, datetime

from peewee import Model

from email_agent.db.connection import database


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class BaseModel(Model):
    """Bind all application models to the shared Peewee database."""

    class Meta:
        database = database
        legacy_table_names = False
