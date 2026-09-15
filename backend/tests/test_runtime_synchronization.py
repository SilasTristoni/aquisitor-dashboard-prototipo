import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.adapters.base import DeviceReading, DeviceStatus
from app.adapters.transports import SerialTransportError
from app.core.database import SessionLocal
from app.models.entities import Device
from app.services.acquisition import AcquisitionService, DeviceRuntime, acquisition_service
from app.services.protocol_probe import protocol_probe_service
from app.services.serial_diagnostic import real_serial_diagnostic_service


class LiveSource:
    expected_interval_seconds = 1.0

    def __init__(self, device):
        self.port = device.port
        self.role = "electrical" if device.protocol == "gpm8213_serial" else "temperature"
        self.connected = False
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.last_message_at = None

    async def connect(self):
        self.connect_calls += 1
        self.connected = True

    async def disconnect(self):
        self.disconnect_calls += 1
        self.connected = False

    async def stop_reading(self):
        pass

    async def get_status(self):
        return DeviceStatus(
            connected=self.connected,
            state="reading",
            reading=True,
            last_message_at=self.last_message_at,
        )

    async def start_reading(self):
        while self.connected:
            self.last_message_at = datetime.now(UTC)
            yield sample(self.role, self.last_message_at)
            await asyncio.sleep(1)


def sample(role, received):
    return DeviceReading(
        timestamp=received,
        received_timestamp=received,
        power_w=50 if role == "electrical" else None,
        raw_power=50 if role == "electrical" else None,
        raw_power_unit="W",
        temperatures_c=[None] * 24 + [22.0] * 8 if role == "temperature" else [],
    )


