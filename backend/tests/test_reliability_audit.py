import asyncio
import io
import os
import sqlite3
import subprocess
import sys
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from test_partial_combined_acquisition import PhysicalStreamFixtureAdapter
from test_period_reports import _seed_period_data

from app.core.database import SessionLocal, engine
from app.models import MeasurementSession
from app.schemas.contracts import PeriodReportRequest
from app.services.acquisition import AcquisitionService, DeviceRuntime
from app.services.pending_persistence import pending_sample_persistence
from app.services.period_reporting import (
    PeriodReportDataService,
    _integrate_energy_wh,
    _power_cycle_analysis,
)
from app.services.period_workbook import render_period_xlsx


def points(values):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        {"session_id": 1, "timestamp": start + timedelta(seconds=t), "active_power_w": p}
        for t, p in values
    ]


def test_workbook_preserves_untrusted_text_without_executable_formulas(client, auth_headers):
    start, end, ids = _seed_period_data()
    response = client.post(
        f"/api/v1/sessions/{ids[0]}/annotations",
        headers=auth_headers,
        json={"timestamp": start.isoformat(), "title": "=1+1", "description": "=2+2"},
    )
    assert response.status_code == 201
    request = PeriodReportRequest(start=start, end=end, session_ids=[ids[0]], title="=3+3")
    with SessionLocal() as db:
        content = render_period_xlsx(PeriodReportDataService(db).collect(request), request)
    book = load_workbook(io.BytesIO(content), data_only=False)
    dangerous = [c for sheet in book for row in sheet for c in row if c.data_type == "f"]
    assert not dangerous, [(c.coordinate, c.value) for c in dangerous]
    assert book["Resumo Executivo"]["A4"].value == "=3+3"


def test_cycle_duration_does_not_span_an_unobserved_gap():
    result = _power_cycle_analysis(points([(0, 100), (1, 100), (120, 0), (121, 0)]))
    assert result["on_seconds"] == 1
    assert result["mean_cycle_duration_seconds"] is None


def test_energy_does_not_bridge_explicit_unavailable_power():
    energy, _, _ = _integrate_energy_wh(points([(0, 100), (5, None), (10, 100)]), 60)
    assert energy == 0


def test_observed_energy_and_complete_cycle_are_preserved():
    data = points([(0, 100), (5, 100), (10, 0), (15, 0), (20, 100)])
    energy, excluded, _ = _integrate_energy_wh(data, 60)
    assert energy == pytest.approx(1000 / 3600)
    assert excluded == 0
    assert _power_cycle_analysis(data)["mean_cycle_duration_seconds"] == 10


def test_sqlite_online_backup_restores_exact_history(client, tmp_path):
    _seed_period_data()
    backup_path = tmp_path / "backup.db"
    restored_path = tmp_path / "restored.db"
    with engine.connect() as connection, sqlite3.connect(backup_path) as backup:
        source = connection.connection.driver_connection
        before = list(source.iterdump())
        source.backup(backup)
    with sqlite3.connect(backup_path) as backup, sqlite3.connect(restored_path) as restored:
        backup.backup(restored)
        assert restored.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert restored.execute("PRAGMA foreign_key_check").fetchall() == []
        assert list(restored.iterdump()) == before


@pytest.mark.asyncio
async def test_idle_source_persists_buffer_within_flush_deadline(client, monkeypatch):
    _, _, ids = _seed_period_data()
    with SessionLocal() as db:
        device_id = db.scalar(
            select(MeasurementSession.device_id).where(MeasurementSession.id == ids[0])
        )

    class SilentAfterOneReading:
        async def start_reading(self):
            yield PhysicalStreamFixtureAdapter("electrical")._reading()
            await asyncio.Event().wait()

    service = AcquisitionService()
    runtime = DeviceRuntime(adapter=SilentAfterOneReading(), session_id=ids[0])
    service.runtimes[device_id] = runtime
    monkeypatch.setattr(service, "_evaluate_alerts", AsyncMock())
    monkeypatch.setattr(service, "_publish_reading", AsyncMock())
    task = asyncio.create_task(service._read_loop(device_id, runtime))
    try:
        async with pending_sample_persistence(service):
            await asyncio.sleep(3)
            assert runtime.sample_count == 1
            assert runtime.persisted_count == 1
            assert not runtime.buffer, "sample still only in RAM after the persistence deadline"
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def test_windows_migrations_accept_percent_in_application_directory(tmp_path):
    directory = tmp_path / "Lab 100%"
    directory.mkdir()
    backend = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "THERMOPOWER_DATABASE_URL": f"sqlite:///{(directory / 'restored.db').as_posix()}",
    }
    result = subprocess.run(
        [sys.executable, "-c",
         "from pathlib import Path; from app.windows_launcher import _apply_migrations; "
         "_apply_migrations(Path.cwd())"],
        cwd=backend, env=environment, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
