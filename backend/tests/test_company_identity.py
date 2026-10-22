import base64
import io
import socket

import pytest
from PIL import Image
from sqlalchemy import select
from test_period_reports import _seed_period_data

from app.core.database import SessionLocal
from app.models.entities import User
from app.services.company_identity import CompanyIdentity, normalize_logo


def logo_bytes(kind="PNG", size=(64, 32)):
    output = io.BytesIO()
    Image.new("RGB", size, "navy").save(output, format=kind)
    return output.getvalue()


def test_identity_admin_validation_persistence_and_neutral_default(client, auth_headers):
    path = "/api/v1/company-identity"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=auth_headers).json()["company_name"] == ""
    response = client.put(
        path,
        headers=auth_headers,
        json={"company_name": "Empresa sintética A", "laboratory": "DEMO"},
    )
    assert response.status_code == 200
    identity_id = response.json()["identity_id"]
    for kind in ("PNG", "JPEG"):
        response = client.put(path + "/logo", headers=auth_headers, content=logo_bytes(kind))
        assert response.status_code == 200, response.text
        raw = base64.b64decode(response.json()["logo"].split(",")[1])
        assert Image.open(io.BytesIO(raw)).format == "PNG"
    for raw in (
        b"<svg><script>alert(1)</script></svg>",
        b"not an image",
        logo_bytes(size=(4096, 16)),
    ):
        assert client.put(path + "/logo", headers=auth_headers, content=raw).status_code == 422
    assert (
        client.put(path + "/logo", headers=auth_headers, content=b"a" * 1048577).status_code == 413
    )
    with SessionLocal() as db:
        row = db.get(CompanyIdentity, 1)
        assert row.identity_id == identity_id and row.logo
        user = db.scalar(select(User).where(User.role == "admin"))
        user.role = "operator"
        db.commit()
    assert client.put(path, headers=auth_headers, json={"company_name": "B"}).status_code == 403
    assert client.put(path + "/logo", headers=auth_headers, content=logo_bytes()).status_code == 403
    assert client.delete(path + "/logo", headers=auth_headers).status_code == 403


def test_shared_identity_requires_opt_in_and_is_frozen(client, auth_headers):
    _, _, ids = _seed_period_data()
    path = "/api/v1/company-identity"
    client.put(path, headers=auth_headers, json={"company_name": "Empresa A", "laboratory": "A"})
    tokens = []
    for include in (False, True):
        response = client.post(
            f"/api/v1/sessions/{ids[0]}/shares",
            headers=auth_headers,
            json={
                "include_company_identity": include,
                "permissions": {"graphs": True, "pdf": True, "xlsx": False, "csv": True},
            },
        )
        assert response.status_code == 201, response.text
        tokens.append(response.json()["token"])
    client.put(path, headers=auth_headers, json={"company_name": "Empresa B", "laboratory": "B"})
    for index, token in enumerate(tokens):
        result = client.post("/api/v1/public/shares/access", json={"token": token})
        assert result.status_code == 200, result.text
        if index:
            assert result.json()["company_identity"]["company_name"] == "Empresa A"
        else:
            assert "company_identity" not in result.json()
        csv = client.post("/api/v1/public/shares/download/csv", json={"token": token})
        assert csv.status_code == 200 and "Empresa" not in csv.text
        pdf = client.post("/api/v1/public/shares/download/pdf", json={"token": token})
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_logo_rejects_animation_and_truncation():
    with pytest.raises(ValueError):
        normalize_logo(logo_bytes()[:40])
    output = io.BytesIO()
    Image.new("RGB", (32, 32)).save(
        output, format="PNG", save_all=True, append_images=[Image.new("RGB", (32, 32), "red")]
    )
    with pytest.raises(ValueError):
        normalize_logo(output.getvalue())


def test_automated_tests_cannot_connect_to_external_services():
    with socket.socket() as connection, pytest.raises(RuntimeError, match="External network"):
        connection.connect(("203.0.113.1", 443))
