"""Regression fixtures captured from the physically validated instruments."""

from types import SimpleNamespace

import pytest

from app.adapters.specific import (
    Gpm8213Parser,
    Gpm8213UsbSerialAdapter,
    ProtocolResponseError,
)
from app.services.usb_discovery import UsbDeviceDiscoveryService

pytestmark = pytest.mark.physical_regression_fixtures

GPM_IDENTITY_V105 = b"GWInstek,GPM-8213,GES913349,V1.05\r\n"
GPM_NUMBER_SCPI_SHORT = b":NUM:NORM:NUMB 8\r\n"
GPM_PHYSICAL_HEADERS = b"Urms,Irms,P,S,fU,PF,Q,fI\r\n"
GPM_PHYSICAL_VALUES = (
    b"127.58E+00,240.02E-03,17.688E+00,30.622E+00,59.993E+00,"
    b"0.5776E+00,24.997E+00,NAN\r\n"
)


class PhysicalGpmTransport:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = list(responses)
        self.requests: list[bytes] = []
        self.is_open = False

    async def open(self) -> float:
        self.is_open = True
        return 1.0

    async def query(
        self, payload: bytes, _terminator: bytes, _max_bytes: int = 65536
    ) -> tuple[bytes, float]:
        self.requests.append(payload)
        return self.responses.pop(0), 2.0

    async def write(self, payload: bytes) -> tuple[int, float]:
        self.requests.append(payload)
        return len(payload), 1.0

    async def close(self) -> None:
        self.is_open = False


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"8\r\n", id="plain-count"),
        pytest.param(GPM_NUMBER_SCPI_SHORT, id="physical-scpi-short-form"),
        pytest.param(
            b":NUMERIC:NORMAL:NUMBER 8\r\n",
            id="documented-scpi-long-form",
        ),
    ],
)
def test_gpm_number_query_accepts_only_supported_count_shapes(payload: bytes) -> None:
    parser = Gpm8213Parser()

    assert parser.classify(payload) == "item_count"
    assert parser.parse_item_count(payload) == 8


@pytest.mark.parametrize(
    "payload",
    [
        b"arbitrary response 8\r\n",
        b":NUM:NORM:UNKNOWN 8\r\n",
        b":NUMBER 8\r\n",
    ],
)
def test_gpm_number_query_does_not_accept_arbitrary_number_suffixes(payload: bytes) -> None:
    parser = Gpm8213Parser()

    assert parser.classify(payload) == "unknown_response"
    with pytest.raises(ProtocolResponseError):
        parser.parse_item_count(payload)


@pytest.mark.asyncio
async def test_gpm_v105_complete_physical_sequence_reaches_normalized_reading() -> None:
    transport = PhysicalGpmTransport(
        [
            GPM_IDENTITY_V105,
            GPM_NUMBER_SCPI_SHORT,
            GPM_PHYSICAL_HEADERS,
            GPM_PHYSICAL_VALUES,
        ]
    )
    adapter = Gpm8213UsbSerialAdapter("COM3", None, transport=transport)

    await adapter.connect()
    reading = await adapter.read_once()
    information = await adapter.get_device_information()
    await adapter.disconnect()

    assert transport.requests == [
        b"*IDN?\r\n",
        b":NUMERIC:NORMAL:NUMBER 8\r\n",
        b":NUMERIC:NORMAL:NUMBER?\r\n",
        b":NUMERIC:NORMAL:ITEM1 U\r\n",
        b":NUMERIC:NORMAL:ITEM2 I\r\n",
        b":NUMERIC:NORMAL:ITEM3 P\r\n",
        b":NUMERIC:NORMAL:ITEM4 S\r\n",
        b":NUMERIC:NORMAL:ITEM5 FU\r\n",
        b":NUMERIC:NORMAL:ITEM6 LAMBDA\r\n",
        b":NUMERIC:NORMAL:ITEM7 Q\r\n",
        b":NUMERIC:NORMAL:ITEM8 FI\r\n",
        b":NUMERIC:NORMAL:HEADER?\r\n",
        b":NUMERIC:NORMAL:VALUE?\r\n",
    ]
    assert transport.responses == []
    assert transport.is_open is False
    assert adapter.expected_interval_seconds == 1.0
    assert adapter.identity_status == "confirmed"
    assert adapter.number_reported == 8
    assert information.serial_number == "GES913349"
    assert information.firmware_version == "V1.05"

    count_transaction = adapter.transactions[2]
    assert count_transaction["command_name"] == "query_item_count"
    assert count_transaction["actual_response_type"] == "item_count"
    assert count_transaction["parsed"]["number_reported"] == 8
    assert adapter.headers_requested == ["U", "I", "P", "S", "FU", "LAMBDA", "Q", "FI"]
    assert adapter.headers_reported == ["Urms", "Irms", "P", "S", "fU", "PF", "Q", "fI"]

    assert reading.voltage_v == 127.58
    assert reading.current_a == 0.24002
    assert reading.power_w == 17.688
    assert reading.apparent_power_va == 30.622
    assert reading.voltage_frequency_hz == 59.993
    assert reading.power_factor == 0.5776
    assert reading.reactive_power_var == 24.997
    assert reading.current_frequency_hz is None
    assert reading.quality == "missing"
    assert reading.raw_payload["raw_values"]["fI"] == "NAN"
    assert reading.raw_payload["parsed_values"] == {
        "Vrms": 127.58,
        "Irms": 0.24002,
        "P": 17.688,
        "VA": 30.622,
        "VHz": 59.993,
        "PF": 0.5776,
        "VAR": 24.997,
        "IHz": None,
    }


def test_gpm_physical_usb_serial_remains_the_high_confidence_identity() -> None:
    physical_port = SimpleNamespace(
        description="USB Serial Device",
        manufacturer="GW Instek",
        product="GPM-8213",
        serial_number="GES913349",
        vid=0x2184,
        pid=0x0052,
    )

    assert UsbDeviceDiscoveryService._suggestion(physical_port) == {
        "device": "GW Instek GPM-8213 confirmado pelo serial USB",
        "protocol": "gpm8213_serial",
        "status": "confirmed_gpm8213",
        "confidence": "high",
    }
