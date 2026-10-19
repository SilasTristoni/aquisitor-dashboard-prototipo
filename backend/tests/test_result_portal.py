import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from test_period_reports import _seed_period_data

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.entities import MeasurementSession
from app.portal.application import PortalSettings, create_app
from app.portal.contracts import canonical_bytes
from app.portal.models import PortalBase, PublishedResult
from app.services.result_publication import encode_document


@pytest.fixture
def portal(tmp_path):
    url = f"sqlite:///{tmp_path / 'portal.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 5})
    PortalBase.metadata.create_all(engine)
    factory = sessionmaker(engine)
    settings = PortalSettings(database_url=url, publish_key="p" * 40, integrity_key="i" * 40)
    with TestClient(create_app(settings, factory)) as client:
        yield client, factory, settings
    engine.dispose()


def snapshot(token="t" * 43, **changes):
    permissions = {"graphs": True, "pdf": False, "xlsx": False, "csv": True}
    value = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "password_hash": None,
        "expires_at": None,
        "permissions": permissions,
        "result": {
            "name": "Resultado autorizado",
            "metadata": {},
            "status": "finished",
            "official": True,
            "analysis_label": "Oficial",
            "permissions": permissions,
            "period": {},
            "statistics": {},
            "series": [],
            "selected_channels": [25],
            "channel_labels": {"25": "T25"},
            "annotations": [],
        },
        "documents": {"csv": encode_document(b"timestamp;T25\n2026-10-16T12:00Z;80")},
    }
    value.update(changes)
    return value


def publish(client, settings, value):
    return client.post(
        "/portal/v1/results",
        headers={"Authorization": "Bearer " + settings.publish_key},
        content=canonical_bytes(value),
    )


def test_independent_portal_auth_integrity_revocation_and_downloads(portal):
    client, factory, settings = portal
    value = snapshot(password_hash=hash_password("secret-test"))
    token = "t" * 43
    assert client.post("/portal/v1/results", json=value).status_code == 401
    assert publish(client, settings, value).status_code == 201
    assert publish(client, settings, value).status_code == 201
    access = {"token": token, "password": "secret-test"}
    path = "/api/v1/public/shares"
    assert client.post(path + "/access", json={"token": token}).status_code == 401
    assert client.post(path + "/access", json={"token": "other" * 9}).status_code == 404
    assert client.post(path + "/access", json={**access, "session_id": 99}).status_code == 422
    result = client.post(path + "/access", json=access)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert "password_hash" not in result.text and "token" not in result.text
    assert client.post(path + "/download/pdf", json=access).status_code == 403
    assert client.post(path + "/download/csv", json=access).content.endswith(b";80")
    for route in [
        "/api/v1/devices",
        "/api/v1/sessions",
        "/api/v1/support/physical-package",
        "/docs",
    ]:
        assert client.get(route).status_code == 404
    changed = {**value, "result": {**value["result"], "name": "Changed"}}
    assert publish(client, settings, changed).status_code == 409
    with factory() as db:
        row = db.get(PublishedResult, value["token_hash"])
        row.permissions = {**row.permissions, "pdf": True}
        db.commit()
    assert client.post(path + "/access", json=access).status_code == 503
    with factory() as db:
        row = db.get(PublishedResult, value["token_hash"])
        row.permissions = value["permissions"]
        db.commit()
    headers = {"Authorization": "Bearer " + settings.publish_key}
    assert (
        client.delete("/portal/v1/results/" + value["token_hash"], headers=headers).status_code
        == 204
    )
    assert client.post(path + "/access", json=access).status_code == 404
    assert client.post(path + "/download/csv", json=access).status_code == 404
    assert publish(client, settings, value).status_code == 409


