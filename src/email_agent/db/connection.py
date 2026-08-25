from pathlib import Path

from peewee import SqliteDatabase

database = SqliteDatabase(None, pragmas={"foreign_keys": 1, "journal_mode": "wal"})


def initialize_database(path: Path) -> None:
    """Connect the application models to one SQLite database."""
    if not database.is_closed():
        database.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    database.init(path)
    database.connect()

    from email_agent.db.models import MODELS

    database.create_tables(MODELS, safe=True)
