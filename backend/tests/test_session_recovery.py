"""Recovery uses the existing simulator/attachment, never real instruments or customer databases."""

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, text

from app.core.database import SessionLocal, engine
from app.models.entities import (
    Device,
    ElectricalSample,
    MeasurementSession,
    SessionDevice,
    SessionRecovery,
    SystemEvent,
    User,
)
from app.services.acquisition import acquisition_service
from app.services.instance_guard import InstanceGuard
from app.services.session_recovery import recovery_service


def pending_session(second_source=False):
    with SessionLocal() as db:
        device = db.scalar(select(Device).where(Device.protocol == "simulator"))
        session = MeasurementSession(
            device_id=device.id,
            user_id=db.scalar(select(User.id)),
            name="Recovery synthetic",
            started_at=datetime.now(UTC) - timedelta(hours=1),
            status="running",
        )
        db.add(session)
        db.flush()
        ids = [device.id]
        db.add(SessionDevice(session_id=session.id, device_id=device.id, role="combined"))
        if second_source:
            missing = Device(name="Unavailable synthetic", protocol="simulator")
            db.add(missing)
            db.flush()
            ids.append(missing.id)
            db.add(SessionDevice(session_id=session.id, device_id=missing.id, role="temperature"))
        db.add(
            ElectricalSample(
                session_id=session.id,
                device_id=device.id,
                sequence=7,
                received_timestamp=session.started_at,
                active_power_w=123.456,
            )
        )
        db.flush()
        recovery_service._pending(db, session, "unexpected_shutdown", datetime.now(UTC))
        db.commit()
        return session.id, ids