def test_expired_corrupt_snapshots_and_redacted_errors(portal):
    client, factory, settings = portal
    value = snapshot(expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat())
    assert publish(client, settings, value).status_code == 201
    assert client.post("/api/v1/public/shares/access", json={"token": "t" * 43}).status_code == 404
    value = snapshot(token="z" * 43)
    value["documents"]["csv"]["sha256"] = "0" * 64
    assert publish(client, settings, value).status_code == 422
    response = client.post(
        "/api/v1/public/shares/access",
        json={"token": "private-invalid-token", "password": "secret"},
    )
    assert response.status_code == 422
    assert "private-invalid-token" not in response.text and "secret" not in response.text
    assert client.post("/api/v1/public/shares/access", content=b"x" * 4097).status_code == 413


def test_revocation_before_delayed_upload_cannot_resurrect(portal):
    client, _, settings = portal
    value = snapshot()
    assert (
        client.delete(
            "/portal/v1/results/" + value["token_hash"],
            headers={"Authorization": "Bearer " + settings.publish_key},
        ).status_code
        == 204
    )
    assert publish(client, settings, value).status_code == 409
    assert client.post("/api/v1/public/shares/access", json={"token": "t" * 43}).status_code == 404


def test_lost_publication_response_remains_revocable(client, auth_headers, monkeypatch):
    from fastapi import HTTPException

    from app.models.entities import SessionShare

    start, end, ids = _seed_period_data()
    base = f"/api/v1/sessions/{ids[0]}"
    assert (
        client.put(
            base + "/analysis-period",
            headers=auth_headers,
            json={"start": start.isoformat(), "end": end.isoformat(), "label": "Oficial"},
        ).status_code
        == 200
    )
    monkeypatch.setenv("THERMOPOWER_RESULTS_PORTAL_URL", "https://results.example.test")

    def uncertain(*args):
        raise HTTPException(503, "Confirmação indisponível")

    monkeypatch.setattr("app.api.share_routes.publish_snapshot", uncertain)
    response = client.post(base + "/shares", headers=auth_headers, json={"destination": "portal"})
    assert response.status_code == 503
    listed = client.get(base + "/shares", headers=auth_headers).json()["items"][0]
    assert listed["status"] == "pending" and listed["path"] is None
    revoked = []
    monkeypatch.setattr(
        "app.api.share_routes.revoke_publication",
        lambda origin, token_hash: revoked.append(token_hash),
    )
    assert client.delete(base + f"/shares/{listed['id']}", headers=auth_headers).status_code == 204
    with SessionLocal() as db:
        row = db.get(SessionShare, listed["id"])
        assert row.revoked_at and revoked == [row.token_hash]


def test_limiter_atomic_across_workers_and_restart(portal):
    client, factory, settings = portal

    def attempt(_):
        with TestClient(create_app(settings, factory)) as other:
            return other.post("/api/v1/public/shares/access", json={"token": "t" * 43}).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(attempt, range(32)))
    assert outcomes.count(404) == 30
    assert outcomes.count(429) == 2
    assert attempt(None) == 429


