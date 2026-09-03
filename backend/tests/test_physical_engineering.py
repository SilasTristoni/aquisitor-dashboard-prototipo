from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.adapters.base import DeviceInformation, DeviceReading, DeviceStatus
from app.adapters.specific import (
    At4532Normalizer,
    At4532Parser,
    At4532SerialAdapter,
    Gpm8213Normalizer,
    Gpm8213Parser,
    Gpm8213Protocol,
    Gpm8213UsbSerialAdapter,
    ProtocolResponseError,
    UnexpectedResponseTypeError,
)
from app.adapters.transports import (
    Gpm8213SerialTransport,
    SerialTransportConfiguration,
    SerialTransportError,
)
from app.core.database import SessionLocal
from app.models.entities import Device, ElectricalSample, TemperatureSample
from app.services.acquisition import acquisition_service
from app.services.device_policy import at4532_identity_fallback_policy
from app.services.diagnostic_export import create_diagnostic_zip
from app.services.protocol_probe import ProtocolProbeService, protocol_probe_service
from app.services.serial_diagnostic import (
    RealSerialDiagnosticService,
    real_serial_diagnostic_service,
)
from app.services.usb_discovery import UsbDeviceDiscoveryService
from app.services.websocket import websocket_hub
from app.windows_launcher import _acquire_single_instance, _configure_environment


class FakeSerial:
    def __init__(self, reads: list[bytes] | None = None, **_: Any) -> None:
        self.is_open = True
        self.reads = list(reads or [])
        self.write_calls = 0

    def read(self, _: int) -> bytes:
        if not self.is_open:
            raise OSError("device disconnected")
        return self.reads.pop(0) if self.reads else b""

    def write(self, _: bytes) -> int:
        self.write_calls += 1
        raise AssertionError("O diagnóstico read-only não pode escrever")

    def close(self) -> None:
        self.is_open = False


def _configuration(port: str = "COM_TEST") -> SerialTransportConfiguration:
    return SerialTransportConfiguration(
        port=port,
        baud_rate=19200,
        data_bits=8,
        parity="N",
        stop_bits=1,
        timeout_s=1,
        read_timeout_s=0.1,
        line_terminator=None,
        framing=None,
    )


@pytest.mark.asyncio
async def test_raw_serial_diagnostic_reads_hex_ascii_timeout_disconnect_and_reconnect():
    serials: list[FakeSerial] = []

    def factory(**kwargs):
        connection = FakeSerial([b"A\x00\r\n"], **kwargs)
        serials.append(connection)
        return connection

    service = RealSerialDiagnosticService(factory)
    opened = await service.open(_configuration())
    assert opened["port_open"] is True
    assert opened["read_only"] is True
    first = await service.read(opened["session_id"], 4096)
    assert first["bytes_received"] == 4
    assert first["raw_hex"] == "41 00 0D 0A"
    assert first["raw_ascii"] == "A.\\r\\n"
    assert serials[0].write_calls == 0
    timeout = await service.read(opened["session_id"], 4096)
    assert timeout["timeout"] is True
    serials[0].is_open = False
    disconnected = await service.read(opened["session_id"], 4096)
    assert disconnected["disconnected"] is True
    await service.close(opened["session_id"])
    reopened = await service.open(_configuration())
    assert reopened["reconnect_detected"] is True
    await service.close(reopened["session_id"])


@pytest.mark.asyncio
async def test_raw_serial_diagnostic_reports_busy_port():
    def busy(**_):
        raise PermissionError("Access denied: port is busy")

    service = RealSerialDiagnosticService(busy)
    with pytest.raises(SerialTransportError) as caught:
        await service.open(_configuration())
    assert caught.value.code == "port_busy"
    assert "software do fabricante" in str(caught.value)


def test_at4532_normalizer_preserves_32_channels_and_marks_undocumented_sentinel_invalid():
    values = [float(index) for index in range(1, 33)]
    values[7] = 1e20
    reading = At4532Normalizer().normalize(values, b"official numeric fixture\n")
    assert len(reading.temperatures_c) == 32
    assert reading.temperatures_c[7] is None
    assert reading.channel_quality[7] == "invalid_out_of_range"
    assert reading.raw_payload["open_sensor_encoding"] == "protocol_documentation_required"
    assert reading.temperatures_c[0] == 1.0
    assert reading.power_w is None
    assert reading.quality == "good"


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [(2, "W", 2), (2000, "mW", 2), (0.002, "kW", 2)],
)
def test_gpm8213_normalizer_preserves_electrical_values_and_power_units(
    value: float, unit: str, expected: float
):
    values = {
        "voltage": 220.1,
        "current": 1.2,
        "power": value,
        "apparent_power": 264.1,
        "reactive_power": 12.3,
        "power_factor": 0.98,
        "voltage_frequency": 60.0,
        "current_frequency": 60.1,
    }
    reading = Gpm8213Normalizer().normalize(values, {"power": unit}, {"frame": "raw"})
    assert reading.power_w == expected
    assert reading.voltage_v == 220.1
    assert reading.current_a == 1.2
    assert reading.power_factor == 0.98
    assert reading.raw_values == values
    assert reading.raw_units == {"power": unit}
    assert reading.raw_payload == {"frame": "raw"}


@pytest.mark.parametrize("count", [1, 32])
def test_at4532_parser_accepts_documented_fetch_scientific_ascii(count):
    payload = ", ".join(f"{(-12.5 + index):+.5e}" for index in range(count)).encode() + b"\n"
    parsed = At4532Parser().parse(payload)
    assert len(parsed) == count
    assert parsed[0] == -12.5


@pytest.mark.parametrize("payload", [b"1.0", b"1.0\x00\n", b"1.0\n2.0\n"])
def test_at4532_parser_rejects_partial_multiple_and_malformed_frames(payload):
    with pytest.raises(ProtocolResponseError):
        At4532Parser().parse(payload)


