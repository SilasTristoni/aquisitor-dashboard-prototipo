from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from typing import Any
from weakref import WeakValueDictionary

import serial

_PORT_OWNERS: WeakValueDictionary = WeakValueDictionary()
_PORT_OWNERS_LOCK = Lock()


def port_key(port: str) -> str:
    return port.strip().removeprefix("\\\\.\\").casefold()


def claim_port(port: str, owner: Any) -> None:
    key = port_key(port)
    with _PORT_OWNERS_LOCK:
        existing = _PORT_OWNERS.get(key)
        if existing is not None and existing is not owner:
            raise SerialTransportError(
                "port_owned_by_thermopower", "A porta pertence a outra sess\u00e3o do ThermoPower."
            )
        _PORT_OWNERS[key] = owner


def release_port(port: str, owner: Any) -> None:
    key = port_key(port)
    with _PORT_OWNERS_LOCK:
        if _PORT_OWNERS.get(key) is owner:
            del _PORT_OWNERS[key]


async def serial_io(function, *args, **kwargs):
    """Do not abandon a serial worker on cancellation and then close/reopen under it."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


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
        async with self._io_lock:
            return await self._open_unlocked()

    async def _open_unlocked(self) -> float:
        if self.is_open:
            return 0.0
        claim_port(self.configuration.port, self)
        started = monotonic()
        try:
            await serial_io(
                self._create_connection,
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
                await serial_io(self.connection.reset_input_buffer)
            if hasattr(self.connection, "reset_output_buffer"):
                await serial_io(self.connection.reset_output_buffer)
            self.open_boundary = {
                "pending_input_bytes": len(pending_payload),
                "pending_input_ascii": pending_payload.decode("ascii", "backslashreplace")
                .replace("\r", "\\r")
                .replace("\n", "\\n"),
                "pending_input_hex": pending_payload.hex(" ").upper(),
                "input_buffer_reset": hasattr(self.connection, "reset_input_buffer"),
                "output_buffer_reset": hasattr(self.connection, "reset_output_buffer"),
            }
        except asyncio.CancelledError:
            await self._close_unlocked(release=True)
            raise
        except SerialTransportError:
            raise
        except (serial.SerialException, PermissionError, OSError) as exc:
            raise classify_serial_error(exc) from exc
        return (monotonic() - started) * 1000

    def _create_connection(self, **kwargs) -> None:
        self.connection = self.serial_factory(**kwargs)

    async def _pending_input(self) -> bytes:
        if not self.connection:
            return b""
        try:
            waiting = int(getattr(self.connection, "in_waiting", 0) or 0)
            if waiting <= 0:
                return b""
            return bytes(await serial_io(self.connection.read, waiting))
        except (serial.SerialException, PermissionError, OSError) as exc:
            raise classify_serial_error(exc) from exc

    async def read(self, max_bytes: int) -> tuple[bytes, float]:
        async with self._io_lock:
            return await self._read_unlocked(max_bytes)

    async def _read_unlocked(self, max_bytes: int) -> tuple[bytes, float]:
        if not self.is_open:
            raise SerialTransportError("disconnected", "O equipamento foi desconectado.")
        started = monotonic()
        try:
            payload = await serial_io(self.connection.read, max_bytes)
        except (serial.SerialException, PermissionError, OSError) as exc:
            raise classify_serial_error(exc) from exc
        return bytes(payload), (monotonic() - started) * 1000

    async def _write_unlocked(self, payload: bytes) -> tuple[int, float]:
        if not self.is_open:
            raise SerialTransportError("disconnected", "O equipamento foi desconectado.")
        started = monotonic()
        try:
            written = await serial_io(self.connection.write, payload)
            if hasattr(self.connection, "flush"):
                await serial_io(self.connection.flush)
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

    def _read_frame(self, terminator: bytes, max_bytes: int) -> bytes:
        # LF/CRLF is the documented boundary. USB chunks and temporary silence are
        # not frames. No guessed TCP-32 length or silence-based framing is introduced.
        connection = self.connection
        deadline = monotonic() + self.configuration.read_timeout_s
        original_timeout = getattr(connection, "timeout", None)
        buffer = bytearray()
        first_byte = last_byte = None
        first_byte_at = last_byte_at = None
        try:
            while len(buffer) < max_bytes and not buffer.endswith(terminator):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                if hasattr(connection, "timeout"):
                    connection.timeout = remaining
                chunk = connection.read(1)
                if not chunk:
                    break
                now = monotonic()
                last_byte_at = datetime.now(UTC).isoformat()
                first_byte_at = first_byte_at or last_byte_at
                first_byte = now if first_byte is None else first_byte
                last_byte = now
                buffer.extend(chunk)
        finally:
            if hasattr(connection, "timeout"):
                connection.timeout = original_timeout
            self.last_query_boundary.update(
                {
                    "timestamp_first_byte": first_byte_at,
                    "timestamp_last_byte": last_byte_at,
                    "first_byte_monotonic": first_byte,
                    "last_byte_monotonic": last_byte,
                    "first_byte_latency_ms": (first_byte - self.last_query_boundary["tx_monotonic"])
                    * 1000
                    if first_byte is not None and "tx_monotonic" in self.last_query_boundary
                    else None,
                    "frame_complete": bytes(buffer).endswith(terminator),
                    "bytes_received": len(buffer),
                    "received_bytes": list(buffer),
                    "received_hex": bytes(buffer).hex(" ").upper(),
                }
            )
        return bytes(buffer)

    async def read_until(self, terminator: bytes, max_bytes: int = 65_536) -> tuple[bytes, float]:
        async with self._io_lock:
            return await self._read_until_unlocked(terminator, max_bytes)

    async def _read_until_unlocked(self, terminator: bytes, max_bytes: int) -> tuple[bytes, float]:
        if not self.is_open:
            raise SerialTransportError("disconnected", "O equipamento foi desconectado.")
        started = monotonic()
        try:
            payload = await serial_io(self._read_frame, terminator, max_bytes)
        except (serial.SerialException, PermissionError, OSError) as exc:
            raise classify_serial_error(exc) from exc
        return payload, (monotonic() - started) * 1000

    async def query(
        self, payload: bytes, response_terminator: bytes, max_bytes: int = 65_536
    ) -> tuple[bytes, float]:
        async with self._io_lock:
            self.last_query_boundary = {
                "buffer_pending_before_tx_bytes": 0,
                "buffer_drained_bytes": 0,
                "pending_before_tx_bytes": 0,
                "pending_before_tx_ascii": "",
                "pending_before_tx_hex": "",
                "tx_flushed": False,
            }
            stale_payload = await self._pending_input()
            started = monotonic()
            timestamp_tx = datetime.now(UTC)
            tx_monotonic = monotonic()
            self.last_query_boundary.update(
                {
                    "buffer_pending_before_tx_bytes": len(stale_payload),
                    "buffer_drained_bytes": len(stale_payload),
                    # Backward-compatible names retained in exported diagnostics.
                    "pending_before_tx_bytes": len(stale_payload),
                    "pending_before_tx_ascii": stale_payload.decode("ascii", "backslashreplace")
                    .replace("\r", "\\r")
                    .replace("\n", "\\n"),
                    "pending_before_tx_hex": stale_payload.hex(" ").upper(),
                    "timestamp_tx": timestamp_tx.isoformat(),
                    "tx_monotonic": tx_monotonic,
                }
            )
            _, write_elapsed_ms = await self._write_unlocked(payload)
            response, read_elapsed_ms = await self._read_until_unlocked(
                response_terminator, max_bytes
            )
            rx_monotonic = monotonic()
            timestamp_rx = datetime.now(UTC)
            elapsed_ms = (rx_monotonic - started) * 1000
            self.last_query_boundary.update(
                {
                    "timestamp_rx": timestamp_rx.isoformat(),
                    "rx_monotonic": rx_monotonic,
                    "tx_flushed": True,
                    "write_elapsed_ms": round(write_elapsed_ms, 3),
                    "read_elapsed_ms": round(read_elapsed_ms, 3),
                    "query_duration_ms": round(elapsed_ms, 3),
                }
            )
            if not response:
                raise SerialTransportError(
                    "protocol_timeout", "Instrumento não respondeu ao comando."
                )
            return response, elapsed_ms

    async def close(self, *, release: bool = True) -> None:
        async with self._io_lock:
            await self._close_unlocked(release=release)

    async def _close_unlocked(self, *, release: bool) -> None:
        connection = self.connection
        if connection and getattr(connection, "is_open", False):
            try:
                await serial_io(connection.close)
            except (serial.SerialException, PermissionError, OSError) as exc:
                raise classify_serial_error(exc) from exc
            if getattr(connection, "is_open", False):
                raise SerialTransportError(
                    "serial_close_failed", "A porta serial não foi liberada."
                )
        self.connection = None
        if release:
            release_port(self.configuration.port, self)


class At4532SerialTransport(SerialTransport):
    """AT45xx RS-232/USB-serial transport boundary."""


class Gpm8213SerialTransport(SerialTransport):
    """GPM-8213 USB CDC/RS-232 transport boundary."""
