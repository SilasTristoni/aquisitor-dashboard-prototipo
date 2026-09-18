import io
import json
import logging
import os
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.observability import StructuredFormatter, configure_logging, sanitize
from app.models.entities import (
    Device,
    ElectricalSample,
    MeasurementSession,
    SessionDevice,
    SystemEvent,
    TemperatureChannelValue,
    TemperatureSample,
    User,
)


def seed_source_session(mode):
    start = datetime(2026, 9, 18, 14, 3, 55, tzinfo=UTC)
    with SessionLocal() as db:
        user = db.scalar(select(User))
        electrical = db.scalar(select(Device).where(Device.protocol == "gpm8213_serial"))
        thermal = db.scalar(select(Device).where(Device.protocol == "at4532_serial"))
        session = MeasurementSession(
            device_id=electrical.id if mode != "thermal" else thermal.id,
            user_id=user.id,
            name="Synthetic single-source regression",
            status="finished",
            started_at=start,
            ended_at=start + timedelta(seconds=141),
        )
        db.add(session)
        db.flush()
        for role, device in (("electrical", electrical), ("temperature", thermal)):
            if (
                role == "electrical"
                and mode == "thermal"
                or role == "temperature"
                and mode == "electrical"
            ):
                continue
            db.add(SessionDevice(session_id=session.id, device_id=device.id, role=role))
            for index in range(136):
                timestamp = start + timedelta(seconds=index + 2)
                if role == "electrical":
                    db.add(
                        ElectricalSample(
                            session_id=session.id,
                            device_id=device.id,
                            received_timestamp=timestamp,
                            active_power_w=778.14 if 25 <= index < 45 else 0.48,
                            voltage_v=220.3,
                            current_a=0.17,
                            quality="good",
                        )
                    )
                else:
                    sample = TemperatureSample(
                        session_id=session.id,
                        device_id=device.id,
                        received_timestamp=timestamp,
                        quality="good",
                    )
                    sample.channels = [
                        TemperatureChannelValue(
                            channel=1, temperature_c=25 + index / 10, original_value=25 + index / 10
                        )
                    ]
                    db.add(sample)
        db.commit()
        return {
            "start": start.isoformat(),
            "end": session.ended_at.replace(tzinfo=UTC).isoformat(),
            "session_ids": [session.id],
            "title": "Teste de fontes",
            "use_device_timestamp": False,
        }


@pytest.mark.parametrize("mode", ["electrical", "thermal", "combined"])
def test_executive_exports_all_source_combinations(client, auth_headers, mode):
    payload = seed_source_session(mode)
    preview = client.post("/api/v1/reports/period/preview", headers=auth_headers, json=payload)
    assert preview.status_code == 200
    stats = preview.json()["statistics"]
    assert stats["general"]["electrical_sample_count"] == (0 if mode == "thermal" else 136)
    assert stats["general"]["temperature_sample_count"] == (0 if mode == "electrical" else 136)
    if mode == "electrical":
        assert stats["temperature"]["max"] is None
        assert stats["temperature"]["critical_channel"] is None
        assert stats["temperature"]["maximum_delta_t"] is None
    for kind in ("executive.pdf", "executive.png", "pdf"):
        response = client.post(f"/api/v1/reports/period/{kind}", headers=auth_headers, json=payload)
        assert response.status_code == 200, response.text[:300]
        if kind.endswith("pdf"):
            assert response.content.startswith(b"%PDF")
        else:
            image = Image.open(io.BytesIO(response.content))
            assert image.size == (1200, 650)


def test_failed_export_is_traceable_in_logs_events_and_support_zip(
    client, auth_headers, monkeypatch
):
    from app.api import routes

    payload = seed_source_session("electrical")
    monkeypatch.setenv("THERMOPOWER_PRIVATE_SECRET", "private-value-do-not-export")

    def fail(*args):
        raise RuntimeError(
            "password=hidden-password Bearer hidden-token private-value-do-not-export"
        )

    monkeypatch.setattr(routes, "render_executive_summary", fail)
    response = client.post(
        "/api/v1/reports/period/executive.pdf", headers=auth_headers, json=payload
    )
    assert response.status_code == 500
    code = response.json()["error"]["correlation_id"]
    assert code.startswith("TP-EXP-")
    assert response.headers["X-Correlation-ID"] == code
    assert "RuntimeError" not in response.text and "hidden-password" not in response.text
    events = client.get(
        f"/api/v1/events?error_code={code}&session_id={payload['session_ids'][0]}",
        headers=auth_headers,
    ).json()
    assert events["total"] == 1
    detail = events["items"][0]["details"]
    assert detail["user_id"] and detail["started_at"] and detail["completed_at"]
    assert detail["status"] == "failed" and detail["exception_type"] == "RuntimeError"
    package = client.get(f"/api/v1/support/package?correlation_id={code}", headers=auth_headers)
    assert package.status_code == 200
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert archive.testzip() is None
        assert "session/session-summary.json" in archive.namelist()
        errors = archive.read("logs/errors.log").decode()
        assert code in errors and "RuntimeError" in errors and "Traceback" in errors
        for name in archive.namelist():
            content = archive.read(name).decode()
            for secret in (
                "hidden-password",
                "hidden-token",
                "private-value-do-not-export",
                auth_headers["Authorization"].split()[1],
            ):
                assert secret not in content
    with SessionLocal() as db:
        assert db.get(MeasurementSession, payload["session_ids"][0]).status == "finished"