def test_at4532_preserves_unknown_channels_without_losing_valid_readings():
    tokens = ["UNPROVEN_OPEN_TOKEN"] * 32
    tokens[5] = "70.1"
    tokens[8] = "69.8"
    tokens[12] = "70.4"
    payload = (", ".join(tokens) + "\r\n").encode("ascii")

    parser = At4532Parser()
    reading = At4532Normalizer().normalize(parser.parse(payload), payload)

    assert parser.classify(payload) == "temperature_measurement"
    assert reading.temperatures_c[5] == 70.1
    assert reading.temperatures_c[8] == 69.8
    assert reading.temperatures_c[12] == 70.4
    assert sum(value is not None for value in reading.temperatures_c) == 3
    assert reading.channel_quality[0] == "unknown_unavailable"
    assert reading.channel_quality[5] == "good"
    assert reading.raw_payload["channel_count_received"] == 32
    assert reading.raw_payload["valid_channels"] == 3
    assert reading.raw_payload["unavailable_channels"] == 29
    assert reading.raw_payload["valid_channel_results"]["CH06"]["temperature_c"] == 70.1
    assert reading.raw_payload["unknown_tokens"][0]["raw_token"] == "UNPROVEN_OPEN_TOKEN"


def test_at4532_zero_negative_and_scientific_values_remain_real_temperatures():
    payload = b"0, -12.5, +7.01e1, UNKNOWN\n"
    reading = At4532Normalizer().normalize(At4532Parser().parse(payload), payload)
    assert reading.temperatures_c[:4] == [0.0, -12.5, 70.1, None]
    assert reading.channel_quality[:4] == ["good", "good", "good", "unknown_unavailable"]


def _at4532_export_shape_payload(values: list[float]) -> bytes:
    tokens = ["Open"] * 24 + [str(value) for value in values]
    return (",".join(tokens) + "\r\n").encode("ascii")


def test_at4532_maps_export_shape_ch25_through_ch32_without_off_by_one():
    payload = _at4532_export_shape_payload([23.2, 23.7, 23.8, 26.5, 35.6, 28.1, 24.4, 21.9])
    reading = At4532Normalizer().normalize(At4532Parser().parse(payload), payload)

    assert reading.temperatures_c[:24] == [None] * 24
    assert reading.temperatures_c[24:] == [23.2, 23.7, 23.8, 26.5, 35.6, 28.1, 24.4, 21.9]
    assert reading.channel_quality[:24] == ["unknown_unavailable"] * 24
    assert reading.channel_quality[24:] == ["good"] * 8
    assert reading.raw_payload["channels"][24]["channel"] == "CH25"
    assert reading.raw_payload["channels"][24]["temperature_c"] == 23.2
    assert reading.raw_payload["channels"][31]["channel"] == "CH32"
    assert reading.raw_payload["valid_channels"] == 8
    assert reading.raw_payload["unavailable_channels"] == 24
    assert reading.raw_payload["token_count"] == 32
    assert reading.raw_payload["observed_terminator"] == "CRLF (0x0D 0x0A)"
    assert reading.raw_payload["frame_count"] == 1
    assert reading.raw_payload["unknown_tokens"][0]["raw_token"] == "Open"
    assert reading.raw_payload["open_sensor_encoding"] == "protocol_documentation_required"


def test_at4532_heating_series_changes_only_ch29():
    readings = [
        At4532Normalizer().normalize(
            At4532Parser().parse(payload), payload
        )
        for payload in (
            _at4532_export_shape_payload([23.2, 23.7, 23.8, 26.5, value, 28.1, 24.4, 21.9])
            for value in (25.0, 27.0, 31.0)
        )
    ]
    assert [reading.temperatures_c[28] for reading in readings] == [25.0, 27.0, 31.0]
    for index in (*range(24), 24, 25, 26, 27, 29, 30, 31):
        assert len({reading.temperatures_c[index] for reading in readings}) == 1


def test_gpm8213_parser_accepts_documented_identity_and_eight_numeric_items():
    parser = Gpm8213Parser()
    identity = parser.parse_identity(b"GWInstek,GPM-8213,GES913349,V1.05\r\n")
    assert identity["serial_number"] == "GES913349"
    assert identity["firmware_version"] == "V1.05"
    headers = parser.parse_headers(b"Irms,Urms,P,S,Q,LAMBDA,FU,FI\r\n", 8)
    values = parser.parse(
        b"1.2500E+00,220.00E+00,250.00E+00,275.00E+00,10.00E+00,0.980E+00,60.000E+00,60.010E+00\r\n",
        headers,
    )
    assert values["voltage"] == 220
    assert values["current"] == 1.25
    assert values["power"] == 250
    assert values["reactive_power"] == 10
    assert values["voltage_frequency"] == 60
    assert values["current_frequency"] == 60.01


def test_gpm_powermeter_series_physical_reference_preserves_fu_lambda_q_mapping():
    parser = Gpm8213Parser()
    physical_header = b"Urms,Irms,P,S,fU,PF,Q,fI\r\n"
    assert parser.classify(physical_header) == "header_list"
    headers = parser.parse_headers(physical_header, 8)
    values = parser.parse(
        b"126.86,2.0199,256.07,256.25,59.989,0.9993,-9.5985,59.988\r\n",
        headers,
    )
    reading = Gpm8213Normalizer().normalize(values, parser.units)

    assert reading.voltage_v == 126.86
    assert reading.current_a == 2.0199
    assert reading.power_w == 256.07
    assert reading.apparent_power_va == 256.25
    assert reading.voltage_frequency_hz == 59.989
    assert reading.power_factor == 0.9993
    assert reading.reactive_power_var == -9.5985
    assert reading.current_frequency_hz == 59.988


@pytest.mark.parametrize(("fu", "fi"), [("fu", "fi"), ("fU", "fI"), ("FU", "FI")])
def test_gpm_physical_frequency_headers_are_case_insensitive(fu: str, fi: str):
    parser = Gpm8213Parser()
    payload = f"Urms,Irms,P,S,{fu},PF,Q,{fi}\r\n".encode("ascii")
    assert parser.classify(payload) == "header_list"
    assert parser.parse_headers(payload, 8) == [
        "voltage",
        "current",
        "power",
        "apparent_power",
        "voltage_frequency",
        "power_factor",
        "reactive_power",
        "current_frequency",
    ]


