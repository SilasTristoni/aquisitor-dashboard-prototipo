"""Regressions from Britania October 13–15; no physical device access."""

import asyncio
import hashlib
import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError
from test_pending_persistence import make_pending_service, sample_counts

from app.adapters.base import DeviceStatus
from app.adapters.specific import Gpm8213Adapter, ProtocolResponseError
from app.core.database import SessionLocal
from app.services.pending_persistence import flush_pending_samples

PARTIALS = json.loads((Path(__file__).parent / "fixtures/at4532_partial_20261013_15.json")
                     .read_text(encoding="utf-8"))


def full_error():
    original = sqlite3.OperationalError("database or disk is full")
    original.sqlite_errorcode = sqlite3.SQLITE_FULL
    return OperationalError("INSERT", {}, original)


class ControlledSource:
    def __init__(self, readings):
        self.readings = readings
        self.requested = 0
        self.stop_reading = AsyncMock()
        self.disconnect = AsyncMock()

    async def start_reading(self):
        for reading in self.readings:
            self.requested += 1
            yield reading
        await asyncio.Event().wait()

    async def get_status(self):
        return DeviceStatus(state="connected", connected=True, reading=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [0, 1], ids=["electrical", "thermal"])
async def test_full_backpressures_reader_preserves_buffer_and_recovers(client, monkeypatch, source):
    service, ids, _ = make_pending_service()
    device_id = ids[source]
    runtime = service.runtimes[device_id]
    reading = runtime.buffer[0]
    runtime.buffer.clear()
    runtime.last_error = None
    runtime.last_flush = 0
    runtime.adapter = ControlledSource([reading, reading.model_copy(update={
        "received_timestamp": reading.received_timestamp + timedelta(seconds=5),
        "device_timestamp": reading.device_timestamp + timedelta(seconds=5),
    })])
    fail = True

    def session():
        db = SessionLocal()
        commit = db.commit

        def commit_or_full():
            if fail:
                db.flush()
                raise full_error()
            commit()

        db.commit = commit_or_full
        return db

    monkeypatch.setattr("app.services.acquisition.SessionLocal", session)
    monkeypatch.setattr(service, "_evaluate_alerts", AsyncMock())
    runtime.task = asyncio.create_task(service._read_loop(device_id, runtime))
    try:
        await asyncio.sleep(0.05)
        assert not runtime.task.done(), "A storage fault must not terminate the source reader"
        assert runtime.adapter.requested == 1
        assert runtime.buffer == [reading]
        assert runtime.adapter.disconnect.await_count == 0
        state = await service.status(device_id)
        assert not state["reading"] and state["state"] == "error"
        assert state["storage"]["code"] == "storage_full"
        fail = False
        await service._flush(device_id, runtime)
        await asyncio.sleep(0.15)
        await flush_pending_samples(service)
        counts = sample_counts()
        assert counts[source] == 2
        assert runtime.persisted_count == 2
        assert not runtime.storage_fault
    finally:
        runtime.task.cancel()
        await asyncio.gather(runtime.task, return_exceptions=True)


