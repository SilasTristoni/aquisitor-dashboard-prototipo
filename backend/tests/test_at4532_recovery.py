from datetime import UTC, datetime, timedelta
from pathlib import Path
from runpy import run_path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_at4532_tcp32_physical import CadenceSensitiveAt4532Transport, FakeClock

from app.adapters.specific import At4532SerialAdapter
from app.adapters.transports import SerialTransportError
from app.core.database import SessionLocal
from app.models.entities import Device, MeasurementSession, SessionDevice, TemperatureSample, User
from app.services.acquisition import AcquisitionService, DeviceRuntime
from app.services.period_reporting import period_statistics

pytestmark = pytest.mark.physical_regression_fixtures


class RecoverableTransport(CadenceSensitiveAt4532Transport):
    """One transient failure after each open; reopening restarts the fault cycle."""

    def __init__(self, clock, failures=1, disconnect=False):
        super().__init__(clock)
        self.failures = failures
        self.failures_by_connection = {}
        self.successes_by_connection = {}
        self.disconnect_on_failure = disconnect

    async def query(self, payload, terminator, max_bytes=65536):
        count = self.failures_by_connection.get(self.open_calls, 0)
        if (
            payload == b"FETCH?\n"
            and self.successes_by_connection.get(self.open_calls, 0)
            and count < self.failures
        ):
            self.requests.append(payload)
            tx = self.clock.monotonic()
            self.clock.advance(2)
            self.last_query_boundary = self._boundary(tx, self.clock.monotonic())
            self.failures_by_connection[self.open_calls] = count + 1
            if self.disconnect_on_failure:
                self.is_open = False
            raise SerialTransportError("protocol_timeout", "Synthetic transient FETCH timeout")
        result = await super().query(payload, terminator, max_bytes)
        if payload == b"FETCH?\n":
            self.successes_by_connection[self.open_calls] = (
                self.successes_by_connection.get(self.open_calls, 0) + 1
            )
        return result


@pytest.mark.asyncio
async def test_isolated_fetch_timeout_does_not_restart_identity_cycle(monkeypatch):
    clock = FakeClock()
    transport = RecoverableTransport(clock)
    monkeypatch.setattr("app.adapters.specific.monotonic", clock.monotonic)
    monkeypatch.setattr("app.adapters.specific.asyncio.sleep", clock.sleep)
    adapter = At4532SerialAdapter("COM_TEST", 19200, transport, allow_identity_fallback=True)
    await adapter.connect()
    stream = adapter.start_reading()
    times, readings = [], []
    try:
        for _ in range(6):
            readings.append(await anext(stream))
            times.append(clock.monotonic())
    finally:
        await stream.aclose()
    intervals = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert transport.open_calls == 1, f"Reconnect loop; successful RX intervals: {intervals}"
    assert len({r.raw_payload["device_timestamp_raw"] for r in readings}) == 6
    assert intervals[-3:] == pytest.approx([1, 1, 1])
    metrics = adapter.fetch_diagnostics.snapshot()
    assert metrics["fetch_timeouts"] == 1
    assert metrics["reconnect_count"] == 0
    assert metrics["successful_fetches"] == 6
    assert metrics["consecutive_fetch_timeouts"] == 0
    assert metrics["last_failure"]["port_open"] is True
    assert metrics["last_failure"]["recovery_reason"] == "isolated_fetch_timeout"


@pytest.mark.asyncio
@pytest.mark.parametrize("failures,disconnected,expected_timeouts", [(3, False, 3), (1, True, 1)])
async def test_reconnect_only_after_consecutive_timeouts_or_closed_port(
    monkeypatch,
    failures,
    disconnected,
    expected_timeouts,
):
    clock = FakeClock()
    transport = RecoverableTransport(clock, failures, disconnected)
    monkeypatch.setattr("app.adapters.specific.monotonic", clock.monotonic)
    monkeypatch.setattr("app.adapters.specific.asyncio.sleep", clock.sleep)
    adapter = At4532SerialAdapter("COM_TEST", 19200, transport, allow_identity_fallback=True)
    await adapter.connect()
    stream = adapter.start_reading()
    try:
        first, second = await anext(stream), await anext(stream)
    finally:
        await stream.aclose()
    assert first.raw_payload["device_timestamp_raw"] != second.raw_payload["device_timestamp_raw"]
    metrics = adapter.fetch_diagnostics.snapshot()
    assert metrics["successful_fetches"] == 2
    assert metrics["fetch_timeouts"] == expected_timeouts
    assert metrics["reconnect_count"] == 1
    assert transport.open_calls == 2
    assert metrics["last_failure"]["recovery_reason"] == (
        "port_closed" if disconnected else "consecutive_fetch_timeouts"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [100, 300])
