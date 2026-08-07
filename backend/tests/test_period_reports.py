from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.release import release_configuration
from app.models.entities import (
    Device,
    ElectricalSample,
    Measurement,
    MeasurementSession,
    Report,
    SessionChannelConfiguration,
    TemperatureChannelValue,
    TemperatureMeasurement,
    TemperatureSample,
    User,
)
from app.schemas.contracts import PeriodReportRequest
from app.services.period_reporting import PeriodReportDataService, downsample_time_buckets
from app.services.usb_discovery import usb_discovery_service


def _seed_period_data() -> tuple[datetime, datetime, list[int]]:
    start = datetime(2026, 1, 15, 13, 0, tzinfo=UTC)
    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(User.email == release_configuration.homologation_email)
        )
        device = db.scalar(select(Device).where(Device.name == "Aquisitor simulado"))
        sessions = [
            MeasurementSession(
                device_id=device.id,
                user_id=user.id,
                name="Período A",
                started_at=start,
                ended_at=start + timedelta(minutes=3),
                status="finished",
            ),
            MeasurementSession(
                device_id=device.id,
                user_id=user.id,
                name="Período B concorrente",
                started_at=start + timedelta(seconds=5),
                ended_at=start + timedelta(minutes=2),
                status="finished",
            ),
        ]
        db.add_all(sessions)
        db.flush()
        for session in sessions:
            db.add(
                SessionChannelConfiguration(
                    session_id=session.id,
                    channel=1,
                    name=f"Entrada {session.id}",
                    enabled=True,
                    sensor_type="K",
                    unit="°C",
                    correction_offset=0,
                    color="#2563EB",
                    display_order=1,
                )
            )

        electrical_rows = [
            (sessions[0], 0, 100.0, True),
            (sessions[0], 10, 200.0, True),
            (sessions[0], 120, 300.0, False),
            (sessions[1], 5, 400.0, True),
            (sessions[1], 15, 400.0, True),
        ]
        for session, seconds, power, has_device_timestamp in electrical_rows:
            timestamp = start + timedelta(seconds=seconds)
            db.add(
                ElectricalSample(
                    session_id=session.id,
                    device_id=device.id,
                    device_timestamp=timestamp if has_device_timestamp else None,
                    received_timestamp=timestamp,
                    active_power_w=power,
                    voltage_v=220,
                    current_a=power / 220,
                    power_factor=0.95,
                    quality="good",
                    source="test",
                    original_values={"active_power": power},
                    original_units={"active_power": "W"},
                    raw_payload={},
                )
            )
        for session, seconds, temperature in [
            (sessions[0], 0, 30.0),
            (sessions[0], 10, 32.0),
            (sessions[1], 5, 40.0),
            (sessions[1], 15, 42.0),
        ]:
            timestamp = start + timedelta(seconds=seconds)
            sample = TemperatureSample(
                session_id=session.id,
                device_id=device.id,
                device_timestamp=timestamp,
                received_timestamp=timestamp,
                quality="good",
                source="test",
                raw_payload={},
            )
            sample.channels.append(
                TemperatureChannelValue(
                    channel=1,
                    temperature_c=temperature,
                    original_value=temperature,
                    original_unit="°C",
                    quality="good",
                )
            )
            db.add(sample)
        db.commit()
        return start, start + timedelta(minutes=3), [session.id for session in sessions]


def _payload(start: datetime, end: datetime) -> dict:
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "timezone": "America/Sao_Paulo",
        "title": "Ensaio período A/B",
        "channels": [1],
        "table_max_rows": 20,
        "dpi": 96,
    }


def test_period_contract_normalizes_naive_local_time_and_validates_metrics():
    request = PeriodReportRequest(
        start=datetime(2026, 1, 15, 10, 0),
        end=datetime(2026, 1, 15, 11, 0),
        channels=[2, 1, 2],
    )
    assert request.start == datetime(2026, 1, 15, 13, 0, tzinfo=UTC)
    assert request.channels == [1, 2]
    with pytest.raises(ValueError, match="posterior"):
        PeriodReportRequest(start=request.end, end=request.start)
    with pytest.raises(ValueError, match="ao menos uma métrica"):
        PeriodReportRequest(
            start=request.start,
            end=request.end,
            include_power=False,
            include_temperatures=False,
            include_electrical_details=False,
        )


def test_period_statistics_do_not_integrate_between_sessions(client: TestClient):
    start, end, session_ids = _seed_period_data()
    request = PeriodReportRequest(**_payload(start, end))
    with SessionLocal() as db:
        data = PeriodReportDataService(db).collect(request)
    assert [session["id"] for session in data["sessions"]] == session_ids
    assert data["statistics"]["general"]["session_count"] == 2
    assert data["statistics"]["general"]["gap_count"] >= 1
    assert data["statistics"]["general"]["timestamp_fallback_count"] == 1
    assert data["statistics"]["electrical"]["excluded_energy_intervals"] == 1
    assert data["statistics"]["electrical"]["energy_wh"] == pytest.approx(1.527777, rel=1e-5)
    assert {row["session_id"] for row in data["table_rows"]} == set(session_ids)