@pytest.mark.parametrize(
    "payload",
    [b"1,2,3\r\n", b"1,2,3,4,5,6,7,broken\r\n", b"1,2,3,4,5,6,7,8\n"],
)
def test_gpm8213_parser_rejects_wrong_count_malformed_and_partial(payload):
    with pytest.raises(ProtocolResponseError):
        Gpm8213Parser().parse(
            payload,
            [
                "voltage",
                "current",
                "power",
                "apparent_power",
                "reactive_power",
                "power_factor",
                "voltage_frequency",
                "current_frequency",
            ],
        )


class FakeVendorTransport:
    def __init__(self, responses: list[bytes]):
        self.responses = list(responses)
        self.requests: list[bytes] = []
        self.is_open = False

    async def open(self):
        self.is_open = True
        return 1.0

    async def query(self, payload, _terminator, _max_bytes=65536):
        self.requests.append(payload)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response, 2.0

    async def write(self, payload):
        self.requests.append(payload)
        return len(payload), 1.0

    async def close(self):
        self.is_open = False


class BufferedSerial:
    def __init__(self, initial: bytes = b"") -> None:
        self.is_open = True
        self.buffer = bytearray(initial)
        self.responses: dict[bytes, bytes] = {}
        self.input_resets = 0
        self.output_resets = 0

    @property
    def in_waiting(self) -> int:
        return len(self.buffer)

    def read(self, size: int) -> bytes:
        payload = bytes(self.buffer[:size])
        del self.buffer[:size]
        return payload

    def read_until(self, terminator: bytes, size: int) -> bytes:
        index = self.buffer.find(terminator)
        count = min(index + len(terminator), size) if index >= 0 else min(len(self.buffer), size)
        return self.read(count)

    def write(self, payload: bytes) -> int:
        self.buffer.extend(self.responses.get(payload, b""))
        return len(payload)

    def flush(self) -> None:
        return None

    def reset_input_buffer(self) -> None:
        self.input_resets += 1
        self.buffer.clear()

    def reset_output_buffer(self) -> None:
        self.output_resets += 1

    def close(self) -> None:
        self.is_open = False


@pytest.mark.asyncio
async def test_gpm_transport_clears_open_buffer_and_drains_second_buffered_response():
    serial_connection = BufferedSerial(b"OLD")
    transport = Gpm8213SerialTransport(
        _configuration("COM3"), serial_factory=lambda **_: serial_connection
    )
    await transport.open()
    assert transport.open_boundary["pending_input_bytes"] == 3
    assert transport.open_boundary["pending_input_ascii"] == "OLD"
    assert serial_connection.input_resets == 1
    assert serial_connection.output_resets == 1

    identity = b"GWInstek,GPM-8213,GES913349,V1.05\r\n"
    extra = b"GWInstek,GPM-8213,GES913349,V1.05\r\n"
    serial_connection.responses[Gpm8213Protocol.identity.request] = identity + extra
    serial_connection.responses[Gpm8213Protocol.number_query.request] = b"8\r\n"
    response, _ = await transport.query(Gpm8213Protocol.identity.request, b"\r\n")
    assert response == identity
    response, _ = await transport.query(Gpm8213Protocol.number_query.request, b"\r\n")
    assert response == b"8\r\n"
    assert transport.last_query_boundary["pending_before_tx_bytes"] == len(extra)
    assert transport.last_query_boundary["buffer_pending_before_tx_bytes"] == len(extra)
    assert transport.last_query_boundary["buffer_drained_bytes"] == len(extra)
    assert transport.last_query_boundary["timestamp_tx"]
    assert transport.last_query_boundary["timestamp_rx"]
    assert transport.last_query_boundary["query_duration_ms"] >= 0
    assert transport.last_query_boundary["pending_before_tx_ascii"].startswith("GWInstek")
    await transport.close()


@pytest.mark.asyncio
async def test_gpm_transport_reassembles_fragmented_crlf_response():
    class FragmentedSerial:
        def __init__(self) -> None:
            self.is_open = True
            self.fragments = list(b"8\r\n")

        @property
        def in_waiting(self) -> int:
            return 0

        def read(self, _: int) -> bytes:
            return bytes([self.fragments.pop(0)]) if self.fragments else b""

        def write(self, payload: bytes) -> int:
            return len(payload)

        def flush(self) -> None:
            return None

        def reset_input_buffer(self) -> None:
            return None

        def reset_output_buffer(self) -> None:
            return None

        def close(self) -> None:
            self.is_open = False

    connection = FragmentedSerial()
    transport = Gpm8213SerialTransport(
        _configuration("COM3"), serial_factory=lambda **_: connection
    )
    await transport.open()
    response, _ = await transport.query(Gpm8213Protocol.number_query.request, b"\r\n")
    assert response == b"8\r\n"
    await transport.close()


@pytest.mark.asyncio
async def test_at4532_adapter_runs_documented_transport_protocol_parser_normalizer_chain():
    temperatures = b",".join(f"{index}.25".encode() for index in range(1, 33)) + b"\n"
    transport = FakeVendorTransport([b"AT4532,A6,SN123,Applent\n", temperatures])
    adapter = At4532SerialAdapter("COM5", 19200, transport=transport)
    await adapter.connect()
    reading = await adapter.read_once()
    await adapter.disconnect()
    assert transport.requests == [b"*IDN?\n", b"SYST:UNIT CEL\n", b"FETCH?\n"]
    assert reading.temperatures_c[0] == 1.25
    assert reading.temperatures_c[31] == 32.25
    assert all(item["vendor_documented"] for item in adapter.transactions)


