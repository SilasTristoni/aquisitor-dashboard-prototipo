"""Hardware-derived integration coverage for independent electrical/thermal sources."""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from statistics import fmean
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.adapters.base import DeviceInformation, DeviceReading, DeviceStatus
from app.adapters.specific import (
    At4532Normalizer,
    At4532Parser,
    Gpm8213Normalizer,
    Gpm8213Parser,
)
from app.core.database import SessionLocal
from app.models import (
    Device,
    ElectricalSample,
    MeasurementSession,
    SessionChannelConfiguration,
    SessionDevice,
    TemperatureChannelValue,
    TemperatureSample,
)
from app.services.acquisition import AcquisitionService, DeviceRuntime, acquisition_service
from app.services.usb_discovery import usb_discovery_service

pytestmark = pytest.mark.physical_regression_fixtures

PHYSICAL_TEMPERATURES = [21.79, 21.62, 21.38, 21.34, 21.57, 21.71, 21.90, 22.19]
PHYSICAL_AUXILIARY_FIELDS = [f"AUXILIARY_RAW_{index:02d}" for index in range(1, 35)]
GPM_PHYSICAL_HEADERS = b"Urms,Irms,P,S,fU,PF,Q,fI\r\n"
GPM_PHYSICAL_VALUES = (
    b"127.58E+00,240.02E-03,17.688E+00,30.622E+00,59.993E+00,"
    b"0.5776E+00,24.997E+00,NAN\r\n"
)


def _tcp32_physical_frame(timestamp: datetime) -> bytes:
    local_timestamp = timestamp.astimezone(ZoneInfo("America/Sao_Paulo"))
    channels = ["Open|K|℃"] * 24 + [
        f"{value:.2f}|K|℃" for value in PHYSICAL_TEMPERATURES
    ]
    fields = [
        "TCP-32",
        f"T:{local_timestamp:%Y/%m/%d %H:%M:%S}",
        "27.3",
        *channels,
        *PHYSICAL_AUXILIARY_FIELDS,
    ]
    assert len(fields) == 69
    return (",".join(fields) + "\r\n").encode("cp936")


class PhysicalStreamFixtureAdapter:
    def __init__(
        self,
        role: str,
        *,
        fail_connect: bool = False,
        fail_after: int | None = None,
        fail_stop: bool = False,
        fail_disconnect_attempts: int = 0,
    ) -> None:
        self.role = role
        self.fail_connect = fail_connect
        self.fail_after = fail_after
        self.fail_stop = fail_stop
        self.fail_disconnect_attempts = fail_disconnect_attempts
        self.interval_seconds = 0.012 if role == "electrical" else 0.045
        self.connected = False
        self.reading = False
        self.messages = 0
        self.last_message_at: datetime | None = None
        self.disconnect_calls = 0
        self.base_timestamp = datetime(2026, 8, 25, 19, 35, 12, tzinfo=UTC)

    async def connect(self) -> None:
        if self.fail_connect:
            equipment = "GPM-8213" if self.role == "electrical" else "AT4532"
            raise ConnectionError(f"{equipment} fixture connection failed")
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        if self.disconnect_calls <= self.fail_disconnect_attempts:
            raise RuntimeError(f"{self.role} fixture disconnect failure")
        self.connected = False
        self.reading = False

    async def stop_reading(self) -> None:
        if self.fail_stop:
            raise RuntimeError(f"{self.role} fixture stop failure")
        self.reading = False

    def _reading(self) -> DeviceReading:
        timestamp = self.base_timestamp + timedelta(
            seconds=self.messages * (1 if self.role == "electrical" else 3)
        )
        if self.role == "electrical":
            parser = Gpm8213Parser()
            headers = parser.parse_headers(GPM_PHYSICAL_HEADERS, 8)
            values = parser.parse(GPM_PHYSICAL_VALUES, headers)
            return Gpm8213Normalizer().normalize(
                values,
                parser.units,
                {
                    "fixture": "GPM physical VALUE?",
                    "raw_header": GPM_PHYSICAL_HEADERS.decode("ascii").strip(),
                    "raw_values": GPM_PHYSICAL_VALUES.decode("ascii").strip(),
                },
            )
        payload = _tcp32_physical_frame(timestamp)
        return At4532Normalizer().normalize(
            At4532Parser().parse(payload),
            payload,
        )

    async def start_reading(self):
        if not self.connected:
            raise RuntimeError("Fixture source is disconnected")
        self.reading = True
        try:
            while self.connected and self.reading:
                if self.fail_after is not None and self.messages >= self.fail_after:
                    raise RuntimeError(f"{self.role} fixture read failure")
                reading = self._reading()
                self.messages += 1
                self.last_message_at = reading.received_timestamp
                yield reading
                await asyncio.sleep(self.interval_seconds)
        finally:
            self.reading = False

    def parse_message(self, _raw: bytes | str) -> DeviceReading:
        return self._reading()

    async def get_status(self) -> DeviceStatus:
        return DeviceStatus(
            state="reading"
            if self.reading
            else "connected"
            if self.connected
            else "disconnected",
            connected=self.connected,
            reading=self.reading,
            last_message_at=self.last_message_at,
            messages_per_second=0,
        )

    async def get_device_information(self) -> DeviceInformation:
        return DeviceInformation(adapter=f"physical-{self.role}-fixture")


