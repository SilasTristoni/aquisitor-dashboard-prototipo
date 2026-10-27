"""Record confirmed GPM availability without driving serial communication."""

import asyncio
import logging
import math
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Device, MeasurementSession, SessionDevice, SourceAvailability
from app.services.pending_persistence import bounded_pending_writes, sample_write_session
from app.services.session_clock import utc

logger = logging.getLogger(__name__)
PHYSICAL_LOSS = {"port_not_found", "driver_unavailable", "serial_error", "port_not_open"}


def confirmed_loss(snapshot):
    if snapshot.get("explicit_disconnect"):
        return "explicit_disconnect"
    if snapshot.get("state") == "recovering" and snapshot.get("cause") in PHYSICAL_LOSS:
        return snapshot["cause"]
    return None


def interval_dict(row):
    return {
        "start": utc(row.started_at).isoformat(),
        "confirmed_until": utc(row.confirmed_until).isoformat(),
        "end": utc(row.ended_at).isoformat() if row.ended_at else None,
        "end_reason": row.end_reason,
        "source": "electrical",
        "evidence": "backend_observed_v1",
    }


class AvailabilityObserver:
    def __init__(self, factory=SessionLocal):
        self.factory = factory
        self.owned = set()

    def tick(self, snapshots, now):
        """A snapshot is memory-only; storage faults cannot trigger physical recovery."""
        owned = set(self.owned)
        with bounded_pending_writes(), sample_write_session(self.factory) as db:
            active = list(
                db.execute(
                    select(MeasurementSession, SessionDevice.device_id)
                    .join(SessionDevice, SessionDevice.session_id == MeasurementSession.id)
                    .join(Device, Device.id == SessionDevice.device_id)
                    .where(
                        MeasurementSession.status.in_(["running", "paused"]),
                        Device.protocol == "gpm8213_serial",
                    )
                )
            )
            open_rows = list(
                db.scalars(select(SourceAvailability).where(SourceAvailability.ended_at.is_(None)))
            )
            by_key = {(row.session_id, row.device_id): row for row in open_rows}
            active_keys = {(session.id, device) for session, device in active}
            for row in open_rows:
                key = (row.session_id, row.device_id)
                if (
                    row.id not in owned
                    or key not in active_keys
                    or (now - utc(row.confirmed_until)).total_seconds() > 2
                ):
                    row.ended_at = row.confirmed_until
                    row.end_reason = "observation_ended"
                    by_key.pop(key, None)
                    owned.discard(row.id)
            for session, device in active:
                snapshot = snapshots.get(device, {})
                if snapshot.get("session_id") not in {None, session.id}:
                    snapshot = {}
                key = (session.id, device)
                row = by_key.get(key)
                paused = session.status == "paused" or snapshot.get("paused", False)
                cause = None if paused else confirmed_loss(snapshot)
                if row and paused:
                    row.ended_at, row.end_reason = row.confirmed_until, "paused"
                    owned.discard(row.id)
                elif row and snapshot.get("state") == "connected":
                    readings = [
                        at
                        for at, power in snapshot.get("readings", [])
                        if power is not None
                        and math.isfinite(power)
                        and utc(at) > utc(row.started_at)
                    ]
                    if readings:
                        row.ended_at = min(readings)
                        row.confirmed_until = row.ended_at
                        row.end_reason = "reading_resumed"
                        owned.discard(row.id)
                    # No fresh physical measurement: do not extend the zero reference.
                elif cause:
                    if row:
                        row.confirmed_until = now
                    else:
                        row = SourceAvailability(
                            session_id=session.id,
                            device_id=device,
                            started_at=now,
                            confirmed_until=now,
                            cause=cause,
                        )
                        db.add(row)
                        db.flush()
                        owned.add(row.id)
            db.commit()
        self.owned = owned


def runtime_snapshots(service):
    snapshots = {}
    for device, runtime in list(service.runtimes.items()):
        if runtime.protocol != "gpm8213_serial":
            continue
        snapshots[device] = {
            "session_id": runtime.session_id,
            "paused": runtime.paused,
            "state": getattr(runtime.adapter, "connection_state", None),
            "cause": getattr(runtime.adapter, "recovery_status", {}).get("cause"),
            "readings": [
                (reading.received_timestamp, reading.power_w)
                for reading in list(runtime.observed_readings)
            ],
        }
    for device, result in list(service.last_connection_results.items()):
        if device not in snapshots and result.get("status") == "disconnected":
            snapshots[device] = {"explicit_disconnect": True}
    return snapshots


@asynccontextmanager
async def observe_source_availability(service):
    observer = AvailabilityObserver()

    async def run():
        while True:
            await asyncio.sleep(0.5)
            try:
                snapshots = runtime_snapshots(service)
                if not snapshots and not observer.owned:
                    # An idle application must not create a worker/DB connection or
                    # contend with sample persistence. Unclosed historical evidence
                    # already stops at confirmed_until; no extrapolation is allowed.
                    continue
                write = asyncio.create_task(
                    asyncio.to_thread(observer.tick, snapshots, datetime.now(UTC))
                )
                try:
                    await asyncio.shield(write)
                except asyncio.CancelledError:
                    with suppress(Exception):
                        await write
                    raise
            except Exception:
                observer.owned.clear()
                logger.exception("Availability observation failed; no interval inferred")

    task = asyncio.create_task(run(), name="source-availability-observer")
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def collect_availability(db, session_ids, start, end):
    rows = db.scalars(
        select(SourceAvailability)
        .where(
            SourceAvailability.session_id.in_(session_ids),
            SourceAvailability.started_at <= end,
            SourceAvailability.confirmed_until >= start,
        )
        .order_by(SourceAvailability.started_at, SourceAvailability.id)
    )
    result = []
    for row in rows:
        item = interval_dict(row)
        item["start"] = max(start, utc(row.started_at)).isoformat()
        item["confirmed_until"] = min(end, utc(row.confirmed_until)).isoformat()
        if row.ended_at and utc(row.ended_at) > end:
            item["end"], item["end_reason"] = None, None
        result.append({"session_id": row.session_id, **item})
    return result


def visual_segments(intervals, points, start, end):
    """Presentation coordinates, never returned as electrical samples."""
    points = sorted(
        (
            p
            for p in points
            if p.get("active_power_w") is not None and math.isfinite(p["active_power_w"])
        ),
        key=lambda p: p["timestamp"],
    )
    result = []
    for interval in intervals:
        if interval.get("evidence") != "backend_observed_v1":
            continue
        left = utc(datetime.fromisoformat(interval["start"]))
        right = utc(datetime.fromisoformat(interval["end"] or interval["confirmed_until"]))
        right = min(right, utc(datetime.fromisoformat(interval["confirmed_until"])))
        if right < left or left > end or right < start:
            continue
        before = next((p for p in reversed(points) if utc(p["timestamp"]) <= left), None)
        after = next((p for p in points if utc(p["timestamp"]) == right), None)
        segment = [(max(left, start), 0), (min(right, end), 0)]
        if before and start <= utc(before["timestamp"]) and left >= start:
            segment.insert(0, (utc(before["timestamp"]), before["active_power_w"]))
        if after and interval["end_reason"] == "reading_resumed" and right <= end:
            segment.append((right, after["active_power_w"]))
        result.append(segment)
    return result
