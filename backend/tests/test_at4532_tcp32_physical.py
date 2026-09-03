from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.adapters.specific import (
    At4532Normalizer,
    At4532ParsedFrame,
    At4532Parser,
    At4532SerialAdapter,
    ProtocolResponseError,
)
from app.adapters.transports import (
    SerialTransport,
    SerialTransportConfiguration,
    SerialTransportError,
)
from app.core.database import SessionLocal
from app.models.entities import Device
from app.services.device_policy import (
    at4532_identity_fallback_policy,
    invalidate_stale_at4532_verification,
    mark_at4532_verified_by_measurement,
)
from app.services.protocol_probe import ProtocolProbeService, protocol_probe_service
from app.services.serial_diagnostic import RealSerialDiagnosticService
from app.services.usb_discovery import UsbDeviceDiscoveryService

pytestmark = pytest.mark.physical_regression_fixtures


PHYSICAL_CHANNEL_VALUES = [21.79, 21.62, 21.38, 21.34, 21.57, 21.71, 21.90, 22.19]
PHYSICAL_AUXILIARY_FIELDS = ["0.00|K|℃"] * 32 + ["001", "068214"]


def tcp32_physical_fixture(
    *,
    timestamp: str = "2026/08/25 16:35:12",
    channel_29: float = 21.57,
) -> bytes:
    values = list(PHYSICAL_CHANNEL_VALUES)
    values[4] = channel_29
    channels = ["Open|K|℃"] * 24 + [f"{value:.2f}|K|℃" for value in values]
    fields = ["TCP-32", f"T:{timestamp}", "27.3", *channels, *PHYSICAL_AUXILIARY_FIELDS]
    assert len(fields) == 69
    return (",".join(fields) + "\r\n").encode("cp936")


class FakeAt4532Transport:
    def __init__(
        self, responses: list[bytes | Exception], *, fail_close: bool = False
    ) -> None:
        self.responses = list(responses)
        self.fail_close = fail_close
        self.requests: list[bytes] = []
        self.is_open = False
        self.open_boundary: dict[str, Any] = {}
        self.last_query_boundary: dict[str, Any] = {}
        self.open_calls = 0
        self.close_calls = 0

    async def open(self) -> float:
        self.open_calls += 1
        self.is_open = True
        return 1.0

    async def query(
        self, payload: bytes, _terminator: bytes, _max_bytes: int = 65_536
    ) -> tuple[bytes, float]:
        self.requests.append(payload)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response, 2.0

    async def write(self, payload: bytes) -> tuple[int, float]:
        self.requests.append(payload)
        return len(payload), 1.0

    async def close(self) -> None:
        self.close_calls += 1
        if self.fail_close:
            raise SerialTransportError("serial_error", "fixture close failure")
        self.is_open = False


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.value += seconds

    def advance(self, seconds: float) -> None:
        self.value += seconds


class CadenceSensitiveAt4532Transport:
    """Physical-like transport that rejects FETCH before the post-RX window."""

    minimum_interval_after_rx_seconds = 3.4

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.requests: list[bytes] = []
        self.is_open = False
        self.open_calls = 0
        self.close_calls = 0
        self.rejected_fetches = 0
        self.fetch_count = 0
        self.last_fetch_completed: float | None = None
        self.open_boundary: dict[str, Any] = {}
        self.last_query_boundary: dict[str, Any] = {}
        self.started_at = datetime(2026, 8, 25, 16, 35, 12)

    def _boundary(self, tx: float, rx: float) -> dict[str, Any]:
        utc_base = datetime(2026, 8, 25, 19, 35, 12, tzinfo=UTC)
        return {
            "timestamp_tx": (utc_base + timedelta(seconds=tx)).isoformat(),
            "timestamp_rx": (utc_base + timedelta(seconds=rx)).isoformat(),
            "tx_monotonic": tx,
            "rx_monotonic": rx,
            "query_duration_ms": round((rx - tx) * 1000, 3),
            "buffer_pending_before_tx_bytes": 0,
            "buffer_drained_bytes": 0,
            "pending_before_tx_bytes": 0,
            "pending_before_tx_ascii": "",
            "pending_before_tx_hex": "",
            "tx_flushed": True,
        }

    async def open(self) -> float:
        self.open_calls += 1
        self.is_open = True
        return 1.0

    async def write(self, payload: bytes) -> tuple[int, float]:
        self.requests.append(payload)
        return len(payload), 1.0

    async def query(
        self, payload: bytes, _terminator: bytes, _max_bytes: int = 65_536
    ) -> tuple[bytes, float]:
        self.requests.append(payload)
        tx = self.clock.monotonic()
        if payload == b"*IDN?\n":
            self.clock.advance(2.0)
            self.last_query_boundary = self._boundary(tx, self.clock.monotonic())
            raise SerialTransportError(
                "protocol_timeout", "Instrumento não respondeu ao comando."
            )
        assert payload == b"FETCH?\n"
        if (
            self.last_fetch_completed is not None
            and tx + 1e-9
            < self.last_fetch_completed + self.minimum_interval_after_rx_seconds
        ):
            self.rejected_fetches += 1
            self.clock.advance(2.0)
            self.last_query_boundary = self._boundary(tx, self.clock.monotonic())
            raise SerialTransportError(
                "protocol_timeout", "FETCH recebido antes da janela física simulada."
            )

        device_timestamp = self.started_at + timedelta(seconds=self.fetch_count * 3)
        payload_response = tcp32_physical_fixture(
            timestamp=device_timestamp.strftime("%Y/%m/%d %H:%M:%S"),
            channel_29=21.57 + self.fetch_count / 100,
        )
        assert len(payload_response) == 694
        self.fetch_count += 1
        self.clock.advance(0.375)
        self.last_fetch_completed = self.clock.monotonic()
        self.last_query_boundary = self._boundary(tx, self.last_fetch_completed)
        return payload_response, 375.0

    async def close(self) -> None:
        self.close_calls += 1
        self.is_open = False


