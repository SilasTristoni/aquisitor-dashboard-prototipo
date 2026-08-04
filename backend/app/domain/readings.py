"""Device-neutral contracts. Adapters and importers must emit these canonical units."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Quality = Literal["good", "missing", "invalid", "overload", "estimated"]


class TemperatureChannelReading(BaseModel):
    channel: int = Field(ge=1, le=32)
    temperature_c: float | None
    original_value: float | None = None
    original_unit: str = "°C"
    quality: Quality = "good"


class TemperatureReading(BaseModel):
    device_timestamp: datetime | None = None
    received_timestamp: datetime
    ambient_temperature_c: float | None = None
    channels: list[TemperatureChannelReading] = Field(max_length=32)
    quality: Quality = "good"
    sequence: int | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("channels")
    @classmethod
    def unique_channels(
        cls, value: list[TemperatureChannelReading]
    ) -> list[TemperatureChannelReading]:
        numbers = [item.channel for item in value]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Canais de temperatura duplicados")
        return value


class ElectricalReading(BaseModel):
    device_timestamp: datetime | None = None
    received_timestamp: datetime
    voltage_v: float | None = None
    current_a: float | None = None
    active_power_w: float | None = None
    apparent_power_va: float | None = None
    reactive_power_var: float | None = None
    power_factor: float | None = None
    voltage_frequency_hz: float | None = None
    current_frequency_hz: float | None = None
    original_values: dict[str, float | None] = Field(default_factory=dict)
    original_units: dict[str, str] = Field(default_factory=dict)
    quality: Quality = "good"
    sequence: int | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


UNIT_FACTORS: dict[str, tuple[str, float]] = {
    "v": ("V", 1.0),
    "mv": ("V", 1e-3),
    "a": ("A", 1.0),
    "ma": ("A", 1e-3),
    "ua": ("A", 1e-6),
    "w": ("W", 1.0),
    "mw": ("W", 1e-3),
    "kw": ("W", 1e3),
    "va": ("VA", 1.0),
    "kva": ("VA", 1e3),
    "var": ("var", 1.0),
    "kvar": ("var", 1e3),
    "hz": ("Hz", 1.0),
    "khz": ("Hz", 1e3),
}


def normalize_value(value: float | None, unit: str, expected: str) -> float | None:
    if value is None:
        return None
    normalized = unit.strip().lower().replace("µ", "u")
    canonical = UNIT_FACTORS.get(normalized)
    if not canonical or canonical[0].lower() != expected.lower():
        raise ValueError(f"Unidade {unit!r} incompatível com {expected}")
    return value * canonical[1]


def normalize_temperature(value: float | None, unit: str) -> float | None:
    if value is None:
        return None
    normalized = unit.strip().lower().replace("°", "")
    if normalized == "c":
        return value
    if normalized == "f":
        return (value - 32) * 5 / 9
    if normalized == "k":
        return value - 273.15
    raise ValueError(f"Unidade de temperatura não suportada: {unit}")