def test_support_without_active_session_and_authentication(client, auth_headers):
    assert client.get("/api/v1/support/package").status_code == 401
    result = client.get("/api/v1/support/package", headers=auth_headers)
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert json.loads(archive.read("session/session-summary.json")) is None
        assert "hardware/devices.json" in archive.namelist()


def test_rotation_and_sanitization(tmp_path, monkeypatch):
    monkeypatch.setenv("THERMOPOWER_LOG_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("THERMOPOWER_JWT_SECRET", "raw-configured-secret")
    root = logging.getLogger()
    original = list(root.handlers)
    try:
        configure_logging(tmp_path, max_bytes=1500, backup_count=2)
        for index in range(20):
            logging.getLogger("app.reports").error(
                "Failure %s password=bad-pass raw-configured-secret", index
            )
        assert (tmp_path / "errors.log.1").is_file()
        assert len(list(tmp_path.glob("errors.log*"))) <= 3
        for path in tmp_path.glob("*.log*"):
            text = path.read_text(encoding="utf-8")
            assert "bad-pass" not in text and "raw-configured-secret" not in text
            record = json.loads(text.splitlines()[-1])
            assert record["timestamp"] and record["version"] and record["correlation_id"]
    finally:
        for handler in list(root.handlers):
            if handler not in original:
                root.removeHandler(handler)
                handler.close()
    assert sanitize({"nested": {"access_token": "abc", "password": "xyz"}}) == {
        "nested": {"access_token": "[redacted]", "password": "[redacted]"}
    }
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 1, "GET /ws?token=websocket-secret", (), None
    )
    assert "websocket-secret" not in formatter.format(record)


def test_pdf_backend_and_manual_are_required_in_windows_package():
    root = Path(__file__).resolve().parents[2]
    spec = (root / "thermopower.spec").read_text(encoding="utf-8")
    assert '"matplotlib.backends.backend_pdf"' in spec
    assert '"user-guide.pdf"' in spec
    script = (root / "scripts/build-windows-engineering.ps1").read_text(encoding="utf-8")
    assert '"Manual do Usuário - ThermoPower Monitor.pdf"' in script


def test_launcher_errors_remain_logged_after_alembic_configuration(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import logging
import sys
from logging.config import fileConfig
from pathlib import Path
from app.core.observability import configure_logging

directory = Path(sys.argv[1])
configure_logging(directory)
launcher = logging.getLogger('__main__')
fileConfig('alembic.ini')
configure_logging(directory)
try:
    raise RuntimeError('startup regression sentinel')
except RuntimeError:
    launcher.exception('Launcher failed after migrations')
logging.shutdown()
""",
            str(tmp_path),
        ],
        cwd=backend,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    errors = (tmp_path / "errors.log").read_text(encoding="utf-8")
    assert "startup regression sentinel" in errors
    record = json.loads(errors.splitlines()[-1])
    assert record["exception_type"] == "RuntimeError"
    assert record["error_code"] == record["correlation_id"]


def test_launcher_failure_exits_without_an_unhandled_operator_traceback(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    environment = {k: v for k, v in os.environ.items() if not k.startswith("THERMOPOWER_")}
    environment.update(
        {
            "PYTHONPATH": str(backend),
            "THERMOPOWER_APP_DATA_DIR": str(tmp_path),
            "THERMOPOWER_DATABASE_URL": f"sqlite:///{(tmp_path / 'missing/data.db').as_posix()}",
            "THERMOPOWER_MUTEX_NAME": f"ThermoPowerLauncherRegression-{tmp_path.name}",
            "THERMOPOWER_NO_BROWSER": "1",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy, sys; sys.frozen = True; "
            "sys._MEIPASS = sys.argv[1]; runpy.run_path(sys.argv[2], run_name='__main__')",
            str(backend),
            str(backend / "app/windows_launcher.py"),
        ],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 1
    errors = (tmp_path / "logs/errors.log").read_text(encoding="utf-8")
    record = json.loads(errors.splitlines()[-1])
    assert record["exception_type"] == "OperationalError"
    assert record["error_code"] and record["traceback"]
    # A bare traceback would also trigger PyInstaller's unhandled-error dialog.
    assert "Traceback (most recent call last):" not in result.stderr.splitlines()


def test_existing_acquisition_event_gets_searchable_code_without_serial_access(
    client, auth_headers
):
    with SessionLocal() as db:
        device = db.scalar(select(Device))
        event = SystemEvent(
            device_id=device.id,
            category="read_error",
            level="error",
            message="Aquisição interrompida",
            details={"error": "RuntimeError", "password": "do-not-log"},
        )
        db.add(event)
        db.commit()
        code, device_id = event.details["correlation_id"], device.id
    response = client.get(
        f"/api/v1/events?error_code={code}&device_id={device_id}&category=ACQUISITION",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert "do-not-log" not in response.text