@pytest.mark.asyncio
async def test_secondary_event_failure_does_not_escape_reader(client, monkeypatch):
    service, ids, _ = make_pending_service()
    runtime = service.runtimes[ids[0]]
    runtime.buffer.clear()
    runtime.adapter = ControlledSource([])

    async def fail_read():
        raise RuntimeError("physical failure")
        yield  # pragma: no cover

    runtime.adapter.start_reading = fail_read

    def broken_db():
        raise full_error()

    monkeypatch.setattr("app.services.acquisition.SessionLocal", broken_db)
    await service._read_loop(ids[0], runtime)
    assert "physical failure" in runtime.last_error
    runtime.adapter.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_gpm_partial_response_recovers_without_terminating_reader(monkeypatch):
    from datetime import UTC, datetime

    from app.adapters.base import DeviceReading

    reading = DeviceReading(timestamp=datetime.now(UTC), power_w=100, raw_power=100,
                            raw_power_unit="W", temperatures_c=[])
    adapter = Gpm8213Adapter("COM_TEST", None)
    adapter._read_once = AsyncMock(side_effect=[ProtocolResponseError("missing CRLF"), reading])
    adapter.connect = AsyncMock()
    adapter.expected_interval_seconds = 0
    # Production retry delay is tested separately with a virtual clock.
    monkeypatch.setattr("app.adapters.specific.asyncio.sleep", AsyncMock())
    stream = adapter.start_reading()
    try:
        assert await anext(stream) is reading
        assert adapter.read_errors == 1
        adapter.connect.assert_awaited_once()
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_capacity_retry_budget_retains_all_pending_samples(client, monkeypatch, caplog):
    from app.services.storage_health import MAX_AUTOMATIC_ATTEMPTS

    service, ids, _ = make_pending_service()
    original = [r.buffer[:] for r in service.runtimes.values()]
    attempts = 0

    def broken():
        nonlocal attempts
        attempts += 1
        raise full_error()

    monkeypatch.setattr("app.services.acquisition.SessionLocal", broken)
    for _ in range(100):
        for runtime in service.runtimes.values():
            if runtime.storage_fault:
                runtime.storage_fault["retry_at_monotonic"] = 0
        await flush_pending_samples(service)
    assert attempts == 2 * MAX_AUTOMATIC_ATTEMPTS
    assert [r.buffer for r in service.runtimes.values()] == original
    assert caplog.text.count("Sample persistence unavailable") == 4
    monkeypatch.setattr("app.services.acquisition.SessionLocal", SessionLocal)
    # Explicit operator retry remains possible after the automatic budget is spent.
    for device_id in ids:
        await service._flush(device_id, service.runtimes[device_id])
    await flush_pending_samples(service)
    assert sample_counts() == (2, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("port", ["COM3", "COM9"])
async def test_usb_return_requires_exact_unique_identity(port):
    from app.adapters.transports import SerialTransportError
    from app.adapters.usb_identity import UsbIdentityResolver

    expected = {"vid": 0x2184, "pid": 0x0052, "serial_number": "GES913349"}
    ports = []
    resolver = UsbIdentityResolver(expected, lambda: ports)
    with pytest.raises(SerialTransportError, match="ausente"):
        await resolver.resolve("COM3", recovering=True)
    # Another instrument gets the old COM: never open it.
    ports.append(SimpleNamespace(device="COM3", **{**expected, "serial_number": "OTHER"}))
    with pytest.raises(SerialTransportError, match="ausente"):
        await resolver.resolve("COM3", recovering=True)
    ports[:] = [SimpleNamespace(device=port, **expected)]
    assert await resolver.resolve("COM3", recovering=True) == port
    ports.append(SimpleNamespace(device="COM10", **expected))
    with pytest.raises(SerialTransportError, match="ambígua"):
        await resolver.resolve("COM3", recovering=True)


@pytest.mark.asyncio
async def test_gpm_absent_soak_backoff_no_serial_opens_and_stop(monkeypatch, caplog):
    from app.adapters.transports import SerialTransportError

    adapter = Gpm8213Adapter("COM3", None, usb_identity={
        "vid": 0x2184, "pid": 0x0052, "serial_number": "GES913349",
    })
    adapter.usb_resolver.provider = lambda: []
    adapter._read_once = AsyncMock(side_effect=SerialTransportError("disconnected", "USB lost"))
    opens = AsyncMock()
    monkeypatch.setattr("app.adapters.transports.SerialTransport.open", opens)
    delays = []
    now = 100.0

    async def virtual_sleep(delay):
        nonlocal now
        delays.append(delay)
        now += delay
        if len(delays) >= 125:
            await adapter.stop_reading()

    monkeypatch.setattr("app.adapters.specific.asyncio", SimpleNamespace(sleep=virtual_sleep))
    monkeypatch.setattr("app.adapters.specific.monotonic", lambda: now)
    assert [r async for r in adapter.start_reading()] == []
    assert delays[:5] == [2, 4, 8, 16, 30]
    assert sum(delays) > 3600  # More than one hour of simulated absence.
    assert max(delays) == 30
    assert adapter.recovery_status["attempts"] == 124
    assert adapter.recovery_status["port_available"] is False
    assert caplog.text.count("GPM recovery") < 65
    opens.assert_not_called()
    adapter._read_once.assert_awaited_once()
    assert not adapter._reading


@pytest.mark.asyncio
@pytest.mark.parametrize("capture", PARTIALS, ids=lambda r: r["event_timestamp"])
async def test_physical_at_partial_never_published_or_overwritten(monkeypatch, capture):
    from test_at4532_input_boundary import setup_transport

    from app.adapters.specific import At4532Parser
    from app.adapters.transports import SerialTransportError

    raw = bytes.fromhex(capture["hex"])
    assert hashlib.sha256(raw).hexdigest() == capture["sha256"]
    assert len(raw) == capture["length"]
    with pytest.raises(ProtocolResponseError):
        At4532Parser().parse(raw)
    _, wire, transport = setup_transport(monkeypatch)
    wire.on_write = lambda _: wire.schedule(0.02, raw)
    await transport.open()
    try:
        with pytest.raises(SerialTransportError):
            await transport.query(b"SYST:UNIT CEL\n", b"\n")
        sent = len(wire.writes)
        with pytest.raises(SerialTransportError):
            await transport.query(b"SYST:UNIT CEL\n", b"\n")
        assert len(wire.writes) == sent
        assert wire.input_resets == 0
    finally:
        await transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [True, False])
