from sqlalchemy import select

from app import main as main_module
from app.core.database import Base, SessionLocal, engine
from app.models.entities import Device, User


def test_client_preview_seeds_no_simulator_and_exposes_no_credentials(client, monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main_module.settings, "environment", "client-preview")
    monkeypatch.setattr(main_module.settings, "demo_admin_email", "admin@thermopower.com.br")
    monkeypatch.setattr(main_module.settings, "demo_admin_password", "senha-temporaria-teste")
    monkeypatch.setattr(main_module.settings, "initial_admin_name", "Administrador local")

    main_module.seed_database()

    with SessionLocal() as db:
        protocols = set(db.scalars(select(Device.protocol)))
        admin = db.scalar(select(User).where(User.email == "admin@thermopower.com.br"))
    assert "simulator" not in protocols
    assert {"at4532_serial", "gpm8213_serial"} <= protocols
    assert admin is not None
    assert admin.name == "Administrador local"

    information = client.get("/api/v1/build-info")
    assert information.status_code == 200
    assert information.json()["environment"] == "client-preview"
    assert information.json()["demo_credentials"] is None

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@thermopower.com.br", "password": "senha-temporaria-teste"},
    )
    assert login.status_code == 200
    devices = client.get(
        "/api/v1/devices",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert devices.status_code == 200
    assert all(device["protocol"] != "simulator" for device in devices.json())
