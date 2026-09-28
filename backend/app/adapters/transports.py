from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from typing import Any
from weakref import WeakValueDictionary

import serial

logger = logging.getLogger(__name__)
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
        except Exception:
            logger.warning("Serial worker failed while cancellation was pending", exc_info=True)
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

    preserve_input_on_open = False

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
            pending_payload = b"" if self.preserve_input_on_open else await self._pending_input()
            if not self.preserve_input_on_open and hasattr(self.connection, "reset_input_buffer"):
                await serial_io(self.connection.reset_input_buffer)
            if hasattr(self.connection, "reset_output_buffer"):
                await serial_io(self.connection.reset_output_buffer)
            self.open_boundary = {
                "pending_input_bytes": int(getattr(self.connection, "in_waiting", 0) or 0)
                if self.preserve_input_on_open
                else len(pending_payload),
                "pending_input_ascii": pending_payload.decode("ascii", "backslashreplace")
                .replace("\r", "\\r")
                .replace("\n", "\\n"),
                "pending_input_hex": pending_payload.hex(" ").upper(),
                "input_buffer_reset": not self.preserve_input_on_open
                and hasattr(self.connection, "reset_input_buffer"),
                "input_preserved": self.preserve_input_on_open,
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
            stale_payload = await self._prepare_query(response_terminator, max_bytes)
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
            self.last_query_boundary["tx_sent"] = True
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
            self._observe_response(response, response_terminator)
            if not response:
                raise SerialTransportError(
                    "protocol_timeout", "Instrumento não respondeu ao comando."
                )
            return response, elapsed_ms

    async def _prepare_query(self, terminator: bytes, max_bytes: int) -> bytes:
        return await self._pending_input()

    def _observe_response(self, response: bytes, terminator: bytes) -> None:
        pass

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
    """Isolate late AT frames before TX; never join them to a new query's RX."""

    preserve_input_on_open = True
    # Separate, bounded recovery window, not an extension of FETCH's read timeout.
    resynchronization_timeout_s = 2.0
    boundary_quiet_s = 0.05

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._partial_input = bytearray()
        self._settle_required = False
        self.synchronization_metrics = dict.fromkeys(
            (
                "late_frames",
                "completed_late_frames",
                "incomplete_late_frames",
                "discarded_complete_frames",
                "discarded_partial_bytes",
                "resynchronizations",
                "resynchronization_failures",
            ),
            0,
        )
        self._resynchronization_history: deque[dict] = deque(maxlen=32)

    def input_boundary_diagnostics(self) -> dict:
        return {
            **self.synchronization_metrics,
            "pending_partial_bytes": len(self._partial_input),
            "recent_resynchronizations": list(self._resynchronization_history),
        }

    async def synchronize_input_boundary(
        self,
        terminator: bytes = b"\n",
        max_bytes: int = 65_536,
    ) -> list[bytes]:
        async with self._io_lock:
            return await self._synchronize_input_boundary(terminator, max_bytes)

    async def _synchronize_input_boundary(self, terminator: bytes, max_bytes: int) -> list[bytes]:
        if not self.is_open:
            raise SerialTransportError("disconnected", "O equipamento foi desconectado.")
        try:
            return await serial_io(self._synchronize_frames, terminator, max_bytes)
        except (serial.SerialException, PermissionError, OSError) as exc:
            raise classify_serial_error(exc) from exc

    def _synchronize_frames(self, terminator: bytes, max_bytes: int) -> list[bytes]:
        connection = self.connection
        waiting = int(getattr(connection, "in_waiting", 0) or 0)
        if not waiting and not self._partial_input and not self._settle_required:
            return []
        started = monotonic()
        deadline = started + self.resynchronization_timeout_s
        original_timeout = getattr(connection, "timeout", None)
        metrics = self.synchronization_metrics
        metrics["resynchronizations"] += 1
        event = {
            "sequence": metrics["resynchronizations"],
            "timestamp": datetime.now(UTC).isoformat(),
            "bytes_present_before_resync": waiting,
            "retained_partial_bytes": len(self._partial_input),
            "bytes_completed": 0,
            "frames": [],
        }
        frames: list[bytes] = []
        consumed = 0
        clean = False
        try:
            while monotonic() < deadline and consumed < max_bytes:
                if self._partial_input.endswith(terminator):
                    frame = bytes(self._partial_input)
                    frames.append(frame)
                    event["frames"].append(
                        {
                            "full_frame_length": len(frame),
                            "prefix": frame[:32].decode("ascii", "backslashreplace"),
                            "terminator_found": True,
                            "raw_hex": frame.hex(" ").upper(),
                        }
                    )
                    metrics["completed_late_frames"] += 1
                    metrics["discarded_complete_frames"] += 1
                    self._partial_input.clear()
                remaining = deadline - monotonic()
                # After a complete frame require a bounded quiet interval. Following a
                # timeout, wait the full recovery budget for the first delayed byte.
                wait = (
                    remaining
                    if self._partial_input or not frames
                    else min(remaining, self.boundary_quiet_s)
                )
                connection.timeout = max(0, wait)
                chunk = connection.read(1)
                if not chunk:
                    clean = not self._partial_input
                    break
                if not self._partial_input:
                    metrics["late_frames"] += 1
                self._partial_input.extend(chunk)
                consumed += len(chunk)
                if len(self._partial_input) >= max_bytes:
                    break
            if not clean:
                if self._partial_input:
                    metrics["incomplete_late_frames"] += 1
                raise SerialTransportError(
                    "incomplete_late_frame",
                    "Ressincronização AT4532 não concluiu uma fronteira segura; TX bloqueado.",
                )
            self._settle_required = False
            return frames
        finally:
            connection.timeout = original_timeout
            event.update(
                {
                    "bytes_completed": consumed,
                    "full_frame_length": sum(len(frame) for frame in frames),
                    "prefix": (frames[0] if frames else bytes(self._partial_input))[:32].decode(
                        "ascii", "backslashreplace"
                    ),
                    "terminator_found": bool(frames),
                    "boundary_clean": clean,
                    "incomplete_late_frame": bool(self._partial_input),
                    "retained_partial_hex": bytes(self._partial_input).hex(" ").upper(),
                    "elapsed_ms": round((monotonic() - started) * 1000, 3),
                }
            )
            if not clean:
                metrics["resynchronization_failures"] += 1
                self._settle_required = True
            self._resynchronization_history.append(event)
            self.last_query_boundary["input_resynchronization"] = event
            logger.info(
                "AT4532 input resynchronization port=%s details=%s", self.configuration.port, event
            )

    async def _prepare_query(self, terminator: bytes, max_bytes: int) -> bytes:
        self.last_query_boundary["tx_sent"] = False
        frames = await self._synchronize_input_boundary(terminator, max_bytes)
        # Compatibility counters now describe complete isolated frames, never fragments.
        return b"".join(frames)

    def _observe_response(self, response: bytes, terminator: bytes) -> None:
        if not response or not response.endswith(terminator):
            self._settle_required = True
            if response:
                raise SerialTransportError(
                    "incomplete_frame",
                    "Frame AT4532 incompleto preservado para ressincronização.",
                )

    def _read_frame(self, terminator: bytes, max_bytes: int) -> bytes:
        try:
            return super()._read_frame(terminator, max_bytes)
        finally:
            # This runs inside the I/O worker, also on cancellation or physical error.
            # Retaining only in query() would lose the fragment when its await is cancelled.
            response = bytes(self.last_query_boundary.get("received_bytes", []))
            if not response.endswith(terminator):
                self._settle_required = True
                self._partial_input.extend(response)
                if response:
                    self.synchronization_metrics["late_frames"] += 1

    async def write(self, payload: bytes) -> tuple[int, float]:
        async with self._io_lock:
            self.last_query_boundary = {"tx_sent": False}
            await self._synchronize_input_boundary(b"\n", 65_536)
            result = await self._write_unlocked(payload)
            self.last_query_boundary["tx_sent"] = True
            return result

    async def _close_unlocked(self, *, release: bool) -> None:
        if self.is_open:
            try:
                await self._synchronize_input_boundary(b"\n", 65_536)
            except SerialTransportError:
                # Explicit disconnect/physical recovery may abandon an unfinishable
                # frame, but its exact bytes and loss must remain visible in diagnostics.
                logger.warning(
                    "AT4532 close without clean boundary port=%s",
                    self.configuration.port,
                    exc_info=True,
                )
        await super()._close_unlocked(release=release)
        if self._partial_input:
            self.synchronization_metrics["discarded_partial_bytes"] += len(self._partial_input)
            logger.warning(
                "AT4532 partial bytes abandoned on close port=%s raw_hex=%s",
                self.configuration.port,
                bytes(self._partial_input).hex(" ").upper(),
            )
            self._partial_input.clear()
        self._settle_required = True


class Gpm8213SerialTransport(SerialTransport):
    """GPM-8213 USB CDC/RS-232 transport boundary."""