def _physical_device_ids(
    client: TestClient, auth_headers: dict[str, str]
) -> tuple[int, int]:
    devices = client.get("/api/v1/devices", headers=auth_headers).json()
    electrical_id = next(
        device["id"] for device in devices if device["protocol"] == "gpm8213_serial"
    )
    thermal_id = next(
        device["id"] for device in devices if device["protocol"] == "at4532_serial"
    )
    return electrical_id, thermal_id


def _install_fixture_adapters(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_connect_role: str | None = None,
    fail_after_role: str | None = None,
    fail_stop_role: str | None = None,
) -> dict[str, list[PhysicalStreamFixtureAdapter]]:
    created: dict[str, list[PhysicalStreamFixtureAdapter]] = {
        "electrical": [],
        "thermal": [],
    }

    def adapter_for(device) -> PhysicalStreamFixtureAdapter:
        role = "electrical" if device.protocol == "gpm8213_serial" else "thermal"
        adapter = PhysicalStreamFixtureAdapter(
            role,
            fail_connect=role == fail_connect_role,
            fail_after=5 if role == fail_after_role else None,
            fail_stop=role == fail_stop_role,
        )
        created[role].append(adapter)
        return adapter

    monkeypatch.setattr(acquisition_service, "_adapter_for", adapter_for)
    monkeypatch.setattr(usb_discovery_service, "discover", lambda *_args, **_kwargs: [])
    return created


def _connect_sources(
    client: TestClient,
    auth_headers: dict[str, str],
    electrical_id: int,
    thermal_id: int,
):
    return client.post(
        "/api/v1/devices/connect-sources",
        headers=auth_headers,
        json={
            "electrical_device_id": electrical_id,
            "thermal_device_id": thermal_id,
        },
    )


def _start_session(
    client: TestClient,
    auth_headers: dict[str, str],
    electrical_id: int,
    thermal_id: int,
):
    return client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={
            "name": "Physical combined fixture",
            "electrical_device_id": electrical_id,
            "temperature_device_id": thermal_id,
        },
    )


