from datetime import timedelta
from pathlib import Path
from runpy import run_path

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.entities import (
    AlertEvent,
    Device,
    ElectricalSample,
    MeasurementSession,
    SessionAnnotation,
    SessionDevice,
    SessionShare,
    TemperatureChannelValue,
    TemperatureSample,
    User,
)
from app.schemas.contracts import PeriodReportRequest
from app.services.period_reporting import PeriodReportDataService, period_statistics

SEED = run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "seed-ux-demo.py"))


@pytest.mark.parametrize(
    "environment", ["client-preview", "production", "physical-alpha", "windows-beta", ""]
)
def test_seed_rejects_non_development_environments_before_opening_database(environment):
    with pytest.raises(ValueError, match="development/test"):
        SEED["validate_target"](environment, "sqlite:///./thermopower.db")


def test_seed_uses_backend_database_and_rejects_external_targets():
    target = SEED["validate_target"]("development", "sqlite:///./thermopower.db")
    assert Path(target.removeprefix("sqlite:///")) == SEED["BACKEND"] / "thermopower.db"
    for url in (
        "sqlite:///../../client-preview.db",
        "postgresql://localhost/production",
        "postgresql://remote.example/thermopower_dev",
    ):
        with pytest.raises(ValueError):
            SEED["validate_target"]("development", url)
    assert SEED["validate_target"]("test", "postgresql://localhost/thermopower_test")


def test_seed_is_deterministic_plausible_and_marks_missing_channels():
    for seconds in (0, 120, 600, 750, 1200):
        values = SEED["electrical_values"]("peak", seconds)
        assert values == SEED["electrical_values"]("peak", seconds)
        assert 218 <= values["voltage_v"] <= 222
        assert 0 < values["active_power_w"] <= values["apparent_power_va"]
        assert values["current_a"] * values["voltage_v"] == pytest.approx(
            values["apparent_power_va"], abs=0.02
        )
    assert SEED["thermal_value"]("warmup", 1200, 1) == (None, "open_sensor")
    assert SEED["thermal_value"]("gap", 500, 27) == (None, "open_sensor")
    assert SEED["thermal_value"]("peak", 750, 29)[0] > 100


