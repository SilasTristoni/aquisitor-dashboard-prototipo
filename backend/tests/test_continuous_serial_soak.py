"""Deterministic long-running protocol/service tests, never physical homologation."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_at4532_tcp32_physical import (
    CadenceSensitiveAt4532Transport,
    FakeClock,
    tcp32_physical_fixture,
)
from test_physical_engineering import BufferedSerial, _configuration

from app.adapters.specific import At4532SerialAdapter
from app.adapters.transports import SerialTransport, SerialTransportError
from app.services.usb_discovery import UsbDeviceDiscoveryService

pytestmark = pytest.mark.physical_regression_fixtures


@pytest.fixture(autouse=True)
def quiet_serial_logs(caplog):
    # Thousands of frames exercise the protocol, not the rotating disk log throughput.
    import logging

    caplog.set_level(logging.WARNING, logger="app.adapters.specific")


class ScriptedTransport(CadenceSensitiveAt4532Transport):
    def __init__(self, clock, fault=None, failed_opens=0):
        super().__init__(clock)
        self.fault = fault
        self.failed_opens = failed_opens
        self.fired = False
        self.snapshots = []
        self.adapter = None

    async def open(self):
        if self.fired and self.failed_opens:
            self.failed_opens -= 1
            raise SerialTransportError("port_not_found", "USB absent")
        return await super().open()

    async def query(self, payload, terminator, max_bytes=65536):
        if payload == b"FETCH?\n" and self.fetch_count == 100 and not self.fired and self.fault:
            self.fired = True
            tx = self.clock.monotonic()
            self.clock.advance(2 if self.fault == "timeout" else 0.375)
            self.last_query_boundary = self._boundary(tx, self.clock.monotonic())
            if self.fault == "closed":
                self.is_open = False
                raise SerialTransportError("disconnected", "USB unplugged")
            if self.fault == "timeout":
                raise SerialTransportError("protocol_timeout", "Late response")
            return (
                b"unknown\r\n" if self.fault == "invalid" else tcp32_physical_fixture()[:200]
            ), 375
        if self.adapter and self.fired:
            self.snapshots.append((await self.adapter.get_status()).model_dump())
        return await super().query(payload, terminator, max_bytes)


def setup_adapter(monkeypatch, fault=None, failed_opens=0):
    clock = FakeClock()
    transport = ScriptedTransport(clock, fault, failed_opens)
    monkeypatch.setattr("app.adapters.specific.monotonic", clock.monotonic)
    monkeypatch.setattr("app.adapters.specific.asyncio", SimpleNamespace(sleep=clock.sleep))
    adapter = At4532SerialAdapter("COM_SOAK", 19200, transport, allow_identity_fallback=True)
    transport.adapter = adapter
    return clock, transport, adapter


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault,count,reconnects",
    [
        (None, 1000, 0),
        ("invalid", 200, 0),
        ("timeout", 200, 0),
        ("closed", 200, 1),
        ("partial", 200, 0),
    ],
)
async def test_soak_a_to_e(monkeypatch, fault, count, reconnects, record_property):
    clock, transport, adapter = setup_adapter(monkeypatch, fault)
    await adapter.connect()
    stream = adapter.start_reading()
    try:
        readings = [await anext(stream) for _ in range(count)]
        metrics = adapter.fetch_diagnostics.snapshot(clock.monotonic())
        record_property("stability_scenario", fault or "healthy")
        record_property("stability_metrics", json.dumps(metrics))
        assert metrics["successful_fetches"] == count
        assert metrics["fetch_attempts"] == count + bool(fault)
        assert metrics["reconnect_count"] == reconnects
        assert metrics["discarded_fetches"] == bool(fault)
        assert metrics["fetch_timeouts"] == (fault == "timeout")
        assert metrics["unknown_responses"] == (fault in {"partial", "invalid"})
        assert transport.open_calls == 1 + reconnects
        assert transport.rejected_fetches == 0
        assert len({r.device_timestamp for r in readings}) == count
        assert (await adapter.get_status()).connected
        assert len(adapter.transactions) <= 256
        if fault:
            assert "communication_gap" in readings[100].raw_payload
            assert all(item["connected"] for item in transport.snapshots)
        else:
            assert metrics["maximum_gap_ms"] == pytest.approx(1000)
            assert metrics["average_query_duration_ms"] == pytest.approx(375)
    finally:
        await stream.aclose()
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_usb_returns_after_many_failed_opens_without_manual_intervention(monkeypatch):
    clock, transport, adapter = setup_adapter(monkeypatch, "closed", failed_opens=5)
    await adapter.connect()
    stream = adapter.start_reading()
    try:
        readings = [await anext(stream) for _ in range(101)]
        assert len(readings) == 101
        assert adapter.fetch_diagnostics.reconnect_count == 6
        assert adapter.fetch_diagnostics.reconnect_failures == 5
        assert adapter.fetch_diagnostics.consecutive_reconnect_failures == 0
        assert clock.monotonic() > 160
        assert (await adapter.get_status()).state == "connected"
    finally:
        await stream.aclose()
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_three_timeouts_with_open_port_do_not_force_reconnection(monkeypatch):
    from test_at4532_recovery import RecoverableTransport

    clock, _, adapter = setup_adapter(monkeypatch)
    transport = RecoverableTransport(clock, failures=3)
    adapter.transport = transport
    await adapter.connect()
    stream = adapter.start_reading()
    try:
        await anext(stream)
        await anext(stream)
        assert adapter.fetch_diagnostics.fetch_timeouts == 3
        assert adapter.fetch_diagnostics.reconnect_count == 0
    finally:
        await stream.aclose()
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_global_port_lease_includes_recovery_and_usb_discovery():
    config = _configuration("COM_LEASE")
    connection = BufferedSerial()
    owner = SerialTransport(config, serial_factory=lambda **_: connection)
    calls = []
    contender = SerialTransport(
        replace(config, port="com_lease"), serial_factory=lambda **kw: calls.append(kw)
    )
    discovery = UsbDeviceDiscoveryService(serial_factory=lambda **kw: calls.append(kw))
    await owner.open()
    await owner.open()  # Idempotent; never replace a live connection.
    try:
        for recovering in [False, True]:
            if recovering:
                await owner.close(release=False)
            with pytest.raises(SerialTransportError, match="ThermoPower"):
                await contender.open()
            assert discovery._port_status("COM_LEASE", set())[0] == "port_busy"
            assert calls == []
    finally:
        await owner.close()
    contender.serial_factory = lambda **_: BufferedSerial()
    await contender.open()
    await contender.close()


@pytest.mark.asyncio
async def test_fragmented_tcp32_and_partial_timeout_keep_full_raw_evidence():
    connection = BufferedSerial()
    transport = SerialTransport(_configuration("COM_FRAME"), serial_factory=lambda **_: connection)
    await transport.open()
    try:
        complete = tcp32_physical_fixture()
        connection.responses[b"FETCH?\n"] = complete
        response, _ = await transport.query(b"FETCH?\n", b"\n")
        assert response == complete
        boundary = transport.last_query_boundary
        assert boundary["frame_complete"] is True
        assert boundary["bytes_received"] == len(complete)
        assert boundary["last_byte_monotonic"] >= boundary["first_byte_monotonic"]
        connection.responses[b"FETCH?\n"] = complete[:200]
        response, _ = await transport.query(b"FETCH?\n", b"\n")
        assert response == complete[:200]
        assert transport.last_query_boundary["frame_complete"] is False
        connection.buffer.extend(b"stale tail\r\n")
        connection.responses[b"FETCH?\n"] = complete
        response, _ = await transport.query(b"FETCH?\n", b"\n")
        assert response == complete
        assert transport.last_query_boundary["buffer_drained_bytes"] == 12
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_cancelled_query_finishes_worker_before_close():
    from threading import Event

    entered, finish = Event(), Event()
    connection = BufferedSerial()
    original_read = connection.read

    def slow_read(size):
        entered.set()
        assert finish.wait(5)
        assert connection.is_open
        return original_read(size)

    connection.read = slow_read
    connection.responses[b"Q\n"] = b"OK\n"
    transport = SerialTransport(_configuration("COM_CANCEL"), serial_factory=lambda **_: connection)
    await transport.open()
    task = asyncio.create_task(transport.query(b"Q\n", b"\n"))
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    close = asyncio.create_task(transport.close())
    await asyncio.sleep(0)
    assert not close.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await close
    assert not connection.is_open


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["invalid", "timeout", "closed", "partial"])
async def test_soak_f_dual_source_service_keeps_session_and_electrical_stream(
    client, monkeypatch, fault
):
    from datetime import UTC, datetime

    from sqlalchemy import select
    from test_partial_combined_acquisition import GPM_PHYSICAL_HEADERS, GPM_PHYSICAL_VALUES
    from test_physical_engineering import FakeVendorTransport

    from app.adapters.specific import Gpm8213UsbSerialAdapter
    from app.core.database import SessionLocal
    from app.models.entities import (
        Device,
        ElectricalSample,
        MeasurementSession,
        SessionDevice,
        TemperatureSample,
        User,
    )
    from app.services.acquisition import AcquisitionService, DeviceRuntime

    clock, transport, thermal = setup_adapter(monkeypatch, fault)
    real_sleep = asyncio.sleep

    async def yielding_sleep(seconds):
        clock.advance(seconds)
        await real_sleep(0)

    monkeypatch.setattr("app.adapters.specific.asyncio", SimpleNamespace(sleep=yielding_sleep))
    gpm_transport = FakeVendorTransport(
        [
            b"GWInstek,GPM-8213,GES913349,V1.05\r\n",
            b"8\r\n",
            GPM_PHYSICAL_HEADERS,
            *([GPM_PHYSICAL_VALUES] * 200),
        ]
    )
    electrical = Gpm8213UsbSerialAdapter("COM_GPM_SOAK", 9600, gpm_transport)
    await thermal.connect()
    await electrical.connect()
    with SessionLocal() as db:
        user = db.scalar(select(User))
        devices = [
            Device(name="Thermal soak", protocol="at4532_serial", connection_type="serial"),
            Device(name="Electrical soak", protocol="gpm8213_serial", connection_type="serial"),
        ]
        db.add_all(devices)
        db.flush()
        session = MeasurementSession(
            name="Dual stability",
            device_id=devices[0].id,
            user_id=user.id,
            status="running",
            started_at=datetime.now(UTC),
        )
        db.add(session)
        db.flush()
        db.add_all(
            [
                SessionDevice(session_id=session.id, device_id=devices[0].id, role="temperature"),
                SessionDevice(session_id=session.id, device_id=devices[1].id, role="electrical"),
            ]
        )
        db.commit()
        device_ids, session_id = [d.id for d in devices], session.id
    service = AcquisitionService()
    runtimes = [
        DeviceRuntime(adapter=thermal, session_id=session_id, source_role="temperature"),
        DeviceRuntime(adapter=electrical, session_id=session_id, source_role="electrical"),
    ]
    # Limit the real adapters' streams while still using their complete protocol loops.
    for adapter in [thermal, electrical]:
        original = adapter.start_reading

        async def limited(original=original, adapter=adapter):
            stream = original()
            try:
                for _ in range(200):
                    yield await anext(stream)
            finally:
                await stream.aclose()

        monkeypatch.setattr(adapter, "start_reading", limited)
    for device_id, runtime in zip(device_ids, runtimes, strict=True):
        service.runtimes[device_id] = runtime
    try:
        await asyncio.gather(
            *(service._read_loop(i, r) for i, r in zip(device_ids, runtimes, strict=True))
        )
        for i, r in zip(device_ids, runtimes, strict=True):
            await service._flush(i, r)
            assert r.session_id == session_id
            assert r.last_error is None
            assert r.sample_count == r.persisted_count == 200
            assert r.latest is not None
        assert gpm_transport.requests.count(b"*IDN?\r\n") == 1
        assert transport.open_calls == (2 if fault == "closed" else 1)
        with SessionLocal() as db:
            for model in [TemperatureSample, ElectricalSample]:
                rows = list(db.scalars(select(model).where(model.session_id == session_id)))
                assert len(rows) == 200
                assert sorted(row.sequence for row in rows) == list(range(1, 201))
    finally:
        await thermal.disconnect()
        await electrical.disconnect()


@pytest.mark.asyncio
async def test_all_open_channels_after_validation_are_sensor_state_not_port_loss(monkeypatch):
    clock, transport, adapter = setup_adapter(monkeypatch)
    await adapter.connect()
    fields = tcp32_physical_fixture().decode("cp936").strip().split(",")
    fields[3:35] = ["Open|K|\u2103"] * 32
    payload = (",".join(fields) + "\r\n").encode("cp936")
    original = transport.query

    async def all_open(command, *args):
        if command == b"FETCH?\n":
            clock.advance(0.375)
            return payload, 375
        return await original(command, *args)

    transport.query = all_open
    stream = adapter.start_reading()
    try:
        await anext(stream)
        for _ in range(30):
            reading = await anext(stream)
            assert reading.channel_quality == ["open_sensor"] * 32
            assert reading.temperatures_c == [None] * 32
        assert adapter.fetch_diagnostics.reconnect_count == 0
        assert (await adapter.get_status()).state == "connected"
    finally:
        await stream.aclose()
        await adapter.disconnect()
