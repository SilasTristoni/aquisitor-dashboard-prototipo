from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict[str, Any]


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    role: Literal["admin", "operator", "viewer"] = "viewer"


class UserRead(ApiModel):
    id: int
    name: str
    email: str
    role: str
    active: bool
    created_at: datetime


class DeviceInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    connection_type: Literal["simulator", "serial", "file", "tcp"] = "simulator"
    port: str | None = None
    baud_rate: int = Field(default=115200, ge=300, le=4_000_000)
    protocol: Literal[
        "simulator",
        "serial_json",
        "serial_csv",
        "mock_failure",
        "at4532_serial",
        "gpm8213_serial",
        "temperature_file",
        "electrical_file",
    ] = "simulator"
    active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionCreate(BaseModel):
    device_id: int | None = None
    temperature_device_id: int | None = None
    electrical_device_id: int | None = None
    name: str = Field(min_length=2, max_length=160)
    description: str | None = None
    notes: str | None = None
    sample_interval_ms: int = Field(default=1000, ge=100, le=60_000)
    sync_grid_ms: int = Field(default=1000, ge=100, le=60_000)
    sync_tolerance_ms: int = Field(default=1500, ge=0, le=3000)

    @model_validator(mode="after")
    def at_least_one_device(self) -> "SessionCreate":
        if not (self.device_id or self.temperature_device_id or self.electrical_device_id):
            raise ValueError("Selecione ao menos um equipamento")
        return self


class ChannelInput(BaseModel):
    channel: int = Field(ge=1, le=32)
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    sensor_type: str = Field(default="K", max_length=20)
    unit: Literal["°C"] = "°C"
    correction_offset: float = Field(default=0, ge=-100, le=100)
    warning_limit: float | None = Field(default=None, ge=-270, le=1800)
    critical_limit: float | None = Field(default=None, ge=-270, le=1800)
    color: str = "#3667E9"
    description: str | None = None
    physical_location: str | None = None
    display_order: int = Field(default=0, ge=0, le=32)

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str) -> str:
        if len(value) != 7 or not value.startswith("#"):
            raise ValueError("Cor deve usar o formato #RRGGBB")
        int(value[1:], 16)
        return value.upper()


class ChannelProfileCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    channels: list[ChannelInput] = Field(min_length=1, max_length=32)


class AlertRuleInput(BaseModel):
    device_id: int
    metric: Literal["power", "temperature", "missing_reading", "acquisition_rate"]
    channel: int | None = Field(default=None, ge=1, le=32)
    operator: Literal[">", ">=", "<", "<="] = ">"
    threshold: float
    severity: Literal["info", "warning", "critical"] = "warning"
    enabled: bool = True
    cooldown_seconds: int = Field(default=60, ge=1, le=86_400)


class SimulatorConfigInput(BaseModel):
    channel_count: int = Field(default=16, ge=1, le=32)
    interval_ms: int = Field(default=1000, ge=100, le=60_000)
    base_power_w: float = Field(default=850, ge=0, le=10_000_000)
    power_variation_w: float = Field(default=180, ge=0)
    noise: float = Field(default=0.4, ge=0, le=100)
    initial_temperature_c: float = Field(default=30, ge=-100, le=1000)
    temperature_trend_c_per_minute: float = Field(default=0, ge=-100, le=100)
    failed_channel: int | None = Field(default=None, ge=1, le=32)
    missing_probability: float = Field(default=0, ge=0, le=1)
    malformed_probability: float = Field(default=0, ge=0, le=1)
    irregular_frequency: bool = False
    change_units: bool = True


class PeriodReportRequest(BaseModel):
    start: datetime
    end: datetime
    timezone: str = "America/Sao_Paulo"
    title: str = Field(default="Relatório de medições por período", min_length=2, max_length=180)
    subtitle: str | None = Field(default=None, max_length=240)
    description: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=4000)
    device_ids: list[int] | None = Field(default=None, max_length=100)
    session_ids: list[int] | None = Field(default=None, max_length=100)
    channels: list[int] | None = Field(default=None, max_length=32)
    include_power: bool = True
    include_temperatures: bool = True
    include_electrical_details: bool = True
    include_alerts: bool = True
    include_quality: bool = True
    include_session_list: bool = True
    include_table: bool = True
    orientation: Literal["portrait", "landscape"] = "landscape"
    theme: Literal["light", "dark"] = "light"
    dpi: int = Field(default=160, ge=96, le=300)
    table_max_rows: int = Field(default=100, ge=0, le=2000)
    channel_group_size: int = Field(default=8, ge=1, le=16)
    sync_tolerance_ms: int = Field(default=1500, ge=0, le=3000)
    use_device_timestamp: bool = True
    interpolation: Literal["none", "visual_only"] = "none"

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Fuso horário IANA inválido") from exc
        return value

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        unique = sorted(set(value))
        if not unique or any(channel < 1 or channel > 32 for channel in unique):
            raise ValueError("Canais devem estar entre 1 e 32")
        return unique

    @field_validator("device_ids", "session_ids")
    @classmethod
    def normalize_ids(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        unique = sorted(set(value))
        if not unique or any(item < 1 for item in unique):
            raise ValueError("Identificadores devem ser inteiros positivos")
        return unique

    @model_validator(mode="after")
    def validate_period(self) -> "PeriodReportRequest":
        zone = ZoneInfo(self.timezone)
        start = self.start.replace(tzinfo=zone) if self.start.tzinfo is None else self.start
        end = self.end.replace(tzinfo=zone) if self.end.tzinfo is None else self.end
        self.start = start.astimezone(UTC)
        self.end = end.astimezone(UTC)
        if self.end <= self.start:
            raise ValueError("O fim do período deve ser posterior ao início")
        if not (self.include_power or self.include_temperatures or self.include_electrical_details):
            raise ValueError("Selecione ao menos uma métrica")
        return self


class UsbAssociationRequest(BaseModel):
    port: str = Field(min_length=1, max_length=120)
    device_id: int = Field(ge=1)
