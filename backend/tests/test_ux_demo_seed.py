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
    SessionDevice,
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
        second = SEED["seed_demo"](db, user, environment="test")
        db.commit()
        assert first["created_sessions"] == 7
        assert second["created_sessions"] == 0
        assert first["sessions"] == second["sessions"]
        assert first["electrical_samples"] == second["electrical_samples"] == 4746
        assert first["temperature_samples"] == second["temperature_samples"] == 4921
        assert first["alerts"] == second["alerts"] == 2
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
            == 13
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(TemperatureChannelValue)
                .join(TemperatureSample, TemperatureChannelValue.sample_id == TemperatureSample.id)
                .where(TemperatureSample.session_id.in_(ids))
            )
            == 4921 * 32
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
            end=SEED["START"] + timedelta(days=7),
            session_ids=ids,
            channels=[25, 26, 27, 28, 29, 30, 31, 32],
        )
        data = PeriodReportDataService(db).collect(request)
        statistics = period_statistics(data)
        assert statistics["general"]["electrical_sample_count"] == 4746
        assert statistics["general"]["temperature_sample_count"] == 4921


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
