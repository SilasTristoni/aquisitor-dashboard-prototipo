"""Persistence-only regressions: no serial transport or acquisition scheduling."""

import asyncio
import os
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.adapters.base import DeviceReading
from app.core.database import SessionLocal, engine
from app.models import (
    Device,
    ElectricalSample,
    MeasurementSession,
    SessionDevice,
    TemperatureSample,
    User,
)
from app.services.acquisition import AcquisitionService, DeviceRuntime
from app.services.pending_persistence import flush_pending_samples, pending_sample_persistence
from app.services.session_clock import utc


class NoDeviceAccess:
    def __getattr__(self, name):
        raise AssertionError(f"Persistence must not access device operation {name}")


def make_pending_service():
    origin = datetime(2026, 10, 11, 12, tzinfo=UTC)
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id))
        devices = [
            Device(name=f"Persistence {role}", protocol="simulator", connection_type="virtual")
            for role in ("electrical", "temperature")
        ]
        db.add_all(devices)
        db.flush()
        session = MeasurementSession(
            device_id=devices[0].id, user_id=user_id, name="Persistence audit",
            status="running", started_at=origin,
        )
        db.add(session)
        db.flush()
        ids = [device.id for device in devices]
        for device_id, role in zip(ids, ("electrical", "temperature"), strict=True):
            db.add(SessionDevice(session_id=session.id, device_id=device_id, role=role))
        db.commit()
        session_id = session.id
    service = AcquisitionService()
    for device_id, thermal in zip(ids, (False, True), strict=True):
        readings = [DeviceReading(
            timestamp=origin + timedelta(seconds=offset),
            device_timestamp=origin - timedelta(minutes=5) + timedelta(seconds=offset),
            received_timestamp=origin + timedelta(seconds=offset),
            raw_power=None if thermal else 100 + offset,
            raw_power_unit="W", power_w=None if thermal else 100 + offset,
            temperatures_c=[None, 23.75] if thermal else [],
        ) for offset in ([0] if thermal else [0, 120])]
        service.runtimes[device_id] = DeviceRuntime(
            adapter=NoDeviceAccess(), session_id=session_id, buffer=readings,
            sample_count=len(readings), last_error="existing acquisition error",
        )
    return service, ids, session_id


def sample_counts():
    with SessionLocal() as db:
        return tuple(db.scalar(select(func.count()).select_from(model)) for model in (
            ElectricalSample, TemperatureSample,
        ))


@pytest.mark.asyncio
@pytest.mark.parametrize("normal_first", [False, True])
async def test_pending_flush_preserves_samples_gaps_and_does_not_duplicate(client, normal_first):
    service, ids, session_id = make_pending_service()
    original = [r.model_copy(deep=True) for r in service.runtimes[ids[0]].buffer]
    # Exercise the same competing entry points used by batch and timer flushes.
    writers = [flush_pending_samples(service), service._flush(ids[0], service.runtimes[ids[0]])]
    await asyncio.gather(*(reversed(writers) if normal_first else writers))
    await flush_pending_samples(service)
    assert sample_counts() == (2, 1)
    with SessionLocal() as db:
        rows = list(db.scalars(select(ElectricalSample).order_by(ElectricalSample.sequence)))
        for row, reading in zip(rows, original, strict=True):
            assert utc(row.received_timestamp) == reading.received_timestamp
            assert utc(row.device_timestamp) == reading.device_timestamp
            assert row.active_power_w == reading.power_w
            assert row.session_id == session_id
        thermal = db.scalar(select(TemperatureSample))
        assert [channel.temperature_c for channel in thermal.channels] == [None, 23.75]
    for runtime, count in zip(service.runtimes.values(), (2, 1), strict=True):
        assert not runtime.buffer
        assert runtime.persisted_count == runtime.sample_count == count
        assert runtime.session_id == session_id
        assert runtime.paused is False
        assert runtime.last_error == "existing acquisition error"


@pytest.mark.asyncio
async def test_commit_failure_keeps_buffer_and_other_source_persists_then_retry(
    client, monkeypatch,
):
    service, ids, session_id = make_pending_service()
    first = service.runtimes[ids[0]]
    original_buffer = first.buffer[:]
    original_flush = first.last_flush
    fail_next = True

    def failing_session():
        nonlocal fail_next
        db = SessionLocal()
        if fail_next:
            fail_next = False

            def fail_commit():
                # Reach real SQL writes, then fail before commit. Context exit rolls back.
                db.flush()
                raise RuntimeError("simulated database failure")

            db.commit = fail_commit
        return db

    monkeypatch.setattr("app.services.acquisition.SessionLocal", failing_session)
    await flush_pending_samples(service)
    assert sample_counts() == (0, 1)
    assert first.buffer == original_buffer
    assert first.persisted_count == 0
    assert first.last_flush == original_flush
    assert first.session_id == session_id and not first.paused
    assert first.last_error == "existing acquisition error"
    await flush_pending_samples(service)
    assert sample_counts() == (2, 1)
    assert first.persisted_count == 2 and not first.buffer


