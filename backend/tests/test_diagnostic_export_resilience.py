import asyncio
import io
import json
import os
import sqlite3
import sys
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import support_collection as diagnostic_export
from app.services.acquisition import acquisition_service
from app.services.diagnostic_snapshot import runtime_snapshot


@pytest.fixture(autouse=True)
def isolated_evidence_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("THERMOPOWER_LOG_DIRECTORY", str(tmp_path / "logs"))


@pytest.mark.parametrize("endpoint", ["physical-package", "package"])
def test_export_does_not_wait_for_runtime_status(client, auth_headers, monkeypatch, endpoint):
    async def blocked(_device_id):
        await asyncio.Event().wait()

    status = AsyncMock(side_effect=blocked)
    monkeypatch.setattr(acquisition_service, "status", status)
    response = client.get(f"/api/v1/support/{endpoint}", headers=auth_headers)
    assert response.status_code == 200
    with read_archive(response.content) as archive:
        assert "serial-events.jsonl" in archive.namelist()
    status.assert_not_called()


def read_archive(content):
    archive = zipfile.ZipFile(io.BytesIO(content))
    assert archive.testzip() is None
    return archive


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["deadline", "disconnect", "cancel"])
async def test_hung_worker_is_killed_reaped_and_gate_released(monkeypatch, reason, tmp_path):
    from fastapi import HTTPException

    processes = []
    original = diagnostic_export.subprocess.Popen

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        processes.append(child)
        return child

    monkeypatch.setattr(diagnostic_export.subprocess, "Popen", spawn)
    monkeypatch.setattr(
        diagnostic_export,
        "worker_command",
        lambda *args: [sys.executable, "-c", "import time; time.sleep(300)"],
    )
    monkeypatch.setattr(diagnostic_export, "EXPORT_TIMEOUT", 0.15)
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=reason == "disconnect"))
    task = asyncio.create_task(diagnostic_export.export_diagnostic(request, {}, "sqlite://"))
    await asyncio.sleep(0.03)
    if reason == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(HTTPException) as failure:
            await task
        assert failure.value.status_code == (504 if reason == "deadline" else 499)
    assert processes and all(child.poll() is not None for child in processes)
    assert not diagnostic_export._active


