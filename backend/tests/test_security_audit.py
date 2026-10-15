"""Local security regressions; synthetic users and no hardware connections."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from pydantic import ValidationError

from app.api import routes
from app.core.config import Settings
from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.entities import User


@pytest.mark.parametrize(
    "environment",
    [
        "development",
        "test",
        "windows-beta",
        "physical-alpha",
        "client-preview",
        "production",
        "engineering",
    ],
)
def test_build_info_never_discloses_initial_password(client, monkeypatch, environment):
    monkeypatch.setattr(routes.settings, "environment", environment)
    response = client.get("/api/v1/build-info")
    assert response.status_code == 200
    assert response.json()["demo_credentials"] is None
    assert routes.settings.demo_admin_password not in response.text


@pytest.mark.parametrize(
    "secret",
    [
        "",
        "short",
        "change-this-development-secret-before-production",
        "replace-this-before-any-network-exposure",
        "gere-uma-chave-aleatoria-com-pelo-menos-32-bytes",
    ],
)
def test_known_or_short_jwt_keys_are_rejected(secret):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret=secret)


def test_missing_jwt_key_is_rejected(monkeypatch):
    monkeypatch.delenv("THERMOPOWER_JWT_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_compose_requires_explicit_secrets():
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    for key in ["POSTGRES_PASSWORD", "THERMOPOWER_JWT_SECRET", "THERMOPOWER_DEMO_ADMIN_PASSWORD"]:
        assert "${" + key + ":?" in compose
        assert "${" + key + ":-" not in compose


def test_known_key_forgery_is_rejected_with_private_key(client):
    forged = jwt.encode(
        {"sub": "1", "role": "admin", "exp": datetime.now(UTC) + timedelta(minutes=1)},
        "change-this-development-secret-before-production",
        algorithm="HS256",
    )
    assert (
        client.get("/api/v1/users", headers={"Authorization": "Bearer " + forged}).status_code
        == 401
    )


@pytest.mark.parametrize("role", ["operator", "viewer"])
def test_signed_admin_claim_does_not_override_database_role(client, role):
    with SessionLocal() as db:
        user = User(
            name="Synthetic", email=f"{role}@example.test", password_hash="unused", role=role
        )
        db.add(user)
        db.commit()
        token = create_access_token(str(user.id), "admin")
    response = client.get("/api/v1/users", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 403


def test_login_upload_cors_and_http_auth_boundaries(client, auth_headers):
    assert client.get("/api/v1/sessions").status_code == 401
    assert client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin' OR 1=1--@example.test",
            "password": "synthetic-password",
        },
    ).status_code in {401, 422}
    for filename, content, expected in [("bad.exe", b"x", 415), ("empty.txt", b"", 422)]:
        response = client.post(
            "/api/v1/imports/gpm8213/preview",
            headers=auth_headers,
            files={"file": (filename, content, "application/octet-stream")},
        )
        assert response.status_code == expected
    response = client.options(
        "/api/v1/sessions",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_default_signing_key_allows_admin_impersonation_before_fix(client, monkeypatch):
    """Safe reproduction of impact, independent of startup validation."""
    monkeypatch.setattr(
        routes.settings, "jwt_secret", "change-this-development-secret-before-production"
    )
    forged = jwt.encode(
        {"sub": "1", "role": "admin", "exp": datetime.now(UTC) + timedelta(minutes=1)},
        routes.settings.jwt_secret,
        algorithm="HS256",
    )
    response = client.get("/api/v1/users", headers={"Authorization": "Bearer " + forged})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/assets/%5C%5Caudit.invalid%5Cshare%5Cfile.js",
        "/%5C%5Caudit.invalid%5Cshare%5Cfile.js",
        "/assets/C:%5Caudit%5Cfile.js",
        "/%2F%2Faudit.invalid/share/file.js",
    ],
)
def test_windows_network_paths_are_rejected_before_filesystem_resolution(client, monkeypatch, path):
    import os

    original = os.path.realpath
    attempted = []

    def guarded_realpath(value, *args, **kwargs):
        if "audit.invalid" in str(value) or "C:\\audit" in str(value):
            attempted.append(str(value))
            raise OSError("Synthetic resolver: external filesystem access blocked")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", guarded_realpath)
    response = client.get(path)
    assert not attempted, "Untrusted path reached filesystem resolution"
    assert response.status_code == 400


@pytest.mark.parametrize(
    "value", ["bytes=" + "0" * 5000 + "a-", "bytes=0-0,2-2,4-4", "bytes=invalid"]
)
def test_hostile_ranges_are_rejected_before_file_response(client, value):
    response = client.get("/", headers={"Range": value})
    assert response.status_code == 416


def test_multipart_headers_are_bounded_before_authentication(client, monkeypatch):
    from starlette import formparsers

    observed = []
    original = formparsers.MultiPartParser.on_header_value

    def record_header(self, data, start, end):
        observed.append(end - start)
        return original(self, data, start, end)

    monkeypatch.setattr(formparsers.MultiPartParser, "on_header_value", record_header)
    body = (
        b'--audit\r\nContent-Disposition: form-data; name="file"; filename="test.txt"\r\n'
        b"X-Audit: " + b"a" * 65536 + b"\r\n\r\ndata\r\n--audit--\r\n"
    )
    response = client.post(
        "/api/v1/imports/gpm8213/preview",
        content=body,
        headers={"Content-Type": "multipart/form-data; boundary=audit"},
    )
    assert max(observed, default=0) < 65536
    assert response.status_code == 400


def test_normal_file_download_and_single_ranges_still_work(client, tmp_path, monkeypatch):
    from fastapi.responses import FileResponse
    from fastapi.routing import APIRoute

    from app.main import app

    path = tmp_path / "synthetic.txt"
    path.write_bytes(b"synthetic-file")

    def download():
        return FileResponse(path)

    route = APIRoute("/_audit/file", download, methods=["GET"])
    monkeypatch.setattr(app.router, "routes", [route, *app.router.routes])
    assert client.get("/_audit/file").content == b"synthetic-file"
    for value, expected in [("bytes=0-2", b"syn"), ("bytes=-4", b"file"), ("bytes=10-", b"file")]:
        response = client.get("/_audit/file", headers={"Range": value})
        assert response.status_code == 206
        assert response.content == expected
    assert (
        client.get(
            "/_audit/file", headers=[("Range", "bytes=0-1"), ("Range", "bytes=4-5")]
        ).status_code
        == 416
    )