@pytest.mark.asyncio
async def test_at4532_adapter_keeps_unknown_channel_tokens_and_complete_tx_rx_diagnostic():
    tokens = ["UNDOCUMENTED"] * 32
    tokens[5], tokens[8], tokens[12] = "70.1", "69.8", "70.4"
    fetch = (",".join(tokens) + "\r\n").encode("ascii")
    transport = FakeVendorTransport([b"AT4532,A6,SN123,Applent\r\n", fetch])
    adapter = At4532SerialAdapter("COM5", 19200, transport=transport)

    await adapter.connect()
    reading = await adapter.read_once()
    await adapter.disconnect()

    assert reading.temperatures_c[5] == 70.1
    transaction = adapter.transactions[-1]
    assert transaction["actual_response_type"] == "temperature_measurement"
    assert transaction["expected_for_command"] == "temperature_measurement"
    assert transaction["tx_ascii"] == "FETCH?\\n"
    assert transaction["rx_ascii"].endswith("\\r\\n")
    assert transaction["tx_hex"] == "46 45 54 43 48 3F 0A"
    assert transaction["rx_hex"] == fetch.hex(" ").upper()
    assert transaction["timestamp_tx"]
    assert transaction["timestamp_rx"]
    assert transaction["elapsed_ms"] >= 0
    assert transaction["parsed"]["valid_channels"] == 3
    assert transaction["parsed"]["unavailable_channels"] == 29


def _manual_at4532_device(port: str = "COM5", confirmed_port: str = "COM5") -> SimpleNamespace:
    return SimpleNamespace(
        id=4532,
        protocol="at4532_serial",
        model="AT4532",
        port=port,
        baud_rate=19200,
        metadata_json={
            "usb": {"manual_confirmed": True, "confirmed_port": confirmed_port},
            "serial": {"data_bits": 8, "parity": "N", "stop_bits": 1},
        },
    )


def test_at4532_identity_fallback_requires_exact_manual_port_and_serial_parameters():
    assert at4532_identity_fallback_policy(_manual_at4532_device()).allowed is True
    unknown_port = at4532_identity_fallback_policy(
        _manual_at4532_device(port="COM2", confirmed_port="COM5")
    )
    assert unknown_port.allowed is False
    assert unknown_port.reason == "manual_port_not_confirmed"
    unconfirmed = _manual_at4532_device()
    unconfirmed.metadata_json["usb"]["manual_confirmed"] = False
    assert at4532_identity_fallback_policy(unconfirmed).allowed is False
    wrong_framing = _manual_at4532_device()
    wrong_framing.metadata_json["serial"]["data_bits"] = 7
    assert at4532_identity_fallback_policy(wrong_framing).reason == "serial_parameters_mismatch"


@pytest.mark.asyncio
async def test_at4532_manual_com5_fallback_verifies_measurement_after_identity_timeout():
    fetch = _at4532_export_shape_payload([23.2, 23.7, 23.8, 26.5, 35.6, 28.1, 24.4, 21.9])
    transport = FakeVendorTransport(
        [SerialTransportError("protocol_timeout", "Instrumento não respondeu ao comando."), fetch]
    )
    adapter = At4532SerialAdapter(
        "COM5",
        19200,
        transport=transport,
        allow_identity_fallback=True,
        association_source="manual_port",
    )

    await adapter.connect()
    reading = await adapter.read_once()
    information = await adapter.get_device_information()
    await adapter.disconnect()

    assert transport.requests == [b"*IDN?\n", b"SYST:UNIT CEL\n", b"FETCH?\n"]
    assert adapter.identity_status == "unconfirmed"
    assert adapter.protocol_status == "verified_by_measurement"
    assert reading.temperatures_c[24] == 23.2
    assert information.capabilities["identity_status"] == "unconfirmed"
    assert information.capabilities["association_source"] == "manual_port"
    identity_transaction = adapter.transactions[0]
    assert identity_transaction["bytes_received"] == 0
    assert identity_transaction["actual_response_type"] == "no_response"
    assert identity_transaction["error"]["code"] == "protocol_timeout"
    assert identity_transaction["tx_hex"] == "2A 49 44 4E 3F 0A"


@pytest.mark.asyncio
async def test_at4532_identity_timeout_does_not_fallback_without_manual_authorization():
    transport = FakeVendorTransport(
        [SerialTransportError("protocol_timeout", "Instrumento não respondeu ao comando.")]
    )
    adapter = At4532SerialAdapter("COM2", 19200, transport=transport)
    with pytest.raises(SerialTransportError) as caught:
        await adapter.connect()
    assert caught.value.code == "protocol_timeout"
    assert transport.requests == [b"*IDN?\n"]
    assert adapter.identity_status == "unconfirmed"
    assert adapter.protocol_status == "not_verified"


@pytest.mark.asyncio
async def test_at4532_full_probe_reaches_fetch_and_acquisition_after_identity_timeout(
    monkeypatch,
):
    first = _at4532_export_shape_payload([23.2, 23.7, 23.8, 26.5, 25.0, 28.1, 24.4, 21.9])
    second = _at4532_export_shape_payload([23.2, 23.7, 23.8, 26.5, 27.0, 28.1, 24.4, 21.9])
    transport = FakeVendorTransport(
        [
            SerialTransportError("protocol_timeout", "Instrumento não respondeu ao comando."),
            first,
            second,
        ]
    )

    def adapter_factory(port, baud_rate, **kwargs):
        return At4532SerialAdapter(port, baud_rate, transport=transport, **kwargs)

    async def no_delay(_):
        return None

    monkeypatch.setattr("app.services.protocol_probe.At4532SerialAdapter", adapter_factory)
    monkeypatch.setattr("app.services.protocol_probe.asyncio.sleep", no_delay)
    report = await ProtocolProbeService().run(_manual_at4532_device(), "full")

    statuses = {stage["key"]: stage["status"] for stage in report["stages"]}
    assert statuses == {
        "usb": "passed",
        "identity": "warning",
        "port": "passed",
        "protocol": "passed",
        "configuration": "passed",
        "reading": "passed",
        "acquisition": "passed",
    }
    assert report["result"] == "passed_with_warning"
    assert report["identity_status"] == "unconfirmed"
    assert report["protocol_status"] == "verified_by_measurement"
    assert report["identity_fallback_policy"]["allowed"] is True
    assert transport.requests.count(b"FETCH?\n") == 2
    assert report["readings"][0]["temperatures_c"][28] == 25.0
    assert report["readings"][1]["temperatures_c"][28] == 27.0


