import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.release import release_configuration
from app.windows_launcher import _configure_environment


def test_homologation_release_user_authenticates(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": release_configuration.homologation_email,
            "password": release_configuration.homologation_password,
        },
    )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == release_configuration.homologation_email


def test_windows_launcher_enables_prefill_for_the_seeded_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("THERMOPOWER_DEMO_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("THERMOPOWER_DEMO_ADMIN_PASSWORD", raising=False)

    _configure_environment(tmp_path, tmp_path / "application")
    launcher_settings = Settings(_env_file=None)

    assert os.environ["THERMOPOWER_LOGIN_PREFILL_ENABLED"] == "1"
    assert launcher_settings.login_prefill_enabled is True
    assert launcher_settings.demo_admin_email == release_configuration.homologation_email
    assert launcher_settings.demo_admin_password == release_configuration.homologation_password


def test_public_config_health_and_runtime_share_release_version(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    health = client.get("/health")
    public_config = client.get("/api/v1/public-config")
    runtime = client.get("/api/v1/runtime", headers=auth_headers)

    assert health.status_code == public_config.status_code == runtime.status_code == 200
    assert health.json()["version"] == release_configuration.version
    assert public_config.json()["version"] == release_configuration.version
    assert runtime.json()["version"] == release_configuration.version
    assert public_config.json()["login_prefill"] == {
        "enabled": True,
        "email": release_configuration.homologation_email,
        "password": release_configuration.homologation_password,
    }


def test_frontend_package_metadata_matches_backend_version() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    frontend_package = json.loads(
        (repository_root / "frontend" / "package.json").read_text(encoding="utf-8")
    )

    assert frontend_package["version"] == release_configuration.version
