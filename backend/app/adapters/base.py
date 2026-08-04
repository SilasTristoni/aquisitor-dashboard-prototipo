from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

POWER_FACTORS = {"mw": 0.001, "w": 1.0, "kw": 1000.0}


def power_to_watts(value: float, unit: str) -> float:
    normalized = unit.strip().lower()
    if normalized not in POWER_FACTORS:
        raise ValueError(f"Unidade de potência não suportada: {unit}")
    numeric = float(value)
    if not 0 <= numeric < 1e12:
        raise ValueError("Valor de potência fora da faixa aceita")
    return numeric * POWER_FACTORS[normalized]


class DeviceReading(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_power: float
    raw_power_unit: str
    power_w: float
    temperatures_c: list[float | None] = Field(max_length=32)
    quality: str = "good"

    @field_validator("temperatures_c")
    @classmethod
    def validate_temperatures(cls, values: list[float | None]) -> list[float | None]:
        for value in values:
            if value is not None and not -270 <= value <= 1800:
                raise ValueError("Temperatura fora da faixa defensiva")
        return values


class DeviceStatus(BaseModel):
    state: str
    connected: bool
    reading: bool
    last_message_at: datetime | None = None
    messages_per_second: float = 0
    read_errors: int = 0


class DeviceInformation(BaseModel):
    adapter: str
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    firmware_version: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)


class DeviceAdapter(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    def start_reading(self) -> AsyncIterator[DeviceReading]: ...

    @abstractmethod
    async def stop_reading(self) -> None: ...

    @abstractmethod
    def parse_message(self, raw: bytes | str) -> DeviceReading: ...

    @abstractmethod
    async def get_status(self) -> DeviceStatus: ...

    @abstractmethod
    async def get_device_information(self) -> DeviceInformation: ...
