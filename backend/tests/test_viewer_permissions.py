import re

from fastapi.routing import APIRoute

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.main import app
from app.models.entities import User


def viewer_headers():
    with SessionLocal() as db:
        user = User(
            name="Consulta", email="viewer@example.test", password_hash="unused", role="viewer"
        )
        db.add(user)
        db.commit()
        return {"Authorization": "Bearer " + create_access_token(str(user.id), user.role)}


def test_viewer_cannot_execute_any_operational_route(client, auth_headers):
    headers = viewer_headers()
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1/"):
            continue
        if route.path.startswith(("/api/v1/auth/", "/api/v1/reports/period/", "/api/v1/public/")):
            continue
        for method in route.methods & {"POST", "PUT", "PATCH", "DELETE"}:
            path = re.sub(r"\{[^}]+\}", "1", route.path)
            response = client.request(method, path, headers=headers, json={})
            assert response.status_code == 403, (method, path, response.text)
    for path in ["/sessions", "/reports", "/statistics/executive", "/auth/me"]:
        assert client.get("/api/v1" + path, headers=headers).status_code == 200
    for path in [
        "/users",
        "/hardware/discovery",
        "/device-ports",
        "/diagnostics",
        "/support/package",
    ]:
        assert client.get("/api/v1" + path, headers=headers).status_code == 403
