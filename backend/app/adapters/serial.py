import asyncio
import csv
import io
import json
from collections.abc import AsyncIterator
from datetime import datetime

import serial

from app.adapters.base import (
    DeviceAdapter,
    DeviceInformation,
    DeviceReading,
    DeviceStatus,
    power_to_watts,
)


class SerialJsonAdapter(DeviceAdapter):
    def __init__(self, port: str | None, baud_rate: int = 115200) -> None:
        self.port = port
        self.baud_rate = baud_rate
        self.connection: serial.Serial | None = None
        self.reading = False
        self.last_message_at: datetime | None = None
        self.read_errors = 0
        self.message_count = 0

    async def connect(self) -> None:
        if not self.port:
            raise ValueError("Porta serial não configurada")
        self.connection = await asyncio.to_thread(
            serial.Serial, self.port, self.baud_rate, timeout=1
        )

    async def disconnect(self) -> None:
        self.reading = False
        if self.connection and self.connection.is_open:
            await asyncio.to_thread(self.connection.close)
        self.connection = None

    async def stop_reading(self) -> None:
        self.reading = False

    def parse_message(self, raw: bytes | str) -> DeviceReading:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        payload = json.loads(text.strip())
        raw_power = float(payload["power"])
        unit = str(payload.get("powerUnit", "W"))
        return DeviceReading(
            raw_power=raw_power,
            raw_power_unit=unit,
            power_w=power_to_watts(raw_power, unit),
            temperatures_c=payload.get("temperatures", []),
        )

    async def start_reading(self) -> AsyncIterator[DeviceReading]:
        if not self.connection:
            raise RuntimeError("Porta serial não conectada")
        self.reading = True
        while self.reading and self.connection.is_open:
            line = await asyncio.to_thread(self.connection.readline)
            if not line:
                continue
            try:
                reading = self.parse_message(line)
                self.last_message_at = reading.timestamp
                self.message_count += 1
                yield reading
            except (ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError):
                self.read_errors += 1

    async def get_status(self) -> DeviceStatus:
        connected = bool(self.connection and self.connection.is_open)
        return DeviceStatus(
            state="reading" if self.reading else ("connected" if connected else "disconnected"),
            connected=connected,
            reading=self.reading,
            last_message_at=self.last_message_at,
            read_errors=self.read_errors,
        )

    async def get_device_information(self) -> DeviceInformation:
        return DeviceInformation(
            adapter="serial_json",
            capabilities={
                "port": self.port,
                "baud_rate": self.baud_rate,
                "protocol_validated": False,
            },
        )


class SerialCsvAdapter(SerialJsonAdapter):
    """Prepared parser. Disabled until the physical column contract is approved."""

    enabled = False

    async def connect(self) -> None:
        if not self.enabled:
            raise RuntimeError("Adaptador CSV aguarda homologação do protocolo")
        await super().connect()

    def parse_message(self, raw: bytes | str) -> DeviceReading:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        row = next(csv.reader(io.StringIO(text.strip())))
        if len(row) < 3:
            raise ValueError("CSV deve conter potência, unidade e ao menos um canal")
        raw_power, unit = float(row[0]), row[1]
        temperatures = [float(value) if value.strip() else None for value in row[2:18]]
        return DeviceReading(
            raw_power=raw_power,
            raw_power_unit=unit,
            power_w=power_to_watts(raw_power, unit),
            temperatures_c=temperatures,
        )

    async def get_device_information(self) -> DeviceInformation:
        return DeviceInformation(
            adapter="serial_csv",
            capabilities={"enabled": False, "protocol_validated": False},
        )
