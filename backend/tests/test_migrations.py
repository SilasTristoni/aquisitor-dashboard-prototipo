import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import Device

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
            "0008_session_metadata"
        )
        assert "metadata" in {
            column["name"] for column in inspect(connection).get_columns("measurement_sessions")
        }
        assert "session_devices" in inspect(connection).get_table_names()
        assert connection.scalar(text("SELECT count(*) FROM session_devices")) == 0
        assert connection.scalar(text("SELECT session_id FROM system_events WHERE id = 1")) is None


def test_upgrade_neutralizes_duplicate_at4532_port_without_deleting_history(tmp_path):
    database_path = tmp_path / "duplicate-at4532.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
        connection.execute(
            text(
                "INSERT INTO alembic_version (version_num) "
                "VALUES ('0006_documented_physical_protocols')"
            )
        )
    with Session(engine) as db:
        old = Device(
            name="AT4532 antigo",
            manufacturer="Applent",
            model="AT4532",
            connection_type="serial",
            port="COM5",
            baud_rate=115200,
            protocol="at4532_serial",
            active=True,
            metadata_json={},
        )
        canonical = Device(
            name="Applent AT4532 · LAB",
            manufacturer="Applent",
            model="AT4532",
            connection_type="serial",
            port="COM5",
            baud_rate=19200,
            protocol="at4532_serial",
            active=True,
            metadata_json={"usb": {"manual_confirmed": True, "confirmed_port": "COM5"}},
        )
        db.add_all([old, canonical])
        db.commit()
        old_id = old.id
        canonical_id = canonical.id

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

    with Session(engine) as db:
        old = db.get(Device, old_id)
        canonical = db.get(Device, canonical_id)
        assert old is not None and canonical is not None
        assert old.active is False
        assert old.port == "COM5"
        assert old.baud_rate == 115200
        assert old.metadata_json["configuration_status"] == "archived_duplicate"
        assert old.metadata_json["superseded_by_device_id"] == canonical_id
        assert canonical.active is True
        assert canonical.metadata_json["configuration_status"] == "canonical"
        assert canonical.metadata_json["neutralized_duplicate_ids"] == [old_id]