def test_seed_populates_idempotently_without_touching_physical_devices(client, monkeypatch):
    def no_serial(*args, **kwargs):
        raise AssertionError("UX seed must never open a serial port")

    monkeypatch.setattr("serial.Serial", no_serial)
    with SessionLocal() as db:
        user = db.scalar(select(User))
        physical = {
            device.id: (
                device.name,
                device.port,
                device.baud_rate,
                device.protocol,
                device.metadata_json,
            )
            for device in db.scalars(select(Device).where(Device.protocol != "simulator"))
        }
        first = SEED["seed_demo"](db, user, environment="test")
        db.commit()
        # A previous seed may lack cadence metadata; repeat runs backfill only that field.
        previous = db.get(MeasurementSession, first["sessions"][0]["id"])
        previous.metadata_json = {
            key: value
            for key, value in previous.metadata_json.items()
            if key != "source_cadence_ms"
        }
        db.commit()
        second = SEED["seed_demo"](db, user, environment="test")
        db.commit()
        assert first["created_sessions"] == 8
        assert second["created_sessions"] == 0
        assert first["sessions"] == second["sessions"]
        assert first["electrical_samples"] == second["electrical_samples"] == 5227
        assert first["temperature_samples"] == second["temperature_samples"] == 5402
        assert first["alerts"] == second["alerts"] == 2
        assert db.scalar(select(func.count()).select_from(SessionShare)) == 0
        assert db.scalar(select(func.count()).select_from(SessionAnnotation)) == 3
        recommended = db.get(MeasurementSession, first["recommended_session"]["id"])
        assert recommended.status == "finished"
        assert recommended.analysis_start is None
        assert recommended.analysis_end is None
        assert (recommended.ended_at - recommended.started_at).total_seconds() > 2400
        events = list(
            db.scalars(
                select(SessionAnnotation)
                .where(SessionAnnotation.session_id == recommended.id)
                .order_by(SessionAnnotation.timestamp)
            )
        )
        assert [(item.timestamp - recommended.started_at).total_seconds() for item in events] == [
            600,
            1500,
            1800,
        ]
        assert [item.kind for item in events] == ["stabilization", "shutdown", "note"]
        stable = PeriodReportDataService(db).preview(
            PeriodReportRequest(
                start=recommended.started_at + timedelta(seconds=600),
                end=recommended.started_at + timedelta(seconds=1495),
                timezone="UTC",
                session_ids=[recommended.id],
            )
        )
        assert stable["statistics"]["temperature"]["stabilization"]["suggested"]
        assert len(stable["selected_channels"]) == 8
        assert 775 < stable["statistics"]["electrical"]["active_power_w"]["mean"] < 785
        # Repeating the seed also preserves manual validation work on seeded sessions.
        events[0].title = "Evento revisado pelo operador"
        recommended.analysis_start = events[0].timestamp
        recommended.analysis_end = events[1].timestamp
        recommended.analysis_label = "Meu período oficial"
        recommended.analysis_selected_by = user.id
        recommended.analysis_selected_at = events[1].timestamp
        db.commit()
        SEED["seed_demo"](db, user, environment="test")
        db.commit()
        assert events[0].title == "Evento revisado pelo operador"
        assert recommended.analysis_label == "Meu período oficial"
        for device_id, original in physical.items():
            device = db.get(Device, device_id)
            assert (
                device.name,
                device.port,
                device.baud_rate,
                device.protocol,
                device.metadata_json,
            ) == original
        devices = [db.get(Device, item["id"]) for item in first["devices"]]
        assert [item.name for item in devices] == list(SEED["DEVICE_NAMES"])
        assert all(
            item.port is None
            and item.baud_rate is None
            and item.protocol == "simulator"
            and item.connection_type == "simulator"
            for item in devices
        )
        ids = [row["id"] for row in first["sessions"]]
        assert (
            db.scalar(
                select(func.count())
                .select_from(SessionDevice)
                .where(SessionDevice.session_id.in_(ids))
            )
            == 15
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(TemperatureChannelValue)
                .join(TemperatureSample, TemperatureChannelValue.sample_id == TemperatureSample.id)
                .where(TemperatureSample.session_id.in_(ids))
            )
            == 5402 * 32
        )
        assert all(
            row.status in {"finished", "cancelled"}
            for row in db.scalars(select(MeasurementSession).where(MeasurementSession.id.in_(ids)))
        )
        assert all(
            row.measured_value > row.threshold
            for row in db.scalars(select(AlertEvent).where(AlertEvent.session_id.in_(ids)))
        )
        for row in db.scalars(select(ElectricalSample).where(ElectricalSample.session_id.in_(ids))):
            factor = {"mW": 0.001, "W": 1, "kW": 1000}[row.original_units["active_power"]]
            assert row.original_values["active_power"] * factor == pytest.approx(row.active_power_w)
        # Exercise the production report query/statistics against the seeded source tables.
        request = PeriodReportRequest(
            start=SEED["START"],
            end=SEED["START"] + timedelta(days=8),
            session_ids=ids,
            channels=[25, 26, 27, 28, 29, 30, 31, 32],
        )
        data = PeriodReportDataService(db).collect(request)
        statistics = period_statistics(data)
        assert statistics["general"]["electrical_sample_count"] == 5227
        assert statistics["general"]["temperature_sample_count"] == 5402
        quality = statistics["general"]["source_quality"]
        assert len(quality) == 15
        assert all(not source["frequency_reduced"] for source in quality)
        assert {source["expected_interval_seconds"] for source in quality} == {1, 5}


