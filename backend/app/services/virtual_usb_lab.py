from __future__ import annotations

import asyncio
import math
import random
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any, Literal

from app.adapters.base import DeviceAdapter, DeviceInformation, DeviceReading, DeviceStatus


@dataclass
class VirtualPort:
    profile: Literal["at4532", "gpm8213"]
    port: str
    description: str
    manufacturer: str
    product: str
    serial_number: str | None
    vid: int | None
    pid: int | None
    hwid: str
    location: str | None
    busy: bool = False
    driver_missing: bool = False
    connected: bool = True
    options: dict[str, Any] = field(default_factory=dict)
    first_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def device(self) -> str:
        return self.port

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source"] = "virtual"
        data["simulated"] = True
        data["hardware_id"] = data.pop("hwid")
        data["first_seen_at"] = self.first_seen_at.isoformat()
        data["last_seen_at"] = self.last_seen_at.isoformat()
        return data


PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "at4532": {
        "description": "Virtual Applent AT4532",
        "manufacturer": "Applent (simulado)",
        "product": "Virtual AT4532 - 32 termopares",
        "serial_number": "VLAB-AT4532-001",
        "vid": 0x1209,
        "pid": 0x4532,
        "hwid": "VIRTUAL\\VID_1209&PID_4532",
        "location": "Virtual USB Lab / slot A",
    },
    "gpm8213": {
        "description": "Virtual GW Instek GPM-8213",
        "manufacturer": "GW Instek (simulado)",
        "product": "Virtual GPM-8213 Power Meter",
        "serial_number": "VLAB-GPM8213-001",
        "vid": 0x1209,
        "pid": 0x8213,
        "hwid": "VIRTUAL\\VID_1209&PID_8213",
        "location": "Virtual USB Lab / slot B",
    },
}


