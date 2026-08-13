from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

import serial
from serial.tools import list_ports
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Device

logger = logging.getLogger(__name__)


class UsbDeviceDiscoveryService:
    """Reads operating-system USB/COM metadata without sending protocol commands."""

    def __init__(
        self,
        port_provider: Callable[[], Iterable[Any]] | None = None,
        serial_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.port_provider = port_provider or list_ports.comports
        self.serial_factory = serial_factory or serial.Serial

    def discover(self, db: Session, busy_ports: set[str] | None = None) -> list[dict[str, Any]]:
        busy_ports = {port.casefold() for port in (busy_ports or set())}
        devices = list(
            db.scalars(select(Device).where(Device.active.is_(True)).order_by(Device.id))
        )
        discovered = []
        for item in self.port_provider():
            port = str(getattr(item, "device", "") or "")
            vid = getattr(item, "vid", None)
            pid = getattr(item, "pid", None)
            serial_number = getattr(item, "serial_number", None)
            hardware_id = getattr(item, "hwid", None)
            location = getattr(item, "location", None)
            associations = self._associations(
                devices, port, serial_number, vid, pid, hardware_id, location
            )
            confirmed = [
                match for match in associations if match["matched_by"] != "vid_pid_candidate"
            ]
            status, status_message = self._port_status(port, busy_ports)
            suggestion = self._suggestion(item)
            discovered.append(
                {
                    "port": port,
                    "description": getattr(item, "description", None),
                    "manufacturer": getattr(item, "manufacturer", None),
                    "product": getattr(item, "product", None),
                    "serial_number": serial_number,
                    "vid": vid,
                    "pid": pid,
                    "hardware_id": hardware_id,
                    "location": location,
                    "association": confirmed[0] if len(confirmed) == 1 else None,
                    "association_candidates": associations,
                    "association_status": (
                        "associated"
                        if len(confirmed) == 1
                        else "ambiguous"
                        if associations
                        else "unassociated"
                    ),
                    "status": status,
                    "status_message": status_message,
                    "suggested_device": suggestion["device"],
                    "suggested_protocol": suggestion["protocol"],
                    "identification_status": suggestion["status"],
                    "confidence": suggestion["confidence"],
                    "driver_status": "installed" if port else "missing_or_unavailable",
                    "driver_message": (
                        "Porta enumerada pelo sistema operacional."
                        if port
                        else "O sistema não forneceu uma porta utilizável; verifique o driver."
                    ),
                }
            )
        claims: dict[int, list[dict[str, Any]]] = {}
        for item in discovered:
            if item["association"]:
                claims.setdefault(item["association"]["device_id"], []).append(item)
        for items in claims.values():
            if len(items) <= 1:
                continue
            for item in items:
                item["association"] = None
                item["association_status"] = "ambiguous"
                item["status_message"] = (
                    "Identidade ambígua: mais de uma porta corresponde ao equipamento."
                )
        changed = False
        for item in discovered:
            association = item["association"]
            if not association or association["matched_by"] != "serial_number":
                continue
            device = next(device for device in devices if device.id == association["device_id"])
            if device.port != item["port"]:
                logger.info(
                    "usb serial reassociated device_id=%s old_port=%s new_port=%s",
                    device.id,
                    device.port,
                    item["port"],
                )
                device.port = item["port"]
                changed = True
        if changed:
            db.commit()
        logger.info("device discovery completed ports=%s", len(discovered))
        return sorted(discovered, key=lambda item: item["port"])

    def associate(self, db: Session, port: str, device_id: int) -> dict[str, Any]:
        device = db.get(Device, device_id)
        if not device:
            raise ValueError("Equipamento não encontrado")
        match = next(
            (item for item in self.port_provider() if str(getattr(item, "device", "")) == port),
            None,
        )
        if match is None:
            raise ValueError("A porta informada não está disponível na descoberta atual")
        occupied = db.scalar(
            select(Device).where(
                Device.active.is_(True), Device.port == port, Device.id != device_id
            )
        )
        if occupied:
            raise ValueError(f"A porta já está associada a {occupied.name}")
        metadata = dict(device.metadata_json or {})
        usb_metadata = {
            "serial_number": getattr(match, "serial_number", None),
            "vid": getattr(match, "vid", None),
            "pid": getattr(match, "pid", None),
            "hardware_id": getattr(match, "hwid", None),
            "location": getattr(match, "location", None),
            "manual_confirmed": True,
            "confirmed_port": port,
            "confirmed_at": datetime.now(UTC).isoformat(),
        }
        metadata["usb"] = {key: value for key, value in usb_metadata.items() if value is not None}
        device.port = port
        device.connection_type = "serial"
        device.metadata_json = metadata
        db.commit()
        db.refresh(device)
        logger.info("usb association confirmed device_id=%s port=%s", device.id, port)
        return {
            "device_id": device.id,
            "device_name": device.name,
            "port": device.port,
            "metadata": device.metadata_json,
            "message": "Associação manual confirmada. O protocolo físico continua pendente.",
        }

    @staticmethod
    def _associations(
        devices: list[Device],
        port: str,
        serial_number: str | None,
        vid: int | None,
        pid: int | None,
        hardware_id: str | None,
        location: str | None,
    ) -> list[dict[str, Any]]:
        matches: list[tuple[int, Device, str]] = []
        for device in devices:
            usb = (device.metadata_json or {}).get("usb", {})
            if serial_number and (
                device.serial_number == serial_number or usb.get("serial_number") == serial_number
            ):
                matches.append((5, device, "serial_number"))
            elif usb.get("manual_confirmed") and location and usb.get("location") == location:
                matches.append((4, device, "location"))
            elif (
                usb.get("manual_confirmed")
                and hardware_id
                and usb.get("hardware_id") == hardware_id
            ):
                matches.append((4, device, "hardware_path"))
            elif (
                usb.get("manual_confirmed")
                and port
                and str(usb.get("confirmed_port", "")).casefold() == port.casefold()
            ):
                matches.append((3, device, "manual_port"))
            elif (
                vid is not None
                and pid is not None
                and usb.get("vid") == vid
                and usb.get("pid") == pid
            ):
                matches.append((1, device, "vid_pid_candidate"))
        if not matches:
            return []
        highest = max(priority for priority, _, _ in matches)
        return [
            {"device_id": device.id, "device_name": device.name, "matched_by": matched_by}
            for priority, device, matched_by in matches
            if priority == highest
        ]

    def _port_status(self, port: str, busy_ports: set[str]) -> tuple[str, str]:
        if not port:
            return "driver_missing", "A porta não foi enumerada corretamente."
        if port.casefold() in busy_ports:
            return "port_busy", "Porta em uso por uma aquisição ativa do ThermoPower."
        connection = None
        try:
            connection = self.serial_factory(port=port, timeout=0, write_timeout=0)
            return "available", "Porta aberta e fechada sem envio de comandos."
        except (serial.SerialException, PermissionError, OSError) as exc:
            message = str(exc).lower()
            if any(
                token in message for token in ("access", "permission", "denied", "busy", "used")
            ):
                return (
                    "port_busy",
                    "Porta ocupada pelo software do fabricante. Feche-o antes de continuar.",
                )
            return "unavailable", "Não foi possível abrir a porta; verifique driver e conexão."
        finally:
            if connection is not None and getattr(connection, "is_open", False):
                connection.close()

    @staticmethod
    def _suggestion(item: Any) -> dict[str, str | None]:
        text = " ".join(
            str(value or "")
            for value in (
                getattr(item, "description", None),
                getattr(item, "manufacturer", None),
                getattr(item, "product", None),
            )
        ).casefold()
        vid = getattr(item, "vid", None)
        pid = getattr(item, "pid", None)
        serial_number = str(getattr(item, "serial_number", None) or "")
        if serial_number.casefold() == "ges913349":
            return {
                "device": "GW Instek GPM-8213 confirmado pelo serial USB",
                "protocol": "gpm8213_serial",
                "status": "confirmed_gpm8213",
                "confidence": "high",
            }
        if "at4532" in text or "at-4532" in text:
            return {
                "device": "Possível Applent AT4532",
                "protocol": "at4532_serial",
                "status": "possible_at4532",
                "confidence": "medium",
            }
        if vid == 0x1A86 and pid == 0x7523:
            return {
                "device": "Conversor CH340; AT4532 apenas como candidato",
                "protocol": "at4532_serial",
                "status": "possible_at4532",
                "confidence": "low",
            }
        if "gpm-8213" in text or "gpm8213" in text:
            return {
                "device": "Possível GW Instek GPM-8213",
                "protocol": "gpm8213_serial",
                "status": "possible_gpm8213",
                "confidence": "medium",
            }
        if vid == 0x2184 and pid == 0x0052:
            return {
                "device": "Possível GW Instek GPM-8213",
                "protocol": "gpm8213_serial",
                "status": "possible_gpm8213",
                "confidence": "medium",
            }
        return {
            "device": None,
            "protocol": None,
            "status": "unknown",
            "confidence": "low",
        }


usb_discovery_service = UsbDeviceDiscoveryService()
