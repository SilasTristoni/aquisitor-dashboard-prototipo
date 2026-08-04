from __future__ import annotations

import math
import statistics
from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models.entities import (
    AlertEvent,
    Device,
    ElectricalSample,
    Measurement,
    MeasurementSession,
    SessionChannelConfiguration,
    SessionDevice,
    TemperatureSample,
    User,
)
from app.schemas.contracts import PeriodReportRequest

settings = get_settings()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _effective_timestamp(
    device_timestamp: datetime | None,
    received_timestamp: datetime,
    use_device_timestamp: bool,
) -> tuple[datetime, str]:
    if use_device_timestamp and device_timestamp is not None:
        return _utc(device_timestamp), "device"
    return _utc(received_timestamp), "received"


def _percentile(sorted_values: list[float], percentile: float) -> float | None:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (position - lower)


def _numeric_statistics(values: Iterable[float | None]) -> dict[str, float | int | None]:
    numbers = sorted(float(value) for value in values if value is not None and math.isfinite(value))
    if not numbers:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "standard_deviation": None,
            "p05": None,
            "p95": None,
        }
    return {
        "count": len(numbers),
        "min": numbers[0],
        "max": numbers[-1],
        "mean": statistics.fmean(numbers),
        "median": statistics.median(numbers),
        "standard_deviation": statistics.pstdev(numbers) if len(numbers) > 1 else 0.0,
        "p05": _percentile(numbers, 0.05),
        "p95": _percentile(numbers, 0.95),
    }


def _interval_quality(
    points: list[dict[str, Any]], max_energy_gap_seconds: float
) -> tuple[list[float], int, float]:
    ordered = sorted(points, key=lambda point: point["timestamp"])
    intervals = [
        (current["timestamp"] - previous["timestamp"]).total_seconds()
        for previous, current in zip(ordered, ordered[1:], strict=False)
        if current["timestamp"] > previous["timestamp"]
    ]
    if not intervals:
        return [], 0, 0.0
    median_interval = statistics.median(intervals)
    gap_threshold = min(max_energy_gap_seconds, max(1.0, median_interval * 5))
    gaps = [interval for interval in intervals if interval > gap_threshold]
    return intervals, len(gaps), sum(gaps)


def _integrate_energy_wh(
    points: list[dict[str, Any]], max_gap_seconds: float
) -> tuple[float, int, float]:
    ordered = sorted(
        (point for point in points if point.get("active_power_w") is not None),
        key=lambda point: point["timestamp"],
    )
    energy_wh = 0.0
    excluded_intervals = 0
    excluded_seconds = 0.0
    for previous, current in zip(ordered, ordered[1:], strict=False):
        interval = (current["timestamp"] - previous["timestamp"]).total_seconds()
        if interval <= 0:
            continue
        if interval > max_gap_seconds:
            excluded_intervals += 1
            excluded_seconds += interval
            continue
        average_power = (previous["active_power_w"] + current["active_power_w"]) / 2
        energy_wh += average_power * interval / 3600
    return energy_wh, excluded_intervals, excluded_seconds