@pytest.mark.asyncio
async def test_concurrent_exports_are_rejected_without_queuing(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(
        diagnostic_export,
        "worker_command",
        lambda *args: [sys.executable, "-c", "import time; time.sleep(300)"],
    )
    first = asyncio.create_task(diagnostic_export.export_diagnostic(None, {}, "sqlite://"))
    await asyncio.sleep(0.03)
    try:
        with pytest.raises(HTTPException) as failure:
            await diagnostic_export.export_diagnostic(None, {}, "sqlite://")
        assert failure.value.status_code == 429
    finally:
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
    assert not diagnostic_export._active


@pytest.mark.asyncio
async def test_busy_database_yields_explicit_partial_zip_and_does_not_block_loop(tmp_path):
    path = tmp_path / "busy.db"
    lock = sqlite3.connect(path)
    lock.execute("CREATE TABLE marker (id INTEGER)")
    lock.commit()
    lock.execute("BEGIN EXCLUSIVE")
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    heartbeat_task = asyncio.create_task(heartbeat())
    started = time.monotonic()
    try:
        response = await diagnostic_export.export_diagnostic(
            None, {}, f"sqlite:///{path.as_posix()}"
        )
        try:
            with read_archive(Path(response.path).read_bytes()) as archive:
                evidence = json.loads(archive.read("evidence-status.json"))
                assert evidence["sections"]["database"].startswith("unavailable")
                assert "logs/errors.log" in archive.namelist()
        finally:
            response.cleanup()
        assert ticks >= 5
        assert time.monotonic() - started < 5
    finally:
        heartbeat_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await heartbeat_task
        lock.rollback()
        lock.close()


def test_large_and_malformed_logs_are_bounded_preserved_and_marked(tmp_path, monkeypatch):
    import hashlib

    from app.services.physical_diagnostic import UnavailableDatabase, physical_diagnostic_zip

    monkeypatch.setenv("THERMOPOWER_LOG_DIRECTORY", str(tmp_path))
    directory = tmp_path / "physical"
    directory.mkdir()
    log = directory / "serial-events.jsonl"
    row = json.dumps({"event": "AT_TX", "password": "never-export", "padding": "x" * 1024})
    original = ((row + "\n") * 20000).encode()
    log.write_bytes(original)
    (directory / "invalid.jsonl").write_bytes(b"\n" * 100000)
    before = hashlib.sha256(original).hexdigest()
    content = physical_diagnostic_zip(UnavailableDatabase(), [], {}, {}, {})
    assert len(content) < 1024 * 1024
    with read_archive(content) as archive:
        evidence = json.loads(archive.read("evidence-status.json"))
        assert any(r["reason"] == "size_limit" for r in evidence["read_errors"])
        assert any(r["reason"] == "record_limit" for r in evidence["read_errors"])
        assert len(archive.read("serial-events.jsonl")) < 300000
        assert b"never-export" not in archive.read("serial-events.jsonl")
    assert hashlib.sha256(log.read_bytes()).hexdigest() == before


@pytest.mark.asyncio
async def test_failure_recovery_snapshot_preserves_pending_persistence(client):
    from test_pending_persistence import make_pending_service, sample_counts

    from app.core.database import engine
    from app.services.pending_persistence import flush_pending_samples

    service, ids, _ = make_pending_service()
    service.runtimes[ids[0]].adapter = SimpleNamespace(
        _reconnecting=True,
        transactions=[{"request_hex": "0d0a", "error": "timeout"}],
        transport=SimpleNamespace(_io_lock=asyncio.Lock(), connection=None),
    )
    service.runtimes[ids[1]].adapter = SimpleNamespace(_reading=True)
    await service.runtimes[ids[0]].adapter.transport._io_lock.acquire()
    snapshot = runtime_snapshot(service)
    assert snapshot["states"][0]["serial_lock_held"]
    assert snapshot["states"][0]["adapter_state"]["_reconnecting"]
    assert snapshot["states"][1]["adapter_state"]["_reading"]
    response, _ = await asyncio.gather(
        diagnostic_export.export_diagnostic(None, snapshot, str(engine.url)),
        flush_pending_samples(service),
    )
    try:
        assert sample_counts() == (2, 1)
        assert not any(r.buffer for r in service.runtimes.values())
        with read_archive(Path(response.path).read_bytes()) as archive:
            states = json.loads(archive.read("acquisition-state.json"))
            assert states[0]["buffered_measurements"] == 2  # immutable pre-flush snapshot
            assert states[0]["connection_verified"] is False
    finally:
        response.cleanup()


def test_offline_collection_never_imports_drivers_or_changes_sources(tmp_path):
    import subprocess

    data = tmp_path / "data"
    logs = tmp_path / "logs"
    data.mkdir()
    logs.mkdir()
    database = data / "thermopower.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE marker (value TEXT)")
    source = database.read_bytes()
    output = tmp_path / "offline.zip"
    job = {"snapshot": {"unavailable": "offline"}, "log_directory": str(logs)}
    code = (
        "import sys,json; from app.engineering.local_diagnostic import collect; "
        "collect(json.loads(sys.argv[1]),sys.argv[2]); "
        "assert 'app.main' not in sys.modules; "
        "assert not any(k.startswith('app.adapters') for k in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, json.dumps(job), str(output)],
        env=dict(os.environ, THERMOPOWER_DATABASE_URL=f"sqlite:///{database.as_posix()}"),
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert database.read_bytes() == source
    assert not list(logs.iterdir())
    with read_archive(output.read_bytes()) as archive:
        assert b"offline" in archive.read("runtime-state.json")


@pytest.mark.asyncio
async def test_failed_download_releases_file_and_concurrency_gate(tmp_path):
    response = await diagnostic_export.export_diagnostic(
        None, {}, f"sqlite:///{tmp_path / 'missing.db'}"
    )
    path = Path(response.path)

    async def broken_send(message):
        raise OSError("client disconnected")

    with pytest.raises(OSError):
        await response(
            {"type": "http", "method": "GET", "headers": [], "extensions": {}},
            AsyncMock(),
            broken_send,
        )
    assert not path.exists()
    assert not diagnostic_export._active


@pytest.mark.asyncio
async def test_continuous_gpm_snapshot_does_not_issue_commands_or_stop_reading():
    from test_physical_regression_fixtures import (
        GPM_IDENTITY_V105,
        GPM_NUMBER_SCPI_SHORT,
        GPM_PHYSICAL_HEADERS,
        GPM_PHYSICAL_VALUES,
        PhysicalGpmTransport,
    )

    from app.adapters.specific import Gpm8213UsbSerialAdapter
    from app.services.acquisition import AcquisitionService, DeviceRuntime

    wire = PhysicalGpmTransport(
        [
            GPM_IDENTITY_V105,
            GPM_NUMBER_SCPI_SHORT,
            GPM_PHYSICAL_HEADERS,
            *([GPM_PHYSICAL_VALUES] * 3),
        ]
    )
    adapter = Gpm8213UsbSerialAdapter("COM_TEST", None, transport=wire)
    service = AcquisitionService()
    runtime = DeviceRuntime(adapter, protocol="gpm8213_serial")
    service.runtimes[1] = runtime
    await adapter.connect()
    readings = adapter.start_reading()
    try:
        for _ in range(3):
            reading = await anext(readings)
            runtime.latest = reading
            requests = list(wire.requests)
            snap = runtime_snapshot(service)
            assert snap["states"][0]["adapter_state"]["_reading"]
            assert wire.requests == requests
            assert reading.power_w == 17.688
        assert wire.requests.count(b":NUMERIC:NORMAL:VALUE?\r\n") == 3
        assert all(request.endswith(b"\r\n") for request in wire.requests)
        assert adapter.expected_interval_seconds == 1.0
    finally:
        await readings.aclose()
        await adapter.disconnect()


@pytest.mark.parametrize("flag", ["--diagnostic-worker", "--export-local-diagnostic"])
def test_launcher_diagnostic_bypasses_mutex_and_acquisition(monkeypatch, flag):
    from app import windows_launcher
    from app.engineering import local_diagnostic

    calls = []
    monkeypatch.setattr(sys, "argv", ["ThermoPowerMonitor.exe", flag, "argument"])
    monkeypatch.setattr(local_diagnostic, "entrypoint", calls.append)
    monkeypatch.setattr(
        windows_launcher,
        "_acquire_single_instance",
        lambda *args: pytest.fail("Diagnostic must not start app lifecycle"),
    )
    windows_launcher.main()
    assert calls == [["argument"] if flag == "--export-local-diagnostic" else [flag, "argument"]]


def test_offline_cli_preserves_existing_output(tmp_path):
    from app.engineering.local_diagnostic import entrypoint

    output = tmp_path / "evidence.zip"
    output.write_bytes(b"previous evidence")
    with pytest.raises(SystemExit) as error:
        entrypoint(["--app-data", str(tmp_path), "--output", str(output)])
    assert error.value.code == 2
    assert output.read_bytes() == b"previous evidence"
