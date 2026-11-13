"""Explicit acquisition boundaries on report copies, never synthetic measurements."""

from bisect import bisect_right
from collections import defaultdict

from sqlalchemy import select

from app.models.entities import SystemEvent
from app.services.session_clock import utc


def mark_recovery_epochs(db, session_ids, *streams):
    boundaries = defaultdict(list)
    for event in db.scalars(
        select(SystemEvent)
        .where(
            SystemEvent.session_id.in_(session_ids),
            SystemEvent.category.in_(["session_recovery_intent", "session_recovery_resume"]),
        )
        .order_by(SystemEvent.timestamp)
    ):
        # Decision time precedes attachment. First new physical reading starts a new epoch.
        resumed_at = (event.details or {}).get("resumed_at")
        if resumed_at:
            from datetime import datetime

            boundaries[event.session_id].append(utc(datetime.fromisoformat(resumed_at)))
    boundaries = {sid: sorted(set(values)) for sid, values in boundaries.items()}
    for stream in streams:
        for point in stream:
            if boundaries.get(point["session_id"]):
                point["acquisition_epoch"] = bisect_right(
                    boundaries[point["session_id"]],
                    point["timestamp"],
                )
