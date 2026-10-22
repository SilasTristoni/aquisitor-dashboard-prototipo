import os
from pathlib import Path

os.environ["THERMOPOWER_LOG_DIRECTORY"] = str(
    Path(__file__).resolve().parents[2] / "build/test-logs"
)

os.environ["THERMOPOWER_DATABASE_URL"] = "sqlite:///./test-thermopower.db"
os.environ["THERMOPOWER_JWT_SECRET"] = "test-secret-with-enough-entropy-for-tests-only"
os.environ["THERMOPOWER_DEMO_ADMIN_EMAIL"] = "admin@demo.thermopower.com"
os.environ["THERMOPOWER_DEMO_ADMIN_PASSWORD"] = "ThermoPower@123"

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def isolated_network_and_credentials(monkeypatch):
    """Tests may use loopback servers, but never external services or real credentials."""
    import ipaddress
    import socket

    from app.services import portal_configuration

    original_connect = socket.socket.connect
    original_read = portal_configuration.read_vault

    def connect(sock, address):
        if isinstance(address, tuple):
            host = str(address[0])
            try:
                allowed = ipaddress.ip_address(host).is_loopback
            except ValueError:
                allowed = host == "localhost"
            if not allowed:
                raise RuntimeError("External network disabled during automated tests")
        return original_connect(sock, address)

    def read_test_vault():
        if portal_configuration.TARGET == "ThermoPower/ResultsPortal/v1":
            return {}
        return original_read()

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(portal_configuration, "read_vault", read_test_vault)


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(engine)


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@demo.thermopower.com", "password": "ThermoPower@123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
