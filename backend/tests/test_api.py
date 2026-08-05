import time

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.core.database import SessionLocal
from app.models import (
    ElectricalSample,
    Measurement,
    MeasurementSession,
    SessionChannelConfiguration,
    SessionDevice,
    TemperatureSample,
)


def test_authentication_and_permissions(client: TestClient, auth_headers: dict[str, str]):
    assert client.get("/api/v1/auth/me", headers=auth_headers).status_code == 200
    created = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "name": "Pessoa Visualizadora",
            "email": "viewer@example.com",
            "password": "SenhaTemporaria@123",
            "role": "viewer",
        },
    )
    assert created.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@example.com", "password": "SenhaTemporaria@123"},
    )
    viewer = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/v1/devices", headers=viewer).status_code == 200
    assert (
        client.post("/api/v1/devices", headers=viewer, json={"name": "Negado"}).status_code == 403
    )


def test_paginated_collections(client: TestClient, auth_headers: dict[str, str]):
    response = client.get("/api/v1/sessions?page=1&page_size=5", headers=auth_headers)
    assert response.status_code == 200
    assert response.json().keys() >= {"items", "page", "page_size", "total", "pages"}
    invalid = client.get("/api/v1/measurements?session_id=1&page_size=1000", headers=auth_headers)
    assert invalid.status_code == 422


def test_complete_simulated_measurement_flow(client: TestClient, auth_headers: dict[str, str]):
    devices = client.get("/api/v1/devices", headers=auth_headers).json()
    device_id = devices[0]["id"]
    connected = client.post(f"/api/v1/devices/{device_id}/connect", headers=auth_headers)
    assert connected.status_code == 200
    scenario = client.post(
        f"/api/v1/simulator/{device_id}/scenarios/power_spike", headers=auth_headers
    )
    assert scenario.status_code == 200
    started = client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={
            "device_id": device_id,
            "name": "Fluxo automatizado",
            "description": "Teste ponta a ponta",
            "sample_interval_ms": 1000,
        },
    )
    assert started.status_code == 201
    session_id = started.json()["id"]
    time.sleep(2.3)
    finished = client.post(f"/api/v1/sessions/{session_id}/finish", headers=auth_headers)
    assert finished.status_code == 200
    measurements = client.get(
        f"/api/v1/measurements?session_id={session_id}&page=1&page_size=10", headers=auth_headers
    )
    assert measurements.status_code == 200
    assert measurements.json()["total"] >= 2
    first = measurements.json()["items"][0]
    assert first["power_w"] > 0
    assert first["raw_power_unit"] in {"mW", "W", "kW"}
    alerts = client.get("/api/v1/alerts?page_size=100", headers=auth_headers).json()["items"]
    assert any(alert["session_id"] == session_id for alert in alerts)
    history = client.get("/api/v1/sessions?page_size=20", headers=auth_headers).json()["items"]
    assert any(item["id"] == session_id and item["status"] == "finished" for item in history)
    for report_type, content_type in [
        ("csv", "text/csv"),
        ("xlsx", "application/vnd.openxmlformats-officedocument"),
        ("pdf", "application/pdf"),
        ("png", "image/png"),
        ("jpg", "image/jpeg"),
    ]:
        report = client.get(
            f"/api/v1/reports/sessions/{session_id}.{report_type}", headers=auth_headers
        )
        assert report.status_code == 200
        assert content_type in report.headers["content-type"]
        assert len(report.content) > 50
    client.post(f"/api/v1/devices/{device_id}/disconnect", headers=auth_headers)


def test_deleted_session_leaves_no_rows_that_block_the_next_session(
    client: TestClient, auth_headers: dict[str, str]
):
    device_id = client.get("/api/v1/devices", headers=auth_headers).json()[0]["id"]
    assert client.post(
        f"/api/v1/devices/{device_id}/connect", headers=auth_headers
    ).status_code == 200

    first = client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={"device_id": device_id, "name": "Sessão que será excluída"},
    )
    assert first.status_code == 201, first.text
    session_id = first.json()["id"]
    time.sleep(1.1)
    assert client.post(
        f"/api/v1/sessions/{session_id}/finish", headers=auth_headers
    ).status_code == 200
    assert client.delete(
        f"/api/v1/sessions/{session_id}", headers=auth_headers
    ).status_code == 204

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MeasurementSession)) == 0
        for model in (
            Measurement,
            TemperatureSample,
            ElectricalSample,
            SessionChannelConfiguration,
            SessionDevice,
        ):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.scalar(text("PRAGMA foreign_keys")) == 1

    second = client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={"device_id": device_id, "name": "Sessão após exclusão"},
    )
    assert second.status_code == 201, second.text
    assert client.post(
        f"/api/v1/sessions/{second.json()['id']}/finish", headers=auth_headers
    ).status_code == 200
    client.post(f"/api/v1/devices/{device_id}/disconnect", headers=auth_headers)


def test_websocket_authentication_and_heartbeat(client: TestClient, auth_headers: dict[str, str]):
    token = auth_headers["Authorization"].split()[1]
    with client.websocket_connect(f"/api/v1/ws?token={token}") as websocket:
        message = websocket.receive_json()
        assert message["type"] == "connection.ready"
        assert message["payload"]["heartbeat_seconds"] == 20