def test_analysis_curve_has_distinct_heating_plateau_and_shutdown():
    thermal = SEED["thermal_value"]
    electric = SEED["electrical_values"]
    assert thermal("analysis", 300, 29)[0] > thermal("analysis", 0, 29)[0] + 40
    values = [thermal("analysis", second, 29)[0] for second in range(600, 1500, 5)]
    assert max(values) - min(values) < 1
    assert thermal("analysis", 2400, 29)[0] < thermal("analysis", 1500, 29)[0] - 45
    assert electric("analysis", 300)["active_power_w"] > 1170
    assert 775 < electric("analysis", 900)["active_power_w"] < 785
    assert electric("analysis", 1500)["active_power_w"] == 0
    assert electric("analysis", 2400)["active_power_w"] == 0


def test_demo_viewer_preserves_existing_users_and_passwords(client):
    from app.core.security import hash_password, verify_password

    with SessionLocal() as db:
        db.add(
            User(
                name="Operador existente",
                email="existing.operator@example.test",
                role="operator",
                active=True,
                password_hash=hash_password("test-only-existing"),
            )
        )
        db.commit()
        original = {
            row.id: (row.email, row.role, row.active, row.password_hash)
            for row in db.scalars(select(User))
        }
        viewer, password = SEED["ensure_demo_viewer"](db, environment="test")
        db.commit()
        assert viewer.role == "viewer" and viewer.active
        login = client.post(
            "/api/v1/auth/login", json={"email": viewer.email, "password": password}
        )
        assert login.status_code == 200, login.text
        assert login.json()["user"]["role"] == "viewer"
        assert password and verify_password(password, viewer.password_hash)
        repeated, new_password = SEED["ensure_demo_viewer"](
            db, environment="test", password="do-not-reset-existing"
        )
        db.commit()
        assert repeated.id == viewer.id and new_password is None
        assert verify_password(password, repeated.password_hash)
        for user_id, expected in original.items():
            row = db.get(User, user_id)
            assert (row.email, row.role, row.active, row.password_hash) == expected


def test_viewer_collision_and_non_dev_environment_are_rejected(client):
    with SessionLocal() as db:
        existing = User(
            name="Conta preservada",
            email=SEED["VIEWER_EMAIL"],
            role="operator",
            active=True,
            password_hash="unchanged",
        )
        db.add(existing)
        db.commit()
        with pytest.raises(ValueError, match="conflitante"):
            SEED["ensure_demo_viewer"](db, environment="test")
        for environment in ["production", "client-preview"]:
            with pytest.raises(ValueError, match="development/test"):
                SEED["ensure_demo_viewer"](db, environment=environment)
        assert existing.role == "operator" and existing.password_hash == "unchanged"


def test_seed_rejects_frozen_runtime_and_is_not_packaged(monkeypatch):
    monkeypatch.setattr("sys.frozen", True, raising=False)
    with pytest.raises(ValueError, match="development/test"):
        SEED["validate_target"]("development", "sqlite:///./thermopower.db")
    with pytest.raises(ValueError, match="development/test"):
        SEED["seed_demo"](None, None, environment="development")
    with pytest.raises(ValueError, match="development/test"):
        SEED["ensure_demo_viewer"](None, environment="development")
    spec = (SEED["ROOT"] / "thermopower.spec").read_text(encoding="utf-8")
    assert "seed-ux-demo" not in spec
    assert 'root / "scripts"' not in spec


def test_seed_preserves_conflicting_registration(client):
    with SessionLocal() as db:
        db.add(
            Device(
                name=SEED["DEVICE_NAMES"][0],
                protocol="serial_json",
                connection_type="serial",
                port="COM_EXISTING",
            )
        )
        db.commit()
        with pytest.raises(ValueError, match="conflitante"):
            SEED["seed_demo"](db, db.scalar(select(User)), environment="test")
        db.rollback()
        assert (
            db.scalar(select(Device.port).where(Device.name == SEED["DEVICE_NAMES"][0]))
            == "COM_EXISTING"
        )