@pytest.mark.asyncio
async def test_at4532_unknown_com_probe_stops_after_identity_timeout(monkeypatch):
    transport = FakeVendorTransport(
        [SerialTransportError("protocol_timeout", "Instrumento não respondeu ao comando.")]
    )

    def adapter_factory(port, baud_rate, **kwargs):
        assert kwargs["allow_identity_fallback"] is False
        return At4532SerialAdapter(port, baud_rate, transport=transport, **kwargs)

    monkeypatch.setattr("app.services.protocol_probe.At4532SerialAdapter", adapter_factory)
    report = await ProtocolProbeService().run(
        _manual_at4532_device(port="COM2", confirmed_port="COM5"), "read"
    )

    assert report["result"] == "failed"
    assert report["identity_fallback_policy"]["allowed"] is False
    assert transport.requests == [b"*IDN?\n"]


@pytest.mark.asyncio
async def test_gpm_adapter_configures_and_reads_documented_numeric_items():
    transport = FakeVendorTransport(
        [
            b"GWInstek,GPM-8213,GES913349,V1.05\r\n",
            b":NUMERIC:NORMAL:NUMBER 8\r\n",
            b"Urms,Irms,P,S,fU,PF,Q,fI\r\n",
            b"126.86,2.0199,256.07,256.25,59.989,0.9993,-9.5985,59.988\r\n",
        ]
    )
    adapter = Gpm8213UsbSerialAdapter("COM7", None, transport=transport)
    await adapter.connect()
    reading = await adapter.read_once()
    await adapter.disconnect()
    assert transport.requests[0] == b"*IDN?\r\n"
    assert transport.requests[1:4] == [
        b":NUMERIC:NORMAL:NUMBER 8\r\n",
        b":NUMERIC:NORMAL:NUMBER?\r\n",
        b":NUMERIC:NORMAL:ITEM1 U\r\n",
    ]
    assert transport.requests[-2:] == [
        b":NUMERIC:NORMAL:HEADER?\r\n",
        b":NUMERIC:NORMAL:VALUE?\r\n",
    ]
    assert transport.requests[-1] == b":NUMERIC:NORMAL:VALUE?\r\n"
    assert transport.requests[7] == b":NUMERIC:NORMAL:ITEM5 FU\r\n"
    assert transport.requests[9] == b":NUMERIC:NORMAL:ITEM7 Q\r\n"
    assert len(transport.requests) == 13
    assert adapter.number_reported == 8
    assert adapter.headers_requested == ["U", "I", "P", "S", "FU", "LAMBDA", "Q", "FI"]
    assert adapter.headers_reported == ["Urms", "Irms", "P", "S", "fU", "PF", "Q", "fI"]
    assert reading.power_w == 256.07
    assert reading.apparent_power_va == 256.25
    assert reading.voltage_frequency_hz == 59.989
    assert reading.power_factor == 0.9993
    assert reading.reactive_power_var == -9.5985
    parsed = adapter.transactions[-1]["parsed"]
    assert parsed["number_requested"] == parsed["number_reported"] == 8
    assert parsed["headers_requested"] != parsed["headers_reported"]
    assert parsed["headers_reported"] == [
        "Urms",
        "Irms",
        "P",
        "S",
        "fU",
        "PF",
        "Q",
        "fI",
    ]
    assert parsed["raw_values"]["Q"] == "-9.5985"
    assert parsed["parsed_values"] == {
        "Vrms": 126.86,
        "Irms": 2.0199,
        "P": 256.07,
        "VA": 256.25,
        "VHz": 59.989,
        "PF": 0.9993,
        "VAR": -9.5985,
        "IHz": 59.988,
    }


@pytest.mark.asyncio
async def test_gpm_value_identity_response_is_classified_as_stale_before_numeric_parser():
    stale_identity = b"GWInstek,GPM-8213,GES913349,V1.05\r\n"
    transport = FakeVendorTransport(
        [
            stale_identity,
            b"8\r\n",
            b"Urms,Irms,P,S,Q,LAMBDA,FU,FI\r\n",
            stale_identity,
        ]
    )
    adapter = Gpm8213UsbSerialAdapter("COM3", None, transport=transport)
    await adapter.connect()
    with pytest.raises(UnexpectedResponseTypeError) as caught:
        await adapter.read_once()
    await adapter.disconnect()

    assert caught.value.code == "unexpected_response_type"
    assert caught.value.details == {
        "expected_for_command": "numeric_measurement",
        "actual_response_type": "identity_response",
        "raw_response": "GWInstek,GPM-8213,GES913349,V1.05\\r\\n",
        "previous_command": "query_headers",
        "possible_stale_response": True,
    }
    assert "oito itens" not in str(caught.value)
    transaction = adapter.transactions[-1]
    assert transaction["possible_stale_response"] is True
    assert transaction["rx_hex"] == stale_identity.hex(" ").upper()


def test_gpm_nan_is_unavailable_without_invalidating_other_measurements():
    parser = Gpm8213Parser()
    headers = parser.parse_headers(b"Urms,Irms,P,S,Q,LAMBDA,FU,FI\r\n", 8)
    values = parser.parse(b"220,1.25,NAN,275,10,0.98,60,60.01\r\n", headers)
    reading = Gpm8213Normalizer().normalize(values, parser.units)
    assert reading.power_w is None
    assert reading.raw_power is None
    assert reading.voltage_v == 220
    assert reading.current_a == 1.25
    assert reading.quality == "missing"