def test_recovery_requires_confirmation_preserves_identity_and_sequences(client, auth_headers):
    session_id, ids = pending_session()
    result = client.get("/api/v1/recovery/sessions", headers=auth_headers).json()
    assert result["total"] == 1
    assert result["items"][0]["counts"] == {"electrical": 1, "thermal": 0}
    assert acquisition_service.runtimes == {}
    assert (
        client.post(f"/api/v1/sessions/{session_id}/resume", headers=auth_headers).status_code
        == 409
    )
    original_start = result["items"][0]["started_at"]
    response = client.post(
        f"/api/v1/recovery/sessions/{session_id}", headers=auth_headers, json={"action": "resume"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == session_id
    assert acquisition_service.runtimes[ids[0]].persisted_count >= 7
    assert datetime.fromisoformat(
        client.get(f"/api/v1/sessions/{session_id}", headers=auth_headers).json()["started_at"]
    ) == datetime.fromisoformat(original_start)
    assert (
        client.post(
            f"/api/v1/recovery/sessions/{session_id}",
            headers=auth_headers,
            json={"action": "resume"},
        ).status_code
        == 409
    )
    assert (
        client.post(f"/api/v1/sessions/{session_id}/finish", headers=auth_headers).status_code
        == 200
    )
    assert client.get("/api/v1/recovery/sessions", headers=auth_headers).json()["total"] == 0
    with SessionLocal() as db:
        first = db.scalar(
            select(ElectricalSample)
            .where(ElectricalSample.session_id == session_id)
            .order_by(ElectricalSample.id)
        )
        assert first.active_power_w == 123.456 and first.sequence == 7
        event = db.scalar(
            select(SystemEvent).where(SystemEvent.category == "session_recovery_resume")
        )
        assert event.details["actor_id"] and event.details["resumed_at"]


def test_close_and_pagination_permissions(client, auth_headers):
    session_id, _ = pending_session()
    assert client.get("/api/v1/recovery/sessions").status_code == 401
    with SessionLocal() as db:
        from app.core.security import create_access_token

        viewer = User(
            name="Read only",
            email="recovery-viewer@example.invalid",
            password_hash="unused",
            role="viewer",
        )
        db.add(viewer)
        db.commit()
        token = create_access_token(str(viewer.id), "viewer")
    assert (
        client.get(
            "/api/v1/recovery/sessions", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 403
    )
    assert (
        client.get("/api/v1/recovery/sessions?page_size=51", headers=auth_headers).status_code
        == 422
    )
    response = client.post(
        f"/api/v1/recovery/sessions/{session_id}", headers=auth_headers, json={"action": "close"}
    )
    assert response.json()["status"] == "interrupted_closed"
    assert acquisition_service.runtimes == {}
    assert (
        client.get(f"/api/v1/reports/sessions/{session_id}.csv", headers=auth_headers).status_code
        == 200
    )
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ElectricalSample)) == 1
        assert db.get(SessionRecovery, session_id).state == "resolved"


def test_partial_recovery_and_all_sources_unavailable(client, auth_headers, monkeypatch):
    session_id, ids = pending_session(second_source=True)
    original = acquisition_service.resume_session

    async def partial(device_id, sid):
        if device_id == ids[1]:
            raise ConnectionError("synthetic absent source")
        await original(device_id, sid)

    monkeypatch.setattr(
        acquisition_service, "resume_session", AsyncMock(side_effect=ConnectionError)
    )
    assert (
        client.post(
            f"/api/v1/recovery/sessions/{session_id}",
            headers=auth_headers,
            json={"action": "resume"},
        ).status_code
        == 422
    )
    with SessionLocal() as db:
        assert db.get(SessionRecovery, session_id).state == "pending"
    monkeypatch.setattr(acquisition_service, "resume_session", partial)
    response = client.post(
        f"/api/v1/recovery/sessions/{session_id}", headers=auth_headers, json={"action": "resume"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["sources"] == [ids[0]]
    assert response.json()["unavailable_sources"][0]["device_id"] == ids[1]


def test_second_process_guard_does_not_reclassify_active_session(client, auth_headers):
    with pytest.raises(RuntimeError, match="uso exclusivo"):
        InstanceGuard(engine).acquire()
    session_id, _ = pending_session()
    assert (
        client.post(
            f"/api/v1/recovery/sessions/{session_id}",
            headers=auth_headers,
            json={"action": "resume"},
        ).status_code
        == 200
    )
    assert client.get("/api/v1/recovery/sessions", headers=auth_headers).json()["total"] == 0
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA synchronous")) == 2


CHILD = r"""
import json, os, time
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from app.main import app
from app.core.database import SessionLocal
from app.models.entities import Device, ElectricalSample, MeasurementSession
from app.services.acquisition import acquisition_service
mode, ready = os.environ['RECOVERY_MODE'], Path(os.environ['RECOVERY_READY'])
with TestClient(app) as client:
    login=client.post('/api/v1/auth/login',json={'email':os.environ['THERMOPOWER_DEMO_ADMIN_EMAIL'],'password':os.environ['THERMOPOWER_DEMO_ADMIN_PASSWORD']})
    headers={'Authorization':'Bearer '+login.json()['access_token']}
    pending=client.get('/api/v1/recovery/sessions',headers=headers).json()
    assert not acquisition_service.runtimes
    if mode=='start':
        with SessionLocal() as db:
            device_id=db.scalar(select(Device.id).where(Device.protocol=='simulator'))
        response=client.post('/api/v1/sessions',headers=headers,
                            json={'name':'Process crash synthetic','device_id':device_id})
        assert response.status_code==201,response.text
        sid=response.json()['id']
    elif mode in ('resume','close'):
        assert pending['total']==1,pending
        sid=pending['items'][0]['id']
        response=client.post('/api/v1/recovery/sessions/'+str(sid),headers=headers,json={'action':mode})
        assert response.status_code==200,response.text
    else:
        assert pending['total']==0,pending
        sid=1
    if mode in ('start','resume'):
        time.sleep(3.5)
    with SessionLocal() as db:
        rows=list(db.scalars(select(ElectricalSample).where(ElectricalSample.session_id==sid).order_by(ElectricalSample.id)))
        assert db.scalar(text('PRAGMA integrity_check'))=='ok'
        assert not db.execute(text('PRAGMA foreign_key_check')).all()
        data={'id':sid,'count':len(rows),'sequences':[r.sequence for r in rows],
              'values':[r.active_power_w for r in rows],
              'started_at':str(db.get(MeasurementSession,sid).started_at),'pending':pending}
    ready.write_text(json.dumps(data),encoding='utf-8')
    if mode in ('start','resume'):
        time.sleep(120)
"""


def test_repeated_abrupt_process_death_and_real_restart(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / "crash.sqlite"
    previous = None
    for index, mode in enumerate(("start", "resume", "resume", "close", "verify")):
        ready = tmp_path / f"ready-{index}.json"
        env = {
            **os.environ,
            "THERMOPOWER_DATABASE_URL": f"sqlite:///{database.as_posix()}",
            "THERMOPOWER_ENVIRONMENT": "test",
            "THERMOPOWER_LOG_DIRECTORY": str(tmp_path / "logs"),
            "RECOVERY_MODE": mode,
            "RECOVERY_READY": str(ready),
        }
        with (tmp_path / f"child-{index}.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-c", CHILD], cwd=backend, env=env, stdout=log, stderr=log
            )
            try:
                deadline = time.monotonic() + 35
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert ready.exists(), (tmp_path / f"child-{index}.log").read_text(encoding="utf-8")
                current = json.loads(ready.read_text(encoding="utf-8"))
                assert current["count"] > 0
                assert len(current["sequences"]) == len(set(current["sequences"]))
                if previous:
                    assert current["id"] == previous["id"]
                    assert current["started_at"] == previous["started_at"]
                    assert current["values"][: previous["count"]] == previous["values"]
                    if mode == "resume":
                        assert current["count"] > previous["count"]
                previous = current
                if mode in {"start", "resume"}:
                    process.kill()  # Only the synthetic child created above.
                assert process.wait(timeout=10) == 0 or mode in {"start", "resume"}
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)


def test_short_restart_breaks_energy_and_plot_without_artificial_rows(client):
    from app.schemas.contracts import PeriodReportRequest
    from app.services.period_documents import _segments
    from app.services.period_reporting import PeriodReportDataService

    session_id, ids = pending_session()
    with SessionLocal() as db:
        session = db.get(MeasurementSession, session_id)
        start = session.started_at.replace(tzinfo=UTC)
        db.add(
            ElectricalSample(
                session_id=session_id,
                device_id=ids[0],
                sequence=8,
                received_timestamp=start + timedelta(seconds=4),
                active_power_w=123.456,
            )
        )
        db.add(
            SystemEvent(
                session_id=session_id,
                category="session_recovery_resume",
                message="Synthetic",
                details={"resumed_at": (start + timedelta(seconds=2)).isoformat()},
            )
        )
        db.commit()
        request = PeriodReportRequest(
            start=start, end=start + timedelta(seconds=5), session_ids=[session_id]
        )
        data = PeriodReportDataService(db).collect(request)
        assert len(data["electrical"]) == 2
        assert len(_segments(data["electrical"])) == 2
        preview = PeriodReportDataService(db).preview_data(data, request)
        assert len(preview["series"][0]["gaps"]) == 1
        assert data["statistics"]["electrical"]["energy_wh"] == 0


def test_controlled_shutdown_distinct_from_crash_and_finalized_sessions(client):
    sid, _ = pending_session()
    with SessionLocal() as db:
        session = db.get(MeasurementSession, sid)
        session.status = "running"
        recovery_service.register(db, sid)
        finished = MeasurementSession(
            name="Already finished",
            device_id=session.device_id,
            user_id=session.user_id,
            status="finished",
        )
        db.add(finished)
        db.commit()
    recovery_service.shutdown()
    recovery_service.start()
    with SessionLocal() as db:
        listing = recovery_service.listing(db, 1, 10)
        assert listing["total"] == 1
        assert listing["items"][0]["reason"] == "controlled_shutdown"
        assert db.get(MeasurementSession, sid).status == "suspended"


def test_restart_during_attachment_returns_to_pending(client):
    sid, _ = pending_session()
    with SessionLocal() as db:
        db.get(SessionRecovery, sid).state = "resuming"
        db.commit()
    recovery_service.start()  # No runtime exists, and this test already owns the DB guard.
    with SessionLocal() as db:
        assert db.get(SessionRecovery, sid).state == "pending"
        assert recovery_service.listing(db, 1, 10)["total"] == 1
    assert not acquisition_service.runtimes


def test_storage_capacity_warning_is_bounded_and_audited(client, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.services.session_recovery.shutil.disk_usage",
        lambda _: SimpleNamespace(free=50 * 1024**2),
    )
    recovery_service.storage_checked_at = None
    recovery_service.storage = {"state": "ok"}
    recovery_service.check_storage()
    recovery_service.check_storage()
    assert recovery_service.storage["state"] == "critical"
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(SystemEvent)
                .where(SystemEvent.category == "storage_capacity")
            )
            == 1
        )