async def test_gpm_fragmentation_and_partial_transaction_evidence(monkeypatch, complete):
    from test_at4532_input_boundary import setup_transport

    from app.adapters.transports import Gpm8213SerialTransport, SerialTransportError

    _, wire, transport = setup_transport(monkeypatch, Gpm8213SerialTransport)
    adapter = Gpm8213Adapter("COM_BOUNDARY", None, transport)

    def respond(_):
        wire.schedule(0.01, b"8")
        wire.schedule(0.2, b"\r")
        if complete:
            wire.schedule(0.3, b"\n")

    wire.on_write = respond
    await transport.open()
    try:
        if complete:
            assert await adapter._transaction(adapter.protocol.number_query,
                                              expect_response=True) == b"8\r\n"
        else:
            with pytest.raises(SerialTransportError) as failure:
                await adapter._transaction(adapter.protocol.number_query, expect_response=True)
            assert failure.value.code == "incomplete_frame"
            transaction = adapter.transactions[-1]
            assert transaction["rx_bytes"] == list(b"8\r")
            assert transaction["error"]["code"] == "incomplete_frame"
        assert not transport._io_lock.locked()
    finally:
        await transport.close()


def test_serial_exception_classification_distinguishes_windows_missing_busy_io():
    import serial

    from app.adapters.transports import classify_serial_error

    assert classify_serial_error(serial.SerialException(
        "could not open port COM3: FileNotFoundError(2, 'O sistema não pode encontrar')"
    )).code == "port_not_found"
    assert classify_serial_error(PermissionError("Access denied")).code == "port_busy"
    assert classify_serial_error(OSError("I/O failure")).code == "serial_error"


@pytest.mark.asyncio
async def test_resume_keeps_recovering_gpm_task_and_session(client, monkeypatch):
    service, ids, session_id = make_pending_service()
    runtime = service.runtimes[ids[0]]
    runtime.last_error = None
    runtime.paused = True
    runtime.adapter = ControlledSource([])
    runtime.adapter.connection_state = "recovering"
    runtime.adapter.get_status = AsyncMock(return_value=DeviceStatus(
        state="recovering", connected=False, reading=False,
    ))
    runtime.task = asyncio.create_task(asyncio.Event().wait())
    original = runtime.task
    connect = AsyncMock()
    monkeypatch.setattr(service, "connect", connect)
    try:
        await service.resume_session(ids[0], session_id)
        assert runtime.task is original and not original.done()
        assert not runtime.paused and runtime.session_id == session_id
        connect.assert_not_called()
    finally:
        original.cancel()
        await asyncio.gather(original, return_exceptions=True)


@pytest.mark.asyncio
async def test_export_during_storage_full_and_absent_source(client):
    import io
    import zipfile

    from app.services.diagnostic_snapshot import runtime_snapshot
    from app.services.physical_diagnostic import UnavailableDatabase, physical_diagnostic_zip
    from app.services.storage_health import record_failure

    service, ids, _ = make_pending_service()
    for device_id, runtime in service.runtimes.items():
        runtime.adapter = ControlledSource([])
        runtime.adapter.recovery_status = {"cause": "port_not_found", "attempts": 100}
        record_failure(runtime, device_id, full_error())
    snapshot = runtime_snapshot(service)
    content = physical_diagnostic_zip(UnavailableDatabase(), snapshot["states"],
                                     snapshot["transactions"], snapshot["boundaries"], {},
                                     snapshot=snapshot)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert archive.testzip() is None
        states = json.loads(archive.read("acquisition-state.json"))
        assert all(s["storage"]["code"] == "storage_full" for s in states)
        assert all(s["adapter_state"]["recovery_status"]["cause"] == "port_not_found"
                   for s in states)
        assert json.loads(archive.read("evidence-status.json"))["sections"]
    assert [len(r.buffer) for r in service.runtimes.values()] == [2, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [0, 1])