@pytest.mark.asyncio
async def test_timer_retries_and_stops_with_its_lifecycle(client, monkeypatch):
    service, _, _ = make_pending_service()
    original_flush = service._flush
    attempts = 0

    async def fail_first(device_id, runtime):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary database failure")
        await original_flush(device_id, runtime)

    monkeypatch.setattr(service, "_flush", fail_first)
    monkeypatch.setattr("app.services.pending_persistence.FLUSH_INTERVAL_SECONDS", 0.01)
    async with pending_sample_persistence(service):
        async with asyncio.timeout(2):
            while sample_counts() != (2, 1):
                await asyncio.sleep(0.01)
    assert attempts == 3
    for _ in range(3):
        async with pending_sample_persistence(service):
            await asyncio.sleep(0)
    assert not any(task.get_name() == "pending-sample-persistence" for task in asyncio.all_tasks())


@pytest.mark.asyncio
async def test_persistence_does_not_change_paused_state_or_discard_unbound_buffer(client):
    service, ids, _ = make_pending_service()
    paused = service.runtimes[ids[0]]
    paused.paused = True
    unbound = service.runtimes[ids[1]]
    unbound.session_id = None
    buffer = unbound.buffer[:]
    await flush_pending_samples(service)
    assert sample_counts() == (2, 0)
    assert paused.paused and not paused.buffer
    assert unbound.buffer == buffer
    assert unbound.persisted_count == 0


@pytest.mark.asyncio
async def test_real_sqlite_lock_has_bounded_wait_and_retry(client, record_property):
    service, _, _ = make_pending_service()
    with sqlite3.connect(engine.url.database) as locker:
        locker.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        await flush_pending_samples(service)
        elapsed = time.monotonic() - started
        locker.rollback()
    record_property("sqlite_lock_wait_ms", round(elapsed * 1000, 3))
    assert sample_counts() == (0, 0)
    assert elapsed < 0.3, f"periodic writer blocked event loop for {elapsed:.3f}s"
    assert [len(runtime.buffer) for runtime in service.runtimes.values()] == [2, 1]
    await flush_pending_samples(service)
    assert sample_counts() == (2, 1)


@pytest.mark.asyncio
async def test_timeout_is_restored_before_pool_return_and_normal_writes(client):
    from sqlalchemy import event

    service, ids, _ = make_pending_service()
    returned_timeouts = []
    with engine.connect() as connection:
        original = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()

    def on_checkin(connection, _record):
        returned_timeouts.append(connection.execute("PRAGMA busy_timeout").fetchone()[0])

    event.listen(engine.pool, "checkin", on_checkin)
    try:
        await flush_pending_samples(service)
        await service._flush(ids[0], service.runtimes[ids[0]])
        with sqlite3.connect(engine.url.database) as locker:
            locker.execute("BEGIN IMMEDIATE")
            # Add a fresh accepted sample and exercise the exception cleanup.
            service.runtimes[ids[0]].buffer.append(DeviceReading(
                raw_power=1, raw_power_unit="W", power_w=1, temperatures_c=[],
            ))
            await flush_pending_samples(service)
            locker.rollback()
    finally:
        event.remove(engine.pool, "checkin", on_checkin)
    assert returned_timeouts and all(value == original for value in returned_timeouts)


@pytest.mark.asyncio
async def test_different_cadences_preserve_counts_and_event_loop_responsiveness(
    client, record_property,
):
    service, ids, _ = make_pending_service()
    readings = [runtime.buffer[0] for runtime in service.runtimes.values()]
    for runtime in service.runtimes.values():
        runtime.buffer.clear()
        runtime.sample_count = 0
    gaps = []
    stopped = asyncio.Event()

    async def heartbeat():
        previous = time.monotonic()
        while not stopped.is_set():
            await asyncio.sleep(0.01)
            current = time.monotonic()
            gaps.append(current - previous)
            previous = current

    async def produce(device_id, template, interval, count):
        runtime = service.runtimes[device_id]
        for index in range(count):
            if index:
                await asyncio.sleep(interval)
            received = datetime.now(UTC)
            runtime.buffer.append(template.model_copy(update={
                "timestamp": received, "received_timestamp": received,
            }))
            runtime.sample_count += 1
            if runtime.sample_count % 3 == 0:
                await service._flush(device_id, runtime)

    before_threads = {thread.ident for thread in threading.enumerate()}
    pulse = asyncio.create_task(heartbeat())
    try:
        await asyncio.sleep(0.1)
        baseline_gap = max(gaps)
        gaps.clear()
        async with pending_sample_persistence(service), asyncio.timeout(12):
            await asyncio.gather(
                produce(ids[0], readings[0], 1, 6),
                produce(ids[1], readings[1], 5, 2),
            )
            while any(runtime.buffer for runtime in service.runtimes.values()):
                await asyncio.sleep(0.01)
    finally:
        stopped.set()
        await pulse
    record_property("healthy_max_event_loop_gap_ms", round(max(gaps) * 1000, 3))
    record_property("idle_max_event_loop_gap_ms", round(baseline_gap * 1000, 3))
    assert max(gaps) < 0.2
    assert max(gaps) - baseline_gap < 0.15
    assert sample_counts() == (6, 2)
    assert [runtime.persisted_count for runtime in service.runtimes.values()] == [6, 2]
    assert {thread.ident for thread in threading.enumerate()} == before_threads


