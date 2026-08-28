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

    _migrate_triage_schema()

    from email_agent.persistence.models import MODELS

    database.create_tables(MODELS, safe=True)


def _migrate_triage_schema() -> None:
    """Normalize databases created before triage terminology and sync state."""
    tables = {
        row[0]
        for row in database.execute_sql(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if "classifications" in tables and "triages" not in tables:
        database.execute_sql('ALTER TABLE "classifications" RENAME TO "triages"')

    if "triages" not in tables and "classifications" not in tables:
        return
    columns = {row[1] for row in database.execute_sql('PRAGMA table_info("triages")').fetchall()}
    if "category_sync_pending" not in columns:
        database.execute_sql(
            'ALTER TABLE "triages" ADD COLUMN "category_sync_pending" INTEGER NOT NULL DEFAULT 0'
        )

    indexes = {row[1] for row in database.execute_sql('PRAGMA index_list("triages")').fetchall()}
    if "classifications_message_id" in indexes:
        database.execute_sql('DROP INDEX "classifications_message_id"')
    database.execute_sql(
        'CREATE UNIQUE INDEX IF NOT EXISTS "triages_message_id" ON "triages" ("message_id")'
    )