def period_statistics(data: dict[str, Any]) -> dict[str, Any]:
    electrical = data["electrical"]
    temperatures = data["temperatures"]
    by_session_electrical: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_session_temperature: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for point in electrical:
        by_session_electrical[point["session_id"]].append(point)
    for point in temperatures:
        by_session_temperature[point["session_id"]].append(point)

    energy_wh = 0.0
    excluded_energy_intervals = 0
    excluded_energy_seconds = 0.0
    gaps = 0
    gap_seconds = 0.0
    observed_intervals: list[float] = []
    for points in [*by_session_electrical.values(), *by_session_temperature.values()]:
        intervals, stream_gaps, stream_gap_seconds = _interval_quality(
            points, settings.report_energy_max_gap_seconds
        )
        observed_intervals.extend(intervals)
        gaps += stream_gaps
        gap_seconds += stream_gap_seconds
    for points in by_session_electrical.values():
        session_energy, excluded, excluded_seconds = _integrate_energy_wh(
            points, settings.report_energy_max_gap_seconds
        )
        energy_wh += session_energy
        excluded_energy_intervals += excluded
        excluded_energy_seconds += excluded_seconds

    all_timestamps = [point["timestamp"] for point in electrical + temperatures]
    duration = (
        (max(all_timestamps) - min(all_timestamps)).total_seconds()
        if len(all_timestamps) > 1
        else 0.0
    )
    median_interval = statistics.median(observed_intervals) if observed_intervals else None
    channel_values: dict[int, list[float]] = defaultdict(list)
    channel_available: Counter[int] = Counter()
    channel_expected: Counter[int] = Counter()
    channel_names: dict[int, set[str]] = defaultdict(set)
    per_session_channels: dict[tuple[int, int], list[float]] = defaultdict(list)
    for point in temperatures:
        for channel in data["selected_channels"]:
            channel_expected[channel] += 1
            value = point["channels"].get(channel)
            if value is not None:
                channel_available[channel] += 1
                channel_values[channel].append(value)
                per_session_channels[(point["session_id"], channel)].append(value)
            name = point["channel_names"].get(channel)
            if name:
                channel_names[channel].add(name)

    channel_stats = []
    for channel in data["selected_channels"]:
        result = _numeric_statistics(channel_values[channel])
        result.update(
            {
                "channel": channel,
                "names": sorted(channel_names[channel]) or [f"Termopar {channel}"],
                "availability_percent": round(
                    100 * channel_available[channel] / channel_expected[channel], 2
                )
                if channel_expected[channel]
                else 0.0,
                "sessions": [
                    {
                        "session_id": session_id,
                        **_numeric_statistics(per_session_channels[(session_id, channel)]),
                    }
                    for session_id in sorted(
                        session_id
                        for session_id, candidate in per_session_channels
                        if candidate == channel
                    )
                ],
            }
        )
        channel_stats.append(result)

    return {
        "general": {
            "session_count": len(data["sessions"]),
            "electrical_sample_count": len(electrical),
            "temperature_sample_count": len(temperatures),
            "alert_count": len(data["alerts"]),
            "coverage_start": min(all_timestamps).isoformat() if all_timestamps else None,
            "coverage_end": max(all_timestamps).isoformat() if all_timestamps else None,
            "coverage_seconds": duration,
            "observed_frequency_hz": 1 / median_interval if median_interval else None,
            "gap_count": gaps,
            "gap_seconds": gap_seconds,
            "timestamp_fallback_count": data["timestamp_fallback_count"],
            "quality_counts": dict(
                Counter(point["quality"] for point in electrical + temperatures)
            ),
        },
        "electrical": {
            "active_power_w": _numeric_statistics(point["active_power_w"] for point in electrical),
            "voltage_v": _numeric_statistics(point["voltage_v"] for point in electrical),
            "current_a": _numeric_statistics(point["current_a"] for point in electrical),
            "apparent_power_va": _numeric_statistics(
                point["apparent_power_va"] for point in electrical
            ),
            "reactive_power_var": _numeric_statistics(
                point["reactive_power_var"] for point in electrical
            ),
            "power_factor": _numeric_statistics(point["power_factor"] for point in electrical),
            "voltage_frequency_hz": _numeric_statistics(
                point["voltage_frequency_hz"] for point in electrical
            ),
            "current_frequency_hz": _numeric_statistics(
                point["current_frequency_hz"] for point in electrical
            ),
            "energy_wh": energy_wh,
            "energy_gap_limit_seconds": settings.report_energy_max_gap_seconds,
            "excluded_energy_intervals": excluded_energy_intervals,
            "excluded_energy_seconds": excluded_energy_seconds,
        },
        "channels": channel_stats,
    }