def test_period_endpoints_render_and_audit_files(client: TestClient, auth_headers: dict[str, str]):
    start, end, _ = _seed_period_data()
    payload = {**_payload(start, end), "channels": list(range(1, 10))}
    preview = client.post("/api/v1/reports/period/preview", headers=auth_headers, json=payload)
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["series"]) == 2
    for endpoint, media, signature in [
        ("pdf", "application/pdf", b"%PDF"),
        ("chart.png", "image/png", b"\x89PNG"),
        ("chart.jpeg", "image/jpeg", b"\xff\xd8"),
    ]:
        response = client.post(
            f"/api/v1/reports/period/{endpoint}", headers=auth_headers, json=payload
        )
        assert response.status_code == 200, response.text
        assert media in response.headers["content-type"]
        assert response.content.startswith(signature)
        assert "attachment" in response.headers["content-disposition"]
        if endpoint == "pdf":
            assert b"/Subtype /Image" in response.content
            assert response.content.count(b"/Type /Page") >= 3
    history = client.get("/api/v1/reports", headers=auth_headers).json()
    period_reports = [row for row in history if row["scope_type"] == "period"]
    assert len(period_reports) == 3
    assert all(row["status"] == "completed" for row in period_reports)


def test_period_endpoint_reports_clear_empty_data_error(
    client: TestClient, auth_headers: dict[str, str]
):
    response = client.post(
        "/api/v1/reports/period/preview",
        headers=auth_headers,
        json=_payload(datetime(2035, 1, 1, tzinfo=UTC), datetime(2035, 1, 2, tzinfo=UTC)),
    )
    assert response.status_code == 422
    assert "Nenhuma sessão" in response.json()["error"]["message"]


def test_downsampling_preserves_global_extremes():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    points = [
        {"timestamp": start + timedelta(seconds=index), "active_power_w": float(index)}
        for index in range(1000)
    ]
    points[501]["active_power_w"] = -500
    reduced = downsample_time_buckets(points, ["active_power_w"], 80)
    values = [point["active_power_w"] for point in reduced]
    assert len(reduced) <= 80
    assert min(values) == -500
    assert max(values) == 999
    assert reduced[0]["timestamp"] == points[0]["timestamp"]
    assert reduced[-1]["timestamp"] == points[-1]["timestamp"]


def test_period_service_falls_back_to_unmigrated_legacy_rows(client: TestClient):
    start = datetime(2025, 4, 1, 12, 0, tzinfo=UTC)
    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(User.email == release_configuration.homologation_email)
        )
        device = db.scalar(select(Device).where(Device.name == "Aquisitor simulado"))
        session = MeasurementSession(
            device_id=device.id,
            user_id=user.id,
            name="Somente legado",
            started_at=start,
            ended_at=start + timedelta(minutes=1),
            status="finished",
        )
        db.add(session)
        db.flush()
        measurement = Measurement(
            session_id=session.id,
            timestamp=start + timedelta(seconds=10),
            power_w=123.0,
            raw_power=123.0,
            raw_power_unit="W",
            quality="good",
        )
        measurement.temperatures.append(
            TemperatureMeasurement(channel=1, temperature_c=31.5, quality="good")
        )
        db.add(measurement)
        db.commit()
        request = PeriodReportRequest(
            start=start,
            end=start + timedelta(minutes=1),
            session_ids=[session.id],
            channels=[1],
        )
        data = PeriodReportDataService(db).collect(request)
    assert data["electrical"][0]["source"] == "legacy"
    assert data["temperatures"][0]["channels"] == {1: 31.5}


def test_usb_discovery_association_and_conservative_suggestion(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
):
    port = SimpleNamespace(
        device="COM9",
        description="USB AT4532 bridge",
        manufacturer="Laboratório",
        product="AT4532",
        serial_number="USB-TEST-9",
        vid=0x1234,
        pid=0x5678,
        hwid="USB VID:PID=1234:5678",
        location="1-4",
    )

    class FakeSerial:
        is_open = True

        def close(self):
            self.is_open = False

    busy_port = SimpleNamespace(
        device="COM10",
        description="Conversor USB serial",
        manufacturer=None,
        product=None,
        serial_number=None,
        vid=None,
        pid=None,
        hwid="USB UNKNOWN",
        location=None,
    )

    def serial_factory(**kwargs):
        if kwargs["port"] == "COM10":
            from serial import SerialException

            raise SerialException("Access denied: port is busy")
        return FakeSerial()

    monkeypatch.setattr(usb_discovery_service, "port_provider", lambda: [port, busy_port])
    monkeypatch.setattr(usb_discovery_service, "serial_factory", serial_factory)
    discovery = client.get("/api/v1/hardware/discovery", headers=auth_headers)
    assert discovery.status_code == 200
    item = next(row for row in discovery.json() if row["port"] == "COM9")
    assert item["status"] == "available"
    assert item["identification_status"] == "possible_at4532"
    assert item["confidence"] == "medium"
    assert item["association_status"] == "unassociated"
    busy = next(row for row in discovery.json() if row["port"] == "COM10")
    assert busy["status"] == "port_busy"
    assert busy["manufacturer"] is None
    device_id = client.get("/api/v1/devices", headers=auth_headers).json()[0]["id"]
    associated = client.post(
        "/api/v1/hardware/discovery/associate",
        headers=auth_headers,
        json={"port": "COM9", "device_id": device_id},
    )
    assert associated.status_code == 200
    assert associated.json()["metadata"]["usb"]["serial_number"] == "USB-TEST-9"
    second = next(
        row
        for row in client.get("/api/v1/hardware/discovery", headers=auth_headers).json()
        if row["port"] == "COM9"
    )
    assert second["association"]["matched_by"] == "serial_number"
    disposable = client.post(
        "/api/v1/devices", headers=auth_headers, json={"name": "Equipamento descartável"}
    )
    assert disposable.status_code == 201
    removed = client.delete(f"/api/v1/devices/{disposable.json()['id']}", headers=auth_headers)
    assert removed.status_code == 204
    active_ids = {row["id"] for row in client.get("/api/v1/devices", headers=auth_headers).json()}
    assert disposable.json()["id"] not in active_ids
    with SessionLocal() as db:
        report = db.scalar(select(Report).where(Report.scope_type == "period"))
        assert report is None