@pytest.mark.asyncio
@pytest.mark.parametrize("locked", [False, True])
async def test_application_shutdown_final_flush_is_bounded_and_explicit(
    monkeypatch, caplog, locked, record_property,
):
    from app import main
    from app.core.database import Base

    Base.metadata.drop_all(engine)
    service = AcquisitionService()
    monkeypatch.setattr(main, "acquisition_service", service)
    calls = []

    class ShutdownOnly:
        async def stop_reading(self):
            calls.append("stop")

        async def disconnect(self):
            calls.append("close")

    lock = None
    original_flush = service._flush
    flushed = []
    flush_durations = []

    async def count_flush(device_id, runtime):
        flushed.append(device_id)
        started_flush = time.monotonic()
        try:
            await original_flush(device_id, runtime)
        finally:
            flush_durations.append(time.monotonic() - started_flush)

    monkeypatch.setattr(service, "_flush", count_flush)
    try:
        async with main.lifespan(main.app):
            seeded, ids, _ = make_pending_service()
            service.runtimes.update(seeded.runtimes)
            for runtime in service.runtimes.values():
                runtime.adapter = ShutdownOnly()
            if locked:
                lock = sqlite3.connect(engine.url.database)
                lock.execute("BEGIN IMMEDIATE")
            started = time.monotonic()
        elapsed = time.monotonic() - started
        record_property("shutdown_elapsed_ms", round(elapsed * 1000, 3))
        # Include real log formatting and file flushes in the application budget.
        assert elapsed < 2
        assert max(flush_durations) < 0.2
        assert flushed == ids  # one final attempt per source, no retry loop
        assert calls == ["stop", "close", "stop", "close"]
        assert not any(t.get_name() == "pending-sample-persistence" for t in asyncio.all_tasks())
        if locked:
            assert [len(runtime.buffer) for runtime in service.runtimes.values()] == [2, 1]
            assert caplog.text.count("shutdown failed for acquisition device_id=") == 2
        else:
            assert not service.runtimes
            assert sample_counts() == (2, 1)
    finally:
        if lock:
            lock.rollback()
            lock.close()
        Base.metadata.drop_all(engine)


def test_committed_pending_samples_survive_forced_process_termination(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / "process.db"
    marker = tmp_path / "persisted.txt"
    program = """
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, 'tests')
from test_pending_persistence import make_pending_service
from app.main import app, lifespan
from app.services.acquisition import acquisition_service

async def main():
    async with lifespan(app):
        service, ids, _ = make_pending_service()
        acquisition_service.runtimes.update(service.runtimes)
        while any(runtime.buffer for runtime in service.runtimes.values()):
            await asyncio.sleep(0.05)
        Path(os.environ['PERSISTENCE_MARKER']).write_text('committed')
        await asyncio.Event().wait()
asyncio.run(main())
"""
    with (tmp_path / "child.log").open("w") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", program], cwd=backend, stdout=log, stderr=log,
            env={**os.environ, "THERMOPOWER_DATABASE_URL": f"sqlite:///{database.as_posix()}",
                 "THERMOPOWER_LOG_DIRECTORY": str(tmp_path / "logs"),
                 "PERSISTENCE_MARKER": str(marker)},
        )
        try:
            deadline = time.monotonic() + 20
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.1)
            assert marker.exists(), "isolated process did not persist pending samples"
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
    restart = """
import asyncio
from app.main import app, lifespan
async def main():
    async with lifespan(app):
        await asyncio.sleep(2.1)
asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", restart], cwd=backend, capture_output=True, timeout=20,
        env={**os.environ, "THERMOPOWER_DATABASE_URL": f"sqlite:///{database.as_posix()}",
             "THERMOPOWER_LOG_DIRECTORY": str(tmp_path / "logs")},
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    with sqlite3.connect(database) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        rows = db.execute(
            "SELECT active_power_w FROM electrical_samples ORDER BY sequence"
        ).fetchall()
        assert rows == [(100.0,), (220.0,)]
        assert db.execute("SELECT COUNT(*) FROM temperature_samples").fetchone() == (1,)
