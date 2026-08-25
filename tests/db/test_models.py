import sqlite3
from pathlib import Path

from email_agent.db import initialize_database


def connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def schema_signature(connection):
    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {
        table: {
            "columns": [
                tuple(row) for row in connection.execute(f'PRAGMA table_info("{table}")')
            ],
            "indexes": [
                tuple(row) for row in connection.execute(f'PRAGMA index_list("{table}")')
            ],
            "foreign_keys": [
                tuple(row)
                for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
            ],
        }
        for table in tables
    }


def test_initialize_database_creates_tables_from_peewee_models(tmp_path):
    path = tmp_path / "email-agent.db"

    initialize_database(path)

    with connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    assert tables == {"category_syncs", "classifications", "drafts", "messages"}


def test_schema_snapshot_matches_peewee_models(tmp_path):
    model_path = tmp_path / "models.db"
    snapshot_path = tmp_path / "snapshot.db"
    initialize_database(model_path)
    schema_path = Path(__file__).parents[2] / "src/email_agent/db/schema.sql"

    with connect(snapshot_path) as snapshot:
        snapshot.executescript(schema_path.read_text())
    with connect(model_path) as models, connect(snapshot_path) as snapshot:
        assert schema_signature(snapshot) == schema_signature(models)