def manual_at4532_device() -> Any:
    return type(
        "ManualAt4532Device",
        (),
        {
            "id": 4532,
            "protocol": "at4532_serial",
            "model": "AT4532",
            "port": "COM5",
            "baud_rate": 19200,
            "metadata_json": {
                "usb": {"manual_confirmed": True, "confirmed_port": "COM5"},
                "serial": {"data_bits": 8, "parity": "N", "stop_bits": 1},
            },
        },
    )()


@pytest.mark.parametrize("environment", ["development", "test", "physical-alpha"])
def test_at4532_fallback_requires_an_explicit_engineering_context(environment: str) -> None:
    policy = at4532_identity_fallback_policy(manual_at4532_device(), environment=environment)

    assert policy.allowed is True
    assert policy.execution_environment == environment
    assert policy.previously_verified_by_measurement is False


@pytest.mark.parametrize("environment", ["windows-beta", "production"])
def test_at4532_fallback_is_denied_outside_engineering_until_measurement_verified(
    environment: str,
) -> None:
    device = manual_at4532_device()
    denied = at4532_identity_fallback_policy(device, environment=environment)
    assert denied.allowed is False
    assert denied.reason == "engineering_context_or_measurement_verification_required"

    mark_at4532_verified_by_measurement(device, "2026-08-25T19:35:12+00:00")
    allowed = at4532_identity_fallback_policy(device, environment=environment)
    assert allowed.allowed is True
    assert allowed.reason == "previously_verified_by_measurement"
    assert allowed.previously_verified_by_measurement is True

    device.port = "COM2"
    device.metadata_json["usb"]["confirmed_port"] = "COM2"
    stale = at4532_identity_fallback_policy(device, environment=environment)
    assert stale.allowed is False
    assert stale.previously_verified_by_measurement is False
    assert invalidate_stale_at4532_verification(device) is True
    assert device.metadata_json["protocol_status"].endswith("physical_validation_pending")
    assert "protocol_verification" not in device.metadata_json


