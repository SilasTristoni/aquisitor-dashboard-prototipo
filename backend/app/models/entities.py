from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class UserRole(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=UserRole.VIEWER.value)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    manufacturer: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120))
    serial_number: Mapped[str | None] = mapped_column(String(120), unique=True)
    connection_type: Mapped[str] = mapped_column(String(30), default="simulator")
    port: Mapped[str | None] = mapped_column(String(120))
    baud_rate: Mapped[int] = mapped_column(Integer, default=115200)
    protocol: Mapped[str] = mapped_column(String(40), default="simulator")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    channels: Mapped[list["ChannelConfiguration"]] = relationship(cascade="all, delete-orphan")


class MeasurementSession(Base):
    __tablename__ = "measurement_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)
    sample_interval_ms: Mapped[int] = mapped_column(Integer, default=1000)
    acquisition_mode: Mapped[str] = mapped_column(String(24), default="live")
    sync_grid_ms: Mapped[int] = mapped_column(Integer, default=1000)
    sync_tolerance_ms: Mapped[int] = mapped_column(Integer, default=1500)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    device: Mapped[Device] = relationship()
    user: Mapped[User] = relationship()


class Measurement(Base):
    __tablename__ = "measurements"
    __table_args__ = (Index("ix_measurements_session_timestamp", "session_id", "timestamp"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("measurement_sessions.id", ondelete="CASCADE")
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    power_w: Mapped[float] = mapped_column(Float)
    raw_power: Mapped[float] = mapped_column(Float)
    raw_power_unit: Mapped[str] = mapped_column(String(4))
    quality: Mapped[str] = mapped_column(String(24), default="good")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    temperatures: Mapped[list["TemperatureMeasurement"]] = relationship(
        cascade="all, delete-orphan"
    )


class TemperatureMeasurement(Base):
    __tablename__ = "temperature_measurements"
    __table_args__ = (
        Index("ix_temperatures_measurement_channel", "measurement_id", "channel", unique=True),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    measurement_id: Mapped[int] = mapped_column(ForeignKey("measurements.id", ondelete="CASCADE"))
    channel: Mapped[int] = mapped_column(Integer)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    quality: Mapped[str] = mapped_column(String(24), default="good")


class ChannelConfiguration(Base):
    __tablename__ = "channel_configurations"
    __table_args__ = (Index("ix_channels_device_channel", "device_id", "channel", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    channel: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sensor_type: Mapped[str] = mapped_column(String(20), default="K")
    unit: Mapped[str] = mapped_column(String(4), default="°C")
    correction_offset: Mapped[float] = mapped_column(Float, default=0)
    warning_limit: Mapped[float | None] = mapped_column(Float)
    critical_limit: Mapped[float | None] = mapped_column(Float)
    color: Mapped[str] = mapped_column(String(10), default="#3667E9")
    description: Mapped[str | None] = mapped_column(Text)
    physical_location: Mapped[str | None] = mapped_column(String(160))
    display_order: Mapped[int] = mapped_column(Integer, default=0)


class SessionDevice(Base):
    """Associates independently acquired streams with a measurement session."""

    __tablename__ = "session_devices"
    __table_args__ = (
        UniqueConstraint("session_id", "role", name="uq_session_devices_session_role"),
        UniqueConstraint("session_id", "device_id", "role", name="uq_session_devices_mapping"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("measurement_sessions.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    role: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    device: Mapped[Device] = relationship()


class TemperatureSample(Base):
    __tablename__ = "temperature_samples"
    __table_args__ = (
        Index("ix_temperature_samples_session_time", "session_id", "received_timestamp"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("measurement_sessions.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    device_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ambient_temperature_c: Mapped[float | None] = mapped_column(Float)
    quality: Mapped[str] = mapped_column(String(24), default="good")
    source: Mapped[str] = mapped_column(String(24), default="live")
    source_row: Mapped[int | None] = mapped_column(Integer)
    sequence: Mapped[int | None] = mapped_column(Integer)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    channels: Mapped[list["TemperatureChannelValue"]] = relationship(cascade="all, delete-orphan")


class TemperatureChannelValue(Base):
    __tablename__ = "temperature_channel_values"
    __table_args__ = (
        UniqueConstraint("sample_id", "channel", name="uq_temperature_sample_channel"),
        Index("ix_temperature_channel_values_channel", "channel"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    sample_id: Mapped[int] = mapped_column(
        ForeignKey("temperature_samples.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[int] = mapped_column(Integer)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    original_value: Mapped[float | None] = mapped_column(Float)
    original_unit: Mapped[str] = mapped_column(String(12), default="°C")
    quality: Mapped[str] = mapped_column(String(24), default="good")


class ElectricalSample(Base):
    __tablename__ = "electrical_samples"
    __table_args__ = (
        Index("ix_electrical_samples_session_time", "session_id", "received_timestamp"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("measurement_sessions.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    device_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    voltage_v: Mapped[float | None] = mapped_column(Float)
    current_a: Mapped[float | None] = mapped_column(Float)
    active_power_w: Mapped[float | None] = mapped_column(Float)
    apparent_power_va: Mapped[float | None] = mapped_column(Float)
    reactive_power_var: Mapped[float | None] = mapped_column(Float)
    power_factor: Mapped[float | None] = mapped_column(Float)
    voltage_frequency_hz: Mapped[float | None] = mapped_column(Float)
    current_frequency_hz: Mapped[float | None] = mapped_column(Float)
    original_values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    original_units: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    quality: Mapped[str] = mapped_column(String(24), default="good")
    source: Mapped[str] = mapped_column(String(24), default="live")
    source_row: Mapped[int | None] = mapped_column(Integer)
    sequence: Mapped[int | None] = mapped_column(Integer)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SessionChannelConfiguration(Base):
    __tablename__ = "session_channel_configurations"
    __table_args__ = (
        UniqueConstraint("session_id", "channel", name="uq_session_channel_snapshot"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("measurement_sessions.id", ondelete="CASCADE"), index=True
    )
    source_configuration_id: Mapped[int | None] = mapped_column(
        ForeignKey("channel_configurations.id", ondelete="SET NULL")
    )
    channel: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sensor_type: Mapped[str] = mapped_column(String(20), default="K")
    unit: Mapped[str] = mapped_column(String(12), default="°C")
    correction_offset: Mapped[float] = mapped_column(Float, default=0)
    warning_limit: Mapped[float | None] = mapped_column(Float)
    critical_limit: Mapped[float | None] = mapped_column(Float)
    color: Mapped[str] = mapped_column(String(10), default="#3667E9")
    description: Mapped[str | None] = mapped_column(Text)
    physical_location: Mapped[str | None] = mapped_column(String(160))
    display_order: Mapped[int] = mapped_column(Integer, default=0)


class ChannelProfile(Base):
    __tablename__ = "channel_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    channels: Mapped[list["ChannelProfileValue"]] = relationship(cascade="all, delete-orphan")


class ChannelProfileValue(Base):
    __tablename__ = "channel_profile_values"
    __table_args__ = (UniqueConstraint("profile_id", "channel", name="uq_profile_channel"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("channel_profiles.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[int] = mapped_column(Integer)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(40))
    channel: Mapped[int | None] = mapped_column(Integer)
    operator: Mapped[str] = mapped_column(String(8), default=">")
    threshold: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(20), default="warning")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=60)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alerts_session_timestamp", "session_id", "timestamp"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("measurement_sessions.id"), index=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    metric: Mapped[str] = mapped_column(String(40))
    channel: Mapped[int | None] = mapped_column(Integer)
    measured_value: Mapped[float] = mapped_column(Float)
    threshold: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(20))
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class SystemEvent(Base):
    __tablename__ = "system_events"
    __table_args__ = (Index("ix_events_timestamp_category", "timestamp", "category"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("measurement_sessions.id"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    level: Mapped[str] = mapped_column(String(20), default="info")
    category: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("measurement_sessions.id"))
    type: Mapped[str] = mapped_column(String(12))
    file_path: Mapped[str | None] = mapped_column(String(500))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    generated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
