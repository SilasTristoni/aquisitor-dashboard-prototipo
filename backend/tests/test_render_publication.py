# ruff: noqa: F811
import ctypes
import hashlib
import io
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_period_reports import _seed_period_data
from test_result_portal import portal, publish, snapshot  # noqa: F401

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.entities import MeasurementSession, SessionShare, User
from app.portal.application import create_app
from app.portal.models import PublishedResult
from app.portal.settings import Installation, database_url
from app.services import portal_configuration as config
from app.services import result_publication as transport


def headers(identity="lab-a", secret="p" * 40):
    return {"Authorization": "Bearer " + identity + "." + secret}


def test_tenant_installation_isolation_and_disabled_credentials(portal):
    client, factory, settings = portal
    for identity, tenant in [("lab-b", "company-b"), ("lab-c", "company-a")]:
        settings.installations[identity] = Installation(
            tenant_id=tenant, credential_sha256=hashlib.sha256(b"q" * 40).hexdigest()
        )
    value = snapshot()
    assert publish(client, settings, value).status_code == 201
    path = "/portal/v1/results/" + value["token_hash"]
    for identity in ["lab-b", "lab-c"]:
        assert client.delete(path, headers=headers(identity, "q" * 40)).status_code == 404
        assert (
            client.patch(
                path + "/permissions",
                headers=headers(identity, "q" * 40),
                json={"revision": 1, "permissions": {}},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/portal/v1/results", headers=headers(identity, "q" * 40), json=value
            ).status_code
            == 404
        )
    assert client.get("/portal/v1/installation", headers=headers(secret="wrong")).status_code == 401
    settings.installations["lab-a"].enabled = False
    assert client.delete(path, headers=headers()).status_code == 401
    with factory() as db:
        assert db.get(PublishedResult, value["token_hash"]).revoked_at is None


def test_policy_sync_retries_integrity_and_restart(portal):
    client, factory, settings = portal
    value = snapshot()
    value["result"]["series"] = [{"temperatures": [{"channel_25": 80}]}]
    assert publish(client, settings, value).status_code == 201
    path = "/portal/v1/results/" + value["token_hash"] + "/permissions"
    policy = {"revision": 1, "permissions": {"graphs": False, "csv": False}}
    for _ in range(2):
        assert client.patch(path, headers=headers(), json=policy).status_code == 200
    access = {"token": "t" * 43}
    with TestClient(create_app(settings, factory)) as restarted:
        result = restarted.post("/api/v1/public/shares/access", json=access)
        assert result.status_code == 200 and result.json()["series"] == []
        assert result.json()["permissions"]["graphs"] is False
        assert restarted.post("/api/v1/public/shares/download/csv", json=access).status_code == 403
        assert (
            restarted.patch(
                path, headers=headers(), json={"revision": 2, "permissions": {"pdf": True}}
            ).status_code
            == 422
        )
        assert (
            restarted.patch(
                path, headers=headers(), json={"revision": 1, "permissions": {"csv": True}}
            ).status_code
            == 409
        )
        assert (
            restarted.patch(
                path, headers=headers(), json={"revision": 2, "permissions": value["permissions"]}
            ).status_code
            == 200
        )
        assert restarted.post("/api/v1/public/shares/download/csv", json=access).status_code == 200
    with factory() as db:
        row = db.get(PublishedResult, value["token_hash"])
        row.tenant_id = "company-b"
        db.commit()
    assert client.post("/api/v1/public/shares/access", json=access).status_code == 503


def test_concurrent_duplicate_and_delayed_upload_after_revocation(portal):
    _, factory, settings = portal
    value = snapshot()

    def attempt(_):
        with TestClient(create_app(settings, factory)) as client:
            return publish(client, settings, value).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(attempt, range(4))) == [201] * 4
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PublishedResult)) == 1


