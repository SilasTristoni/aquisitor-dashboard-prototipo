from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.readings import ElectricalReading, TemperatureReading
from app.models.entities import (
    ChannelConfiguration,
    Device,
    ElectricalSample,
    MeasurementSession,
    SessionChannelConfiguration,
    SessionDevice,
    TemperatureChannelValue,
    TemperatureSample,
    User,
)


def get_or_create_import_device(db: Session, role: str) -> Device:
    protocol = f"{role}_file"
    device = db.scalar(select(Device).where(Device.protocol == protocol))
    if device:
        return device
    if role == "temperature":
        name, manufacturer, model = "AT4532 (arquivo)", "Applent", "AT4532"
    else:
        name, manufacturer, model = "GPM-8213 (arquivo)", "GW Instek", "GPM-8213"
    device = Device(
        name=name,
        manufacturer=manufacturer,
        model=model,
        connection_type="file",
        protocol=protocol,
        metadata_json={"hardware_validation": "pending_reference_files"},
    )
    db.add(device)
    db.flush()
    if role == "temperature":
        for channel in range(1, 33):
            db.add(
                ChannelConfiguration(
                    device_id=device.id,
                    channel=channel,
                    name=f"Termopar {channel}",
                    enabled=True,
                    display_order=channel,
                )
            )
    return device


def create_import_session(
    db: Session,
    user: User,
    name: str,
    temperature_readings: list[TemperatureReading],
    electrical_readings: list[ElectricalReading],
    temperature_device_id: int | None = None,
    electrical_device_id: int | None = None,
    description: str | None = None,
    grid_ms: int = 1000,
    tolerance_ms: int = 1500,
) -> MeasurementSession:
    if not temperature_readings and not electrical_readings:
        raise ValueError("Nenhuma linha válida para importar")
    temperature_device = db.get(Device, temperature_device_id) if temperature_device_id else None
    electrical_device = db.get(Device, electrical_device_id) if electrical_device_id else None
    if temperature_readings and not temperature_device:
        temperature_device = get_or_create_import_device(db, "temperature")
    if electrical_readings and not electrical_device:
        electrical_device = get_or_create_import_device(db, "electrical")
    primary_device = temperature_device or electrical_device
    if not primary_device:
        raise ValueError("Equipamento de importação não encontrado")
    all_times = [item.received_timestamp for item in temperature_readings + electrical_readings]
    session = MeasurementSession(
        device_id=primary_device.id,
        user_id=user.id,
        name=name,
        description=description,
        started_at=min(all_times),
        ended_at=max(all_times),
        status="finished",
        acquisition_mode="import",
        sample_interval_ms=grid_ms,
        sync_grid_ms=grid_ms,
        sync_tolerance_ms=tolerance_ms,
    )
    db.add(session)
    db.flush()
    if temperature_device:
        db.add(
            SessionDevice(
                session_id=session.id, device_id=temperature_device.id, role="temperature"
            )
        )
        _snapshot_channels(db, session.id, temperature_device.id)
    if electrical_device:
        db.add(
            SessionDevice(session_id=session.id, device_id=electrical_device.id, role="electrical")
        )
    for sequence, reading in enumerate(temperature_readings, 1):
        sample = TemperatureSample(
            session_id=session.id,
            device_id=temperature_device.id,
            device_timestamp=reading.device_timestamp,
            received_timestamp=reading.received_timestamp,
            ambient_temperature_c=reading.ambient_temperature_c,
            quality=reading.quality,
            source="import",
            sequence=sequence,
            raw_payload=reading.raw_payload,
        )
        sample.channels = [
            TemperatureChannelValue(
                channel=value.channel,
                temperature_c=value.temperature_c,
                original_value=value.original_value,
                original_unit=value.original_unit,
                quality=value.quality,
            )
            for value in reading.channels
        ]
        db.add(sample)
    for sequence, reading in enumerate(electrical_readings, 1):
        db.add(
            ElectricalSample(
                session_id=session.id,
                device_id=electrical_device.id,
                device_timestamp=reading.device_timestamp,
                received_timestamp=reading.received_timestamp,
                voltage_v=reading.voltage_v,
                current_a=reading.current_a,
                active_power_w=reading.active_power_w,
                apparent_power_va=reading.apparent_power_va,
                reactive_power_var=reading.reactive_power_var,
                power_factor=reading.power_factor,
                voltage_frequency_hz=reading.voltage_frequency_hz,
                current_frequency_hz=reading.current_frequency_hz,
                original_values=reading.original_values,
                original_units=reading.original_units,
                quality=reading.quality,
                source="import",
                sequence=sequence,
                raw_payload=reading.raw_payload,
            )
        )
    db.commit()
    db.refresh(session)
    return session


def _snapshot_channels(db: Session, session_id: int, device_id: int) -> None:
    channels = db.scalars(
        select(ChannelConfiguration).where(ChannelConfiguration.device_id == device_id)
    ).all()
    for config in channels:
        db.add(
            SessionChannelConfiguration(
                session_id=session_id,
                source_configuration_id=config.id,
                channel=config.channel,
                name=config.name,
                enabled=config.enabled,
                sensor_type=config.sensor_type,
                unit=config.unit,
                correction_offset=config.correction_offset,
                warning_limit=config.warning_limit,
                critical_limit=config.critical_limit,
                color=config.color,
                description=config.description,
                physical_location=config.physical_location,
                display_order=config.display_order or config.channel,
            )
        )
