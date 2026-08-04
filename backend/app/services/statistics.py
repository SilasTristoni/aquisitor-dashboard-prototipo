import math
import statistics
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    AlertEvent,
    ElectricalSample,
    Measurement,
    MeasurementSession,
    TemperatureChannelValue,
    TemperatureMeasurement,
    TemperatureSample,
)


def describe(values: list[float]) -> dict:
    clean = sorted(value for value in values if math.isfinite(value))
    if not clean:
        return {
            "count": 0,
            "mean": None,
            "min": None,
            "max": None,
            "median": None,
            "stddev": None,
            "range": None,
            "p95": None,
        }
    p95_index = min(len(clean) - 1, max(0, math.ceil(len(clean) * 0.95) - 1))
    return {
        "count": len(clean),
        "mean": statistics.fmean(clean),
        "min": clean[0],
        "max": clean[-1],
        "median": statistics.median(clean),
        "stddev": statistics.pstdev(clean),
        "range": clean[-1] - clean[0],
        "p95": clean[p95_index],
    }


def session_statistics(db: Session, session_id: int) -> dict:
    session = db.get(MeasurementSession, session_id)
    if not session:
        raise ValueError("Sessão não encontrada")
    powers = list(
        db.scalars(
            select(ElectricalSample.active_power_w).where(
                ElectricalSample.session_id == session_id,
                ElectricalSample.active_power_w.is_not(None),
            )
        )
    )
    if not powers:
        powers = list(
            db.scalars(select(Measurement.power_w).where(Measurement.session_id == session_id))
        )
    channel_rows = db.execute(
        select(TemperatureChannelValue.channel, TemperatureChannelValue.temperature_c)
        .join(TemperatureSample)
        .where(
            TemperatureSample.session_id == session_id,
            TemperatureChannelValue.temperature_c.is_not(None),
        )
    ).all()
    if not channel_rows:
        channel_rows = db.execute(
            select(TemperatureMeasurement.channel, TemperatureMeasurement.temperature_c)
            .join(Measurement)
            .where(
                Measurement.session_id == session_id,
                TemperatureMeasurement.temperature_c.is_not(None),
            )
        ).all()
    by_channel: dict[int, list[float]] = {}
    for channel, value in channel_rows:
        by_channel.setdefault(channel, []).append(value)
    alerts = (
        db.scalar(
            select(func.count()).select_from(AlertEvent).where(AlertEvent.session_id == session_id)
        )
        or 0
    )
    expected_interval = session.sample_interval_ms / 1000
    timestamps = list(
        db.scalars(
            select(ElectricalSample.received_timestamp)
            .where(ElectricalSample.session_id == session_id)
            .order_by(ElectricalSample.received_timestamp)
        )
    )
    if not timestamps:
        timestamps = list(
            db.scalars(
                select(Measurement.timestamp)
                .where(Measurement.session_id == session_id)
                .order_by(Measurement.timestamp)
            )
        )
    gaps = 0
    if len(timestamps) > 1:
        gaps = sum(
            1
            for previous, current in zip(timestamps, timestamps[1:], strict=False)
            if (current - previous).total_seconds() > expected_interval * 2.5
        )
    duration = 0.0
    if session.started_at:
        end = session.ended_at or datetime.now(UTC)
        start = session.started_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        duration = max(0, (end - start).total_seconds())
    return {
        "session_id": session_id,
        "power": describe(powers),
        "temperatures": {str(channel): describe(values) for channel, values in by_channel.items()},
        "hottest_channel": max(by_channel, key=lambda channel: max(by_channel[channel]))
        if by_channel
        else None,
        "coldest_channel": min(by_channel, key=lambda channel: min(by_channel[channel]))
        if by_channel
        else None,
        "highest_variation_channel": max(
            by_channel, key=lambda channel: max(by_channel[channel]) - min(by_channel[channel])
        )
        if by_channel
        else None,
        "channels_without_readings": [
            channel for channel in range(1, 33) if channel not in by_channel
        ],
        "acquisition_gaps": gaps,
        "alert_count": alerts,
        "duration_seconds": duration,
        "actual_frequency_hz": len(powers) / duration if duration else 0,
    }


def executive_statistics(db: Session) -> dict:
    total_sessions = db.scalar(select(func.count()).select_from(MeasurementSession)) or 0
    legacy_samples = db.scalar(select(func.count()).select_from(Measurement)) or 0
    electrical_samples = db.scalar(select(func.count()).select_from(ElectricalSample)) or 0
    temperature_samples = db.scalar(select(func.count()).select_from(TemperatureSample)) or 0
    total_samples = legacy_samples + electrical_samples + temperature_samples
    total_alerts = db.scalar(select(func.count()).select_from(AlertEvent)) or 0
    completed_periods = db.execute(
        select(MeasurementSession.started_at, MeasurementSession.ended_at).where(
            MeasurementSession.ended_at.is_not(None)
        )
    ).all()
    monitored_seconds = sum(
        (ended - started).total_seconds() for started, ended in completed_periods
    )
    return {
        "total_sessions": total_sessions,
        "total_samples": total_samples,
        "total_alerts": total_alerts,
        "monitored_hours": monitored_seconds / 3600,
    }