async def test_real_sqlite_full_rollback_and_restored_capacity(client, monkeypatch, source):
    from sqlalchemy import text

    from app.core.database import engine

    service, ids, _ = make_pending_service()
    runtime = service.runtimes[ids[source]]
    with engine.connect() as connection:
        page_count = connection.exec_driver_sql("PRAGMA page_count").scalar()
        page_size = connection.exec_driver_sql("PRAGMA page_size").scalar()
    # Exceed all existing pages, including reusable pages from previous test schemas.
    runtime.buffer[0].raw_payload = {
        "synthetic_large_payload": "x" * (page_count * page_size + 4096),
    }
    original = runtime.buffer[:]

    def constrained():
        db = SessionLocal()
        db.execute(text(f"PRAGMA max_page_count={page_count}"))
        return db

    monkeypatch.setattr("app.services.acquisition.SessionLocal", constrained)
    try:
        with pytest.raises(OperationalError) as error:
            await service._flush(ids[source], runtime)
        assert error.value.orig.sqlite_errorcode == sqlite3.SQLITE_FULL
        assert runtime.buffer == original and runtime.persisted_count == 0
        assert sample_counts() == (0, 0)
    finally:
        monkeypatch.setattr("app.services.acquisition.SessionLocal", SessionLocal)
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA max_page_count=1073741823")
    await service._flush(ids[source], runtime)
    await service._flush(ids[source], runtime)
    assert sample_counts()[source] == len(original)


@pytest.mark.asyncio
async def test_recreated_runtime_resumes_after_persisted_sequence(client):
    from sqlalchemy import select

    from app.models import ElectricalSample
    from app.services.acquisition import DeviceRuntime

    service, ids, session_id = make_pending_service()
    reading = service.runtimes[ids[0]].buffer[0]
    await flush_pending_samples(service)
    runtime = DeviceRuntime(adapter=ControlledSource([]))
    service.runtimes[ids[0]] = runtime
    await service.attach_session(ids[0], session_id)
    assert runtime.persisted_count == 2
    runtime.buffer.append(reading.model_copy(update={
        "received_timestamp": reading.received_timestamp + timedelta(seconds=500),
    }))
    await service._flush(ids[0], runtime)
    with SessionLocal() as db:
        assert list(db.scalars(select(ElectricalSample.sequence).order_by(
            ElectricalSample.sequence,
        ))) == [1, 2, 3]


