import sqlite3
from pathlib import Path

from email_agent.persistence import initialize_database


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
            "columns": [tuple(row) for row in connection.execute(f'PRAGMA table_info("{table}")')],
            "indexes": [tuple(row) for row in connection.execute(f'PRAGMA index_list("{table}")')],
            "foreign_keys": [
                tuple(row) for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
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
    assert tables == {"category_syncs", "triages", "drafts", "messages"}


def test_schema_snapshot_matches_peewee_models(tmp_path):
    model_path = tmp_path / "models.db"
    snapshot_path = tmp_path / "snapshot.db"
    initialize_database(model_path)
    schema_path = Path(__file__).parents[2] / "src/email_agent/persistence/schema.sql"

    with connect(snapshot_path) as snapshot:
        snapshot.executescript(schema_path.read_text())
    with connect(model_path) as models, connect(snapshot_path) as snapshot:
        assert schema_signature(snapshot) == schema_signature(models)


def test_initialize_database_migrates_pre_triage_schema(tmp_path):
    database_path = tmp_path / "legacy.db"
    schema_path = Path(__file__).parents[2] / "src/email_agent/persistence/schema.sql"
    legacy_schema = (
        schema_path.read_text()
        .replace("triaged_at", "classified_at")
        .replace("triages", "classifications")
        .replace('    "category_sync_pending" INTEGER NOT NULL,\n', "")
    )
    with connect(database_path) as connection:
        connection.executescript(legacy_schema)

    initialize_database(database_path)

    with connect(database_path) as connection:
        tables = schema_signature(connection)
    assert "triages" in tables
    assert "classifications" not in tables
    assert all(column[1] != "triaged_at" for column in tables["messages"]["columns"])
    assert any(index[1] == "triages_message_id" for index in tables["triages"]["indexes"])
    assert any(column[1] == "category_sync_pending" for column in tables["triages"]["columns"])
