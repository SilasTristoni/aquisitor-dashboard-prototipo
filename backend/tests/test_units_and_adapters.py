import asyncio
import json

import pytest

from app.adapters.base import power_to_watts
from app.adapters.serial import SerialCsvAdapter, SerialJsonAdapter
from app.adapters.simulator import MockFailureAdapter, SimulatorAdapter
from app.schemas.contracts import SimulatorConfigInput


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [(850_000, "mW", 850), (850, "W", 850), (0.85, "kW", 850)],
)
def test_power_conversion(value, unit, expected):
    assert power_to_watts(value, unit) == expected


@pytest.mark.parametrize("value,unit", [(-1, "W"), (1, "horsepower"), (float("inf"), "W")])
def test_power_conversion_rejects_invalid_values(value, unit):
    with pytest.raises(ValueError):
        power_to_watts(value, unit)


def test_serial_json_parser_preserves_raw_unit():
    adapter = SerialJsonAdapter("COM_TEST")
    reading = adapter.parse_message(
        json.dumps({"power": 900_000, "powerUnit": "mW", "temperatures": [31.2, 32.4]})
    )
    assert reading.power_w == 900
    assert reading.raw_power == 900_000
    assert reading.raw_power_unit == "mW"
    assert reading.temperatures_c == [31.2, 32.4]


def test_serial_csv_parser_is_ready_but_connection_disabled():
    adapter = SerialCsvAdapter("COM_TEST")
    reading = adapter.parse_message("0.9,kW,31.2,32.4")
    assert reading.power_w == 900
    with pytest.raises(RuntimeError, match="homologação"):
        asyncio.run(adapter.connect())


@pytest.mark.asyncio
async def test_simulator_generates_configured_channels_and_units():
    adapter = SimulatorAdapter(
        SimulatorConfigInput(channel_count=4, interval_ms=100, change_units=True), seed=7
    )
    await adapter.connect()
    iterator = adapter.start_reading()
    reading = await anext(iterator)
    await adapter.stop_reading()
    await adapter.disconnect()
    assert len(reading.temperatures_c) == 4
    assert reading.raw_power_unit in {"mW", "W", "kW"}
    assert reading.power_w >= 0


@pytest.mark.asyncio
async def test_simulator_scenario_and_failure_adapter():
    adapter = SimulatorAdapter()
    adapter.apply_scenario("sensor_failure")
    assert adapter.config.failed_channel == 3
    failing = MockFailureAdapter("connect")
    with pytest.raises(ConnectionError, match="simulada"):
        await failing.connect()
