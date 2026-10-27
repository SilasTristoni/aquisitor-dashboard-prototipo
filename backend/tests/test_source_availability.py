from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Device,
    ElectricalSample,
    MeasurementSession,
    SessionDevice,
    SourceAvailability,
    User,
)
from app.schemas.contracts import PeriodReportRequest
from app.services.period_reporting import PeriodReportDataService, period_statistics
from app.services.source_availability import AvailabilityObserver, interval_dict, visual_segments

ORIGIN = datetime(2026, 10, 27, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def deterministic_observer(monkeypatch):
    @asynccontextmanager
    async def manual_ticks(_):
        yield

    monkeypatch.setattr(
        "app.services.source_availability.observe_source_availability", manual_ticks
    )


def at(seconds):
    return ORIGIN + timedelta(seconds=seconds)


def seed_session():
    with SessionLocal() as db:
        device = db.scalar(select(Device).where(Device.protocol == "gpm8213_serial"))
        user = db.scalar(select(User))
        session = MeasurementSession(
            device_id=device.id,
            user_id=user.id,
            name="Availability test",
            started_at=ORIGIN,
            status="running",
        )
        db.add(session)
        db.flush()
        db.add(SessionDevice(session_id=session.id, device_id=device.id, role="electrical"))
        db.commit()
        return session.id, device.id


def snapshot(session_id, state="connected", cause=None, readings=(), paused=False):
    return {
        "session_id": session_id,
        "state": state,
        "cause": cause,
        "readings": list(readings),
        "paused": paused,
    }


def test_two_disconnects_history_exports_and_api(client, auth_headers):
    session_id, device = seed_session()
    observer = AvailabilityObserver()
    readings = []
    for second in range(71):
        lost = 10 <= second < 20 or 40 <= second < 50
        paused = 60 <= second < 65
        if not lost and not paused:
            power = 0 if second == 5 else 100 + second
            readings.append((at(second), power))
            with SessionLocal() as db:
                db.add(
                    ElectricalSample(
                        session_id=session_id,
                        device_id=device,
                        received_timestamp=at(second),
                        active_power_w=power,
                        sequence=second + 1,
                        source="live",
                        quality="good",
                        original_values={"active_power": power},
                        original_units={"active_power": "W"},
                    )
                )
                db.commit()
        observer.tick(
            {
                device: snapshot(
                    session_id,
                    "recovering" if lost or paused or second == 30 else "connected",
                    "port_not_found"
                    if lost or paused
                    else "protocol_response_invalid"
                    if second == 30
                    else None,
                    readings,
                    paused,
                )
            },
            at(second),
        )
    with SessionLocal() as db:
        records = list(
            db.scalars(select(SourceAvailability).order_by(SourceAvailability.started_at))
        )
        assert len(records) == 2
        intervals = [interval_dict(row) for row in records]
        assert [(row["start"], row["end"]) for row in intervals] == [
            (at(10).isoformat(), at(20).isoformat()),
            (at(40).isoformat(), at(50).isoformat()),
        ]
        request = PeriodReportRequest(
            start=at(0),
            end=at(71),
            session_ids=[session_id],
            include_temperatures=False,
            include_power=True,
        )
        service = PeriodReportDataService(db)
        data = service.collect(request)
        before = deepcopy(data)
        preview = service.preview_data(data, request)
        assert len(preview["series"][0]["availability"]) == 2
        assert len([p for p in data["electrical"] if p["active_power_w"] == 0]) == 1
        overlays = visual_segments(intervals, data["electrical"], request.start, request.end)
        assert overlays[0] == [(at(9), 109), (at(10), 0), (at(20), 0), (at(20), 120)]
        assert overlays[1] == [(at(39), 139), (at(40), 0), (at(50), 0), (at(50), 150)]
        assert data["electrical"] == before["electrical"]
        assert period_statistics(data) == data["statistics"]
        from app.services.period_workbook import render_period_csv

        with_visual = render_period_csv(data, request)
        data["availability"] = []
        assert render_period_csv(data, request) == with_visual
        assert period_statistics(data) == before["statistics"]
        import io

        from openpyxl import load_workbook

        from app.services.period_workbook import render_period_xlsx

        def cells(content):
            workbook = load_workbook(io.BytesIO(content), data_only=True)
            return {sheet.title: list(sheet.values) for sheet in workbook}

        assert cells(render_period_xlsx(data, request)) == cells(
            render_period_xlsx(before, request)
        )
    response = client.get(
        f"/api/v1/sessions/{session_id}/availability?page_size=1", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["total"] == 2 and len(response.json()["items"]) == 1
    assert client.get(f"/api/v1/sessions/{session_id}/availability").status_code == 401


def test_pause_restart_and_unknown_gaps_do_not_extend_zero(client):
    session_id, device = seed_session()
    observer = AvailabilityObserver()
    lost = snapshot(session_id, "recovering", "serial_error")
    observer.tick({device: lost}, at(10))
    observer.tick({device: lost}, at(11))
    observer.tick({device: {**lost, "paused": True}}, at(12))
    observer.tick({device: {**lost, "paused": True}}, at(13))
    observer.tick({device: lost}, at(14))
    observer.tick({device: lost}, at(15))
    # New process/observer must not bridge the period with no evidence.
    observer = AvailabilityObserver()
    observer.tick({device: lost}, at(30))
    with SessionLocal() as db:
        rows = list(db.scalars(select(SourceAvailability).order_by(SourceAvailability.started_at)))
        assert len(rows) == 3
        assert interval_dict(rows[0])["end"] == at(11).isoformat()
        assert rows[0].end_reason == "paused"
        assert interval_dict(rows[1])["end"] == at(15).isoformat()
        assert rows[1].end_reason == "observation_ended"
    assert visual_segments([], [{"timestamp": at(0), "active_power_w": 0}], at(0), at(30)) == []


def test_timeout_or_stale_reading_cannot_confirm_recovery(client):
    session_id, device = seed_session()
    observer = AvailabilityObserver()
    observer.tick({device: snapshot(session_id, "recovering", "protocol_response_invalid")}, at(10))
    with SessionLocal() as db:
        assert list(db.scalars(select(SourceAvailability))) == []
    observer.tick({device: snapshot(session_id, "recovering", "port_not_found")}, at(11))
    observer.tick({device: snapshot(session_id, readings=[(at(10), 0)])}, at(12))
    with SessionLocal() as db:
        row = db.scalar(select(SourceAvailability))
        assert row.ended_at is None
        assert interval_dict(row)["confirmed_until"] == at(11).isoformat()


def test_optional_snapshot_extension_is_backward_compatible():
    import subprocess

    from test_result_portal import snapshot

    from app.portal.contracts import ResultSnapshot

    value = snapshot()
    ResultSnapshot.model_validate(value)  # Old publication without the optional extension.
    value["result"]["series"] = [
        {
            "availability": [
                {
                    "start": at(10).isoformat(),
                    "confirmed_until": at(20).isoformat(),
                    "end": at(20).isoformat(),
                    "end_reason": "reading_resumed",
                    "source": "electrical",
                    "evidence": "backend_observed_v1",
                }
            ]
        }
    ]
    ResultSnapshot.model_validate(value)
    # Actual r4 contract accepts the new field inside a v1 series.
    source = subprocess.check_output(
        ["git", "show", "30dbddc:backend/app/portal/contracts.py"], text=True
    )
    namespace = {"__name__": "legacy_contract"}
    exec(compile(source, "legacy_contract", "exec"), namespace)
    namespace["ResultSnapshot"].model_validate(value)
    value["result"]["series"][0]["availability"][0]["evidence"] = "inferred_gap"
    with pytest.raises(ValueError):
        ResultSnapshot.model_validate(value)


def test_existing_gpm_state_is_observed_without_serial_commands(client):
    from types import SimpleNamespace

    from app.adapters import DeviceReading, Gpm8213Adapter
    from app.adapters.transports import SerialTransportError
    from app.services.acquisition import DeviceRuntime
    from app.services.source_availability import runtime_snapshots

    session_id, device = seed_session()
    # An object with no transport methods proves this observation cannot perform I/O.
    adapter = Gpm8213Adapter("SYNTHETIC", 9600, transport=object())
    runtime = DeviceRuntime(adapter=adapter, protocol="gpm8213_serial", session_id=session_id)
    service = SimpleNamespace(runtimes={device: runtime}, last_connection_results={})
    observer = AvailabilityObserver()
    adapter._record_recovery_failure(SerialTransportError("protocol_timeout", "synthetic timeout"))
    observer.tick(runtime_snapshots(service), at(10))
    adapter._record_recovery_failure(SerialTransportError("port_not_found", "synthetic loss"))
    observer.tick(runtime_snapshots(service), at(11))
    adapter.connection_state = "connected"
    runtime.observed_readings.append(
        DeviceReading(
            received_timestamp=at(12), raw_power=0, raw_power_unit="W", power_w=0, temperatures_c=[]
        )
    )
    observer.tick(runtime_snapshots(service), at(12))
    with SessionLocal() as db:
        row = db.scalar(select(SourceAvailability))
        assert interval_dict(row)["start"] == at(11).isoformat()
        assert interval_dict(row)["end"] == at(12).isoformat()
        assert row.end_reason == "reading_resumed"


def test_report_interval_does_not_disclose_times_outside_authorized_period(client):
    from app.services.source_availability import collect_availability

    session_id, device = seed_session()
    with SessionLocal() as db:
        db.add(
            SourceAvailability(
                session_id=session_id,
                device_id=device,
                started_at=at(5),
                confirmed_until=at(20),
                ended_at=at(20),
                end_reason="reading_resumed",
                cause="port_not_found",
            )
        )
        db.commit()
        rows = collect_availability(db, [session_id], at(10), at(15))
    assert rows[0]["start"] == at(10).isoformat()
    assert rows[0]["confirmed_until"] == at(15).isoformat()
    assert rows[0]["end"] is None and rows[0]["end_reason"] is None
