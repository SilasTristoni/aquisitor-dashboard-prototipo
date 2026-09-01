from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import asdict, dataclass
from time import monotonic
from typing import Any

import serial


class SerialTransportError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SerialTransportConfiguration:
    port: str
    baud_rate: int
    data_bits: int
    parity: str
    stop_bits: float
    timeout_s: float
    read_timeout_s: float
    line_terminator: str | None = None
    framing: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_serial_error(exc: BaseException) -> SerialTransportError:
    message = str(exc).casefold()
    if any(token in message for token in ("access", "permission", "denied", "busy", "used")):
        return SerialTransportError(
            "port_busy",
            "Porta ocupada pelo software do fabricante. Feche o software e tente novamente.",
        )
    if any(token in message for token in ("cannot find", "not found", "no such", "file not")):
        return SerialTransportError("port_not_found", "Porta não encontrada.")
    if any(token in message for token in ("driver", "device not configured")):
        return SerialTransportError("driver_unavailable", "Driver não disponível.")
    return SerialTransportError("serial_error", "Falha ao abrir ou ler a porta serial.")


class SerialTransport:
    """Raw pyserial transport used by reviewed, vendor-documented protocols."""

    def __init__(
        self,
        configuration: SerialTransportConfiguration,
        serial_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.configuration = configuration
        self.serial_factory = serial_factory or serial.Serial
        self.connection: Any | None = None
        self._io_lock = asyncio.Lock()
        self.open_boundary: dict[str, Any] = {}
        self.last_query_boundary: dict[str, Any] = {}

    @property
    def is_open(self) -> bool:
        return bool(self.connection and getattr(self.connection, "is_open", False))

    async def open(self) -> float:
        started = monotonic()
        try:
            self.connection = await asyncio.to_thread(
                self.serial_factory,
                port=self.configuration.port,
                baudrate=self.configuration.baud_rate,
                bytesize=self.configuration.data_bits,
                parity=self.configuration.parity,
                stopbits=self.configuration.stop_bits,
                timeout=self.configuration.read_timeout_s,
                write_timeout=self.configuration.timeout_s,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            if not self.is_open:
                raise SerialTransportError(
                    "serial_open_failed", "A porta serial não permaneceu aberta."
                )
            pending_payload = await self._pending_input()
            if hasattr(self.connection, "reset_input_buffer"):
                await asyncio.to_thread(self.connection.reset_input_buffer)
            if hasattr(self.connection, "reset_output_buffer"):
                await asyncio.to_thread(self.connection.reset_output_buffer)
            self.open_boundary = {
                "pending_input_bytes": len(pending_payload),
                "pending_input_ascii": pending_payload.decode("ascii", "backslashreplace")
                .replace("\r", "\\r")
                .replace("\n", "\\n"),
                "pending_input_hex": pending_payload.hex(" ").upper(),
                "input_buffer_reset": hasattr(self.connection, "reset_input_buffer"),
                "output_buffer_reset": hasattr(self.connection, "reset_output_buffer"),
            }
        except SerialTransportError:
            raise
        except (serial.SerialException, PermissionError, OSError) as exc:
            raise classify_serial_error(exc) from exc
        return (monotonic() - started) * 1000

    async def _pending_input(self) -> bytes:
        if not self.connection:
            return b""
        try:
            waiting = int(getattr(self.connection, "in_waiting", 0) or 0)
            if waiting <= 0:
                return b""
            return bytes(await asyncio.to_thread(self.connection.read, waiting))
        except (serial.SerialException, PermissionError, OSError) as exc:
            raise classify_serial_error(exc) from exc

    async def read(self, max_bytes: int) -> tuple[bytes, float]:
        if not self.is_open:
            raise SerialTransportError("disconnected", "O equipamento foi desconectado.")
        started = monotonic()
        try:
            payload = await asyncio.to_thread(self.connection.read, max_bytes)
        except (serial.SerialException, PermissionError, OSError) as exc:
            raise classify_serial_error(exc) from exc
        return bytes(payload), (monotonic() - started) * 1000

    async def _write_unlocked(self, payload: bytes) -> tuple[int, float]:
        if not self.is_open:
            raise SerialTransportError("disconnected", "O equipamento foi desconectado.")
        started = monotonic()
        try:
            written = await asyncio.to_thread(self.connection.write, payload)
            if hasattr(self.connection, "flush"):
                await asyncio.to_thread(self.connection.flush)
        except (serial.SerialException, PermissionError, OSError) as exc:
            raise classify_serial_error(exc) from exc
        if written != len(payload):
            raise SerialTransportError(
                "partial_write", "O comando serial não foi enviado por inteiro."
            )
        return int(written), (monotonic() - started) * 1000

    async def write(self, payload: bytes) -> tuple[int, float]:
        async with self._io_lock:
            return await self._write_unlocked(payload)

    async def read_until(self, terminator: bytes, max_bytes: int = 65_536) -> tuple[bytes, float]:
        if not self.is_open:
            raise SerialTransportError("disconnected", "O equipamento foi desconectado.")
        started = monotonic()
        try:
            if hasattr(self.connection, "read_until"):
                payload = await asyncio.to_thread(self.connection.read_until, terminator, max_bytes)
            else:  # Small fake transports used by protocol tests.
                buffer = bytearray()
                while len(buffer) < max_bytes and not buffer.endswith(terminator):
                    chunk = await asyncio.to_thread(self.connection.read, 1)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                payload = bytes(buffer)
        except (serial.SerialException, PermissionError, OSError) as exc:
            raise classify_serial_error(exc) from exc
        return bytes(payload), (monotonic() - started) * 1000

    async def query(
        self, payload: bytes, response_terminator: bytes, max_bytes: int = 65_536
    ) -> tuple[bytes, float]:
        async with self._io_lock:
            stale_payload = await self._pending_input()
            started = monotonic()
            _, write_elapsed_ms = await self._write_unlocked(payload)
            response, read_elapsed_ms = await self.read_until(response_terminator, max_bytes)
            elapsed_ms = (monotonic() - started) * 1000
            self.last_query_boundary = {
                "pending_before_tx_bytes": len(stale_payload),
                "pending_before_tx_ascii": stale_payload.decode("ascii", "backslashreplace")
                .replace("\r", "\\r")
                .replace("\n", "\\n"),
                "pending_before_tx_hex": stale_payload.hex(" ").upper(),
                "tx_flushed": True,
                "write_elapsed_ms": round(write_elapsed_ms, 3),
                "read_elapsed_ms": round(read_elapsed_ms, 3),
            }
            if not response:
                raise SerialTransportError(
                    "protocol_timeout", "Instrumento não respondeu ao comando."
                )
            return response, elapsed_ms

    async def close(self) -> None:
        connection = self.connection
        if connection and getattr(connection, "is_open", False):
            try:
                await asyncio.to_thread(connection.close)
            except (serial.SerialException, PermissionError, OSError) as exc:
                raise classify_serial_error(exc) from exc
            if getattr(connection, "is_open", False):
                raise SerialTransportError(
                    "serial_close_failed", "A porta serial não foi liberada."
                )
        self.connection = None


class At4532SerialTransport(SerialTransport):
    """AT45xx RS-232/USB-serial transport boundary."""


class Gpm8213SerialTransport(SerialTransport):
    """GPM-8213 USB CDC/RS-232 transport boundary."""