@pytest.mark.asyncio
async def test_at4532_adapter_reconnects_after_documented_read_disconnect(monkeypatch):
    transport = FakeVendorTransport(
        [
            b"AT4532,A6,SN123,Applent\n",
            SerialTransportError("disconnected", "cable removed"),
            b"AT4532,A6,SN123,Applent\n",
            b"21.5\n",
        ]
    )
    adapter = At4532SerialAdapter("COM5", 19200, transport=transport)
    await adapter.connect()

    async def no_delay(_):
        return None

    monkeypatch.setattr("app.adapters.specific.asyncio.sleep", no_delay)
    stream = adapter.start_reading()
    reading = await anext(stream)
    await adapter.stop_reading()
    await stream.aclose()
    await adapter.disconnect()
    assert reading.temperatures_c[0] == 21.5
    assert transport.requests.count(b"*IDN?\n") == 2


class FakePollingAdapter:
    def __init__(self, role: str):
        self.role = role
        self.connected = False
        self.reading = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def stop_reading(self):
        self.reading = False

    async def start_reading(self):
        self.reading = True
        while self.reading:
            if self.role == "temperature":
                yield DeviceReading(
                    raw_power=None,
                    raw_power_unit="W",
                    power_w=None,
                    temperatures_c=[21.5] * 32,
                    channel_quality=["good"] * 32,
                    raw_payload={"fixture": "official_fetch_shape"},
                )
            else:
                yield DeviceReading(
                    raw_power=250,
                    raw_power_unit="W",
                    power_w=250,
                    temperatures_c=[],
                    voltage_v=220,
                    current_a=1.25,
                    apparent_power_va=275,
                    reactive_power_var=10,
                    power_factor=0.98,
                    voltage_frequency_hz=60,
                    current_frequency_hz=60,
                    raw_values={"power": 250},
                    raw_units={"power": "W"},
                    raw_payload={"fixture": "official_numeric_shape"},
                )
            await asyncio.sleep(0.02)

    def parse_message(self, _):
        raise NotImplementedError

    async def get_status(self):
        return DeviceStatus(state="connected", connected=self.connected, reading=self.reading)

    async def get_device_information(self):
        return DeviceInformation(adapter="FakePollingAdapter")


def test_dual_physical_pipeline_publishes_and_persists_independently(
    client, auth_headers, monkeypatch
):
    devices = client.get("/api/v1/devices", headers=auth_headers).json()
    at4532 = next(item for item in devices if item["protocol"] == "at4532_serial")
    gpm = next(item for item in devices if item["protocol"] == "gpm8213_serial")
    adapters = {
        at4532["id"]: FakePollingAdapter("temperature"),
        gpm["id"]: FakePollingAdapter("electrical"),
    }
    monkeypatch.setattr(
        acquisition_service,
        "_adapter_for",
        lambda device: adapters[device.id],
    )
    events: list[str] = []
    measurement_payloads: list[dict[str, Any]] = []
    original_publish = websocket_hub.publish

    async def capture(event, payload):
        events.append(event)
        if event == "measurement.created":
            measurement_payloads.append(payload)
        await original_publish(event, payload)

    monkeypatch.setattr(websocket_hub, "publish", capture)
    started = client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={
            "temperature_device_id": at4532["id"],
            "electrical_device_id": gpm["id"],
            "name": "Cadeia física documentada",
        },
    )
    assert started.status_code == 201, started.text
    session_id = started.json()["id"]
    time.sleep(0.15)
    # One stream can stop without changing the other adapter state.
    adapters[at4532["id"]].reading = False
    assert adapters[gpm["id"]].reading is True
    time.sleep(0.08)
    finished = client.post(f"/api/v1/sessions/{session_id}/finish", headers=auth_headers)
    assert finished.status_code == 200, finished.text
    with SessionLocal() as db:
        assert db.scalar(
            select(TemperatureSample).where(TemperatureSample.session_id == session_id)
        )
        assert db.scalar(select(ElectricalSample).where(ElectricalSample.session_id == session_id))
    assert "measurement.created" in events
    assert {payload["source_role"] for payload in measurement_payloads} == {
        "temperature",
        "electrical",
    }
    temperature_payloads = [
        payload for payload in measurement_payloads if payload["source_role"] == "temperature"
    ]
    electrical_payloads = [
        payload for payload in measurement_payloads if payload["source_role"] == "electrical"
    ]
    assert all(payload["power_w"] is None for payload in temperature_payloads)
    assert all(payload["temperatures_c"] == [] for payload in electrical_payloads)
    assert len({payload["timestamp"] for payload in temperature_payloads}) == len(
        temperature_payloads
    )

    snapshot = client.get("/api/v1/acquisition/combined-status", headers=auth_headers)
    assert snapshot.status_code == 200
    roles = {item["source_role"] for item in snapshot.json()["devices"]}
    assert {"temperature", "electrical"} <= roles


def test_same_vid_pid_on_com2_and_com5_is_ambiguous(client):
    ports = [
        SimpleNamespace(
            device=port,
            description="USB-SERIAL CH340",
            manufacturer="wch.cn",
            product="CH340",
            serial_number=None,
            vid=0x1A86,
            pid=0x7523,
            hwid=f"USB VID:PID=1A86:7523 {port}",
            location=None,
        )
        for port in ("COM2", "COM5")
    ]
    service = UsbDeviceDiscoveryService(lambda: ports, lambda **_: FakeSerial())
    with SessionLocal() as db:
        at4532 = db.scalar(select(Device).where(Device.model == "AT4532"))
        at4532.port = None
        at4532.metadata_json = {"usb": {"vid": 0x1A86, "pid": 0x7523}}
        db.commit()
        discovered = service.discover(db)
    assert {item["port"] for item in discovered} == {"COM2", "COM5"}
    assert all(item["association"] is None for item in discovered)
    assert all(item["association_status"] == "ambiguous" for item in discovered)
    assert all(
        item["association_candidates"][0]["matched_by"] == "vid_pid_candidate"
        for item in discovered
    )


def test_gpm_serial_reassociates_when_windows_changes_com(client):
    port = SimpleNamespace(
        device="COM7",
        description="USB Serial Device",
        manufacturer="GW Instek",
        product="GPM-8213",
        serial_number="GES913349",
        vid=0x2184,
        pid=0x0052,
        hwid="USB VID:PID=2184:0052 SER=GES913349",
        location="2-1",
    )
    service = UsbDeviceDiscoveryService(lambda: [port], lambda **_: FakeSerial())
    with SessionLocal() as db:
        gpm = db.scalar(select(Device).where(Device.serial_number == "GES913349"))
        gpm.port = "COM3"
        db.commit()
        item = service.discover(db)[0]
        db.refresh(gpm)
        assert gpm.port == "COM7"
    assert item["association"]["matched_by"] == "serial_number"