def downsample_time_buckets(
    points: list[dict[str, Any]], value_keys: list[str], max_points: int
) -> list[dict[str, Any]]:
    """Reduce a single session/stream while retaining extrema and a bucket mean."""
    if len(points) <= max_points or max_points < 3:
        return points
    ordered = sorted(points, key=lambda point: point["timestamp"])
    start = ordered[0]["timestamp"].timestamp()
    end = ordered[-1]["timestamp"].timestamp()
    if end <= start:
        return ordered[:max_points]
    bucket_count = max(1, max_points // (2 * max(1, len(value_keys)) + 1))
    width = (end - start) / bucket_count
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for point in ordered:
        index = min(bucket_count - 1, int((point["timestamp"].timestamp() - start) / width))
        buckets[index].append(point)

    selected: dict[tuple[datetime, int], dict[str, Any]] = {}
    for bucket in buckets.values():
        for key in value_keys:
            candidates = [point for point in bucket if point.get(key) is not None]
            if candidates:
                for point in (
                    min(candidates, key=lambda item: item[key]),
                    max(candidates, key=lambda item: item[key]),
                ):
                    selected[(point["timestamp"], id(point))] = point
        means = {
            key: statistics.fmean(values)
            for key in value_keys
            if (values := [point[key] for point in bucket if point.get(key) is not None])
        }
        if means:
            representative = dict(bucket[len(bucket) // 2])
            representative.update(means)
            selected[(representative["timestamp"], id(representative))] = representative
    selected[(ordered[0]["timestamp"], id(ordered[0]))] = ordered[0]
    selected[(ordered[-1]["timestamp"], id(ordered[-1]))] = ordered[-1]
    result = sorted(selected.values(), key=lambda point: point["timestamp"])
    if len(result) <= max_points:
        return result
    protected = {0, len(result) - 1}
    for key in value_keys:
        candidates = [
            (index, point) for index, point in enumerate(result) if point.get(key) is not None
        ]
        if candidates:
            protected.add(min(candidates, key=lambda item: item[1][key])[0])
            protected.add(max(candidates, key=lambda item: item[1][key])[0])
    remaining = max_points - len(protected)
    if remaining > 0:
        candidates = [index for index in range(len(result)) if index not in protected]
        step = len(candidates) / remaining
        protected.update(
            candidates[min(len(candidates) - 1, int(i * step))] for i in range(remaining)
        )
    return [result[index] for index in sorted(protected)[:max_points]]


class PeriodReportDataService:
    def __init__(self, db: Session):
        self.db = db

    def collect(self, request: PeriodReportRequest) -> dict[str, Any]:
        if (request.end - request.start).total_seconds() > settings.max_report_period_days * 86400:
            raise ValueError(
                f"O período máximo permitido é de {settings.max_report_period_days} dias"
            )
        sessions = self._sessions(request)
        if not sessions:
            raise ValueError("Nenhuma sessão foi encontrada no período e filtros informados")
        session_ids = [session.id for session in sessions]
        device_ids_by_session = self._session_devices(session_ids, sessions)
        allowed_session_ids = {
            session_id
            for session_id, device_ids in device_ids_by_session.items()
            if not request.device_ids or set(device_ids) & set(request.device_ids)
        }
        sessions = [session for session in sessions if session.id in allowed_session_ids]
        if not sessions:
            raise ValueError("Nenhuma sessão corresponde aos equipamentos selecionados")
        session_ids = [session.id for session in sessions]
        snapshots = self._channel_snapshots(session_ids)
        selected_channels = request.channels or sorted(
            {channel for (_, channel), config in snapshots.items() if config.enabled}
        )
        if not selected_channels:
            selected_channels = list(range(1, 33))

        electrical, electrical_sessions = self._electrical(request, session_ids)
        temperatures, temperature_sessions = self._temperatures(
            request, session_ids, snapshots, selected_channels
        )
        electrical, temperatures = self._legacy_fallback(
            request,
            sessions,
            electrical,
            temperatures,
            electrical_sessions,
            temperature_sessions,
            snapshots,
            selected_channels,
        )
        selected_electrical = request.include_power or request.include_electrical_details
        if not (
            (selected_electrical and electrical) or (request.include_temperatures and temperatures)
        ):
            raise ValueError("Não existem medições no período e filtros informados")
        alerts = self._alerts(request, session_ids)
        fallback_count = sum(
            1 for point in electrical + temperatures if point["timestamp_source"] == "received"
        )
        session_rows = self._session_rows(sessions, device_ids_by_session, electrical, temperatures)
        data = {
            "request": request,
            "sessions": session_rows,
            "electrical": electrical,
            "temperatures": temperatures,
            "alerts": alerts,
            "selected_channels": selected_channels,
            "timestamp_fallback_count": fallback_count,
        }
        data["statistics"] = period_statistics(data)
        data["table_rows"] = self._table_rows(data, request.table_max_rows)
        return data

    def preview(self, request: PeriodReportRequest) -> dict[str, Any]:
        data = self.collect(request)
        session_count = max(1, len(data["sessions"]))
        per_stream_limit = max(50, settings.report_preview_max_points // session_count)
        series = []
        for session in data["sessions"]:
            session_id = session["id"]
            electrical = [
                point for point in data["electrical"] if point["session_id"] == session_id
            ]
            temperatures = [
                point for point in data["temperatures"] if point["session_id"] == session_id
            ]
            temperature_keys = [f"channel_{channel}" for channel in data["selected_channels"]]
            flat_temperatures = [
                {
                    **point,
                    **{
                        f"channel_{channel}": point["channels"].get(channel)
                        for channel in data["selected_channels"]
                    },
                }
                for point in temperatures
            ]
            series.append(
                {
                    "session_id": session_id,
                    "session_name": session["name"],
                    "electrical": self._serialize_points(
                        downsample_time_buckets(electrical, ["active_power_w"], per_stream_limit)
                    )
                    if request.include_power or request.include_electrical_details
                    else [],
                    "temperatures": self._serialize_points(
                        downsample_time_buckets(
                            flat_temperatures, temperature_keys, per_stream_limit
                        )
                    )
                    if request.include_temperatures
                    else [],
                }
            )
        return {
            "period": {
                "start": request.start.isoformat(),
                "end": request.end.isoformat(),
                "timezone": request.timezone,
            },
            "sessions": data["sessions"],
            "statistics": data["statistics"],
            "alerts": data["alerts"] if request.include_alerts else [],
            "selected_channels": data["selected_channels"],
            "series": series,
            "warnings": self._warnings(data),
        }

    def _sessions(self, request: PeriodReportRequest) -> list[MeasurementSession]:
        statement = (
            select(MeasurementSession)
            .where(
                MeasurementSession.started_at < request.end,
                or_(
                    MeasurementSession.ended_at.is_(None),
                    MeasurementSession.ended_at >= request.start,
                ),
            )
            .order_by(MeasurementSession.started_at, MeasurementSession.id)
        )
        if request.session_ids:
            statement = statement.where(MeasurementSession.id.in_(request.session_ids))
        return list(self.db.scalars(statement))

    def _session_devices(
        self, session_ids: list[int], sessions: list[MeasurementSession]
    ) -> dict[int, list[int]]:
        result: dict[int, list[int]] = defaultdict(list)
        for session_id, device_id in self.db.execute(
            select(SessionDevice.session_id, SessionDevice.device_id).where(
                SessionDevice.session_id.in_(session_ids)
            )
        ):
            result[session_id].append(device_id)
        for session in sessions:
            if not result[session.id]:
                result[session.id].append(session.device_id)
        return result

    def _channel_snapshots(
        self, session_ids: list[int]
    ) -> dict[tuple[int, int], SessionChannelConfiguration]:
        rows = self.db.scalars(
            select(SessionChannelConfiguration).where(
                SessionChannelConfiguration.session_id.in_(session_ids)
            )
        )
        return {(row.session_id, row.channel): row for row in rows}

    def _electrical(
        self, request: PeriodReportRequest, session_ids: list[int]
    ) -> tuple[list[dict[str, Any]], set[int]]:
        timestamp = (
            func.coalesce(ElectricalSample.device_timestamp, ElectricalSample.received_timestamp)
            if request.use_device_timestamp
            else ElectricalSample.received_timestamp
        )
        statement = select(ElectricalSample).where(
            ElectricalSample.session_id.in_(session_ids),
            timestamp >= request.start,
            timestamp <= request.end,
        )
        if request.device_ids:
            statement = statement.where(ElectricalSample.device_id.in_(request.device_ids))
        rows = list(self.db.scalars(statement.order_by(ElectricalSample.session_id, timestamp)))
        points = []
        for row in rows:
            effective, timestamp_source = _effective_timestamp(
                row.device_timestamp, row.received_timestamp, request.use_device_timestamp
            )
            points.append(
                {
                    "session_id": row.session_id,
                    "device_id": row.device_id,
                    "timestamp": effective,
                    "timestamp_source": timestamp_source,
                    "quality": row.quality,
                    "source": row.source,
                    "voltage_v": row.voltage_v,
                    "current_a": row.current_a,
                    "active_power_w": row.active_power_w,
                    "apparent_power_va": row.apparent_power_va,
                    "reactive_power_var": row.reactive_power_var,
                    "power_factor": row.power_factor,
                    "voltage_frequency_hz": row.voltage_frequency_hz,
                    "current_frequency_hz": row.current_frequency_hz,
                }
            )
        return points, {row.session_id for row in rows}

    def _temperatures(
        self,
        request: PeriodReportRequest,
        session_ids: list[int],
        snapshots: dict[tuple[int, int], SessionChannelConfiguration],
        selected_channels: list[int],
    ) -> tuple[list[dict[str, Any]], set[int]]:
        timestamp = (
            func.coalesce(TemperatureSample.device_timestamp, TemperatureSample.received_timestamp)
            if request.use_device_timestamp
            else TemperatureSample.received_timestamp
        )
        statement = (
            select(TemperatureSample)
            .options(selectinload(TemperatureSample.channels))
            .where(
                TemperatureSample.session_id.in_(session_ids),
                timestamp >= request.start,
                timestamp <= request.end,
            )
        )
        if request.device_ids:
            statement = statement.where(TemperatureSample.device_id.in_(request.device_ids))
        rows = list(self.db.scalars(statement.order_by(TemperatureSample.session_id, timestamp)))
        points = []
        for row in rows:
            effective, timestamp_source = _effective_timestamp(
                row.device_timestamp, row.received_timestamp, request.use_device_timestamp
            )
            values = {
                item.channel: item.temperature_c
                for item in row.channels
                if item.channel in selected_channels
            }
            points.append(
                {
                    "session_id": row.session_id,
                    "device_id": row.device_id,
                    "timestamp": effective,
                    "timestamp_source": timestamp_source,
                    "quality": row.quality,
                    "source": row.source,
                    "ambient_temperature_c": row.ambient_temperature_c,
                    "channels": values,
                    "channel_names": {
                        channel: snapshots[(row.session_id, channel)].name
                        if (row.session_id, channel) in snapshots
                        else f"Termopar {channel}"
                        for channel in selected_channels
                    },
                }
            )
        return points, {row.session_id for row in rows}

    def _legacy_fallback(
        self,
        request: PeriodReportRequest,
        sessions: list[MeasurementSession],
        electrical: list[dict[str, Any]],
        temperatures: list[dict[str, Any]],
        electrical_sessions: set[int],
        temperature_sessions: set[int],
        snapshots: dict[tuple[int, int], SessionChannelConfiguration],
        selected_channels: list[int],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        missing = {
            session.id
            for session in sessions
            if session.id not in electrical_sessions or session.id not in temperature_sessions
        }
        if not missing:
            return electrical, temperatures
        rows = list(
            self.db.scalars(
                select(Measurement)
                .options(selectinload(Measurement.temperatures))
                .where(
                    Measurement.session_id.in_(missing),
                    Measurement.timestamp >= request.start,
                    Measurement.timestamp <= request.end,
                )
                .order_by(Measurement.session_id, Measurement.timestamp)
            )
        )
        devices = {session.id: session.device_id for session in sessions}
        for row in rows:
            if request.device_ids and devices[row.session_id] not in request.device_ids:
                continue
            timestamp = _utc(row.timestamp)
            if row.session_id not in electrical_sessions:
                electrical.append(
                    {
                        "session_id": row.session_id,
                        "device_id": devices[row.session_id],
                        "timestamp": timestamp,
                        "timestamp_source": "legacy",
                        "quality": row.quality,
                        "source": "legacy",
                        "voltage_v": None,
                        "current_a": None,
                        "active_power_w": row.power_w,
                        "apparent_power_va": None,
                        "reactive_power_var": None,
                        "power_factor": None,
                        "voltage_frequency_hz": None,
                        "current_frequency_hz": None,
                    }
                )
            if row.session_id not in temperature_sessions and row.temperatures:
                values = {
                    item.channel: item.temperature_c
                    for item in row.temperatures
                    if item.channel in selected_channels
                }
                temperatures.append(
                    {
                        "session_id": row.session_id,
                        "device_id": devices[row.session_id],
                        "timestamp": timestamp,
                        "timestamp_source": "legacy",
                        "quality": row.quality,
                        "source": "legacy",
                        "ambient_temperature_c": None,
                        "channels": values,
                        "channel_names": {
                            channel: snapshots[(row.session_id, channel)].name
                            if (row.session_id, channel) in snapshots
                            else f"Termopar {channel}"
                            for channel in selected_channels
                        },
                    }
                )
        electrical.sort(key=lambda point: (point["session_id"], point["timestamp"]))
        temperatures.sort(key=lambda point: (point["session_id"], point["timestamp"]))
        return electrical, temperatures

    def _alerts(self, request: PeriodReportRequest, session_ids: list[int]) -> list[dict[str, Any]]:
        if not request.include_alerts:
            return []
        rows = self.db.scalars(
            select(AlertEvent)
            .where(
                AlertEvent.session_id.in_(session_ids),
                AlertEvent.timestamp >= request.start,
                AlertEvent.timestamp <= request.end,
            )
            .order_by(AlertEvent.timestamp)
        )
        return [
            {
                "id": row.id,
                "session_id": row.session_id,
                "timestamp": _utc(row.timestamp).isoformat(),
                "metric": row.metric,
                "channel": row.channel,
                "measured_value": row.measured_value,
                "threshold": row.threshold,
                "severity": row.severity,
                "acknowledged": row.acknowledged,
            }
            for row in rows
        ]

    def _session_rows(
        self,
        sessions: list[MeasurementSession],
        device_ids_by_session: dict[int, list[int]],
        electrical: list[dict[str, Any]],
        temperatures: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        device_ids = sorted({item for values in device_ids_by_session.values() for item in values})
        devices = {
            row.id: row for row in self.db.scalars(select(Device).where(Device.id.in_(device_ids)))
        }
        user_ids = sorted({session.user_id for session in sessions})
        users = {row.id: row for row in self.db.scalars(select(User).where(User.id.in_(user_ids)))}
        electrical_counts = Counter(point["session_id"] for point in electrical)
        temperature_counts = Counter(point["session_id"] for point in temperatures)
        return [
            {
                "id": session.id,
                "name": session.name,
                "started_at": _utc(session.started_at).isoformat(),
                "ended_at": _utc(session.ended_at).isoformat() if session.ended_at else None,
                "status": session.status,
                "operator": users[session.user_id].name if session.user_id in users else None,
                "devices": [
                    {
                        "id": device_id,
                        "name": devices[device_id].name
                        if device_id in devices
                        else f"#{device_id}",
                    }
                    for device_id in device_ids_by_session[session.id]
                ],
                "electrical_samples": electrical_counts[session.id],
                "temperature_samples": temperature_counts[session.id],
            }
            for session in sessions
        ]

    def _table_rows(self, data: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        rows: list[dict[str, Any]] = []
        tolerance = data["request"].sync_tolerance_ms / 1000
        for session in data["sessions"]:
            session_id = session["id"]
            electrical = sorted(
                (point for point in data["electrical"] if point["session_id"] == session_id),
                key=lambda point: point["timestamp"],
            )
            temperatures = sorted(
                (point for point in data["temperatures"] if point["session_id"] == session_id),
                key=lambda point: point["timestamp"],
            )
            electric_times = [point["timestamp"] for point in electrical]
            if temperatures:
                for temperature in temperatures:
                    nearest = None
                    index = bisect_left(electric_times, temperature["timestamp"])
                    candidates = electrical[max(0, index - 1) : index + 1]
                    if candidates:
                        candidate = min(
                            candidates,
                            key=lambda point: abs(
                                (point["timestamp"] - temperature["timestamp"]).total_seconds()
                            ),
                        )
                        if (
                            abs((candidate["timestamp"] - temperature["timestamp"]).total_seconds())
                            <= tolerance
                        ):
                            nearest = candidate
                    rows.append(
                        {
                            "session_id": session_id,
                            "timestamp": temperature["timestamp"].isoformat(),
                            "active_power_w": nearest["active_power_w"] if nearest else None,
                            "voltage_v": nearest["voltage_v"] if nearest else None,
                            "current_a": nearest["current_a"] if nearest else None,
                            "channels": temperature["channels"],
                        }
                    )
            else:
                rows.extend(
                    {
                        "session_id": session_id,
                        "timestamp": point["timestamp"].isoformat(),
                        "active_power_w": point["active_power_w"],
                        "voltage_v": point["voltage_v"],
                        "current_a": point["current_a"],
                        "channels": {},
                    }
                    for point in electrical
                )
        if len(rows) <= limit:
            return rows
        stride = len(rows) / limit
        return [rows[min(len(rows) - 1, int(index * stride))] for index in range(limit)]

    @staticmethod
    def _serialize_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in point.items()
                if key not in {"channel_names"}
            }
            for point in points
        ]

    @staticmethod
    def _warnings(data: dict[str, Any]) -> list[str]:
        warnings = []
        general = data["statistics"]["general"]
        electrical = data["statistics"]["electrical"]
        if general["timestamp_fallback_count"]:
            warnings.append(
                f"{general['timestamp_fallback_count']} amostras usaram o timestamp de recepção."
            )
        if general["gap_count"]:
            warnings.append(f"Foram detectadas {general['gap_count']} lacunas de aquisição.")
        if electrical["excluded_energy_intervals"]:
            warnings.append(
                "A integração de energia excluiu intervalos maiores que o limite de qualidade."
            )
        if len(data["sessions"]) > 1:
            warnings.append("As sessões são apresentadas como segmentos independentes.")
        return warnings
