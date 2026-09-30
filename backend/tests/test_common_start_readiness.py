import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from test_runtime_synchronization import LiveSource, sample

from app.core.database import SessionLocal
from app.models.entities import Device, ElectricalSample, MeasurementSession, TemperatureSample
from app.services.acquisition import AcquisitionService, DeviceRuntime, acquisition_service


class ScheduledSource(LiveSource):
    def __init__(self, device, delays):
        super().__init__(device)
        self.delays = delays
        self.produced = []

    async def start_reading(self):
        for delay in self.delays:
            if delay is None:
                # Replay the exact observation to exercise preparation deduplication.
                yield self.produced[-1]
                continue
            await asyncio.sleep(delay)
            now = datetime.now(UTC)
            reading = sample(self.role, now).model_copy(
                update={
                    "device_timestamp": now + timedelta(minutes=5),
                }
            )
            self.last_message_at = now
            self.produced.append(reading)
            yield reading
        await asyncio.Event().wait()


def sources(monkeypatch, electrical, thermal):
    with SessionLocal() as db:
        devices = [
            Device(
                name="Ready GPM",
                protocol="gpm8213_serial",
                connection_type="serial",
                port="COM_READY_GPM",
                active=True,
            ),
            Device(
                name="Ready AT",
                protocol="at4532_serial",
                connection_type="serial",
                port="COM_READY_AT",
                baud_rate=19200,
                active=True,
            ),
        ]
        db.add_all(devices)
        db.commit()
        ids = [d.id for d in devices]
        adapters = {
            d.id: ScheduledSource(d, delays)
            for d, delays in zip(devices, [electrical, thermal], strict=True)
        }
    monkeypatch.setattr(acquisition_service, "_adapter_for", lambda d: adapters[d.id])
    return ids, adapters


def as_utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@pytest.mark.parametrize(
    "electrical,thermal",
    [
        ([0.4, 0.4, None, 0.4], [6.0]),
        ([0.15], [0.01, 0.02, None, 0.02]),
    ],
)
def test_api_start_preserves_independent_series(
    client, auth_headers, monkeypatch, electrical, thermal
):
    ids, adapters = sources(monkeypatch, electrical, thermal)
    response = client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={
            "name": "Independent source readiness",
            "electrical_device_id": ids[0],
            "temperature_device_id": ids[1],
            "sync_tolerance_ms": 1,
        },
    )
    assert response.status_code == 201, response.text
    session_id = response.json()["id"]
    origin = datetime.fromisoformat(acquisition_service.common_start_diagnostic["requested_at"])
    with SessionLocal() as db:
        session = db.get(MeasurementSession, session_id)
        assert as_utc(session.started_at) == origin
        for device_id, model in zip(ids, [ElectricalSample, TemperatureSample], strict=True):
            runtime = acquisition_service.runtimes[device_id]
            assert runtime.session_id == session_id and runtime.pending_start is None
            rows = list(
                db.scalars(
                    select(model).where(model.session_id == session_id).order_by(model.sequence)
                )
            )
            expected = adapters[device_id].produced
            assert len(rows) == len(expected) == runtime.persisted_count
            assert [as_utc(r.received_timestamp) for r in rows] == [
                r.received_timestamp for r in expected
            ]
            assert [as_utc(r.device_timestamp) for r in rows] == [
                r.device_timestamp for r in expected
            ]
            if model is ElectricalSample:
                assert [r.active_power_w for r in rows] == [r.power_w for r in expected]
            else:
                assert [
                    [c.temperature_c for c in sorted(r.channels, key=lambda c: c.channel)]
                    for r in rows
                ] == [r.temperatures_c for r in expected]
            assert all(
                r.device_id == device_id and as_utc(r.received_timestamp) >= origin for r in rows
            )
    assert (
        client.post(f"/api/v1/sessions/{session_id}/finish", headers=auth_headers).status_code
        == 200
    )


def test_api_preparation_timeout_preserves_other_reader(client, auth_headers, monkeypatch):
    ids, adapters = sources(monkeypatch, [0.01, 0.01], [])
    original = acquisition_service.prepare_common_start

    async def bounded(ids, tolerance):
        return await original(ids, tolerance, timeout_seconds=0.2)

    monkeypatch.setattr(acquisition_service, "prepare_common_start", bounded)
    response = client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={
            "name": "No thermal sample",
            "electrical_device_id": ids[0],
            "temperature_device_id": ids[1],
        },
    )
    assert response.status_code == 409
    assert acquisition_service.common_start_diagnostic["state"] == "timeout"
    assert adapters[ids[0]].disconnect_calls == 0
    runtime = acquisition_service.runtimes[ids[0]]
    assert runtime.sample_count == 2 and not runtime.task.done()
    assert all(
        r.pending_start is None and r.session_id is None
        for r in acquisition_service.runtimes.values()
    )


@pytest.mark.asyncio
async def test_cancel_preparation_keeps_readers_and_clears_buffers():
    service = AcquisitionService()
    tasks = [asyncio.create_task(asyncio.Event().wait()) for _ in range(2)]
    for device_id, task in enumerate(tasks, 1):
        service.runtimes[device_id] = DeviceRuntime(
            adapter=None, task=task, source_role="electrical" if device_id == 1 else "temperature"
        )
    preparation = asyncio.create_task(service.prepare_common_start([1, 2], 1))
    try:
        await asyncio.sleep(0)
        service._capture_prepared(1, sample("electrical", datetime.now(UTC)))
        preparation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await preparation
        assert not service._preparations
        assert all(not t.done() for t in tasks)
        assert all(
            r.session_id is None and r.pending_start is None for r in service.runtimes.values()
        )
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def test_samples_during_second_connection_are_retained(client, auth_headers, monkeypatch):
    ids, adapters = sources(monkeypatch, [0.01, 0.01], [0.01])
    original = adapters[ids[1]].connect

    async def slow_connection():
        await asyncio.sleep(0.1)
        await original()

    adapters[ids[1]].connect = slow_connection
    response = client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={
            "name": "Capture during connect",
            "electrical_device_id": ids[0],
            "temperature_device_id": ids[1],
        },
    )
    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(ElectricalSample).where(ElectricalSample.session_id == response.json()["id"])
            )
        )
        assert len(rows) == len(adapters[ids[0]].produced) == 2


@pytest.mark.asyncio
async def test_cancel_session_route_leaves_no_session(client, monkeypatch):
    from app.api.routes import start_session
    from app.models.entities import User
    from app.schemas.contracts import SessionCreate

    ids, adapters = sources(monkeypatch, [0.01], [])
    with SessionLocal() as db:
        user = db.scalar(select(User))
        before = set(db.scalars(select(MeasurementSession.id)))
        request = asyncio.create_task(
            start_session(
                SessionCreate(
                    name="Cancelled preparation",
                    electrical_device_id=ids[0],
                    temperature_device_id=ids[1],
                ),
                db,
                user,
            )
        )
        try:
            async with asyncio.timeout(2):
                while not adapters[ids[0]].produced:
                    await asyncio.sleep(0.01)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert set(db.scalars(select(MeasurementSession.id))) == before
            assert all(
                r.pending_start is None and r.session_id is None
                for r in acquisition_service.runtimes.values()
            )
            assert not acquisition_service.runtimes[ids[0]].task.done()
            assert adapters[ids[0]].disconnect_calls == 0
        finally:
            for device_id in ids:
                await acquisition_service._disconnect_device(device_id)