async def test_healthy_fetch_metrics_have_no_reconnects(monkeypatch, count):
    clock = FakeClock()
    transport = CadenceSensitiveAt4532Transport(clock)
    monkeypatch.setattr("app.adapters.specific.monotonic", clock.monotonic)
    monkeypatch.setattr("app.adapters.specific.asyncio.sleep", clock.sleep)
    adapter = At4532SerialAdapter("COM_TEST", 19200, transport, allow_identity_fallback=True)
    await adapter.connect()
    stream = adapter.start_reading()
    try:
        readings = [await anext(stream) for _ in range(count)]
    finally:
        await stream.aclose()
    metrics = adapter.fetch_diagnostics.snapshot()
    assert metrics["successful_fetches"] == count
    assert metrics["fetch_timeouts"] == metrics["reconnect_count"] == 0
    assert metrics["average_fetch_interval_ms"] == pytest.approx(1000)
    assert metrics["average_successful_rx_interval_ms"] == pytest.approx(1000)
    assert metrics["average_query_duration_ms"] == pytest.approx(375)
    assert metrics["maximum_gap_ms"] == pytest.approx(1000)
    assert len({r.raw_payload["device_timestamp_raw"] for r in readings}) == count


def test_observed_cadence_distinguishes_slow_valid_samples_from_invalid_data():
    fixture = run_path(
        str(Path(__file__).resolve().parents[2] / "scripts" / "generate-client-preview-fixtures.py")
    )
    data, _ = fixture["fixture_data"]()
    data["temperatures"] = data["temperatures"][::6]
    quality = period_statistics(data)["general"]["source_quality"]
    by_role = {item["role"]: item for item in quality}
    assert by_role["temperature"]["expected_interval_seconds"] == 1
    assert by_role["temperature"]["observed_interval_seconds"] == 6
    assert by_role["temperature"]["frequency_reduced"] is True
    assert by_role["temperature"]["count"] == 20
    assert by_role["electrical"]["frequency_reduced"] is False
    assert all(row["quality"] == "good" for row in data["temperatures"])


@pytest.mark.asyncio
async def test_reconnect_preserves_session_and_persists_only_real_unique_readings(
    client, monkeypatch
):
    clock = FakeClock()
    transport = RecoverableTransport(clock, failures=3)
    monkeypatch.setattr("app.adapters.specific.monotonic", clock.monotonic)
    # Isolate accelerated adapter sleeps from the real service/event-loop scheduler.
    monkeypatch.setattr("app.adapters.specific.asyncio", SimpleNamespace(sleep=clock.sleep))

    class LimitedAdapter(At4532SerialAdapter):
        async def start_reading(self):
            async for reading in super().start_reading():
                yield reading
                if self._read_count == 3:
                    await self.stop_reading()

    adapter = LimitedAdapter("COM_TEST", 19200, transport, allow_identity_fallback=True)
    await adapter.connect()
    with SessionLocal() as db:
        user = db.scalar(select(User))
        device = Device(
            name="Synthetic recovery", protocol="at4532_serial", connection_type="serial"
        )
        db.add(device)
        db.flush()
        session = MeasurementSession(
            device_id=device.id,
            user_id=user.id,
            name="Recovery fixture",
            status="running",
            started_at=datetime.now(UTC),
        )
        db.add(session)
        db.flush()
        db.add(SessionDevice(session_id=session.id, device_id=device.id, role="temperature"))
        db.commit()
        device_id, session_id = device.id, session.id
    runtime = DeviceRuntime(adapter=adapter, session_id=session_id, source_role="temperature")
    service = AcquisitionService()
    service.runtimes[device_id] = runtime
    await service._read_loop(device_id, runtime)
    await service._flush(device_id, runtime)
    assert runtime.last_error is None
    assert runtime.session_id == session_id
    assert runtime.sample_count == runtime.persisted_count == 3
    assert adapter.fetch_diagnostics.reconnect_count == 2
    with SessionLocal() as db:
        rows = list(
            db.scalars(select(TemperatureSample).where(TemperatureSample.session_id == session_id))
        )
        assert len(rows) == len({r.device_timestamp for r in rows}) == 3
        assert sorted(r.sequence for r in rows) == [1, 2, 3]
    runtime.received_times.clear()
    origin = datetime.now(UTC)
    runtime.received_times.extend(origin + timedelta(seconds=i * 6) for i in range(6))
    status = await service.status(device_id)
    assert status["expected_interval_ms"] == 1000
    assert status["observed_interval_ms"] == 6000
    assert status["cadence_degraded"] is True
    assert status["acquisition_diagnostics"]["successful_fetches"] == 3
