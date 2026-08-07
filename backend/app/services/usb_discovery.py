from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import serial
from serial.tools import list_ports
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Device
from app.services.virtual_usb_lab import virtual_usb_lab_service


class PortDiscoveryProvider(ABC):
    @abstractmethod
    def list_ports(self) -> Iterable[Any]: ...


class WindowsSerialPortDiscoveryProvider(PortDiscoveryProvider):
    def list_ports(self) -> Iterable[Any]:
        return list_ports.comports()


class VirtualUsbDiscoveryProvider(PortDiscoveryProvider):
    def list_ports(self) -> Iterable[Any]:
        return virtual_usb_lab_service.list_ports()


class TestPortDiscoveryProvider(PortDiscoveryProvider):
    __test__ = False

    def __init__(self, ports: Iterable[Any] = ()) -> None:
        self.ports = list(ports)

    def list_ports(self) -> Iterable[Any]:
        return list(self.ports)


class UsbDeviceDiscoveryService:
    """Reads OS or explicitly virtual USB/COM metadata without protocol commands."""

    def __init__(
        self,
        port_provider: Callable[[], Iterable[Any]] | PortDiscoveryProvider | None = None,
        serial_factory: Callable[..., Any] | None = None,
    ) -> None:
        provider = port_provider or WindowsSerialPortDiscoveryProvider()
        self.port_provider = (
            provider.list_ports if isinstance(provider, PortDiscoveryProvider) else provider
        )
        self.serial_factory = serial_factory or serial.Serial
        self._seen: dict[tuple[str, str], datetime] = {}
        self._status_cache: dict[str, tuple[float, tuple[str, str]]] = {}

    def discover(self, db: Session, busy_ports: set[str] | None = None) -> list[dict[str, Any]]:
        busy_ports = {port.casefold() for port in (busy_ports or set())}
        devices = list(
            db.scalars(select(Device).where(Device.active.is_(True)).order_by(Device.id))
        )
        discovered: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        for item in self.port_provider():
            port = str(getattr(item, "device", "") or "")
            source = str(
                getattr(item, "source", "virtual" if getattr(item, "profile", None) else "real")
            )
            simulated = source == "virtual"
            vid = getattr(item, "vid", None)
            pid = getattr(item, "pid", None)
            serial_number = getattr(item, "serial_number", None)
            associations = self._associations(devices, port, serial_number, vid, pid)
            status, status_message = self._port_status(port, busy_ports, item)
            suggestion = self._suggestion(item)
            seen_key = (source, port.casefold())
            first_seen = getattr(item, "first_seen_at", None) or self._seen.setdefault(
                seen_key, now
            )
            last_seen = getattr(item, "last_seen_at", None) or now
            discovered.append(
                {
                    "source": source,
                    "simulated": simulated,
                    "port": port,
                    "description": getattr(item, "description", None),
                    "manufacturer": getattr(item, "manufacturer", None),
                    "product": getattr(item, "product", None),
                    "serial_number": serial_number,
                    "vid": vid,
                    "pid": pid,
                    "hardware_id": getattr(item, "hwid", None),
                    "location": getattr(item, "location", None),
                    "association": associations[0] if len(associations) == 1 else None,
                    "association_candidates": associations,
                    "association_status": (
                        "associated"
                        if len(associations) == 1
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
                    "driver_status": (
                        "missing"
                        if getattr(item, "driver_missing", False)
                        else "simulated"
                        if simulated
                        else "installed"
                        if port
                        else "missing_or_unavailable"
                    ),
                    "driver_message": (
                        "Dispositivo fornecido pelo Laboratório Virtual."
                        if simulated
                        else "Porta enumerada pelo sistema operacional."
                        if port
                        else "O sistema não forneceu uma porta utilizável; verifique o driver."
                    ),
                    "first_seen_at": first_seen,
                    "last_seen_at": last_seen,
                    "validation_states": self._validation_states(
                        simulated, bool(associations), suggestion["status"], status
                    ),
                }
            )
        return sorted(discovered, key=lambda row: (row["source"], row["port"]))

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
        source = "virtual" if getattr(match, "profile", None) else "real"
        metadata = dict(device.metadata_json or {})
        usb_metadata = {
            "source": source,
            "simulated": source == "virtual",
            "serial_number": getattr(match, "serial_number", None),
            "vid": getattr(match, "vid", None),
            "pid": getattr(match, "pid", None),
            "hardware_id": getattr(match, "hwid", None),
            "location": getattr(match, "location", None),
        }
        metadata["usb"] = {key: value for key, value in usb_metadata.items() if value is not None}
        device.port = port
        device.connection_type = "serial"
        device.metadata_json = metadata
        db.commit()
        db.refresh(device)
        return {
            "device_id": device.id,
            "device_name": device.name,
            "port": device.port,
            "metadata": device.metadata_json,
            "message": (
                "Porta virtual associada; o resultado continua sendo somente simulado."
                if source == "virtual"
                else "Porta associada. A integração física continua pendente de validação."
            ),
        }

    @staticmethod
    def _associations(
        devices: list[Device],
        port: str,
        serial_number: str | None,
        vid: int | None,
        pid: int | None,
    ) -> list[dict[str, Any]]:
        matches: list[tuple[int, Device, str]] = []
        for device in devices:
            usb = (device.metadata_json or {}).get("usb", {})
            if serial_number and (
                device.serial_number == serial_number or usb.get("serial_number") == serial_number
            ):
                matches.append((3, device, "serial_number"))
            elif (
                vid is not None
                and pid is not None
                and usb.get("vid") == vid
                and usb.get("pid") == pid
            ):
                matches.append((2, device, "vid_pid"))
            elif port and device.port and device.port.casefold() == port.casefold():
                matches.append((1, device, "port"))
        if not matches:
            return []
        highest = max(priority for priority, _, _ in matches)
        return [
            {"device_id": device.id, "device_name": device.name, "matched_by": matched_by}
            for priority, device, matched_by in matches
            if priority == highest
        ]

    def _port_status(
        self, port: str, busy_ports: set[str], item: Any | None = None
    ) -> tuple[str, str]:
        if getattr(item, "driver_missing", False):
            return "driver_missing", "Driver indisponível no cenário virtual."
        if getattr(item, "busy", False):
            return "port_busy", "Porta ocupada no cenário virtual."
        if getattr(item, "profile", None):
            return "available", "Porta virtual disponível para o teste de software."
        if not port:
            return "driver_missing", "A porta não foi enumerada corretamente."
        if port.casefold() in busy_ports:
            return "port_busy", "Porta em uso por uma aquisição ativa do ThermoPower."
        cached = self._status_cache.get(port.casefold())
        if cached and monotonic() - cached[0] < 3:
            return cached[1]
        connection = None
        try:
            connection = self.serial_factory(port=port, timeout=0, write_timeout=0)
            result = ("available", "Porta aberta e fechada sem envio de comandos.")
            self._status_cache[port.casefold()] = (monotonic(), result)
            return result
        except (serial.SerialException, PermissionError, OSError) as exc:
            message = str(exc).lower()
            busy_tokens = ("access", "permission", "denied", "busy", "used")
            if any(token in message for token in busy_tokens):
                result = ("port_busy", "A porta parece estar em uso por outro processo.")
            else:
                result = (
                    "unavailable",
                    "Não foi possível abrir a porta; verifique driver e conexão.",
                )
            self._status_cache[port.casefold()] = (monotonic(), result)
            return result
        finally:
            if connection is not None and getattr(connection, "is_open", False):
                connection.close()

    @staticmethod
    def _validation_states(
        simulated: bool, associated: bool, suggestion: str, status: str
    ) -> dict[str, bool]:
        return {
            "simulated": simulated,
            "operating_system_detected": not simulated,
            "serial_port_available": status == "available",
            "associated": associated,
            "suggested": suggestion != "unknown",
            "identity_confirmed": False,
            "protocol_validated": False,
            "acquisition_validated": False,
            "homologated": False,
        }

    @staticmethod
    def _suggestion(item: Any) -> dict[str, str | None]:
        profile = getattr(item, "profile", None)
        text = " ".join(
            str(value or "")
            for value in (
                getattr(item, "description", None),
                getattr(item, "manufacturer", None),
                getattr(item, "product", None),
            )
        ).casefold()
        if profile == "at4532" or "at4532" in text or "at-4532" in text:
            return {
                "device": "Virtual Applent AT4532" if profile else "Possível Applent AT4532",
                "protocol": "virtual_at4532" if profile else "at4532_serial",
                "status": "simulated" if profile else "possible_at4532",
                "confidence": "high" if profile else "medium",
            }
        if profile == "gpm8213" or "gpm-8213" in text or "gpm8213" in text:
            return {
                "device": (
                    "Virtual GW Instek GPM-8213"
                    if profile
                    else "Possível GW Instek GPM-8213"
                ),
                "protocol": "virtual_gpm8213" if profile else "gpm8213_serial",
                "status": "simulated" if profile else "possible_gpm8213",
                "confidence": "high" if profile else "medium",
            }
        return {"device": None, "protocol": None, "status": "unknown", "confidence": "low"}


usb_discovery_service = UsbDeviceDiscoveryService()
virtual_usb_discovery_service = UsbDeviceDiscoveryService(VirtualUsbDiscoveryProvider())
