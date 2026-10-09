import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from test_at4532_input_boundary import frame_for, setup_transport
from test_physical_engineering import _manual_at4532_device
from test_runtime_synchronization import sample

from app.adapters.base import DeviceInformation
from app.adapters.specific import At4532Normalizer, At4532Parser, At4532SerialAdapter
from app.services.acquisition import DeviceRuntime, acquisition_service
from app.services.protocol_probe import ProtocolProbeService


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["read", "full"])
async def test_config_frame_alone_is_not_continuous_acquisition(monkeypatch, mode):
    _, connection, transport = setup_transport(monkeypatch)
    connection.on_write = lambda p: (
        connection.schedule(0, frame_for(1)) if p.startswith(b"SYST") else None
    )
    adapter = At4532SerialAdapter("COM_BOUNDARY", 19200, transport, allow_identity_fallback=True)
    monkeypatch.setattr("app.services.protocol_probe.At4532SerialAdapter", lambda *a, **kw: adapter)
    report = await ProtocolProbeService()._run(_manual_at4532_device(), mode)
    assert len(report["readings"]) == 1
    assert not report["continuous_acquisition_verified"]
    assert report["readings"][0]["received_timestamp"]
    assert report["result"] == ("passed_with_warning" if mode == "read" else "failed")
    stages = {s["key"]: s for s in report["stages"]}
    assert stages["reading"]["status"] == "passed"
    if mode == "full":
        assert stages["acquisition"]["status"] == "failed"
    assert connection.input_resets == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,new_count,passed",
    [
        ("read", 0, False),
        ("read", 1, True),
        ("full", 0, False),
        ("full", 1, False),
        ("full", 2, True),
    ],
)
async def test_active_runtime_requires_new_distinct_observations(
    monkeypatch, mode, new_count, passed
):
    service = ProtocolProbeService()
    service.observation_timeout_seconds = 0.12
    device = _manual_at4532_device()
    device.name = "AT progression fixture"
    adapter = AsyncMock()
    adapter.get_device_information.return_value = DeviceInformation(adapter="AT fixture")
    adapter.transactions = []
    adapter.identity_status = "unconfirmed"
    adapter.protocol_status = "verified_by_measurement"
    adapter.expected_interval_seconds = 5.0
    adapter.input_boundary_diagnostics = lambda: {}
    old = sample("temperature", datetime.now(UTC) - timedelta(seconds=60))
    runtime = DeviceRuntime(adapter=adapter, latest=old)

    async def reader():
        # Re-publishing latest with identical provenance is not progress.
        runtime.observed_readings.append(old)
        for index in range(new_count):
            await asyncio.sleep(0.02)
            frame = frame_for(index)
            reading = At4532Normalizer().normalize(At4532Parser().parse(frame), frame)
            reading.received_timestamp = datetime.now(UTC)
            runtime.latest = reading
            runtime.observed_readings.extend([reading, reading])
        await asyncio.Event().wait()

    runtime.task = asyncio.create_task(reader())
    monkeypatch.setitem(acquisition_service.runtimes, device.id, runtime)
    monkeypatch.setattr(acquisition_service, "status", AsyncMock(return_value={"connected": True}))
    try:
        report = await service.run(device, mode)
        assert (report["result"] == "passed_with_warning") == passed
        assert len(report["readings"]) == min(new_count, 2 if mode == "full" else 1)
        assert report["continuous_acquisition_verified"] == (mode == "full" and passed)
        adapter.connect.assert_not_awaited()
        adapter.read_once.assert_not_awaited()
    finally:
        runtime.task.cancel()
        await asyncio.gather(runtime.task, return_exceptions=True)