def test_health_cors_limits_and_invalid_snapshots(portal):
    client, _, settings = portal
    assert client.get("/health").json() == {"status": "ok"}
    for origin, expected in [(settings.public_origin, 200), ("https://evil.test", 400)]:
        response = client.options(
            "/api/v1/public/shares/access",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == expected
    response = client.options(
        "/portal/v1/results",
        headers={
            "Origin": settings.public_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 400
    assert (
        client.patch("/portal/v1/results/abc/permissions", content=b"x" * 4097).status_code == 413
    )
    value = snapshot()
    value["result"]["metadata"] = {"operator": "private-test"}
    assert publish(client, settings, value).status_code == 422
    value = snapshot()
    value["result"]["statistics"] = {"nested": {"raw_payload": "private-test"}}
    response = publish(client, settings, value)
    assert response.status_code == 422 and "private-test" not in response.text
    assert database_url("postgres://user:password@host/database").startswith("postgresql+psycopg:")
    assert database_url("postgresql://host/database").startswith("postgresql+psycopg:")


class PortalBridge:
    """Exercise the real urllib client against a separate ASGI service; no external traffic."""

    def __init__(self, remote):
        self.remote = remote
        self.offline = False
        self.lose_confirmation = False

    def open(self, request, timeout):
        if self.offline:
            raise URLError("synthetic offline")
        response = self.remote.request(
            request.method,
            urlsplit(request.full_url).path,
            content=request.data,
            headers=dict(request.header_items()),
        )
        if self.lose_confirmation:
            self.lose_confirmation = False
            raise URLError("synthetic lost confirmation")
        if response.status_code >= 400:
            raise HTTPError(request.full_url, response.status_code, "redacted", {}, None)
        result = io.BytesIO(response.content)
        result.status = response.status_code
        return result


def test_windows_to_portal_outbox_retry_permissions_and_independence(
    client,
    auth_headers,
    portal,
    monkeypatch,
):
    remote, factory, settings = portal
    bridge = PortalBridge(remote)
    monkeypatch.setattr(transport, "build_opener", lambda *args: bridge)
    monkeypatch.setenv("THERMOPOWER_RESULTS_PORTAL_URL", "https://api.example.test")
    monkeypatch.setenv("THERMOPOWER_RESULTS_PORTAL_INSTALLATION_ID", "lab-a")
    monkeypatch.setenv("THERMOPOWER_RESULTS_PORTAL_PUBLISH_KEY", "p" * 40)
    start, end, ids = _seed_period_data()
    base = f"/api/v1/sessions/{ids[0]}"
    assert (
        client.put(
            base + "/analysis-period",
            headers=auth_headers,
            json={
                "start": start.isoformat(),
                "end": end.isoformat(),
                "label": "Synthetic",
            },
        ).status_code
        == 200
    )
    payload = {
        "destination": "portal",
        "publication_id": str(uuid4()),
        "channels": [1],
        "include_power": False,
        "permissions": {"graphs": True, "csv": True},
    }
    bridge.lose_confirmation = True
    assert client.post(base + "/shares", headers=auth_headers, json=payload).status_code == 503
    pending = client.get(base + "/shares", headers=auth_headers).json()["items"][0]
    assert pending["status"] == "pending" and pending["public_url"] is None
    with SessionLocal() as db:
        session = db.get(MeasurementSession, ids[0])
        session.name = "Changed locally after approved snapshot"
        db.commit()
    created = client.post(base + f"/shares/{pending['id']}/retry", headers=auth_headers)
    assert created.status_code == 200, created.text
    result = created.json()
    assert result["public_url"].startswith(settings.public_origin + "/compartilhado#")
    access = {"token": result["public_url"].split("#")[1]}
    assert remote.post("/api/v1/public/shares/access", json=access).json()["name"] != session.name
    duplicate = client.post(base + "/shares", headers=auth_headers, json=payload)
    assert duplicate.status_code == 201 and duplicate.json()["id"] == pending["id"]
    altered = {**payload, "channels": [2]}
    assert client.post(base + "/shares", headers=auth_headers, json=altered).status_code == 409
    path = base + f"/shares/{pending['id']}"
    bridge.lose_confirmation = True
    policy = {"graphs": False, "csv": False}
    assert client.patch(path + "/permissions", headers=auth_headers, json=policy).status_code == 503
    assert remote.post("/api/v1/public/shares/download/csv", json=access).status_code == 403
    listed = client.get(base + "/shares", headers=auth_headers).json()["items"][0]
    assert listed["permission_update_pending"]["revision"] == 1
    assert client.patch(path + "/permissions", headers=auth_headers, json=policy).status_code == 200
    bridge.offline = True
    assert client.delete(path, headers=auth_headers).status_code == 503
    assert client.get(base, headers=auth_headers).status_code == 200
    # The independent portal still serves the stored snapshot with local transport offline.
    with TestClient(create_app(settings, factory)) as restarted:
        assert restarted.post("/api/v1/public/shares/access", json=access).status_code == 200
    bridge.offline = False
    assert client.delete(path, headers=auth_headers).status_code == 204
    assert remote.post("/api/v1/public/shares/access", json=access).status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SessionShare)) == 1
        assert db.get(SessionShare, pending["id"]).publication_payload is None


def test_configuration_roles_redaction_and_environment(client, auth_headers, monkeypatch):
    monkeypatch.setattr(config, "read_vault", lambda: {})
    for key in ["URL", "INSTALLATION_ID", "PUBLISH_KEY"]:
        monkeypatch.delenv("THERMOPOWER_RESULTS_PORTAL_" + key, raising=False)
    path = "/api/v1/results-portal/configuration"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=auth_headers).json()["configured"] is False
    secret = "synthetic-private-credential" * 2
    response = client.put(
        path,
        headers=auth_headers,
        json={
            "url": "http://bad.test",
            "installation_id": "lab-a",
            "credential": secret,
        },
    )
    assert response.status_code == 422 and secret not in response.text
    with SessionLocal() as db:
        user = User(
            name="Synthetic operator",
            email="operator@example.test",
            role="operator",
            active=True,
            password_hash="unused",
        )
        db.add(user)
        db.commit()
        token = create_access_token(str(user.id), user.role)
    operator = {"Authorization": "Bearer " + token}
    assert (
        client.put(
            path,
            headers=operator,
            json={
                "url": "https://api.example.test",
                "installation_id": "lab-a",
                "credential": secret,
            },
        ).status_code
        == 403
    )
    monkeypatch.setenv("THERMOPOWER_RESULTS_PORTAL_URL", "https://api.example.test")
    monkeypatch.setenv("THERMOPOWER_RESULTS_PORTAL_INSTALLATION_ID", "lab-a")
    monkeypatch.setenv("THERMOPOWER_RESULTS_PORTAL_PUBLISH_KEY", secret)
    response = client.get(path, headers=operator)
    assert response.json()["configured"] is True
    assert response.json()["can_configure"] is False and secret not in response.text