def test_both_sources_persist_independent_physical_series_and_dashboard_values(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fixture_adapters(monkeypatch)
    electrical_id, thermal_id = _physical_device_ids(client, auth_headers)

    connected = _connect_sources(client, auth_headers, electrical_id, thermal_id)
    assert connected.status_code == 200, connected.text
    assert connected.json()["overall"] == "both"
    assert connected.json()["electrical"]["success"] is True
    assert connected.json()["thermal"]["success"] is True

    started = _start_session(client, auth_headers, electrical_id, thermal_id)
    assert started.status_code == 201, started.text
    assert started.json()["status"] == "running"
    assert started.json()["connection"]["overall"] == "both"
    session_id = started.json()["id"]

    time.sleep(0.24)
    electrical_status = client.get(
        f"/api/v1/devices/{electrical_id}/status", headers=auth_headers
    ).json()
    thermal_status = client.get(
        f"/api/v1/devices/{thermal_id}/status", headers=auth_headers
    ).json()
    assert electrical_status["sample_count"] > thermal_status["sample_count"] >= 2
    assert electrical_status["latest_reading"]["power_w"] == pytest.approx(17.688)
    assert thermal_status["latest_reading"]["raw_payload"]["valid_channels"] == 8

    snapshot = client.get(
        "/api/v1/acquisition/combined-status", headers=auth_headers
    ).json()
    assert snapshot["overall"] == "both"
    assert snapshot["electrical"]["sample_count"] >= electrical_status["sample_count"]
    assert snapshot["thermal"]["sample_count"] >= thermal_status["sample_count"]
    assert snapshot["electrical"]["last_reading"]["power_w"] == pytest.approx(17.688)
    assert snapshot["thermal"]["last_reading"]["raw_payload"]["valid_channels"] == 8

    finished = client.post(
        f"/api/v1/sessions/{session_id}/finish", headers=auth_headers
    )
    assert finished.status_code == 200, finished.text

    with SessionLocal() as db:
        electrical_rows = list(
            db.scalars(
                select(ElectricalSample)
                .where(ElectricalSample.session_id == session_id)
                .order_by(ElectricalSample.received_timestamp)
            )
        )
        thermal_rows = list(
            db.scalars(
                select(TemperatureSample)
                .where(TemperatureSample.session_id == session_id)
                .order_by(TemperatureSample.received_timestamp)
            )
        )
        assert len(electrical_rows) > len(thermal_rows) >= 2
        assert len({row.received_timestamp for row in thermal_rows}) == len(thermal_rows)
        assert len({row.device_timestamp for row in thermal_rows}) == len(thermal_rows)
        assert all(row.device_timestamp is None for row in electrical_rows)
        assert all(
            row.received_timestamp != row.device_timestamp for row in thermal_rows
        )
        assert {row.active_power_w for row in electrical_rows} == {17.688}

        latest_thermal = thermal_rows[-1]
        assert latest_thermal.ambient_temperature_c == pytest.approx(27.3)
        assert latest_thermal.raw_payload["wire_encoding"] == "cp936"
        assert latest_thermal.raw_payload["total_fields"] == 69
        channel_rows = list(
            db.scalars(
                select(TemperatureChannelValue)
                .where(TemperatureChannelValue.sample_id == latest_thermal.id)
                .order_by(TemperatureChannelValue.channel)
            )
        )
        values = [row.temperature_c for row in channel_rows]
        valid_values = [value for value in values if value is not None]
        assert values[:24] == [None] * 24
        assert valid_values == PHYSICAL_TEMPERATURES
        assert fmean(valid_values) == pytest.approx(fmean(PHYSICAL_TEMPERATURES))
        assert max(valid_values) == pytest.approx(22.19)
        assert [row.quality for row in channel_rows[:24]] == ["open_sensor"] * 24


@pytest.mark.parametrize(
    ("failed_role", "healthy_role", "expected_session_role"),
    [
        pytest.param("thermal", "electrical", "electrical", id="gpm-ok-at-error"),
        pytest.param("electrical", "thermal", "temperature", id="at-ok-gpm-error"),
    ],
)
def test_partial_connection_and_session_keep_the_healthy_source(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    failed_role: str,
    healthy_role: str,
    expected_session_role: str,
) -> None:
    _install_fixture_adapters(monkeypatch, fail_connect_role=failed_role)
    electrical_id, thermal_id = _physical_device_ids(client, auth_headers)
    ids = {"electrical": electrical_id, "thermal": thermal_id}

    connected = _connect_sources(client, auth_headers, electrical_id, thermal_id)
    assert connected.status_code == 200, connected.text
    result = connected.json()
    assert result["overall"] == "partial"
    assert result[healthy_role]["success"] is True
    assert result[failed_role]["status"] == "error"
    assert result[failed_role]["error"]
    assert ids[healthy_role] in acquisition_service.runtimes
    assert ids[failed_role] not in acquisition_service.runtimes

    failed_status = client.get(
        f"/api/v1/devices/{ids[failed_role]}/status", headers=auth_headers
    ).json()
    assert failed_status["state"] == "error"
    assert failed_status["last_error"] == result[failed_role]["error"]

    started = _start_session(client, auth_headers, electrical_id, thermal_id)
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["status"] == "running"
    assert body["connection"]["overall"] == "partial"
    assert body["connection"][healthy_role]["success"] is True
    assert body["connection"][failed_role]["success"] is False
    assert [source["role"] for source in body["devices"]] == [expected_session_role]
    session_id = body["id"]

    time.sleep(0.16)
    healthy_status = client.get(
        f"/api/v1/devices/{ids[healthy_role]}/status", headers=auth_headers
    ).json()
    assert healthy_status["connected"] is True
    assert healthy_status["sample_count"] >= 2

    snapshot = client.get(
        "/api/v1/acquisition/combined-status", headers=auth_headers
    ).json()
    assert snapshot["overall"] == "partial"
    assert snapshot[healthy_role]["success"] is True
    assert snapshot[failed_role]["status"] == "error"
    assert snapshot[failed_role]["connect_result"]["error"] == result[failed_role]["error"]

    finished = client.post(
        f"/api/v1/sessions/{session_id}/finish", headers=auth_headers
    )
    assert finished.status_code == 200, finished.text
    with SessionLocal() as db:
        roles = set(
            db.scalars(select(SessionDevice.role).where(SessionDevice.session_id == session_id))
        )
        assert roles == {expected_session_role}
        channel_configuration_count = db.scalar(
            select(func.count())
            .select_from(SessionChannelConfiguration)
            .where(SessionChannelConfiguration.session_id == session_id)
        )
        assert channel_configuration_count == (32 if healthy_role == "thermal" else 0)
        electrical_count = db.scalar(
            select(func.count())
            .select_from(ElectricalSample)
            .where(ElectricalSample.session_id == session_id)
        )
        thermal_count = db.scalar(
            select(func.count())
            .select_from(TemperatureSample)
            .where(TemperatureSample.session_id == session_id)
        )
        if healthy_role == "electrical":
            assert electrical_count >= 1
            assert thermal_count == 0
        else:
            assert thermal_count >= 1
            assert electrical_count == 0


def test_read_failure_during_session_does_not_stop_the_other_source(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fixture_adapters(monkeypatch, fail_after_role="thermal")
    electrical_id, thermal_id = _physical_device_ids(client, auth_headers)
    started = _start_session(client, auth_headers, electrical_id, thermal_id)
    assert started.status_code == 201, started.text
    assert started.json()["connection"]["overall"] == "both"
    session_id = started.json()["id"]

    time.sleep(0.27)
    thermal_status = client.get(
        f"/api/v1/devices/{thermal_id}/status", headers=auth_headers
    ).json()
    electrical_before = client.get(
        f"/api/v1/devices/{electrical_id}/status", headers=auth_headers
    ).json()
    assert thermal_status["state"] == "error"
    assert thermal_status["connected"] is False
    assert "thermal fixture read failure" in thermal_status["last_error"]
    assert electrical_before["connected"] is True

    time.sleep(0.08)
    electrical_after = client.get(
        f"/api/v1/devices/{electrical_id}/status", headers=auth_headers
    ).json()
    assert electrical_after["sample_count"] > electrical_before["sample_count"]

    finished = client.post(
        f"/api/v1/sessions/{session_id}/finish", headers=auth_headers
    )
    assert finished.status_code == 200, finished.text
    with SessionLocal() as db:
        electrical_count = db.scalar(
            select(func.count())
            .select_from(ElectricalSample)
            .where(ElectricalSample.session_id == session_id)
        )
        thermal_count = db.scalar(
            select(func.count())
            .select_from(TemperatureSample)
            .where(TemperatureSample.session_id == session_id)
        )
        assert electrical_count > thermal_count >= 1


def test_connect_sources_rejects_swapped_physical_roles_and_never_reports_duplicate_as_both(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _install_fixture_adapters(monkeypatch)
    electrical_id, thermal_id = _physical_device_ids(client, auth_headers)

    swapped = _connect_sources(client, auth_headers, thermal_id, electrical_id)
    assert swapped.status_code == 200, swapped.text
    assert swapped.json()["overall"] == "none"
    assert "não pode ser usado como fonte elétrica" in swapped.json()["electrical"]["error"]
    assert "não pode ser usado como fonte térmica" in swapped.json()["thermal"]["error"]
    assert created == {"electrical": [], "thermal": []}

    duplicate = _connect_sources(client, auth_headers, electrical_id, electrical_id)
    assert duplicate.status_code == 422, duplicate.text
    assert "equipamentos distintos" in duplicate.text

    invalid_session = client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={
            "name": "Duplicate physical role",
            "electrical_device_id": electrical_id,
            "temperature_device_id": electrical_id,
        },
    )
    assert invalid_session.status_code == 422
    assert "equipamentos distintos" in invalid_session.text


def test_session_preflight_failure_keeps_the_other_valid_source(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _install_fixture_adapters(monkeypatch)
    electrical_id, thermal_id = _physical_device_ids(client, auth_headers)
    with SessionLocal() as db:
        thermal = db.get(Device, thermal_id)
        assert thermal is not None
        thermal.active = False
        db.commit()

    started = _start_session(client, auth_headers, electrical_id, thermal_id)
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["status"] == "running"
    assert body["device_id"] == electrical_id
    assert body["connection"]["overall"] == "partial"
    assert body["connection"]["electrical"]["success"] is True
    assert body["connection"]["thermal"]["success"] is False
    assert "inativo" in body["connection"]["thermal"]["error"]
    assert created["thermal"] == []
    assert [item["role"] for item in body["devices"]] == ["electrical"]

    with SessionLocal() as db:
        assert db.scalar(
            select(func.count())
            .select_from(SessionChannelConfiguration)
            .where(SessionChannelConfiguration.session_id == body["id"])
        ) == 0
    assert client.post(
        f"/api/v1/sessions/{body['id']}/finish", headers=auth_headers
    ).status_code == 200


@pytest.mark.asyncio
async def test_flush_failure_retains_buffer_and_restores_pause_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CommitFailureSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _statement):
            return "electrical"

        def scalars(self, _statement):
            return []

        def add(self, _item) -> None:
            return None

        def commit(self) -> None:
            raise RuntimeError("fixture commit failure")

    reading = PhysicalStreamFixtureAdapter("electrical")._reading()
    runtime = DeviceRuntime(
        adapter=PhysicalStreamFixtureAdapter("electrical"),
        session_id=99,
        buffer=[reading],
    )
    service = AcquisitionService()
    service.runtimes[913349] = runtime
    monkeypatch.setattr(
        "app.services.acquisition.SessionLocal", lambda: CommitFailureSession()
    )

    with pytest.raises(RuntimeError, match="fixture commit failure"):
        await service.pause_session(913349)

    assert runtime.buffer == [reading]
    assert runtime.paused is False


@pytest.mark.asyncio
async def test_connection_commit_failure_closes_adapter_before_runtime_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = Device(
        id=913349,
        name="Commit failure fixture",
        connection_type="simulator",
        protocol="simulator",
        active=True,
    )

    class CommitFailureSession:
        rollback_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _model, _device_id):
            return device

        def add(self, _item) -> None:
            return None

        def commit(self) -> None:
            raise RuntimeError("fixture connection commit failure")

        def rollback(self) -> None:
            self.rollback_calls += 1

    adapter = PhysicalStreamFixtureAdapter("electrical")
    service = AcquisitionService()
    monkeypatch.setattr(service, "_adapter_for", lambda _device: adapter)
    monkeypatch.setattr(
        "app.services.acquisition.SessionLocal", lambda: CommitFailureSession()
    )

    with pytest.raises(RuntimeError, match="fixture connection commit failure"):
        await service.connect(device.id)

    assert adapter.disconnect_calls == 1
    assert adapter.connected is False
    assert device.id not in service.runtimes
    assert service.last_connection_results[device.id]["status"] == "error"


@pytest.mark.asyncio
async def test_connection_cleanup_failure_retains_adapter_for_close_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = Device(
        id=913350,
        name="Retryable close fixture",
        connection_type="simulator",
        protocol="simulator",
        active=True,
    )

    class CommitFailureSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _model, _device_id):
            return device

        def add(self, _item) -> None:
            return None

        def commit(self) -> None:
            raise RuntimeError("fixture connection commit failure")

        def rollback(self) -> None:
            return None

    adapter = PhysicalStreamFixtureAdapter("electrical", fail_disconnect_attempts=1)
    service = AcquisitionService()
    monkeypatch.setattr(service, "_adapter_for", lambda _device: adapter)
    monkeypatch.setattr(
        "app.services.acquisition.SessionLocal", lambda: CommitFailureSession()
    )

    with pytest.raises(RuntimeError, match="fixture connection commit failure"):
        await service.connect(device.id)

    assert service.runtimes[device.id].adapter is adapter
    assert "fechamento pendente" in service.runtimes[device.id].last_error
    assert adapter.connected is True

    await service.disconnect(device.id)
    assert adapter.disconnect_calls == 2
    assert adapter.connected is False
    assert device.id not in service.runtimes


