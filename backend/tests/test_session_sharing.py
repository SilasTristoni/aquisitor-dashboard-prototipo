import hashlib
import io
from datetime import UTC, datetime, timedelta

from openpyxl import load_workbook
from sqlalchemy import select
from test_period_reports import _seed_period_data

from app.api.share_routes import share_limiter
from app.core.database import SessionLocal
from app.models.entities import SessionShare


def test_shared_session_security_and_downloads(client, auth_headers):
    share_limiter.buckets.clear()
    start, end, ids = _seed_period_data()
    base = f"/api/v1/sessions/{ids[0]}"
    payload = {
        "password": "test-share-password",
        "expires_in_days": 7,
        "permissions": {"graphs": True, "pdf": True, "xlsx": True, "csv": True},
    }
    created = client.post(base + "/shares", json=payload, headers=auth_headers)
    assert created.status_code == 201, created.text
    share = created.json()
    token = share["token"]
    access = {"token": token, "password": payload["password"]}
    public = "/api/v1/public/shares"
    with SessionLocal() as db:
        row = db.get(SessionShare, share["id"])
        assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert row.password_hash != payload["password"]
    assert client.post(public + "/access", json={"token": "x" * 43}).status_code == 404
    for password in [None, "wrong"]:
        assert (
            client.post(public + "/access", json={"token": token, "password": password}).status_code
            == 401
        )
    response = client.post(public + "/access", json=access)
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Período A"
    assert "Período B" not in response.text
    for key in [
        '"devices"',
        '"device_id"',
        '"session_id"',
        '"operator"',
        '"password_hash"',
        '"created_by"',
    ]:
        assert key not in response.text
    assert response.headers["cache-control"] == "no-store"
    # The caller cannot select a second session, choose a window or grant permissions.
    assert client.post(public + "/access", json={**access, "session_id": ids[1]}).status_code == 422
    assert client.get(f"/api/v1/sessions/{ids[1]}").status_code == 401
    assert client.get(base, headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert (
        client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    )
    assert (
        client.post(base + "/pause", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )
    for kind in ["csv", "xlsx", "pdf"]:
        download = client.post(public + f"/download/{kind}", json=access)
        assert download.status_code == 200, download.text[:200]
        if kind == "xlsx":
            book = load_workbook(io.BytesIO(download.content))
            text = str([[cell.value for row in sheet for cell in row] for sheet in book])
            assert "Período B" not in text
            assert "admin@" not in text and "Aquisitor simulado" not in text
    listed = client.get(base + "/shares", headers=auth_headers).json()["items"][0]
    assert listed["path"] == share["path"]
    assert listed["access_count"] == 4
    assert listed["last_accessed_at"]
    assert "token" not in listed and "password" not in listed
    assert (
        client.get(f"/api/v1/sessions/{ids[1]}/shares", headers=auth_headers).json()["total"] == 0
    )
    assert (
        client.delete(
            f"/api/v1/sessions/{ids[1]}/shares/{share['id']}", headers=auth_headers
        ).status_code
        == 404
    )
    assert client.delete(base + f"/shares/{share['id']}", headers=auth_headers).status_code == 204
    assert client.post(public + "/access", json=access).status_code == 404
    assert client.post(public + "/download/pdf", json=access).status_code == 404


def test_shared_expiry_permissions_and_rate_limit(client, auth_headers):
    share_limiter.buckets.clear()
    _, _, ids = _seed_period_data()
    base = f"/api/v1/sessions/{ids[0]}/shares"
    share = client.post(
        base, headers=auth_headers, json={"expires_in_days": None, "permissions": {"graphs": False}}
    ).json()
    access = {"token": share["token"]}
    public = "/api/v1/public/shares"
    result = client.post(public + "/access", json=access)
    assert result.status_code == 200
    assert result.json()["series"] == []
    for kind in ["pdf", "xlsx", "csv"]:
        assert client.post(public + f"/download/{kind}", json=access).status_code == 403
    with SessionLocal() as db:
        row = db.scalar(select(SessionShare).where(SessionShare.id == share["id"]))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert client.post(public + "/access", json=access).status_code == 404
    share_limiter.buckets.clear()
    for _ in range(30):
        assert client.post(public + "/access", json={"token": "invalid" * 7}).status_code == 404
    assert client.post(public + "/access", json=access).status_code == 429
    share_limiter.buckets.clear()
