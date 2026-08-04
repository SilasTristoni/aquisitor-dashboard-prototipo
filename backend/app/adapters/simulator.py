import asyncio
import json
import math
import random
from collections.abc import AsyncIterator
from datetime import datetime
from time import monotonic

from app.adapters.base import (
    DeviceAdapter,
    DeviceInformation,
    DeviceReading,
    DeviceStatus,
    power_to_watts,
)
from app.schemas.contracts import SimulatorConfigInput

SCENARIOS = {
    "normal": {},
    "gradual_heating": {"temperature_trend_c_per_minute": 4},
    "overheating": {"initial_temperature_c": 76, "temperature_trend_c_per_minute": 8},
    "power_spike": {"base_power_w": 2600, "power_variation_w": 900},
    "sensor_failure": {"failed_channel": 3, "missing_probability": 0.25},
    "connection_loss": {"missing_probability": 0.6, "irregular_frequency": True},
    "invalid_messages": {"malformed_probability": 0.3},
    "long_session": {"interval_ms": 250, "noise": 0.2},
}


class SimulatorAdapter(DeviceAdapter):
    def __init__(self, config: SimulatorConfigInput | None = None, seed: int = 42) -> None:
        self.config = config or SimulatorConfigInput()
        self.random = random.Random(seed)
        self.connected = False
        self.reading = False
        self.started_at = monotonic()
        self.last_message_at: datetime | None = None
        self.messages = 0
        self.errors = 0

    def configure(self, config: SimulatorConfigInput) -> None:
        self.config = config

    def apply_scenario(self, name: str) -> None:
        if name not in SCENARIOS:
            raise ValueError("Cenário desconhecido")
        data = self.config.model_dump()
        data.update(SCENARIOS[name])
        self.config = SimulatorConfigInput(**data)
        self.started_at = monotonic()

    async def connect(self) -> None:
        await asyncio.sleep(0.05)
        self.connected = True

    async def disconnect(self) -> None:
        self.reading = False
        self.connected = False

    async def stop_reading(self) -> None:
        self.reading = False

    def _payload(self) -> dict:
        elapsed = monotonic() - self.started_at
        cfg = self.config
        power_w = max(
            0,
            cfg.base_power_w
            + math.sin(elapsed / 6) * cfg.power_variation_w
            + self.random.gauss(0, cfg.noise * 20),
        )
        units = ["mW", "W", "kW"] if cfg.change_units else ["W"]
        unit = self.random.choice(units)
        raw_power = power_w / {"mW": 0.001, "W": 1, "kW": 1000}[unit]
        temperatures: list[float | None] = []
        for index in range(cfg.channel_count):
            if cfg.failed_channel == index + 1 or self.random.random() < cfg.missing_probability:
                temperatures.append(None)
                continue
            baseline = cfg.initial_temperature_c + index * 0.45
            trend = cfg.temperature_trend_c_per_minute * elapsed / 60
            wave = math.sin(elapsed / 9 + index * 0.7) * 2.5
            temperatures.append(round(baseline + trend + wave + self.random.gauss(0, cfg.noise), 3))
        return {"power": round(raw_power, 6), "powerUnit": unit, "temperatures": temperatures}

    def parse_message(self, raw: bytes | str) -> DeviceReading:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        payload = json.loads(text)
        power = float(payload["power"])
        unit = str(payload.get("powerUnit", "W"))
        return DeviceReading(
            raw_power=power,
            raw_power_unit=unit,
            power_w=power_to_watts(power, unit),
            temperatures_c=payload.get("temperatures", []),
            quality="good",
        )

    async def start_reading(self) -> AsyncIterator[DeviceReading]:
        if not self.connected:
            raise RuntimeError("Simulador não conectado")
        self.reading = True
        while self.connected and self.reading:
            delay = self.config.interval_ms / 1000
            if self.config.irregular_frequency:
                delay *= self.random.uniform(0.5, 2)
            await asyncio.sleep(delay)
            try:
                if self.random.random() < self.config.malformed_probability:
                    reading = self.parse_message("{mensagem-invalida")
                else:
                    reading = self.parse_message(json.dumps(self._payload()))
                self.messages += 1
                self.last_message_at = reading.timestamp
                yield reading
            except (ValueError, KeyError, json.JSONDecodeError):
                self.errors += 1

    async def get_status(self) -> DeviceStatus:
        elapsed = max(monotonic() - self.started_at, 0.001)
        return DeviceStatus(
            state="reading"
            if self.reading
            else ("connected" if self.connected else "disconnected"),
            connected=self.connected,
            reading=self.reading,
            last_message_at=self.last_message_at,
            messages_per_second=self.messages / elapsed,
            read_errors=self.errors,
        )

    async def get_device_information(self) -> DeviceInformation:
        return DeviceInformation(
            adapter="simulator",
            manufacturer="ThermoPower Labs",
            model="Virtual DAQ 32",
            firmware_version="sim-2.0",
            capabilities={"channels": self.config.channel_count, "units": ["mW", "W", "kW"]},
        )


class MockFailureAdapter(SimulatorAdapter):
    def __init__(self, fail_on: str = "connect") -> None:
        super().__init__()
        self.fail_on = fail_on

    async def connect(self) -> None:
        if self.fail_on == "connect":
            raise ConnectionError("Falha simulada de conexão")
        await super().connect()

    async def start_reading(self) -> AsyncIterator[DeviceReading]:
        if self.fail_on == "read":
            raise OSError("Falha simulada de leitura")
        async for reading in super().start_reading():
            yield reading