@pytest.mark.asyncio
async def test_concurrent_connect_uses_one_adapter_and_one_acquisition_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = Device(
        id=913349,
        name="Concurrent connection fixture",
        connection_type="simulator",
        protocol="simulator",
        active=True,
    )

    class SuccessfulSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _model, _device_id):
            return device

        def add(self, _item) -> None:
            return None

        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

    created: list[PhysicalStreamFixtureAdapter] = []

    def adapter_for(_device: Device) -> PhysicalStreamFixtureAdapter:
        adapter = PhysicalStreamFixtureAdapter("electrical")
        created.append(adapter)
        return adapter

    service = AcquisitionService()
    monkeypatch.setattr(service, "_adapter_for", adapter_for)
    monkeypatch.setattr("app.services.acquisition.SessionLocal", lambda: SuccessfulSession())

    first, second = await asyncio.gather(
        service.connect(device.id),
        service.connect(device.id),
    )

    assert first["connected"] is True
    assert second["connected"] is True
    assert len(created) == 1
    assert len(service.runtimes) == 1
    assert service.runtimes[device.id].task is not None
    await service.disconnect(device.id)


@pytest.mark.asyncio
async def test_disconnect_flush_failure_retains_runtime_until_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CommitFailureSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _statement):
            return "electrical"

        def scalars(self, _statement):
            return []

        def add(self, _item) -> None:
            return None

        def commit(self) -> None:
            raise RuntimeError("fixture disconnect flush failure")

    class RecoverySession(CommitFailureSession):
        def commit(self) -> None:
            return None

    adapter = PhysicalStreamFixtureAdapter("electrical")
    adapter.connected = True
    reading = adapter._reading()
    runtime = DeviceRuntime(adapter=adapter, session_id=99, buffer=[reading])
    service = AcquisitionService()
    service.runtimes[913349] = runtime
    monkeypatch.setattr(
        "app.services.acquisition.SessionLocal", lambda: CommitFailureSession()
    )

    with pytest.raises(RuntimeError, match="fixture disconnect flush failure"):
        await service.disconnect(913349)

    assert service.runtimes[913349] is runtime
    assert runtime.buffer == [reading]
    assert runtime.session_id == 99
    assert adapter.connected is False
    assert service.last_connection_results[913349]["status"] == "error"

    monkeypatch.setattr("app.services.acquisition.SessionLocal", lambda: RecoverySession())
    await service.disconnect(913349)

    assert runtime.buffer == []
    assert 913349 not in service.runtimes