def test_launcher_rejects_second_instance_and_writes_startup_log(tmp_path, monkeypatch):
    class Kernel32:
        def __init__(self, last_error: int):
            self.last_error = last_error
            self.closed = []

        def CreateMutexW(self, *_):
            return 123

        def GetLastError(self):
            return self.last_error

        def CloseHandle(self, handle):
            self.closed.append(handle)

    duplicate = Kernel32(183)
    assert _acquire_single_instance(kernel32=duplicate) is False
    assert duplicate.closed == [123]

    before = set(logging.getLogger().handlers)
    application = tmp_path / "app"
    monkeypatch.setenv("THERMOPOWER_APP_DATA_DIR", str(application))
    monkeypatch.delenv("THERMOPOWER_ENVIRONMENT", raising=False)
    _configure_environment(tmp_path, application)
    assert os.environ["THERMOPOWER_ENVIRONMENT"] == "physical-alpha"
    added = [handler for handler in logging.getLogger().handlers if handler not in before]
    try:
        logging.getLogger("physical-test").info("startup diagnostic test")
        for handler in added:
            handler.flush()
        log_path = application / "logs" / "thermopower.log"
        assert log_path.stat().st_size > 0
        assert "launcher configured" in log_path.read_text(encoding="utf-8")
    finally:
        for handler in added:
            logging.getLogger().removeHandler(handler)
            handler.close()


