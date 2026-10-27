import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from alembic.config import Config
from app.core.migration_backup import prepare_migration_backup


def configuration():
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    return config


def database(tmp_path, revision="0012_publication_outbox"):
    path = tmp_path / "history.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE alembic_version(version_num TEXT)")
    connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
    connection.execute("CREATE TABLE samples(value REAL)")
    connection.executemany("INSERT INTO samples VALUES (?)", [(0,), (123.456,), (None,)])
    connection.commit()
    return path, connection


def test_backup_contains_committed_wal_and_preserves_source(tmp_path):
    path, connection = database(tmp_path)
    try:
        backup = prepare_migration_backup(configuration(), f"sqlite:///{path.as_posix()}")
        assert backup and backup.exists()
        with sqlite3.connect(backup) as restored:
            assert restored.execute("SELECT value FROM samples").fetchall() == [
                (0.0,),
                (123.456,),
                (None,),
            ]
            assert (
                restored.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                == "0012_publication_outbox"
            )
        metadata = json.loads(backup.with_suffix(".json").read_text())
        assert metadata["integrity"] == "ok"
        assert len(metadata["sha256"]) == 64
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "0012_publication_outbox"
        )
    finally:
        connection.close()


def test_low_disk_blocks_before_backup_or_migration(tmp_path):
    path, connection = database(tmp_path)
    connection.close()
    with patch("app.core.migration_backup.shutil.disk_usage") as usage:
        usage.return_value.free = 1
        with pytest.raises(RuntimeError, match="Espaço insuficiente"):
            prepare_migration_backup(configuration(), f"sqlite:///{path.as_posix()}")
    assert not (tmp_path / "migration-backups").exists()


def test_current_database_needs_no_migration_backup(tmp_path):
    path, connection = database(tmp_path, "0014_source_availability")
    connection.close()
    assert prepare_migration_backup(configuration(), f"sqlite:///{path.as_posix()}") is None
    assert not (tmp_path / "migration-backups").exists()


def test_unknown_revision_is_not_overwritten(tmp_path):
    path, connection = database(tmp_path, "future_revision")
    connection.close()
    original = path.read_bytes()
    with pytest.raises(Exception, match="future_revision"):
        prepare_migration_backup(configuration(), f"sqlite:///{path.as_posix()}")
    assert path.read_bytes() == original


def test_missing_database_is_not_created_by_backup(tmp_path):
    path = tmp_path / "new.sqlite"
    assert prepare_migration_backup(configuration(), f"sqlite:///{path.as_posix()}") is None
    assert not path.exists()
