"""Identity of an observation, without merging independently received equal values."""

import hashlib
import json

from app.adapters.base import DeviceReading


def reading_identity(reading: DeviceReading) -> str:
    raw = reading.raw_payload
    content = (
        raw.get("raw_hex")
        or raw.get("raw_bytes")
        or {
            "power": reading.power_w,
            "temperatures": reading.temperatures_c,
            "values": reading.raw_values,
        }
    )
    # AT: hardware time + exact frame. GPM: each actual received observation is new,
    # including constant power; equal values must never collapse its stream.
    timestamp = reading.device_timestamp or reading.received_timestamp
    return hashlib.sha256(
        json.dumps([timestamp.isoformat(), content], sort_keys=True, default=str).encode()
    ).hexdigest()
