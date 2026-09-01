from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from app.core.config import get_settings
from app.models.entities import Device

AT4532_ENGINEERING_ENVIRONMENTS = frozenset({"development", "test", "physical-alpha"})
AT4532_PENDING_PROTOCOL_STATUS = "vendor_documented_physical_validation_pending"


def at4532_association_fingerprint(device: Device) -> dict[str, Any]:
    """Return the exact persisted association and serial settings authorized for measurement."""

    metadata = device.metadata_json or {}
    usb = metadata.get("usb", {})
    serial = metadata.get("serial", {})
    return {
        "port": device.port,
        "confirmed_port": usb.get("confirmed_port"),
        "manual_confirmed": usb.get("manual_confirmed") is True,
        "baud_rate": device.baud_rate,
        "data_bits": serial.get("data_bits"),
        "parity": serial.get("parity"),
        "stop_bits": serial.get("stop_bits"),
        "usb_serial_number": usb.get("serial_number"),
        "vid": usb.get("vid"),
        "pid": usb.get("pid"),
        "hardware_id": usb.get("hardware_id"),
        "location": usb.get("location"),
    }


def at4532_has_current_measurement_verification(device: Device) -> bool:
    metadata = device.metadata_json or {}
    verification = metadata.get("protocol_verification") or {}
    return (
        metadata.get("protocol_status") == "verified_by_measurement"
        and verification.get("association") == at4532_association_fingerprint(device)
    )


def mark_at4532_verified_by_measurement(device: Device, verified_at: datetime | str) -> None:
    timestamp = verified_at.isoformat() if isinstance(verified_at, datetime) else verified_at
    metadata = dict(device.metadata_json or {})
    metadata["protocol_status"] = "verified_by_measurement"
    metadata["protocol_verified_at"] = timestamp
    metadata["protocol_verification"] = {
        "verified_at": timestamp,
        "association": at4532_association_fingerprint(device),
    }
    device.metadata_json = metadata


def invalidate_stale_at4532_verification(device: Device) -> bool:
    """Clear a measurement authorization when its exact association no longer matches."""

    metadata = dict(device.metadata_json or {})
    if metadata.get("protocol_status") != "verified_by_measurement":
        return False
    if at4532_has_current_measurement_verification(device):
        return False
    metadata["protocol_status"] = AT4532_PENDING_PROTOCOL_STATUS
    metadata.pop("protocol_verified_at", None)
    metadata.pop("protocol_verification", None)
    device.metadata_json = metadata
    return True


@dataclass(frozen=True)
class At4532IdentityFallbackPolicy:
    allowed: bool
    association_source: str | None
    reason: str
    execution_environment: str | None = None
    previously_verified_by_measurement: bool = False

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


def at4532_identity_fallback_policy(
    device: Device, *, environment: str | None = None
) -> At4532IdentityFallbackPolicy:
    """Authorize measurement verification only for the exact persisted manual association."""
    execution_environment = (environment or get_settings().environment).strip().casefold()
    if device.protocol != "at4532_serial" or device.model != "AT4532":
        return At4532IdentityFallbackPolicy(
            False,
            None,
            "not_at4532",
            execution_environment=execution_environment,
        )
    metadata = device.metadata_json or {}
    usb = metadata.get("usb", {})
    serial = metadata.get("serial", {})
    previously_verified = at4532_has_current_measurement_verification(device)
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
        return At4532IdentityFallbackPolicy(
            False,
            None,
            "manual_port_not_confirmed",
            execution_environment=execution_environment,
            previously_verified_by_measurement=previously_verified,
        )
    if not serial_confirmed:
        return At4532IdentityFallbackPolicy(
            False,
            "manual_port",
            "serial_parameters_mismatch",
            execution_environment=execution_environment,
            previously_verified_by_measurement=previously_verified,
        )
    if execution_environment not in AT4532_ENGINEERING_ENVIRONMENTS and not previously_verified:
        return At4532IdentityFallbackPolicy(
            False,
            "manual_port",
            "engineering_context_or_measurement_verification_required",
            execution_environment=execution_environment,
            previously_verified_by_measurement=False,
        )
    return At4532IdentityFallbackPolicy(
        True,
        "manual_port",
        (
            "previously_verified_by_measurement"
            if previously_verified
            else "engineering_context_manual_association_and_serial_parameters"
        ),
        execution_environment=execution_environment,
        previously_verified_by_measurement=previously_verified,
    )
