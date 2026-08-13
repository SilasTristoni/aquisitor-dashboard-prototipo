from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.adapters.transports import (
    SerialTransport,
    SerialTransportConfiguration,
    SerialTransportError,
)

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticSession:
    identifier: str
    transport: SerialTransport
    opened_at: datetime
    reconnect_detected: bool
    parameters_source: str
    physical_validation: str


class RealSerialDiagnosticService:
    """Read-only raw serial diagnostics. This service has no write operation by design."""

    def __init__(self, serial_factory: Callable[..., Any] | None = None) -> None:
        self.serial_factory = serial_factory
        self.sessions: dict[str, DiagnosticSession] = {}
        self.previously_opened_ports: set[str] = set()
        self._lock = asyncio.Lock()

    async def open(
        self,
        configuration: SerialTransportConfiguration,
        *,
        parameters_source: str = "user_confirmed",
        physical_validation: str = "parameters_confirmed",
    ) -> dict[str, Any]:
        async with self._lock:
            if any(
                session.transport.configuration.port.casefold() == configuration.port.casefold()
                for session in self.sessions.values()
            ):
                raise SerialTransportError(
                    "diagnostic_already_open", "A porta já está aberta neste diagnóstico."
                )
            transport = SerialTransport(configuration, self.serial_factory)
            elapsed_ms = await transport.open()
            identifier = uuid.uuid4().hex
            port_key = configuration.port.casefold()
            reconnect = port_key in self.previously_opened_ports
            self.previously_opened_ports.add(port_key)
            self.sessions[identifier] = DiagnosticSession(
                identifier=identifier,
                transport=transport,
                opened_at=datetime.now(UTC),
                reconnect_detected=reconnect,
                parameters_source=parameters_source,
                physical_validation=physical_validation,
            )
        logger.info(
            "serial diagnostic opened port=%s baud_rate=%s elapsed_ms=%.2f "
            "read_only=true parameters_source=%s physical_validation=%s",
            configuration.port,
            configuration.baud_rate,
            elapsed_ms,
            parameters_source,
            physical_validation,
        )
        return {
            "session_id": identifier,
            "port_open": True,
            "bytes_received": 0,
            "elapsed_ms": round(elapsed_ms, 3),
            "timeout": False,
            "raw_hex": "",
            "raw_ascii": "",
            "timestamp": datetime.now(UTC).isoformat(),
            "errors": [],
            "read_only": True,
            "reconnect_detected": reconnect,
            "parameters": configuration.public_dict(),
            "parameters_source": parameters_source,
            "physical_validation": physical_validation,
        }

    async def read(self, session_id: str, max_bytes: int) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            raise SerialTransportError(
                "diagnostic_session_not_found", "Sessão de diagnóstico não encontrada."
            )
        try:
            payload, elapsed_ms = await session.transport.read(max_bytes)
        except SerialTransportError as exc:
            logger.warning(
                "serial diagnostic read error port=%s code=%s",
                session.transport.configuration.port,
                exc.code,
            )
            return {
                "session_id": session_id,
                "port_open": session.transport.is_open,
                "bytes_received": 0,
                "elapsed_ms": 0,
                "timeout": False,
                "raw_hex": "",
                "raw_ascii": "",
                "timestamp": datetime.now(UTC).isoformat(),
                "errors": [{"code": exc.code, "message": str(exc)}],
                "read_only": True,
                "disconnected": exc.code in {"disconnected", "port_not_found"},
                "parameters_source": session.parameters_source,
                "physical_validation": session.physical_validation,
            }
        timeout = len(payload) == 0
        logger.info(
            "serial diagnostic read port=%s bytes=%s elapsed_ms=%.2f timeout=%s",
            session.transport.configuration.port,
            len(payload),
            elapsed_ms,
            timeout,
        )
        return {
            "session_id": session_id,
            "port_open": session.transport.is_open,
            "bytes_received": len(payload),
            "elapsed_ms": round(elapsed_ms, 3),
            "timeout": timeout,
            "raw_hex": payload.hex(" ").upper(),
            "raw_ascii": _safe_ascii(payload),
            "timestamp": datetime.now(UTC).isoformat(),
            "errors": [],
            "read_only": True,
            "disconnected": False,
            "parameters_source": session.parameters_source,
            "physical_validation": session.physical_validation,
        }

    async def close(self, session_id: str) -> dict[str, Any]:
        async with self._lock:
            session = self.sessions.pop(session_id, None)
        if not session:
            raise SerialTransportError(
                "diagnostic_session_not_found", "Sessão de diagnóstico não encontrada."
            )
        await session.transport.close()
        logger.info("serial diagnostic closed port=%s", session.transport.configuration.port)
        return {
            "session_id": session_id,
            "port_open": False,
            "closed": True,
            "timestamp": datetime.now(UTC).isoformat(),
            "errors": [],
            "read_only": True,
            "parameters_source": session.parameters_source,
            "physical_validation": session.physical_validation,
        }

    async def shutdown(self) -> None:
        for session_id in list(self.sessions):
            try:
                await self.close(session_id)
            except SerialTransportError:
                logger.exception("serial diagnostic shutdown failed session=%s", session_id)


def _safe_ascii(payload: bytes) -> str:
    pieces = []
    for byte in payload:
        if byte == 13:
            pieces.append("\\r")
        elif byte == 10:
            pieces.append("\\n")
        elif 32 <= byte <= 126:
            pieces.append(chr(byte))
        else:
            pieces.append(".")
    return "".join(pieces)


real_serial_diagnostic_service = RealSerialDiagnosticService()