@pytest.mark.skipif(os.name != "nt", reason="Windows Credential Manager")
def test_real_windows_vault_roundtrip_with_disposable_synthetic_target(monkeypatch):
    # Never touch the production credential slot or any existing user credentials.
    target = "ThermoPower/TestOnly/" + str(uuid4())
    monkeypatch.setattr(config, "TARGET", target)
    monkeypatch.delenv("THERMOPOWER_RESULTS_PORTAL_URL", raising=False)
    value = config.PortalConfiguration(
        url="https://synthetic.example.test", installation_id="test-only", credential="s" * 40
    )
    api = config.vault_api()
    try:
        assert config.read_vault() == {}
        config.save_configuration(value)
        assert config.read_vault()["credential"] == "s" * 40
        status = config.configuration_status()
        assert status["configured"] and "credential" not in status
    finally:
        api.CredDeleteW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong]
        api.CredDeleteW.restype = ctypes.c_int
        assert api.CredDeleteW(target, 1, 0)


@pytest.mark.parametrize(
    "origin",
    [
        "http://public.test",
        "https://user:password@example.test",
        "https://example.test/path",
        "https://example.test?key=secret",
        "https://example.test#secret",
        "https://example.test:bad",
    ],
)
def test_reject_unsafe_origins(origin):
    with pytest.raises(ValueError):
        config.validate_origin(origin)


def test_network_errors_redirects_and_invalid_receipts(monkeypatch):
    monkeypatch.setenv("THERMOPOWER_RESULTS_PORTAL_URL", "https://api.example.test")
    monkeypatch.setenv("THERMOPOWER_RESULTS_PORTAL_INSTALLATION_ID", "lab-a")
    monkeypatch.setenv("THERMOPOWER_RESULTS_PORTAL_PUBLISH_KEY", "p" * 40)
    assert (
        transport.NoRedirect().redirect_request(None, None, 307, "", {}, "https://evil.test")
        is None
    )

    class Broken:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 401, "private-body", {}, None)

    monkeypatch.setattr(transport, "build_opener", lambda *args: Broken())
    with pytest.raises(HTTPException) as exc:
        transport.publish_snapshot("https://api.example.test", snapshot())
    assert exc.value.status_code == 401 and "private-body" not in exc.value.detail
