from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.models.entities import Device


@dataclass(frozen=True)
class At4532IdentityFallbackPolicy:
    allowed: bool
    association_source: str | None
    reason: str

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


def at4532_identity_fallback_policy(device: Device) -> At4532IdentityFallbackPolicy:
    """Authorize measurement verification only for the exact persisted manual association."""
    if device.protocol != "at4532_serial" or device.model != "AT4532":
        return At4532IdentityFallbackPolicy(False, None, "not_at4532")
    usb = (device.metadata_json or {}).get("usb", {})
    serial = (device.metadata_json or {}).get("serial", {})
    port = str(device.port or "")
    confirmed_port = str(usb.get("confirmed_port") or "")
    manual_match = (
        usb.get("manual_confirmed") is True
        and bool(port)
        and port.casefold() == confirmed_port.casefold()
    )
    serial_confirmed = (
        device.baud_rate == 19200
        and serial.get("data_bits") == 8
        and serial.get("parity") == "N"
        and serial.get("stop_bits") == 1
    )
    if not manual_match:
        return At4532IdentityFallbackPolicy(False, None, "manual_port_not_confirmed")
    if not serial_confirmed:
        return At4532IdentityFallbackPolicy(False, "manual_port", "serial_parameters_mismatch")
    return At4532IdentityFallbackPolicy(
        True,
        "manual_port",
        "manual_association_and_vendor_documented_serial_parameters",
    )
