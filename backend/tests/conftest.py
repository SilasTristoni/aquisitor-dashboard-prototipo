import os

os.environ["THERMOPOWER_DATABASE_URL"] = "sqlite:///./test-thermopower.db"
os.environ["THERMOPOWER_JWT_SECRET"] = "test-secret-with-enough-entropy-for-tests-only"

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, engine
from app.main import app


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
