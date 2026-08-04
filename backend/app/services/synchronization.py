from bisect import bisect_left
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import ElectricalSample, TemperatureSample


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _nearest(rows: list, timestamps: list[datetime], target: datetime, tolerance_ms: int):
    index = bisect_left(timestamps, target)
    candidates = [candidate for candidate in (index - 1, index) if 0 <= candidate < len(rows)]
    if not candidates:
        return None, None
    winner = min(
        candidates, key=lambda candidate: abs((timestamps[candidate] - target).total_seconds())
    )
    offset_ms = abs((timestamps[winner] - target).total_seconds() * 1000)
    return (rows[winner], offset_ms) if offset_ms <= tolerance_ms else (None, None)


def synchronized_series(
    db: Session,
    session_id: int,
    grid_ms: int = 1000,
    tolerance_ms: int = 1500,
    channels: set[int] | None = None,
    max_points: int = 5000,
) -> dict:
    if not 100 <= grid_ms <= 60_000:
        raise ValueError("A grade deve estar entre 100 ms e 60 s")
    if not 0 <= tolerance_ms <= 3000:
        raise ValueError("A tolerância deve estar entre 0 e 3000 ms")
    temperatures = list(
        db.scalars(
            select(TemperatureSample)
            .options(selectinload(TemperatureSample.channels))
            .where(TemperatureSample.session_id == session_id)
            .order_by(TemperatureSample.received_timestamp)
        )
    )
    electrical = list(
        db.scalars(
            select(ElectricalSample)
            .where(ElectricalSample.session_id == session_id)
            .order_by(ElectricalSample.received_timestamp)
        )
    )
    all_timestamps = [_utc(row.received_timestamp) for row in temperatures + electrical]
    if not all_timestamps:
        return {
            "points": [],
            "metrics": _metrics(0, 0, 0, []),
            "grid_ms": grid_ms,
            "tolerance_ms": tolerance_ms,
        }
    start, end = min(all_timestamps), max(all_timestamps)
    requested_points = int((end - start).total_seconds() * 1000 / grid_ms) + 1
    effective_grid_ms = (
        max(grid_ms, int((end - start).total_seconds() * 1000 / max(max_points - 1, 1)) + 1)
        if requested_points > max_points
        else grid_ms
    )
    temp_times = [_utc(row.received_timestamp) for row in temperatures]
    electrical_times = [_utc(row.received_timestamp) for row in electrical]
    points, offsets = [], []
    matched = temp_only = electrical_only = 0
    cursor = start
    while cursor <= end and len(points) < max_points:
        temp, temp_offset = _nearest(temperatures, temp_times, cursor, tolerance_ms)
        power, power_offset = _nearest(electrical, electrical_times, cursor, tolerance_ms)
        if temp and power:
            matched += 1
            offsets.append(
                abs(
                    (_utc(temp.received_timestamp) - _utc(power.received_timestamp)).total_seconds()
                    * 1000
                )
            )
        elif temp:
            temp_only += 1
        elif power:
            electrical_only += 1
        channel_values = {}
        if temp:
            channel_values = {
                str(value.channel): value.temperature_c
                for value in temp.channels
                if channels is None or value.channel in channels
            }
        points.append(
            {
                "timestamp": cursor.isoformat(),
                "temperature_sample_timestamp": _utc(temp.received_timestamp).isoformat()
                if temp
                else None,
                "electrical_sample_timestamp": _utc(power.received_timestamp).isoformat()
                if power
                else None,
                "temperature_offset_ms": temp_offset,
                "electrical_offset_ms": power_offset,
                "temperatures_c": channel_values,
                "ambient_temperature_c": temp.ambient_temperature_c if temp else None,
                "voltage_v": power.voltage_v if power else None,
                "current_a": power.current_a if power else None,
                "active_power_w": power.active_power_w if power else None,
                "apparent_power_va": power.apparent_power_va if power else None,
                "reactive_power_var": power.reactive_power_var if power else None,
                "power_factor": power.power_factor if power else None,
                "voltage_frequency_hz": power.voltage_frequency_hz if power else None,
                "current_frequency_hz": power.current_frequency_hz if power else None,
            }
        )
        cursor += timedelta(milliseconds=effective_grid_ms)
    populated = matched + temp_only + electrical_only
    return {
        "points": points,
        "metrics": _metrics(matched, temp_only, electrical_only, offsets, len(points), populated),
        "grid_ms": grid_ms,
        "effective_grid_ms": effective_grid_ms,
        "tolerance_ms": tolerance_ms,
        "source_counts": {"temperature": len(temperatures), "electrical": len(electrical)},
    }


def _metrics(
    matched: int,
    temp_only: int,
    electrical_only: int,
    offsets: list[float],
    total: int = 0,
    populated: int = 0,
) -> dict:
    return {
        "matched_points": matched,
        "temperature_only_points": temp_only,
        "electrical_only_points": electrical_only,
        "empty_points": max(total - populated, 0),
        "match_rate": matched / populated if populated else 0,
        "average_pair_offset_ms": sum(offsets) / len(offsets) if offsets else None,
        "maximum_pair_offset_ms": max(offsets) if offsets else None,
    }
