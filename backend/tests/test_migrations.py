import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.core.database import Base

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_upgrade_accepts_schema_precreated_by_sqlalchemy(tmp_path):
    """Regression: old startup created new tables before Alembic recorded revision 0002."""
    database_path = tmp_path / "precreated.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('0001_initial')")
        )
        connection.execute(
            text(
                "INSERT INTO session_devices "
                "(id, session_id, device_id, role, created_at) "
                "VALUES (1, 999, 999, 'combined', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO system_events "
                "(id, session_id, timestamp, level, category, message, details) "
                "VALUES (1, 999, CURRENT_TIMESTAMP, 'info', 'test', 'orphan', '{}')"
            )
        )

    environment = os.environ.copy()
    environment["THERMOPOWER_DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0004_cleanup_orphan_session_data"
        )
        assert "session_devices" in inspect(connection).get_table_names()
        assert connection.scalar(text("SELECT count(*) FROM session_devices")) == 0
        assert connection.scalar(
            text("SELECT session_id FROM system_events WHERE id = 1")
        ) is None