def test_local_publication_freezes_authorized_period_and_channels(
    client, auth_headers, portal, monkeypatch
):
    remote, factory, settings = portal
    start, end, ids = _seed_period_data()
    monkeypatch.setenv("THERMOPOWER_RESULTS_PORTAL_URL", "https://results.example.test")

    def upload(origin, value):
        # Exercise the actual independent service, no network or physical devices.
        value = json.loads(json.dumps(value, default=lambda value: value.isoformat()))
        response = publish(remote, settings, value)
        assert response.status_code == 201, response.text

    monkeypatch.setattr("app.api.share_routes.publish_snapshot", upload)

    def revoke(origin, token_hash):
        assert (
            remote.delete(
                "/portal/v1/results/" + token_hash,
                headers={"Authorization": "Bearer " + settings.publish_key},
            ).status_code
            == 204
        )

    monkeypatch.setattr("app.api.share_routes.revoke_publication", revoke)
    base = f"/api/v1/sessions/{ids[0]}"
    payload = {
        "destination": "portal",
        "channels": [1],
        "include_power": False,
        "permissions": {"graphs": True, "csv": True},
    }
    assert client.post(base + "/shares", headers=auth_headers, json=payload).status_code == 422
    assert (
        client.put(
            base + "/analysis-period",
            headers=auth_headers,
            json={"start": start.isoformat(), "end": end.isoformat(), "label": "Oficial"},
        ).status_code
        == 200
    )
    created = client.post(base + "/shares", headers=auth_headers, json=payload)
    assert created.status_code == 201, created.text
    access = {"token": created.json()["token"]}
    path = "/api/v1/public/shares/access"
    original = remote.post(path, json=access).json()
    assert original["selected_channels"] == [1]
    assert original["series"][0]["electrical"] == []
    assert original["statistics"]["temperature"]["peak"]["value_c"] == 32
    with SessionLocal() as db:
        session = db.get(MeasurementSession, ids[0])
        session.name = "Changed after publication"
        session.analysis_start = start + timedelta(seconds=9)
        db.commit()
    assert remote.post(path, json=access).json() == original
    with factory() as db:
        stored = db.scalar(select(PublishedResult))
        for forbidden in [b'"device_id"', b'"operator"', b'"raw_payload"', b"COM5", b"admin@"]:
            assert forbidden not in stored.payload
    assert (
        client.delete(base + f"/shares/{created.json()['id']}", headers=auth_headers).status_code
        == 204
    )
    assert remote.post(path, json=access).status_code == 404


def test_unconfigured_portal_does_not_block_local_results(client, auth_headers, monkeypatch):
    for name in (
        "THERMOPOWER_RESULTS_PORTAL_URL",
        "THERMOPOWER_RESULTS_PORTAL_PUBLISH_KEY",
        "THERMOPOWER_RESULTS_PORTAL_LOCAL_TEST",
    ):
        monkeypatch.delenv(name, raising=False)
    start, end, ids = _seed_period_data()
    base = f"/api/v1/sessions/{ids[0]}"
    assert client.put(
        base + "/analysis-period",
        headers=auth_headers,
        json={"start": start.isoformat(), "end": end.isoformat(), "label": "Official"},
    ).status_code == 200
    unavailable = client.post(
        base + "/shares", headers=auth_headers, json={"destination": "portal"}
    )
    assert unavailable.status_code == 503
    assert "HTTPS" in unavailable.json()["error"]["message"]
    assert client.get(base + "/shares", headers=auth_headers).json()["items"] == []
    created = client.post(
        base + "/shares",
        headers=auth_headers,
        json={"channels": [1], "permissions": {"graphs": True, "csv": True}},
    )
    assert created.status_code == 201
    access = {"token": created.json()["token"]}
    result = client.post("/api/v1/public/shares/access", json=access)
    assert result.status_code == 200
    assert result.json()["selected_channels"] == [1]
    assert result.json()["statistics"]["temperature"]["peak"]["value_c"] == 32
    exported = client.post("/api/v1/public/shares/download/csv", json=access)
    assert exported.status_code == 200 and exported.content
    assert client.get(base, headers=auth_headers).status_code == 200


def test_portal_import_does_not_load_acquisition():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import app.portal.application; assert 'app.main' not in sys.modules; "
            "assert not any(m.startswith(('app.adapters', 'app.services.acquisition', 'serial')) "
            "for m in sys.modules)",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_portal_migrations_sqlite_and_postgresql_compilation(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "THERMOPOWER_PORTAL_DATABASE_URL": f"sqlite:///{tmp_path / 'migration.db'}",
    }
    for command in [
        ["upgrade", "head"],
        ["check"],
        ["downgrade", "base"],
        ["upgrade", "head"],
        ["check"],
    ]:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "portal-alembic.ini", *command],
            cwd=backend,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    environment["THERMOPOWER_PORTAL_DATABASE_URL"] = (
        "postgresql+psycopg://unused:unused@localhost/unused"
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "portal-alembic.ini", "upgrade", "head", "--sql"],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE published_results" in result.stdout
    assert "BYTEA" in result.stdout and "TIMESTAMP WITH TIME ZONE" in result.stdout