class VirtualUsbLabService:
    """In-memory USB lab state. It never enumerates or opens physical ports."""

    def __init__(self) -> None:
        self._ports: dict[str, VirtualPort] = {}
        self._lock = threading.RLock()

    def list_ports(self) -> list[VirtualPort]:
        with self._lock:
            now = datetime.now(UTC)
            for item in self._ports.values():
                item.last_seen_at = now
            return [item for item in self._ports.values() if item.connected]

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mode": "virtual_lab",
                "warning": "LABORATÓRIO VIRTUAL — não representa equipamento físico",
                "devices": [item.public_dict() for item in self._ports.values()],
            }

    def plug(
        self,
        profile: Literal["at4532", "gpm8213"],
        port: str,
        *,
        serial_number: str | None | object = ...,
        vid: int | None | object = ...,
        pid: int | None | object = ...,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = port.strip().upper()
        if not normalized.startswith("COM") or not normalized[3:].isdigit():
            raise ValueError("A porta virtual deve usar o formato COM seguido de número")
        with self._lock:
            if normalized in self._ports and self._ports[normalized].connected:
                raise ValueError("A porta virtual já está conectada")
            defaults = PROFILE_DEFAULTS[profile]
            item = VirtualPort(
                profile=profile,
                port=normalized,
                description=defaults["description"],
                manufacturer=defaults["manufacturer"],
                product=defaults["product"],
                serial_number=(
                    defaults["serial_number"] if serial_number is ... else serial_number
                ),
                vid=defaults["vid"] if vid is ... else vid,
                pid=defaults["pid"] if pid is ... else pid,
                hwid=defaults["hwid"],
                location=defaults["location"],
                options=dict(options or {}),
            )
            self._ports[normalized] = item
            return item.public_dict()

    def unplug(self, port: str) -> dict[str, Any]:
        item = self.require(port)
        item.connected = False
        item.last_seen_at = datetime.now(UTC)
        return item.public_dict()

    def change_port(self, port: str, new_port: str) -> dict[str, Any]:
        item = self.require(port)
        normalized = new_port.strip().upper()
        if not normalized.startswith("COM") or not normalized[3:].isdigit():
            raise ValueError("A nova porta deve usar o formato COM seguido de número")
        with self._lock:
            if normalized in self._ports and self._ports[normalized].connected:
                raise ValueError("A nova porta já está ocupada no laboratório")
            self._ports.pop(item.port, None)
            item.port = normalized
            item.last_seen_at = datetime.now(UTC)
            self._ports[normalized] = item
        return item.public_dict()

    def set_busy(self, port: str, busy: bool) -> dict[str, Any]:
        item = self.require(port)
        item.busy = busy
        return item.public_dict()

    def set_driver_missing(self, port: str, missing: bool) -> dict[str, Any]:
        item = self.require(port, include_disconnected=True)
        item.driver_missing = missing
        return item.public_dict()

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self._ports.clear()
        return self.state()

    def require(self, port: str, include_disconnected: bool = False) -> VirtualPort:
        normalized = port.strip().upper()
        with self._lock:
            item = self._ports.get(normalized)
            if not item or (not include_disconnected and not item.connected):
                raise ValueError("Porta virtual não conectada")
            return item


class VirtualInstrumentAdapter(DeviceAdapter):
    def __init__(self, port: str | None, profile: str, seed: int = 4532) -> None:
        self.port = port
        self.profile = profile
        self.random = random.Random(seed if profile == "at4532" else seed + 3681)
        self.connected = False
        self.reading = False
        self.started_at = monotonic()
        self.last_message_at: datetime | None = None
        self.messages = 0
        self.errors = 0

    def _port_state(self) -> VirtualPort:
        if not self.port:
            raise ValueError("Porta virtual não configurada")
        item = virtual_usb_lab_service.require(self.port)
        if item.profile != self.profile:
            raise ConnectionError("O perfil da porta virtual não corresponde ao equipamento")
        if item.driver_missing:
            raise ConnectionError("Driver virtual indisponível")
        if item.busy and not self.connected:
            raise ConnectionError("Porta virtual ocupada")
        return item

    async def connect(self) -> None:
        self._port_state()
        self.connected = True
        self.started_at = monotonic()

    async def disconnect(self) -> None:
        self.reading = False
        self.connected = False

    async def stop_reading(self) -> None:
        self.reading = False

    def parse_message(self, raw: bytes | str) -> DeviceReading:
        del raw
        raise NotImplementedError("O laboratório gera contratos tipados, não protocolo físico")

    def _temperature_reading(self, state: VirtualPort, elapsed: float) -> DeviceReading:
        options = state.options
        interval = int(options.get("interval_seconds", 1))
        if interval not in {1, 2, 3}:
            interval = 1
        channel_count = 32
        disabled = {int(value) for value in options.get("disabled_channels", [])}
        open_sensor = int(options.get("open_sensor_channel", 0))
        invalid_channel = int(options.get("invalid_channel", 0))
        peak_channel = int(options.get("peak_channel", 0))
        missing_probability = float(options.get("missing_probability", 0))
        jitter = float(options.get("jitter", 0.15))
        drift = float(options.get("drift_seconds_per_hour", 0)) * elapsed / 3600
        temperatures: list[float | None] = []
        quality = "good"
        for channel in range(1, channel_count + 1):
            if (
                channel in disabled
                or channel == open_sensor
                or self.random.random() < missing_probability
            ):
                temperatures.append(None)
                quality = "partial"
                continue
            value = 24 + channel * 0.22 + math.sin(elapsed / 12 + channel / 4) * 1.8
            value += self.random.gauss(0, jitter)
            if channel == peak_channel:
                value += float(options.get("peak_c", 55))
            if channel == invalid_channel:
                temperatures.append(None)
                quality = "invalid"
            else:
                temperatures.append(round(value, 3))
        now = datetime.now(UTC)
        return DeviceReading(
            timestamp=now,
            device_timestamp=now + timedelta(seconds=drift),
            raw_power=0,
            raw_power_unit="W",
            power_w=0,
            temperatures_c=temperatures,
            ambient_temperature_c=float(options.get("ambient_temperature_c", 23.5)),
            quality=quality,
            raw_payload={"simulated": True, "profile": "at4532", "interval_seconds": interval},
        )

    def _electrical_reading(self, state: VirtualPort, elapsed: float) -> DeviceReading:
        options = state.options
        if options.get("error"):
            self.errors += 1
            return DeviceReading(
                raw_power=0,
                raw_power_unit="W",
                power_w=0,
                temperatures_c=[],
                quality="error",
                raw_payload={"simulated": True, "message": "Error"},
            )
        voltage = 220 + math.sin(elapsed / 8) * 2
        current = max(0, 3.8 + math.sin(elapsed / 5) * 0.6)
        pf = 0.92
        active_w = voltage * current * pf
        if options.get("power_spike"):
            active_w += float(options.get("power_spike_w", 1800))
        units = options.get("power_units", ["mW", "W", "kW"])
        unit = self.random.choice(units)
        factor = {"mW": 0.001, "W": 1.0, "kW": 1000.0}[unit]
        raw_power = active_w / factor
        apparent = voltage * current
        reactive = math.sqrt(max(apparent**2 - active_w**2, 0))
        missing = bool(options.get("missing_values"))
        now = datetime.now(UTC)
        drift = float(options.get("drift_seconds_per_hour", 0)) * elapsed / 3600
        return DeviceReading(
            timestamp=now,
            device_timestamp=now + timedelta(seconds=drift),
            raw_power=round(raw_power, 6),
            raw_power_unit=unit,
            power_w=round(active_w, 6),
            temperatures_c=[],
            voltage_v=None if missing else round(voltage, 4),
            current_a=None if missing else round(current, 6),
            apparent_power_va=round(apparent, 6),
            reactive_power_var=round(reactive, 6),
            power_factor=pf,
            voltage_frequency_hz=60,
            current_frequency_hz=60,
            quality="partial" if missing else "good",
            raw_payload={"simulated": True, "profile": "gpm8213"},
        )

    async def start_reading(self):
        if not self.connected:
            raise RuntimeError("Instrumento virtual não conectado")
        self.reading = True
        while self.reading and self.connected:
            state = self._port_state()
            options = state.options
            delay = float(options.get("interval_seconds", 1)) + float(
                options.get("delay_seconds", 0)
            )
            delay += self.random.uniform(0, max(0, float(options.get("jitter_seconds", 0))))
            await asyncio.sleep(max(0.05, delay))
            if options.get("fail_during_acquisition"):
                raise ConnectionError("Falha virtual durante aquisição")
            elapsed = monotonic() - self.started_at
            reading = (
                self._temperature_reading(state, elapsed)
                if self.profile == "at4532"
                else self._electrical_reading(state, elapsed)
            )
            self.messages += 1
            self.last_message_at = reading.timestamp
            yield reading

    async def get_status(self) -> DeviceStatus:
        elapsed = max(monotonic() - self.started_at, 0.001)
        return DeviceStatus(
            state=(
                "reading"
                if self.reading
                else ("connected" if self.connected else "disconnected")
            ),
            connected=self.connected,
            reading=self.reading,
            last_message_at=self.last_message_at,
            messages_per_second=self.messages / elapsed,
            read_errors=self.errors,
        )

    async def get_device_information(self) -> DeviceInformation:
        model = (
            "Virtual Applent AT4532"
            if self.profile == "at4532"
            else "Virtual GW Instek GPM-8213"
        )
        return DeviceInformation(
            adapter=f"virtual_{self.profile}",
            manufacturer="ThermoPower Virtual Lab",
            model=model,
            capabilities={
                "simulated": True,
                "identity_confirmed": False,
                "protocol_validated": False,
                "acquisition_validated": False,
                "homologated": False,
            },
        )


virtual_usb_lab_service = VirtualUsbLabService()