def test_failed_pause_and_finish_do_not_publish_inconsistent_session_state(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fixture_adapters(monkeypatch)
    electrical_id, thermal_id = _physical_device_ids(client, auth_headers)
    started = _start_session(client, auth_headers, electrical_id, thermal_id)
    assert started.status_code == 201, started.text
    session_id = started.json()["id"]

    original_pause = acquisition_service.pause_session

    async def fail_thermal_pause(device_id: int) -> None:
        if device_id == thermal_id:
            raise RuntimeError("thermal pause fixture failure")
        await original_pause(device_id)

    monkeypatch.setattr(acquisition_service, "pause_session", fail_thermal_pause)
    paused = client.post(f"/api/v1/sessions/{session_id}/pause", headers=auth_headers)
    assert paused.status_code == 422, paused.text
    assert client.get(
        f"/api/v1/sessions/{session_id}", headers=auth_headers
    ).json()["status"] == "running"
    assert acquisition_service.runtimes[electrical_id].paused is False
    assert acquisition_service.runtimes[thermal_id].paused is False

    original_detach = acquisition_service.detach_session

    async def fail_thermal_detach(device_id: int) -> None:
        if device_id == thermal_id:
            raise RuntimeError("thermal finish fixture failure")
        await original_detach(device_id)

    monkeypatch.setattr(acquisition_service, "detach_session", fail_thermal_detach)
    finished = client.post(f"/api/v1/sessions/{session_id}/finish", headers=auth_headers)
    assert finished.status_code == 422, finished.text
    with SessionLocal() as db:
        session = db.get(MeasurementSession, session_id)
        assert session is not None
        assert session.status == "running"
        assert session.ended_at is None
    assert acquisition_service.runtimes[electrical_id].session_id == session_id
    assert acquisition_service.runtimes[thermal_id].session_id == session_id

    monkeypatch.setattr(acquisition_service, "detach_session", original_detach)
    assert client.post(
        f"/api/v1/sessions/{session_id}/finish", headers=auth_headers
    ).status_code == 200


def test_read_cleanup_closes_adapter_even_when_stop_reading_fails(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _install_fixture_adapters(
        monkeypatch,
        fail_after_role="thermal",
        fail_stop_role="thermal",
    )
    electrical_id, thermal_id = _physical_device_ids(client, auth_headers)
    started = _start_session(client, auth_headers, electrical_id, thermal_id)
    assert started.status_code == 201, started.text
    session_id = started.json()["id"]

    time.sleep(0.3)
    thermal_adapter = created["thermal"][0]
    thermal_status = client.get(
        f"/api/v1/devices/{thermal_id}/status", headers=auth_headers
    ).json()
    assert thermal_adapter.disconnect_calls >= 1
    assert thermal_adapter.connected is False
    assert "stop=RuntimeError" in thermal_status["last_error"]
    assert client.get(
        f"/api/v1/devices/{electrical_id}/status", headers=auth_headers
    ).json()["connected"] is True

    assert client.post(
        f"/api/v1/sessions/{session_id}/finish", headers=auth_headers
    ).status_code == 200