def test_streaming_chart_matches_original_nearest_rule():
    from types import SimpleNamespace

    from app.services.synchronization import _ForwardNearest, _nearest

    start = datetime(2026, 11, 1, tzinfo=UTC)
    rows = [
        SimpleNamespace(received_timestamp=start + timedelta(seconds=second))
        for second in (0, 5, 10, 10, 15, 40, 45)
    ]
    cursor = _ForwardNearest(iter(rows))
    for tick in range(100):
        target = start + timedelta(seconds=tick / 2)
        assert cursor.at(target, 1500) == _nearest(
            rows, [r.received_timestamp for r in rows], target, 1500
        )


@pytest.mark.asyncio
async def test_ownership_loss_stops_producer_when_pause_cannot_flush(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from app.services.session_recovery import RecoveryService

    supervisor = RecoveryService()
    supervisor.ready = True
    supervisor.guard.check = Mock(side_effect=ConnectionError("synthetic ownership loss"))
    source = SimpleNamespace(
        runtimes={1: object()}, pause_session=AsyncMock(side_effect=OSError), disconnect=AsyncMock()
    )
    monkeypatch.setattr("app.services.session_recovery.asyncio.sleep", AsyncMock())
    await supervisor.monitor(source)
    assert not supervisor.ready
    source.pause_session.assert_awaited_once_with(1)
    source.disconnect.assert_awaited_once_with(1)


def test_unowned_instance_cannot_start_or_connect(client, auth_headers, monkeypatch):
    monkeypatch.setattr(recovery_service, "ready", False)
    with SessionLocal() as db:
        device_id = db.scalar(select(Device.id).where(Device.protocol == "simulator"))
    assert (
        client.post(f"/api/v1/devices/{device_id}/connect", headers=auth_headers).status_code == 503
    )
    assert (
        client.post(
            "/api/v1/devices/connect-sources",
            headers=auth_headers,
            json={"electrical_device_id": device_id},
        ).status_code
        == 503
    )
    assert (
        client.post(
            "/api/v1/sessions",
            headers=auth_headers,
            json={"name": "Blocked", "device_id": device_id},
        ).status_code
        == 503
    )
    assert not acquisition_service.runtimes