def test_serial_diagnostic_endpoints_are_read_only(client, auth_headers, monkeypatch):
    connection = FakeSerial([b"RAW\x01"])
    monkeypatch.setattr(real_serial_diagnostic_service, "serial_factory", lambda **_: connection)
    opened = client.post(
        "/api/v1/hardware/serial-diagnostic/open",
        headers=auth_headers,
        json={
            "port": "COM_TEST",
            "baud_rate": 19200,
            "data_bits": 8,
            "parity": "N",
            "stop_bits": 1,
            "timeout_s": 1,
            "read_timeout_s": 0.1,
        },
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["parameters_source"] == "user_confirmed"
    assert opened.json()["physical_validation"] == "parameters_confirmed"
    session_id = opened.json()["session_id"]
    read = client.post(
        "/api/v1/hardware/serial-diagnostic/read",
        headers=auth_headers,
        json={"session_id": session_id, "max_bytes": 100},
    )
    assert read.status_code == 200
    assert read.json()["raw_hex"] == "52 41 57 01"
    assert connection.write_calls == 0
    closed = client.post(
        "/api/v1/hardware/serial-diagnostic/close",
        headers=auth_headers,
        json={"session_id": session_id},
    )
    assert closed.status_code == 200


def test_serial_diagnostic_rejects_unknown_parameters_without_consent(
    client, auth_headers, monkeypatch
):
    calls = 0

    def factory(**_):
        nonlocal calls
        calls += 1
        return FakeSerial()

    monkeypatch.setattr(real_serial_diagnostic_service, "serial_factory", factory)
    response = client.post(
        "/api/v1/hardware/serial-diagnostic/open",
        headers=auth_headers,
        json={
            "port": "COM_UNKNOWN",
            "baud_rate": 19200,
            "data_bits": None,
            "parity": None,
            "stop_bits": None,
            "timeout_s": 1.25,
            "read_timeout_s": 4.5,
            "use_engineering_assumption_8n1": False,
        },
    )
    assert response.status_code == 422
    assert calls == 0


def test_serial_diagnostic_uses_8n1_only_after_explicit_engineering_consent(
    client, auth_headers, monkeypatch
):
    serial_arguments: dict[str, Any] = {}

    def factory(**kwargs):
        serial_arguments.update(kwargs)
        return FakeSerial()

    monkeypatch.setattr(real_serial_diagnostic_service, "serial_factory", factory)
    opened = client.post(
        "/api/v1/hardware/serial-diagnostic/open",
        headers=auth_headers,
        json={
            "port": "COM_ASSUMPTION",
            "baud_rate": 19200,
            "data_bits": None,
            "parity": None,
            "stop_bits": None,
            "timeout_s": 1.25,
            "read_timeout_s": 4.5,
            "use_engineering_assumption_8n1": True,
        },
    )
    assert opened.status_code == 200, opened.text
    result = opened.json()
    assert result["parameters_source"] == "engineering_assumption"
    assert result["physical_validation"] == "pending"
    assert result["parameters"]["data_bits"] == 8
    assert result["parameters"]["parity"] == "N"
    assert result["parameters"]["stop_bits"] == 1
    assert serial_arguments["bytesize"] == 8
    assert serial_arguments["parity"] == "N"
    assert serial_arguments["stopbits"] == 1
    assert serial_arguments["write_timeout"] == 1.25
    assert serial_arguments["timeout"] == 4.5
    read = client.post(
        "/api/v1/hardware/serial-diagnostic/read",
        headers=auth_headers,
        json={"session_id": result["session_id"], "max_bytes": 64},
    )
    assert read.status_code == 200
    assert read.json()["parameters_source"] == "engineering_assumption"
    assert read.json()["physical_validation"] == "pending"
    closed = client.post(
        "/api/v1/hardware/serial-diagnostic/close",
        headers=auth_headers,
        json={"session_id": result["session_id"]},
    )
    assert closed.status_code == 200
    assert closed.json()["parameters_source"] == "engineering_assumption"
    with SessionLocal() as db:
        at4532 = db.scalar(select(Device).where(Device.protocol == "at4532_serial"))
        serial_settings = at4532.metadata_json["serial"]
        assert serial_settings["data_bits"] == 8
        assert serial_settings["parity"] == "N"
        assert serial_settings["stop_bits"] == 1
        assert serial_settings["parameters_source"] == "vendor_documented"


def test_serial_diagnostic_does_not_mix_confirmed_and_assumed_parameters(client, auth_headers):
    response = client.post(
        "/api/v1/hardware/serial-diagnostic/open",
        headers=auth_headers,
        json={
            "port": "COM_MIXED",
            "baud_rate": 19200,
            "data_bits": 8,
            "parity": "N",
            "stop_bits": 1,
            "timeout_s": 1,
            "read_timeout_s": 1,
            "use_engineering_assumption_8n1": True,
        },
    )
    assert response.status_code == 422


def test_engineering_version_is_consistent_in_health_and_frontend(client):
    repository = Path(__file__).resolve().parents[2]
    expected = (repository / "VERSION.txt").read_text(encoding="utf-8").strip()
    frontend = json.loads((repository / "frontend" / "package.json").read_text("utf-8"))
    response = client.get("/health")

    assert expected == "0.5.6-physical-alpha"
    assert response.status_code == 200
    assert response.json()["version"] == expected
    assert frontend["version"] == expected


def test_build_info_uses_the_same_demo_credentials_that_authenticate(client):
    information = client.get("/api/v1/build-info")
    assert information.status_code == 200
    credentials = information.json()["demo_credentials"]
    login = client.post("/api/v1/auth/login", json=credentials)
    assert login.status_code == 200
    assert login.json()["user"]["email"] == credentials["email"]


def test_protocol_probe_requires_explicit_operator_confirmation(client, auth_headers, monkeypatch):
    devices = client.get("/api/v1/devices", headers=auth_headers).json()
    at4532 = next(device for device in devices if device["protocol"] == "at4532_serial")
    called = False

    async def fake_run(*_):
        nonlocal called
        called = True
        return {"result": "passed"}

    monkeypatch.setattr(protocol_probe_service, "run", fake_run)
    denied = client.post(
        f"/api/v1/devices/{at4532['id']}/protocol-probe",
        headers=auth_headers,
        json={"mode": "identity", "operator_confirmed": False},
    )
    assert denied.status_code == 422
    assert called is False
    allowed = client.post(
        f"/api/v1/devices/{at4532['id']}/protocol-probe",
        headers=auth_headers,
        json={"mode": "identity", "operator_confirmed": True},
    )
    assert allowed.status_code == 200
    assert called is True


@pytest.mark.asyncio
async def test_protocol_probe_preserves_identity_when_gpm_configuration_fails(monkeypatch):
    class Configuration:
        @staticmethod
        def public_dict():
            return {"port": "COM3"}

    class HeaderFailureAdapter:
        equipment = "GW Instek GPM-8213"
        expected_interval_seconds = 1

        def __init__(self):
            self._identity: dict[str, str] = {}
            self.transactions: list[dict[str, Any]] = []
            self.serial_open_boundary = {}

        @staticmethod
        def _configuration():
            return Configuration()

        async def connect(self):
            self._identity = {
                "manufacturer": "GWInstek",
                "model": "GPM-8213",
                "serial_number": "GES913349",
                "firmware_version": "V1.05",
            }
            self.transactions.append(
                {
                    "command_name": "query_headers",
                    "parsed": {},
                }
            )
            raise ProtocolResponseError("HEADER incompatível")

        async def disconnect(self):
            return None

    adapter = HeaderFailureAdapter()
    monkeypatch.setattr(
        "app.services.protocol_probe.Gpm8213UsbSerialAdapter",
        lambda *_: adapter,
    )
    report = await ProtocolProbeService().run(
        SimpleNamespace(
            id=99,
            protocol="gpm8213_serial",
            port="COM3",
            baud_rate=None,
        ),
        "full",
    )
    statuses = {stage["key"]: stage["status"] for stage in report["stages"]}
    assert statuses == {
        "usb": "passed",
        "identity": "passed",
        "port": "passed",
        "protocol": "passed",
        "configuration": "failed",
        "reading": "pending",
        "acquisition": "pending",
    }


def test_complete_diagnostic_export_contains_required_sanitized_files(
    client, tmp_path, monkeypatch
):
    runtime = tmp_path / "ThermoPower Monitor"
    log_path = runtime / "logs" / "thermopower.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        "startup version=0.5.6-physical-alpha\n"
        "COM open port=COM3\n"
        "protocol TX command=query_headers\n"
        "response classification actual=header_list\n"
        "password=must-not-leak\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("THERMOPOWER_APP_DATA_DIR", str(runtime))
    with SessionLocal() as db:
        device = db.scalar(select(Device).where(Device.protocol == "at4532_serial"))
        payload = create_diagnostic_zip(
            device,
            {
                "result": "failed",
                "transactions": [],
                "serial_parameters": {"data_bits": 8, "parity": "N", "stop_bits": 1},
            },
            [],
            integration={
                "devices": [
                    {
                        "device_id": device.id,
                        "sample_count": 2,
                        "last_error": None,
                        "latest_reading": {"raw_payload": {"response_ascii": "UNKNOWN,70.1"}},
                    }
                ],
                "token": "must-not-leak",
            },
        )
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert {
            "summary.html",
            "summary.pdf",
            "application-version.txt",
            "system.json",
            "serial-ports.json",
            "pnp-devices.json",
            "drivers.json",
            "devices.json",
            "associations.json",
            "serial-parameters.json",
            "protocol-results.json",
            "integration-status.json",
            "recent-log.txt",
            "README.txt",
            "SHA256SUMS.txt",
        } <= names
        assert archive.read("summary.pdf").startswith(b"%PDF")
        assert b"0.5.6-physical-alpha" in archive.read("application-version.txt")
        recent_log = archive.read("recent-log.txt").decode("utf-8")
        assert "COM open port=COM3" in recent_log
        assert "response classification actual=header_list" in recent_log
        assert "must-not-leak" not in recent_log
        assert "password=[redacted]" in recent_log
        integration = json.loads(archive.read("integration-status.json"))
        assert integration["devices"][0]["sample_count"] == 2
        assert integration["token"] == "[redacted]"