def test_physical_journal_budget_preserves_existing_history(tmp_path, monkeypatch):
    from app.core.physical_trace import PhysicalJournal

    monkeypatch.setenv("THERMOPOWER_LOG_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("THERMOPOWER_PHYSICAL_TRACE", "1")
    folder = tmp_path / "physical"
    folder.mkdir()
    original = folder / "previous.jsonl"
    original.write_bytes(b'{"previous": true}\n')
    recorder = PhysicalJournal()
    recorder.storage_limit_bytes = 1024
    for _ in range(100):
        recorder.emit("AT_TIMEOUT", cause="test")
    assert recorder.flush()
    assert original.read_bytes() == b'{"previous": true}\n'
    assert sum(p.stat().st_size for p in folder.iterdir()) <= 1024
    assert recorder.status()["budget_dropped_events"] > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("returned_port", ["COM3", "COM9"])
async def test_gpm_runtime_reconnects_exact_usb_without_new_session(monkeypatch, returned_port):
    from test_partial_combined_acquisition import GPM_PHYSICAL_HEADERS, GPM_PHYSICAL_VALUES
    from test_physical_engineering import FakeVendorTransport

    from app.adapters.transports import SerialTransportError

    expected = {"vid": 0x2184, "pid": 0x0052, "serial_number": "GES913349"}
    ports = [SimpleNamespace(device="COM3", **expected)]
    adapter = Gpm8213Adapter("COM3", None, usb_identity=expected)
    adapter.usb_resolver.provider = lambda: ports
    opens = []
    transport = FakeVendorTransport([
        b"GWInstek,GPM-8213,GES913349,V1.05\r\n", b"8\r\n", GPM_PHYSICAL_HEADERS,
        GPM_PHYSICAL_VALUES, SerialTransportError("serial_error", "USB lost"),
        b"GWInstek,GPM-8213,GES913349,V1.05\r\n", b"8\r\n", GPM_PHYSICAL_HEADERS,
        GPM_PHYSICAL_VALUES,
    ])

    def factory(configuration):
        opens.append(configuration.port)
        return transport

    adapter._transport = factory

    async def delay(_):
        ports[:] = [SimpleNamespace(device=returned_port, **expected)]

    monkeypatch.setattr("app.adapters.specific.asyncio", SimpleNamespace(sleep=delay))
    await adapter.connect()
    stream = adapter.start_reading()
    try:
        first = await anext(stream)
        second = await anext(stream)
        assert second.received_timestamp > first.received_timestamp
        assert adapter.port == returned_port
        assert adapter.recovery_status["attempts"] == 1
        assert adapter.recovery_status["cause"] is None
        assert adapter._read_count == 2
        assert opens == (["COM3", "COM9"] if returned_port == "COM9" else ["COM3"])
        assert transport.requests.count(b"*IDN?\r\n") == 2
    finally:
        await stream.aclose()
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_dual_source_two_hour_soak_simultaneous_recovery_and_periodic_persistence(
    client, monkeypatch, record_property, caplog,
):
    import logging
    from datetime import UTC, datetime

    from sqlalchemy import select
    from test_continuous_serial_soak import setup_adapter
    from test_partial_combined_acquisition import GPM_PHYSICAL_HEADERS, GPM_PHYSICAL_VALUES
    from test_physical_engineering import FakeVendorTransport

    from app.adapters.transports import SerialTransportError
    from app.models import ElectricalSample, TemperatureSample

    caplog.set_level(logging.WARNING, logger="app.adapters.specific")

    clock, thermal_wire, thermal = setup_adapter(monkeypatch, "closed", failed_opens=3)
    real_sleep = asyncio.sleep
    electrical_wire = FakeVendorTransport([])
    reads = 0

    async def query(payload, terminator, max_bytes=65536):
        nonlocal reads
        electrical_wire.requests.append(payload)
        if payload == b"*IDN?\r\n":
            return b"GWInstek,GPM-8213,GES913349,V1.05\r\n", 1
        if payload == b":NUMERIC:NORMAL:NUMBER?\r\n":
            return b"8\r\n", 1
        if payload == b":NUMERIC:NORMAL:HEADER?\r\n":
            return GPM_PHYSICAL_HEADERS, 1
        reads += 1
        if reads in {100, 101, 500}:
            raise SerialTransportError("incomplete_frame" if reads == 500 else "disconnected",
                                       "simulated fault")
        return GPM_PHYSICAL_VALUES, 1

    electrical_wire.query = query
    electrical = Gpm8213Adapter("COM_GPM_SOAK", None, electrical_wire)

    async def advance(seconds):
        clock.advance(seconds)
        await real_sleep(0)

    monkeypatch.setattr("app.adapters.specific.asyncio", SimpleNamespace(sleep=advance))
    service, ids, session_id = make_pending_service()
    for runtime, adapter in zip(service.runtimes.values(), [electrical, thermal], strict=True):
        runtime.buffer.clear()
        runtime.sample_count = 0
        runtime.last_error = None
        runtime.adapter = adapter
    await thermal.connect()
    await electrical.connect()
    stopped = False

    async def timer():
        while not stopped:
            await real_sleep(0)
            await flush_pending_samples(service)

    for adapter in (thermal, electrical):
        original = adapter.start_reading

        async def limited(original=original):
            stream = original()
            try:
                for _ in range(1500):
                    yield await anext(stream)
            finally:
                await stream.aclose()

        monkeypatch.setattr(adapter, "start_reading", limited)
    pending = asyncio.create_task(timer())
    try:
        async with asyncio.timeout(180):
            await asyncio.gather(*(service._read_loop(i, r) for i, r in service.runtimes.items()))
        stopped = True
        await pending
        await flush_pending_samples(service)
        for runtime in service.runtimes.values():
            assert runtime.sample_count == runtime.persisted_count == 1500
            assert runtime.last_error is None and runtime.storage_fault is None
            assert runtime.session_id == session_id and not runtime.buffer
        assert clock.monotonic() >= 7200
        assert thermal.fetch_diagnostics.reconnect_failures == 3
        assert electrical.recovery_status["attempts"] >= 3
        with SessionLocal() as db:
            for model in (ElectricalSample, TemperatureSample):
                rows = list(db.scalars(select(model).where(model.session_id == session_id)))
                assert len(rows) == 1500
                assert sorted(r.sequence for r in rows) == list(range(1, 1501))
                assert len({r.received_timestamp for r in rows}) == 1500
        record_property("simulated_duration_seconds", clock.monotonic())
        record_property("completed_at_utc", datetime.now(UTC).isoformat())
    finally:
        stopped = True
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await thermal.disconnect()
        await electrical.disconnect()