def test_verified_probe_persists_measurement_authorization(
    client: Any,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    devices = client.get("/api/v1/devices", headers=auth_headers).json()
    device_id = next(
        device["id"] for device in devices if device["protocol"] == "at4532_serial"
    )

    async def verified_run(_device: Device, _mode: str) -> dict[str, Any]:
        return {
            "device_id": device_id,
            "timestamp": "2026-08-25T19:35:12+00:00",
            "result": "passed_with_warning",
            "transport_closed": True,
            "protocol_status": "verified_by_measurement",
            "identity_status": "unconfirmed",
            "readings": [{"raw_payload": {"frame_type": "TCP-32"}}],
        }

    monkeypatch.setattr(protocol_probe_service, "run", verified_run)
    response = client.post(
        f"/api/v1/devices/{device_id}/protocol-probe",
        headers=auth_headers,
        json={"mode": "read", "operator_confirmed": True},
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        device = db.get(Device, device_id)
        assert device is not None
        assert device.metadata_json["protocol_status"] == "verified_by_measurement"
        assert device.metadata_json["protocol_verified_at"] == response.json()["timestamp"]
        assert device.metadata_json["protocol_verification"]["association"] == {
            "port": "COM5",
            "confirmed_port": "COM5",
            "manual_confirmed": True,
            "baud_rate": 19200,
            "data_bits": 8,
            "parity": "N",
            "stop_bits": 1,
            "usb_serial_number": None,
            "vid": 6790,
            "pid": 29987,
            "hardware_id": None,
            "location": None,
        }
        assert at4532_identity_fallback_policy(device, environment="production").allowed is True


def test_probe_does_not_persist_measurement_authorization_when_close_failed(
    client: Any,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    devices = client.get("/api/v1/devices", headers=auth_headers).json()
    device_id = next(
        device["id"] for device in devices if device["protocol"] == "at4532_serial"
    )

    async def close_failed_run(_device: Device, _mode: str) -> dict[str, Any]:
        return {
            "device_id": device_id,
            "timestamp": "2026-08-25T19:35:12+00:00",
            "result": "failed",
            "transport_closed": False,
            "protocol_status": "verified_by_measurement",
            "identity_status": "unconfirmed",
            "readings": [{"raw_payload": {"frame_type": "TCP-32"}}],
            "errors": [{"code": "close_failed", "message": "fixture close failure"}],
        }

    monkeypatch.setattr(protocol_probe_service, "run", close_failed_run)
    response = client.post(
        f"/api/v1/devices/{device_id}/protocol-probe",
        headers=auth_headers,
        json={"mode": "read", "operator_confirmed": True},
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        device = db.get(Device, device_id)
        assert device is not None
        assert device.metadata_json["protocol_status"].endswith(
            "physical_validation_pending"
        )
        assert "protocol_verification" not in device.metadata_json


def test_at4532_association_and_verification_metadata_are_server_owned(
    client: Any,
    auth_headers: dict[str, str],
) -> None:
    devices = client.get("/api/v1/devices", headers=auth_headers).json()
    at4532 = next(device for device in devices if device["protocol"] == "at4532_serial")
    device_id = at4532["id"]

    with SessionLocal() as db:
        device = db.get(Device, device_id)
        assert device is not None
        mark_at4532_verified_by_measurement(device, "2026-08-25T19:35:12+00:00")
        db.commit()

    unchanged_payload = {
        key: at4532[key]
        for key in (
            "name",
            "manufacturer",
            "model",
            "serial_number",
            "connection_type",
            "port",
            "baud_rate",
            "protocol",
            "active",
        )
    }
    unchanged_payload["metadata"] = at4532["metadata"]
    unchanged = client.put(
        f"/api/v1/devices/{device_id}", headers=auth_headers, json=unchanged_payload
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["metadata"]["protocol_status"] == "verified_by_measurement"

    forged_metadata = dict(unchanged.json()["metadata"])
    forged_metadata["usb"] = {
        **forged_metadata["usb"],
        "manual_confirmed": True,
        "confirmed_port": "COM2",
    }
    forged_metadata["protocol_status"] = "verified_by_measurement"
    forged_metadata["protocol_verification"] = {
        "verified_at": "forged",
        "association": {"port": "COM2", "confirmed_port": "COM2"},
    }
    changed_payload = {**unchanged_payload, "port": "COM2", "metadata": forged_metadata}
    changed = client.put(
        f"/api/v1/devices/{device_id}", headers=auth_headers, json=changed_payload
    )
    assert changed.status_code == 200, changed.text
    changed_metadata = changed.json()["metadata"]
    assert changed_metadata["usb"]["confirmed_port"] == "COM5"
    assert changed_metadata["protocol_status"].endswith("physical_validation_pending")
    assert "protocol_verification" not in changed_metadata

    forged_create = client.post(
        "/api/v1/devices",
        headers=auth_headers,
        json={
            "name": "Forged AT4532",
            "manufacturer": "Applent",
            "model": "AT4532",
            "connection_type": "serial",
            "port": "COM6",
            "baud_rate": 19200,
            "protocol": "at4532_serial",
            "active": True,
            "serial_settings": {"data_bits": 8, "parity": "N", "stop_bits": 1},
            "metadata": forged_metadata,
        },
    )
    assert forged_create.status_code == 201, forged_create.text
    created_metadata = forged_create.json()["metadata"]
    assert "usb" not in created_metadata
    assert created_metadata["protocol_status"].endswith("physical_validation_pending")
    assert "protocol_verification" not in created_metadata


def test_duplicate_at4532_port_is_reported_and_cannot_take_control(
    client: Any,
    auth_headers: dict[str, str],
) -> None:
    historical = client.post(
        "/api/v1/devices",
        headers=auth_headers,
        json={
            "name": "AT4532 antigo 115200",
            "manufacturer": "Applent",
            "model": "AT4532",
            "connection_type": "serial",
            "port": "COM5",
            "baud_rate": 115200,
            "protocol": "at4532_serial",
            "active": False,
        },
    )
    assert historical.status_code == 201, historical.text

    devices = client.get("/api/v1/devices", headers=auth_headers).json()
    canonical = next(device for device in devices if device["protocol"] == "at4532_serial")
    assert canonical["port"] == "COM5"
    assert canonical["baud_rate"] == 19200
    assert canonical["configuration_conflicts"] == [
        {
            "id": historical.json()["id"],
            "name": "AT4532 antigo 115200",
            "port": "COM5",
            "baud_rate": 115200,
            "active": False,
            "configuration_status": "historical_conflict",
        }
    ]

    conflicting = client.post(
        "/api/v1/devices",
        headers=auth_headers,
        json={
            "name": "AT4532 duplicado ativo",
            "manufacturer": "Applent",
            "model": "AT4532",
            "connection_type": "serial",
            "port": "COM5",
            "baud_rate": 19200,
            "protocol": "at4532_serial",
            "active": True,
        },
    )
    assert conflicting.status_code == 409
    assert "já é controlada" in conflicting.json()["error"]["message"]
    with SessionLocal() as db:
        assert db.get(Device, historical.json()["id"]) is not None


def test_tcp32_cp936_physical_frame_is_lossless_and_maps_ch01_through_ch32() -> None:
    payload = tcp32_physical_fixture()
    assert b"\xa1\xe6" in payload

    parser = At4532Parser()
    frame = parser.parse(payload)
    reading = At4532Normalizer().normalize(frame)

    assert isinstance(frame, At4532ParsedFrame)
    assert parser.classify(payload) == "temperature_measurement"
    assert frame.frame_type == "TCP-32"
    assert frame.wire_encoding == "cp936"
    assert frame.field_count == 69
    assert frame.raw_bytes == payload
    assert frame.raw_hex == payload.hex(" ").upper()
    assert frame.device_timestamp_raw == "T:2026/08/25 16:35:12"
    assert frame.device_timestamp == datetime(2026, 8, 25, 19, 35, 12, tzinfo=UTC)
    assert frame.ambient_temperature_raw == "27.3"
    assert frame.ambient_temperature_c == 27.3
    assert list(frame.auxiliary_fields_raw) == PHYSICAL_AUXILIARY_FIELDS

    assert reading.temperatures_c[:24] == [None] * 24
    assert reading.temperatures_c[24:] == PHYSICAL_CHANNEL_VALUES
    assert reading.channel_quality[:24] == ["open_sensor"] * 24
    assert reading.channel_quality[24:] == ["good"] * 8
    assert reading.raw_payload["valid_channels"] == 8
    assert reading.raw_payload["unavailable_channels"] == 24
    assert reading.raw_payload["open_channels"] == [f"CH{index:02d}" for index in range(1, 25)]
    assert reading.raw_payload["raw_bytes"] == list(payload)
    assert reading.raw_payload["raw_hex"] == payload.hex(" ").upper()
    assert reading.raw_payload["wire_encoding"] == "cp936"
    assert reading.raw_payload["total_fields"] == 69
    assert reading.raw_payload["auxiliary_fields_raw"] == PHYSICAL_AUXILIARY_FIELDS
    assert reading.raw_payload["open_sensor_encoding"] == "verified_tcp32_open_token"
    assert reading.device_timestamp == frame.device_timestamp
    assert reading.timestamp == frame.device_timestamp
    assert reading.received_timestamp != reading.device_timestamp
    assert reading.raw_payload["device_timestamp_timezone_assumption"] == "America/Sao_Paulo"

    ch01 = reading.raw_payload["channels"][0]
    ch25 = reading.raw_payload["channels"][24]
    ch29 = reading.raw_payload["channels"][28]
    ch32 = reading.raw_payload["channels"][31]
    assert ch01 == {
        "channel": "CH01",
        "position": 1,
        "raw_token": "Open|K|℃",
        "temperature_c": None,
        "quality": "open_sensor",
        "thermocouple_type": "K",
        "unit": "℃",
    }
    assert (ch25["channel"], ch25["temperature_c"]) == ("CH25", 21.79)
    assert (ch29["channel"], ch29["temperature_c"]) == ("CH29", 21.57)
    assert (ch32["channel"], ch32["temperature_c"]) == ("CH32", 22.19)
    assert ch25["thermocouple_type"] == "K"
    assert ch25["unit"] == "℃"


def test_at4532_keeps_the_strict_ascii_simple_format_compatible() -> None:
    payload = b"0,-12.5,+7.01e1,UNKNOWN\r\n"
    frame = At4532Parser().parse(payload)
    reading = At4532Normalizer().normalize(frame)

    assert frame.frame_type == "simple"
    assert frame.wire_encoding == "ascii"
    assert list(frame) == [0.0, -12.5, 70.1, None]
    assert reading.temperatures_c[:4] == [0.0, -12.5, 70.1, None]
    assert reading.channel_quality[:4] == ["good", "good", "good", "unknown_unavailable"]
    assert reading.raw_payload["raw_bytes"] == list(payload)


@pytest.mark.parametrize(
    "payload",
    [
        b"TCP-32,T:2026/08/25 16:35:12,27.3," + b",".join([b"0"] * 66) + b"\n",
        b"1,2,3\xa1\xe6\n",
        b"1,2,3\n4,5,6\n",
    ],
)
def test_at4532_rejects_ambiguous_or_non_ascii_simple_frames(payload: bytes) -> None:
    parser = At4532Parser()
    assert parser.classify(payload) == "unknown_response"
    with pytest.raises(ProtocolResponseError):
        parser.parse(payload)


def test_tcp32_rejects_invalid_cp936_wrong_field_count_and_all_open() -> None:
    parser = At4532Parser()
    physical = tcp32_physical_fixture()

    invalid_cp936 = physical[:-2] + b"\x81\n"
    with pytest.raises(ProtocolResponseError, match="CP936"):
        parser.parse(invalid_cp936)

    fields = physical.decode("cp936").strip().split(",")
    with pytest.raises(ProtocolResponseError, match="69 campos"):
        parser.parse((",".join(fields[:-1]) + "\n").encode("cp936"))

    all_open = fields[:3] + ["Open|K|℃"] * 32 + fields[35:]
    with pytest.raises(ProtocolResponseError, match="ao menos uma temperatura"):
        parser.parse((",".join(all_open) + "\n").encode("cp936"))


def test_tcp32_heating_series_changes_only_ch29_and_preserves_device_timestamps() -> None:
    timestamps = [
        "2026/08/25 16:35:12",
        "2026/08/25 16:35:15",
        "2026/08/25 16:35:18",
    ]
    readings = [
        At4532Normalizer().normalize(
            At4532Parser().parse(tcp32_physical_fixture(timestamp=timestamp, channel_29=value))
        )
        for timestamp, value in zip(timestamps, [21.5, 25.0, 29.0], strict=True)
    ]

    assert [reading.temperatures_c[28] for reading in readings] == [21.5, 25.0, 29.0]
    assert [reading.raw_payload["device_timestamp_raw"] for reading in readings] == [
        f"T:{timestamp}" for timestamp in timestamps
    ]
    assert len({reading.timestamp for reading in readings}) == 3
    for channel_index in [*range(28), 29, 30, 31]:
        assert len({reading.temperatures_c[channel_index] for reading in readings}) == 1
    assert [reading.temperatures_c[27] for reading in readings] == [21.34] * 3
    assert [reading.temperatures_c[29] for reading in readings] == [21.71] * 3


@pytest.mark.asyncio
async def test_tcp32_manual_com5_identity_timeout_verifies_measurement_and_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = tcp32_physical_fixture()
    transport = FakeAt4532Transport(
        [
            SerialTransportError("protocol_timeout", "Instrumento não respondeu ao comando."),
            payload,
        ]
    )

    def adapter_factory(port: str, baud_rate: int, **kwargs: Any) -> At4532SerialAdapter:
        return At4532SerialAdapter(port, baud_rate, transport=transport, **kwargs)

    monkeypatch.setattr("app.services.protocol_probe.At4532SerialAdapter", adapter_factory)
    report = await ProtocolProbeService().run(manual_at4532_device(), "read")

    assert transport.requests == [b"*IDN?\n", b"SYST:UNIT CEL\n", b"FETCH?\n"]
    assert report["identity_status"] == "unconfirmed"
    assert report["protocol_status"] == "verified_by_measurement"
    assert report["result"] == "passed_with_warning"
    assert report["transport_closed"] is True
    assert report["identity_error"]["code"] == "protocol_timeout"
    assert {stage["key"]: stage["status"] for stage in report["stages"]} == {
        "usb": "passed",
        "identity": "warning",
        "port": "passed",
        "protocol": "passed",
        "configuration": "passed",
        "reading": "passed",
        "acquisition": "pending",
    }
    summary = report["at4532_channel_summary"]
    assert summary["wire_encoding"] == "cp936"
    assert summary["frame_type"] == "TCP-32"
    assert summary["total_fields"] == 69
    assert summary["valid_channels"] == 8
    assert summary["unavailable_channels"] == 24
    assert summary["raw_bytes"] == list(payload)
    assert summary["raw_hex"] == payload.hex(" ").upper()
    assert summary["auxiliary_fields_raw"] == PHYSICAL_AUXILIARY_FIELDS
    assert len(summary["primary_channel_fields_raw"]) == 32
    assert len(summary["channels"]) == 32
    fetch_transaction = report["transactions"][-1]
    assert fetch_transaction["wire_encoding"] == "cp936"
    assert fetch_transaction["actual_response_type"] == "temperature_measurement"
    assert fetch_transaction["parsed"]["channels"][28]["channel"] == "CH29"
    assert fetch_transaction["parsed"]["channels"][28]["temperature_c"] == 21.57


@pytest.mark.asyncio
async def test_probe_close_failure_fails_gate_after_valid_measurement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeAt4532Transport(
        [
            SerialTransportError("protocol_timeout", "Instrumento não respondeu ao comando."),
            tcp32_physical_fixture(),
        ],
        fail_close=True,
    )

    def adapter_factory(port: str, baud_rate: int, **kwargs: Any) -> At4532SerialAdapter:
        return At4532SerialAdapter(port, baud_rate, transport=transport, **kwargs)

    monkeypatch.setattr("app.services.protocol_probe.At4532SerialAdapter", adapter_factory)
    service = ProtocolProbeService()
    report = await service.run(manual_at4532_device(), "read")

    assert report["protocol_status"] == "verified_by_measurement"
    assert report["result"] == "failed"
    assert report["transport_closed"] is False
    assert report["close_retry_pending"] is True
    assert report["stages"][2]["status"] == "failed"
    assert report["errors"][-1]["code"] == "close_failed"
    assert service.pending_close_adapters[4532][0].transport is transport

    transport.fail_close = False
    await service.shutdown()
    assert service.pending_close_adapters == {}
    assert transport.is_open is False


@pytest.mark.asyncio
async def test_serial_transport_retains_connection_reference_until_close_succeeds() -> None:
    class FailOnceSerial:
        def __init__(self) -> None:
            self.is_open = True
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise OSError("fixture close failure")
            self.is_open = False

    connection = FailOnceSerial()
    transport = SerialTransport(
        SerialTransportConfiguration(
            port="COM5",
            baud_rate=19200,
            data_bits=8,
            parity="N",
            stop_bits=1,
            timeout_s=1,
            read_timeout_s=2,
        ),
        serial_factory=lambda **_kwargs: connection,
    )
    await transport.open()

    with pytest.raises(SerialTransportError):
        await transport.close()
    assert transport.connection is connection
    assert transport.is_open is True

    await transport.close()
    assert transport.connection is None
    assert connection.close_calls == 2


@pytest.mark.asyncio
async def test_serial_diagnostic_retains_session_when_close_needs_retry() -> None:
    class FailOnceSerial:
        def __init__(self, **_kwargs: Any) -> None:
            self.is_open = True
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise OSError("fixture diagnostic close failure")
            self.is_open = False

    connection = FailOnceSerial()
    service = RealSerialDiagnosticService(lambda **_kwargs: connection)
    configuration = SerialTransportConfiguration(
        port="COM5",
        baud_rate=19200,
        data_bits=8,
        parity="N",
        stop_bits=1,
        timeout_s=1,
        read_timeout_s=2,
    )
    opened = await service.open(configuration)

    with pytest.raises(SerialTransportError):
        await service.close(opened["session_id"])
    assert opened["session_id"] in service.sessions

    closed = await service.close(opened["session_id"])
    assert closed["closed"] is True
    assert opened["session_id"] not in service.sessions
    assert connection.close_calls == 2


@pytest.mark.asyncio
async def test_serial_diagnostic_retains_transport_when_open_cleanup_needs_retry() -> None:
    class OpenBoundaryFailureSerial:
        def __init__(self) -> None:
            self.is_open = True
            self.allow_close = False
            self.close_calls = 0

        def reset_input_buffer(self) -> None:
            raise OSError("fixture open boundary failure")

        def close(self) -> None:
            self.close_calls += 1
            if not self.allow_close:
                raise OSError("fixture diagnostic close failure")
            self.is_open = False

    connection = OpenBoundaryFailureSerial()
    service = RealSerialDiagnosticService(lambda **_kwargs: connection)
    configuration = SerialTransportConfiguration(
        port="COM5",
        baud_rate=19200,
        data_bits=8,
        parity="N",
        stop_bits=1,
        timeout_s=1,
        read_timeout_s=2,
    )

    with pytest.raises(SerialTransportError) as caught:
        await service.open(configuration)
    assert caught.value.code == "serial_error"
    assert service.sessions == {}
    assert service.pending_close_transports["com5"][0].connection is connection
    assert connection.is_open is True

    with pytest.raises(SerialTransportError) as retry:
        await service.open(configuration)
    assert retry.value.code == "port_close_pending"

    connection.allow_close = True
    await service.shutdown()
    assert service.pending_close_transports == {}
    assert connection.is_open is False


@pytest.mark.asyncio
async def test_serial_transport_retains_connection_after_silent_close_failure() -> None:
    class SilentFailOnceSerial:
        def __init__(self) -> None:
            self.is_open = True
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            if self.close_calls > 1:
                self.is_open = False

    connection = SilentFailOnceSerial()
    transport = SerialTransport(
        SerialTransportConfiguration(
            port="COM5",
            baud_rate=19200,
            data_bits=8,
            parity="N",
            stop_bits=1,
            timeout_s=1,
            read_timeout_s=2,
        ),
        serial_factory=lambda **_kwargs: connection,
    )
    await transport.open()

    with pytest.raises(SerialTransportError) as caught:
        await transport.close()
    assert caught.value.code == "serial_close_failed"
    assert transport.connection is connection

    await transport.close()
    assert transport.connection is None
    assert connection.close_calls == 2


def test_usb_discovery_retains_failed_close_and_blocks_duplicate_open() -> None:
    close_allowed = False
    connections = []

    class CloseControlledSerial:
        def __init__(self) -> None:
            self.is_open = True
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            if not close_allowed:
                raise OSError("fixture USB discovery close failure")
            self.is_open = False

    def factory(**_kwargs):
        connection = CloseControlledSerial()
        connections.append(connection)
        return connection

    service = UsbDeviceDiscoveryService(lambda: [], factory)
    status, _ = service._port_status("COM5", set())
    assert status == "unavailable"
    assert len(connections) == 1
    assert service.pending_close_connections["com5"] == [connections[0]]

    status, _ = service._port_status("COM5", set())
    assert status == "port_busy"
    assert len(connections) == 1

    close_allowed = True
    service.shutdown()
    assert service.pending_close_connections == {}
    assert connections[0].is_open is False

    status, _ = service._port_status("COM5", set())
    assert status == "available"
    assert len(connections) == 2
    assert connections[1].is_open is False


@pytest.mark.asyncio
async def test_tcp32_continuous_polling_reuses_handshake_and_tracks_ch29(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamps = [
        "2026/08/25 16:35:12",
        "2026/08/25 16:35:15",
        "2026/08/25 16:35:18",
    ]
    payloads = [
        tcp32_physical_fixture(timestamp=timestamp, channel_29=value)
        for timestamp, value in zip(timestamps, [21.5, 25.0, 29.0], strict=True)
    ]
    transport = FakeAt4532Transport(
        [
            SerialTransportError("protocol_timeout", "Instrumento não respondeu ao comando."),
            *payloads,
        ]
    )
    adapter = At4532SerialAdapter(
        "COM5",
        19200,
        transport=transport,
        allow_identity_fallback=True,
        association_source="manual_port",
    )
    sleep_calls: list[float] = []

    async def no_delay(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.adapters.specific.asyncio.sleep", no_delay)

    await adapter.connect()
    stream = adapter.start_reading()
    readings = [await anext(stream), await anext(stream), await anext(stream)]
    await adapter.stop_reading()
    await stream.aclose()
    await adapter.disconnect()

    assert adapter.expected_interval_seconds == 3.0
    assert transport.requests.count(b"*IDN?\n") == 1
    assert transport.requests.count(b"SYST:UNIT CEL\n") == 1
    assert transport.requests.count(b"FETCH?\n") == 3
    assert [reading.temperatures_c[28] for reading in readings] == [21.5, 25.0, 29.0]
    assert [reading.raw_payload["device_timestamp_raw"] for reading in readings] == [
        f"T:{timestamp}" for timestamp in timestamps
    ]
    assert all(3.3 <= delay <= 3.4 for delay in sleep_calls)
    assert len(sleep_calls) == 2
    assert adapter.identity_status == "unconfirmed"
    assert adapter.protocol_status == "verified_by_measurement"


@pytest.mark.asyncio
async def test_at4532_continuous_acquisition_completes_100_samples_after_rx_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    transport = CadenceSensitiveAt4532Transport(clock)
    monkeypatch.setattr("app.adapters.specific.monotonic", clock.monotonic)
    monkeypatch.setattr("app.adapters.specific.asyncio.sleep", clock.sleep)
    adapter = At4532SerialAdapter(
        "COM5",
        19200,
        transport=transport,
        allow_identity_fallback=True,
        association_source="manual_port",
    )

    await adapter.connect()
    stream = adapter.start_reading()
    readings = [await anext(stream) for _ in range(100)]
    await adapter.stop_reading()
    await stream.aclose()
    await adapter.disconnect()

    fetch_transactions = [
        transaction
        for transaction in adapter.transactions
        if transaction["command_name"] == "temperatures"
    ]
    assert transport.rejected_fetches == 0
    assert transport.open_calls == 1
    assert transport.close_calls == 1
    assert transport.requests.count(b"*IDN?\n") == 1
    assert transport.requests.count(b"SYST:UNIT CEL\n") == 1
    assert transport.requests.count(b"FETCH?\n") == 100
    assert len(readings) == len(fetch_transactions) == 100
    assert [transaction["sample_sequence"] for transaction in fetch_transactions] == list(
        range(1, 101)
    )
    assert all(transaction["timeout"] is False for transaction in fetch_transactions)
    assert all(
        transaction["buffer_pending_before_tx_bytes"] == 0
        and transaction["buffer_drained_bytes"] == 0
        for transaction in fetch_transactions
    )
    assert all(transaction["frame_type"] == "TCP-32" for transaction in fetch_transactions)
    assert all(transaction["wire_encoding"] == "cp936" for transaction in fetch_transactions)
    assert all(transaction["parsed_channels"] == 32 for transaction in fetch_transactions)
    assert all(reading.temperatures_c[:24] == [None] * 24 for reading in readings)
    assert [reading.raw_payload["channels"][24]["channel"] for reading in readings] == [
        "CH25"
    ] * 100
    assert all(reading.temperatures_c[24] == PHYSICAL_CHANNEL_VALUES[0] for reading in readings)
    assert all(
        previous.timestamp < current.timestamp
        for previous, current in zip(readings, readings[1:], strict=False)
    )
    assert all(
        transaction["interval_since_previous_rx_ms"] >= 3400
        for transaction in fetch_transactions[1:]
    )


@pytest.mark.parametrize(
    ("field_index", "replacement", "message"),
    [
        (1, "T:2026/13/25 16:35:12", "data válida"),
        (2, "ambient-unknown", "não é numérico"),
        (3, "malformed-channel", "valor, tipo e unidade"),
        (3, "Open|J|℃", "termopar K"),
        (3, "Open|K|C", "unidade Celsius"),
    ],
)
def test_tcp32_rejects_malformed_metadata_and_channel_structure(
    field_index: int, replacement: str, message: str
) -> None:
    fields = tcp32_physical_fixture().decode("cp936").strip().split(",")
    fields[field_index] = replacement
    payload = (",".join(fields) + "\n").encode("cp936")

    with pytest.raises(ProtocolResponseError, match=message):
        At4532Parser().parse(payload)


def test_at4532_rejects_long_numeric_csv_without_tcp32_prefix() -> None:
    payload = (",".join(["21.5"] * 69) + "\n").encode("ascii")

    parser = At4532Parser()
    assert parser.classify(payload) == "unknown_response"
    with pytest.raises(ProtocolResponseError, match="entre 1 e 32"):
        parser.parse(payload)


@pytest.mark.asyncio
async def test_probe_preserves_parser_error_and_raw_wire_on_invalid_tcp32(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fields = tcp32_physical_fixture().decode("cp936").strip().split(",")
    fields[3] = "Open|J|℃"
    malformed = (",".join(fields) + "\n").encode("cp936")
    transport = FakeAt4532Transport(
        [
            SerialTransportError("protocol_timeout", "Instrumento não respondeu ao comando."),
            malformed,
        ]
    )

    def adapter_factory(port: str, baud_rate: int, **kwargs: Any) -> At4532SerialAdapter:
        return At4532SerialAdapter(port, baud_rate, transport=transport, **kwargs)

    monkeypatch.setattr("app.services.protocol_probe.At4532SerialAdapter", adapter_factory)
    report = await ProtocolProbeService().run(manual_at4532_device(), "read")

    assert report["result"] == "failed"
    assert report["errors"][0]["parser_error"]["code"] == "unexpected_protocol_response"
    assert "termopar K" in report["errors"][0]["parser_error"]["message"]
    assert report["at4532_parser_errors"] == [report["errors"][0]["parser_error"]]
    fetch_transaction = report["transactions"][-1]
    assert fetch_transaction["wire_encoding"] == "cp936"
    assert fetch_transaction["rx_bytes"] == list(malformed)
    assert fetch_transaction["rx_hex"] == malformed.hex(" ").upper()