def test_running_one_hz_sources_start_and_diagnostics_leave_acquisition_intact(
    client,
    auth_headers,
    monkeypatch,
):
    with SessionLocal() as db:
        devices = [
            Device(
                name="GPM live",
                protocol="gpm8213_serial",
                connection_type="serial",
                port="COM_RUNTIME1",
                baud_rate=9600,
            ),
            Device(
                name="AT live",
                protocol="at4532_serial",
                connection_type="serial",
                port="COM_RUNTIME2",
                baud_rate=19200,
            ),
        ]
        db.add_all(devices)
        db.commit()
        ids = [d.id for d in devices]
    monkeypatch.setattr(acquisition_service, "_adapter_for", LiveSource)
    probe = AsyncMock(side_effect=AssertionError("Diagnostic must not construct/open an adapter"))
    raw = AsyncMock(side_effect=AssertionError("Diagnostic must not open a second serial"))
    monkeypatch.setattr(protocol_probe_service, "_run", probe)
    monkeypatch.setattr(real_serial_diagnostic_service, "_open", raw)
    token = auth_headers["Authorization"].split()[1]
    with client.websocket_connect(f"/api/v1/ws?token={token}") as ws:
        for device_id in ids:
            assert (
                client.post(
                    f"/api/v1/devices/{device_id}/connect",
                    headers=auth_headers,
                ).status_code
                == 200
            )
        seen = set()
        while len(seen) < 2:
            event = ws.receive_json()
            assert event["type"] != "heartbeat"
            if event["type"] == "measurement.created":
                seen.add(event["payload"]["device_id"])
        runtimes = [acquisition_service.runtimes[i] for i in ids]
        tasks = [r.task for r in runtimes]
        # Call both diagnostic entry points for each already collecting instrument.
        for device_id, runtime in zip(ids, runtimes, strict=True):
            connection_test = client.post(
                f"/api/v1/devices/{device_id}/test",
                headers=auth_headers,
            )
            assert connection_test.status_code == 409, connection_test.text
            response = client.post(
                f"/api/v1/devices/{device_id}/protocol-probe",
                headers=auth_headers,
                json={"mode": "full", "operator_confirmed": True},
            )
            assert response.status_code == 409, response.text
            assert "aquisição pelo ThermoPower" in response.json()["error"]["message"]
            response = client.post(
                "/api/v1/hardware/serial-diagnostic/open",
                headers=auth_headers,
                json={
                    "port": runtime.adapter.port.lower(),
                    "baud_rate": 19200,
                    "use_engineering_assumption_8n1": True,
                    "timeout_s": 1,
                    "read_timeout_s": 1,
                },
            )
            assert response.status_code == 409, response.text
            assert "Desconecte-o" in response.json()["error"]["message"]
        counts = [r.sample_count for r in runtimes]
        started = client.post(
            "/api/v1/sessions",
            headers=auth_headers,
            json={
                "name": "Already acquiring at 1 Hz",
                "electrical_device_id": ids[0],
                "temperature_device_id": ids[1],
            },
        )
        assert started.status_code == 201, started.text
        session_id = started.json()["id"]
        seen = set()
        while len(seen) < 2:
            event = ws.receive_json()
            assert event["type"] != "heartbeat"
            if (
                event["type"] == "measurement.created"
                and event["payload"]["session_id"] == session_id
            ):
                seen.add(event["payload"]["device_id"])
        for i, runtime in enumerate(runtimes):
            assert runtime.task is tasks[i] and not runtime.task.done()
            assert runtime.sample_count > counts[i]
            assert runtime.last_error is None
            assert runtime.adapter.connect_calls == 1
            assert runtime.adapter.disconnect_calls == 0
            assert runtime.persisted_count >= 1
        probe.assert_not_awaited()
        raw.assert_not_awaited()
        assert acquisition_service.common_start_diagnostic["state"] == "matched"
        assert (
            client.post(
                f"/api/v1/sessions/{session_id}/finish",
                headers=auth_headers,
            ).status_code
            == 200
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("transient", ["connected", "last_error", "status_exception"])
async def test_best_pair_in_new_queues_survives_transient_status(monkeypatch, transient, caplog):
    service = AcquisitionService()
    tasks = []
    for device_id, role in [(1, "electrical"), (2, "temperature")]:
        adapter = AsyncMock()
        adapter.get_status.return_value = DeviceStatus(
            connected=transient != "connected", state="reading", reading=True
        )
        if transient == "status_exception":
            adapter.get_status.side_effect = OSError("transient status observation")
        task = asyncio.create_task(asyncio.Event().wait())
        tasks.append(task)
        service.runtimes[device_id] = DeviceRuntime(
            adapter=adapter,
            task=task,
            source_role=role,
            last_error="transient previous error" if transient == "last_error" else None,
        )
    connect = AsyncMock(side_effect=AssertionError("Must not reconnect a running reader"))
    monkeypatch.setattr(service, "connect", connect)
    caplog.set_level("INFO", logger="app.services.acquisition")
    pending = asyncio.create_task(service.prepare_common_start([1, 2], 10, timeout_seconds=1))
    try:
        await asyncio.sleep(0.02)
        origin = datetime.now(UTC)
        await asyncio.sleep(0.05)
        for device_id, role in [(1, "electrical"), (2, "temperature")]:
            runtime = service.runtimes[device_id]
            runtime.pending_start.append(sample(role, origin))
            if device_id == 1:
                runtime.pending_start.append(sample(role, origin + timedelta(milliseconds=30)))
            runtime.latest = runtime.pending_start[-1]
        assert await pending == origin
        assert service.common_start_diagnostic["best_delta_ms"] == 0
        assert service.common_start_diagnostic["sources"]["1"]["fresh_samples"] == 2
        assert "task_running" in caplog.text and "latest_received_timestamp" in caplog.text
        connect.assert_not_awaited()
    finally:
        pending.cancel()
        for task in tasks:
            task.cancel()
        await asyncio.gather(pending, *tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_diagnostic_external_busy_is_distinct(monkeypatch):
    from app.adapters.transports import SerialTransportConfiguration

    def busy(**kwargs):
        raise PermissionError("Access denied by another process")

    monkeypatch.setattr(real_serial_diagnostic_service, "serial_factory", busy)
    with pytest.raises(SerialTransportError) as caught:
        await real_serial_diagnostic_service.open(
            SerialTransportConfiguration(
                port="COM_EXTERNAL",
                baud_rate=19200,
                data_bits=8,
                parity="N",
                stop_bits=1,
                timeout_s=1,
                read_timeout_s=1,
            )
        )
    assert caught.value.code == "port_busy"
    assert "processo externo" in str(caught.value)
    assert "fabricante" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("stopped", [False, True])
async def test_no_pair_or_stopped_reader_times_out_without_affecting_other_source(
    monkeypatch, stopped
):
    service = AcquisitionService()
    tasks = [asyncio.create_task(asyncio.Event().wait()) for _ in range(2)]
    for device_id, task in zip([1, 2], tasks, strict=True):
        adapter = AsyncMock()
        adapter.get_status.return_value = DeviceStatus(
            connected=True, state="reading", reading=True
        )
        service.runtimes[device_id] = DeviceRuntime(
            adapter=adapter,
            task=task,
            source_role="electrical" if device_id == 1 else "temperature",
        )
    pending = asyncio.create_task(service.prepare_common_start([1, 2], 10, timeout_seconds=0.15))
    try:
        await asyncio.sleep(0.02)
        now = datetime.now(UTC)
        service.runtimes[1].pending_start.append(sample("electrical", now))
        if stopped:
            service.runtimes[2].pending_start.append(sample("temperature", now))
            tasks[1].cancel()
            await asyncio.gather(tasks[1], return_exceptions=True)
        with pytest.raises(TimeoutError, match="common_start_diagnostic"):
            await pending
        assert not tasks[0].done()
        assert service.common_start_diagnostic["state"] == "timeout"
        for runtime in service.runtimes.values():
            assert runtime.pending_start is None and runtime.session_id is None
            runtime.adapter.disconnect.assert_not_awaited()
    finally:
        pending.cancel()
        for task in tasks:
            task.cancel()
        await asyncio.gather(pending, *tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_diagnostic_rechecks_ownership_after_in_progress_connection():
    service = AcquisitionService()
    entered = False

    async def diagnostic():
        nonlocal entered
        async with service.diagnostic_port("com_race"):
            entered = True

    async with service._port_lock("COM_RACE"):
        attempt = asyncio.create_task(diagnostic())
        await asyncio.sleep(0)
        assert not attempt.done()
        adapter = AsyncMock()
        adapter.port = "COM_RACE"
        service.runtimes[1] = DeviceRuntime(adapter=adapter)
    with pytest.raises(SerialTransportError) as caught:
        await attempt
    assert caught.value.code == "port_owned_by_thermopower"
    assert not entered
