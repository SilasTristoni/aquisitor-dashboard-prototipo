"""Vendor-documented AT4532 and GPM-8213 serial integrations.

Physical validation remains pending until real instruments answer these documented queries.
No undocumented fallback command or response sentinel is accepted here.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from app.adapters.base import DeviceAdapter, DeviceInformation, DeviceReading, DeviceStatus
from app.adapters.transports import (
    At4532SerialTransport,
    Gpm8213SerialTransport,
    SerialTransport,
    SerialTransportConfiguration,
    SerialTransportError,
)

logger = logging.getLogger(__name__)

AT4532_MANUAL_URL = "https://www.anbai.cn/app_file/products/AT4532/ug_en_AT4532.pdf"
GPM8213_MANUAL_URL = "https://www.gwinstek.com/en-US/download/downloadFile/11551"


class ProtocolDocumentationRequired(RuntimeError):
    """Retained for callers that surface a precise documentation gap."""

    code = "protocol_documentation_required"


class ProtocolResponseError(ValueError):
    code = "unexpected_protocol_response"


class UnexpectedResponseTypeError(ProtocolResponseError):
    code = "unexpected_response_type"

    def __init__(
        self,
        *,
        expected: str,
        actual: str,
        command: str,
        previous_command: str | None,
        raw_response: bytes,
    ) -> None:
        self.details = {
            "expected_for_command": expected,
            "actual_response_type": actual,
            "raw_response": raw_response.decode("ascii", "backslashreplace")
            .replace("\r", "\\r")
            .replace("\n", "\\n"),
            "previous_command": previous_command,
            "possible_stale_response": actual == "identity_response",
        }
        super().__init__(
            f"Resposta incompatível com {command}: esperado {expected}, recebido {actual}."
        )


@dataclass(frozen=True)
class DocumentedCommand:
    name: str
    request: bytes
    response_terminator: bytes
    source: str
    section: str
    purpose: str
    vendor_documented: bool = True
    expected_response_type: str | None = None


class At4532Protocol:
    documentation_status = "vendor_documented_physical_validation_pending"
    identity = DocumentedCommand(
        name="identity",
        request=b"*IDN?\n",
        response_terminator=b"\n",
        source=AT4532_MANUAL_URL,
        section="9.1 e 9.5.5",
        purpose="Identificar modelo, revisão, número de série e fabricante.",
    )
    temperatures = DocumentedCommand(
        name="temperatures",
        request=b"FETCH?\n",
        response_terminator=b"\n",
        source=AT4532_MANUAL_URL,
        section="9.1 e 9.5.3.1",
        purpose="Consultar os valores dos canais de temperatura.",
    )
    celsius = DocumentedCommand(
        name="configure_celsius",
        request=b"SYST:UNIT CEL\n",
        response_terminator=b"\n",
        source=AT4532_MANUAL_URL,
        section="9.5.2.3",
        purpose="Configurar explicitamente a unidade de temperatura como Celsius.",
    )

    def command(self, name: str) -> DocumentedCommand:
        commands = {
            "identity": self.identity,
            "read": self.temperatures,
            "temperatures": self.temperatures,
        }
        try:
            return commands[name]
        except KeyError as exc:
            raise ProtocolDocumentationRequired(f"Comando AT4532 não documentado: {name}") from exc


class Gpm8213Protocol:
    documentation_status = "vendor_documented_physical_validation_pending"
    item_functions = ("U", "I", "P", "S", "FU", "LAMBDA", "Q", "FI")
    identity = DocumentedCommand(
        name="identity",
        request=b"*IDN?\r\n",
        response_terminator=b"\r\n",
        source=GPM8213_MANUAL_URL,
        section="Remote Control, p. 65-72; *IDN, p. 75",
        purpose="Identificar fabricante, modelo, número de série e firmware.",
        expected_response_type="identity_response",
    )
    measurements = DocumentedCommand(
        name="measurements",
        request=b":NUMERIC:NORMAL:VALUE?\r\n",
        response_terminator=b"\r\n",
        source=GPM8213_MANUAL_URL,
        section="NUMeric Commands, p. 96-102",
        purpose="Consultar os itens numéricos configurados.",
        expected_response_type="numeric_measurement",
    )
    number_set = DocumentedCommand(
        name="configure_item_count",
        request=b":NUMERIC:NORMAL:NUMBER 8\r\n",
        response_terminator=b"\r\n",
        source=GPM8213_MANUAL_URL,
        section="NUMeric NUMBer, p. 97",
        purpose="Solicitar oito itens na saída numérica.",
    )
    number_query = DocumentedCommand(
        name="query_item_count",
        request=b":NUMERIC:NORMAL:NUMBER?\r\n",
        response_terminator=b"\r\n",
        source=GPM8213_MANUAL_URL,
        section="NUMeric NUMBer, p. 97",
        purpose="Confirmar a quantidade de itens aceita pelo equipamento.",
        expected_response_type="item_count",
    )
    items = tuple(
        DocumentedCommand(
            name=f"configure_{index}_{function.casefold()}",
            request=f":NUMERIC:NORMAL:ITEM{index} {function}\r\n".encode("ascii"),
            response_terminator=b"\r\n",
            source=GPM8213_MANUAL_URL,
            section="NUMeric ITEM<x>, p. 97-99",
            purpose=f"Configurar o item {index} como {function}.",
        )
        for index, function in enumerate(item_functions, 1)
    )
    header_query = DocumentedCommand(
        name="query_headers",
        request=b":NUMERIC:NORMAL:HEADER?\r\n",
        response_terminator=b"\r\n",
        source=GPM8213_MANUAL_URL,
        section="NUMeric HEADer, p. 102",
        purpose="Confirmar os nomes e a ordem dos itens numéricos configurados.",
        expected_response_type="header_list",
    )
    configuration = (number_set, number_query, *items, header_query)

    def command(self, name: str) -> DocumentedCommand:
        commands = {
            "identity": self.identity,
            "read": self.measurements,
            "measurements": self.measurements,
        }
        try:
            return commands[name]
        except KeyError as exc:
            raise ProtocolDocumentationRequired(
                f"Comando GPM-8213 não documentado: {name}"
            ) from exc


def _single_ascii_line(payload: bytes, terminator: bytes) -> str:
    if not payload.endswith(terminator):
        raise ProtocolResponseError("Resposta parcial: terminador oficial não recebido.")
    body = payload[: -len(terminator)]
    if b"\r" in body or b"\n" in body:
        raise ProtocolResponseError("Foram recebidos múltiplos frames em uma única resposta.")
    try:
        return body.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ProtocolResponseError("Resposta não é ASCII, como exige o protocolo.") from exc


class At4532Parser:
    def parse_identity(self, payload: bytes) -> dict[str, str]:
        fields = [field.strip() for field in _single_ascii_line(payload, b"\n").split(",")]
        if len(fields) != 4 or fields[0].casefold() != "at4532":
            raise ProtocolResponseError("A resposta de identidade não identifica um AT4532.")
        return {
            "model": fields[0],
            "revision": fields[1],
            "serial_number": fields[2],
            "manufacturer": fields[3],
        }

    def parse(self, payload: bytes) -> Sequence[float]:
        line = _single_ascii_line(payload, b"\n")
        fields = [field.strip() for field in line.split(",")]
        if not 1 <= len(fields) <= 32 or any(not field for field in fields):
            raise ProtocolResponseError("FETCH? deve retornar entre 1 e 32 campos numéricos.")
        try:
            values = [float(field) for field in fields]
        except ValueError as exc:
            raise ProtocolResponseError("FETCH? contém um campo não numérico.") from exc
        if any(not math.isfinite(value) for value in values):
            raise ProtocolResponseError("FETCH? contém valor não finito.")
        return values


class Gpm8213Parser:
    header_keys = {
        "u": "voltage",
        "urms": "voltage",
        "i": "current",
        "irms": "current",
        "p": "power",
        "s": "apparent_power",
        "q": "reactive_power",
        "pf": "power_factor",
        "lambda": "power_factor",
        "λ": "power_factor",
        "fu": "voltage_frequency",
        "fi": "current_frequency",
    }
    units = {
        "voltage": "V",
        "current": "A",
        "power": "W",
        "apparent_power": "VA",
        "reactive_power": "VAR",
        "power_factor": "PF",
        "voltage_frequency": "Hz",
        "current_frequency": "Hz",
    }

    def parse_identity(self, payload: bytes) -> dict[str, str]:
        fields = [field.strip() for field in _single_ascii_line(payload, b"\r\n").split(",")]
        if len(fields) != 4 or fields[1].casefold() != "gpm-8213":
            raise ProtocolResponseError("A resposta de identidade não identifica um GPM-8213.")
        return {
            "manufacturer": fields[0],
            "model": fields[1],
            "serial_number": fields[2],
            "firmware_version": fields[3],
        }

    def classify(self, payload: bytes) -> str:
        line = _single_ascii_line(payload, b"\r\n")
        fields = [field.strip() for field in line.split(",")]
        if len(fields) == 4 and fields[1].casefold() == "gpm-8213":
            return "identity_response"
        if self._parse_count_text(line) is not None:
            return "item_count"
        if fields and all(field.casefold() in self.header_keys for field in fields):
            return "header_list"
        if fields and all(self._is_numeric_field(field) for field in fields):
            return "numeric_measurement"
        return "unknown_response"

    @staticmethod
    def _is_numeric_field(field: str) -> bool:
        if field.casefold() == "nan":
            return True
        try:
            return math.isfinite(float(field))
        except ValueError:
            return False

    @staticmethod
    def _parse_count_text(line: str) -> int | None:
        match = re.fullmatch(r"(?::NUMERIC:NORMAL:NUMBER\s+)?(\d+)", line, re.IGNORECASE)
        if not match:
            return None
        value = int(match.group(1))
        return value if 1 <= value <= 34 else None

    def parse_item_count(self, payload: bytes) -> int:
        line = _single_ascii_line(payload, b"\r\n")
        value = self._parse_count_text(line)
        if value is None:
            raise ProtocolResponseError("NUMBER? não retornou uma quantidade válida de 1 a 34.")
        return value

    def parse_headers(self, payload: bytes, expected_count: int) -> list[str]:
        line = _single_ascii_line(payload, b"\r\n")
        reported = [field.strip() for field in line.split(",")]
        if len(reported) != expected_count:
            raise ProtocolResponseError(
                f"HEADER? retornou {len(reported)} itens; NUMBER? informou {expected_count}."
            )
        canonical: list[str] = []
        for header in reported:
            key = self.header_keys.get(header.casefold())
            if key is None:
                raise ProtocolResponseError(f"HEADER? retornou item não mapeado: {header}")
            canonical.append(key)
        if len(set(canonical)) != len(canonical):
            raise ProtocolResponseError("HEADER? retornou itens duplicados.")
        return canonical

    def parse(
        self, payload: bytes, headers: Sequence[str]
    ) -> Mapping[str, float | None]:
        line = _single_ascii_line(payload, b"\r\n")
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != len(headers):
            raise ProtocolResponseError(
                f"VALUE? retornou {len(fields)} valores; HEADER? informou {len(headers)} itens."
            )
        values: dict[str, float | None] = {}
        for key, field in zip(headers, fields, strict=True):
            if field.casefold() == "nan":
                values[key] = None
                continue
            try:
                value = float(field)
            except ValueError as exc:
                raise ProtocolResponseError(f"Item {key} não é numérico.") from exc
            if not math.isfinite(value):
                raise ProtocolResponseError(f"Item {key} não é finito.")
            values[key] = value
        return values


class At4532Normalizer:
    def normalize(self, values: Sequence[float], raw_payload: bytes | None = None) -> DeviceReading:
        if not 1 <= len(values) <= 32:
            raise ValueError("O AT4532 deve fornecer de 1 a 32 canais decodificados.")
        temperatures: list[float | None] = []
        qualities: list[str] = []
        for value in values:
            if -200 <= value <= 1800:
                temperatures.append(float(value))
                qualities.append("good")
            else:
                # The AT45xx manual does not define the open-sensor sentinel.
                temperatures.append(None)
                qualities.append("invalid_out_of_range")
        missing = 32 - len(temperatures)
        temperatures.extend([None] * missing)
        qualities.extend(["missing"] * missing)
        return DeviceReading(
            raw_power=0,
            raw_power_unit="W",
            power_w=0,
            temperatures_c=temperatures,
            channel_quality=qualities,
            quality="missing" if any(value is None for value in temperatures) else "good",
            raw_payload={
                "response_ascii": raw_payload.decode("ascii", "backslashreplace")
                if raw_payload
                else "",
                "response_hex": raw_payload.hex(" ").upper() if raw_payload else "",
                "open_sensor_encoding": "protocol_documentation_required",
            },
        )


class Gpm8213Normalizer:
    def normalize(
        self,
        values: Mapping[str, float | None],
        units: Mapping[str, str],
        raw_payload: Mapping[str, Any] | None = None,
    ) -> DeviceReading:
        power = values.get("power")
        raw_power_unit = units["power"]
        factor = {"mW": 0.001, "W": 1.0, "kW": 1000.0}.get(raw_power_unit)
        if factor is None:
            raise ProtocolResponseError(f"Unidade de potência inesperada: {raw_power_unit}")
        return DeviceReading(
            raw_power=float(power) if power is not None else None,
            raw_power_unit=raw_power_unit,
            power_w=float(power) * factor if power is not None else None,
            temperatures_c=[],
            voltage_v=_optional_float(values, "voltage"),
            current_a=_optional_float(values, "current"),
            apparent_power_va=_optional_float(values, "apparent_power"),
            reactive_power_var=_optional_float(values, "reactive_power"),
            power_factor=_optional_float(values, "power_factor"),
            voltage_frequency_hz=_optional_float(values, "voltage_frequency"),
            current_frequency_hz=_optional_float(values, "current_frequency"),
            raw_values=dict(values),
            raw_units=dict(units),
            raw_payload=dict(raw_payload or {}),
            quality="missing" if any(value is None for value in values.values()) else "good",
        )


def _optional_float(values: Mapping[str, float | None], key: str) -> float | None:
    value = values.get(key)
    return float(value) if value is not None else None


class _DocumentedProtocolAdapter(DeviceAdapter):
    equipment: str
    manufacturer: str
    model: str
    expected_interval_seconds: float
    protocol: Any
    parser: Any
    normalizer: Any

    def __init__(
        self, port: str | None, baud_rate: int | None, transport: SerialTransport | None = None
    ) -> None:
        self.port = port
        self.baud_rate = baud_rate
        self.transport = transport
        self.last_message_at: datetime | None = None
        self.read_errors = 0
        self._reading = False
        self._identity: dict[str, str] = {}
        self.transactions: list[dict[str, Any]] = []
        self._connected_at = 0.0
        self._read_count = 0
        self.serial_open_boundary: dict[str, Any] = {}

    def _configuration(self) -> SerialTransportConfiguration:
        raise NotImplementedError

    def _transport(self, configuration: SerialTransportConfiguration) -> SerialTransport:
        raise NotImplementedError

    async def _transaction(self, command: DocumentedCommand, *, expect_response: bool) -> bytes:
        if not command.vendor_documented:
            raise ProtocolDocumentationRequired(command.name)
        if not self.transport:
            raise SerialTransportError("disconnected", "O equipamento foi desconectado.")
        timestamp = datetime.now(UTC)
        previous_command = (
            self.transactions[-1]["command_name"] if self.transactions else None
        )
        logger.info("protocol TX equipment=%s command=%s", self.equipment, command.name)
        if expect_response:
            response, elapsed_ms = await self.transport.query(
                command.request, command.response_terminator
            )
        else:
            _, elapsed_ms = await self.transport.write(command.request)
            response = b""
        logger.info(
            "protocol RX equipment=%s command=%s length=%s elapsed_ms=%.2f",
            self.equipment,
            command.name,
            len(response),
            elapsed_ms,
        )
        transaction = {
            "command_name": command.name,
            "vendor_documented": True,
            "source": command.source,
            "section": command.section,
            "tx_ascii": command.request.decode("ascii")
            .replace("\r", "\\r")
            .replace("\n", "\\n"),
            "tx_hex": command.request.hex(" ").upper(),
            "timestamp_tx": timestamp.isoformat(),
            "rx_ascii": response.decode("ascii", "backslashreplace")
            .replace("\r", "\\r")
            .replace("\n", "\\n"),
            "rx_hex": response.hex(" ").upper(),
            "timestamp_rx": datetime.now(UTC).isoformat(),
            "elapsed_ms": round(elapsed_ms, 3),
            "bytes_received": len(response),
            "previous_command": previous_command,
        }
        if expect_response:
            boundary = dict(getattr(self.transport, "last_query_boundary", {}))
            transaction["transaction_boundary"] = boundary
            actual_response_type = self._response_type(response)
            transaction["expected_for_command"] = command.expected_response_type
            transaction["actual_response_type"] = actual_response_type
            logger.info(
                "response classification equipment=%s command=%s expected=%s actual=%s",
                self.equipment,
                command.name,
                command.expected_response_type,
                actual_response_type,
            )
            if boundary.get("pending_before_tx_bytes", 0):
                logger.warning(
                    "stale RX drained equipment=%s command=%s bytes=%s",
                    self.equipment,
                    command.name,
                    boundary["pending_before_tx_bytes"],
                )
        else:
            actual_response_type = None
        self.transactions.append(transaction)
        if (
            command.expected_response_type
            and actual_response_type != command.expected_response_type
        ):
            transaction["possible_stale_response"] = actual_response_type == "identity_response"
            logger.error(
                "response classification error equipment=%s command=%s expected=%s actual=%s",
                self.equipment,
                command.name,
                command.expected_response_type,
                actual_response_type,
            )
            raise UnexpectedResponseTypeError(
                expected=command.expected_response_type,
                actual=actual_response_type or "unclassified_response",
                command=command.name,
                previous_command=previous_command,
                raw_response=response,
            )
        return response

    def _response_type(self, payload: bytes) -> str | None:
        return None

    async def connect(self) -> None:
        if not self.port:
            raise SerialTransportError("port_not_found", "Porta serial não associada.")
        configuration = self._configuration()
        self.transport = self.transport or self._transport(configuration)
        elapsed_ms = await self.transport.open()
        self.serial_open_boundary = dict(getattr(self.transport, "open_boundary", {}))
        self._connected_at = monotonic()
        logger.info(
            "COM open equipment=%s port=%s serial_parameters=%s "
            "pending_input_bytes=%s elapsed_ms=%.2f",
            self.equipment,
            self.port,
            configuration.public_dict(),
            self.serial_open_boundary.get("pending_input_bytes", 0),
            elapsed_ms,
        )
        try:
            payload = await self._transaction(self.protocol.identity, expect_response=True)
            self._identity = self.parser.parse_identity(payload)
            logger.info("parser success equipment=%s command=identity", self.equipment)
            await self._after_identity()
        except Exception:
            logger.exception("parser/protocol error equipment=%s command=identity", self.equipment)
            await self.disconnect()
            raise

    async def _after_identity(self) -> None:
        return None

    async def disconnect(self) -> None:
        self._reading = False
        if self.transport:
            await self.transport.close()
        logger.info("COM close equipment=%s port=%s", self.equipment, self.port)

    async def stop_reading(self) -> None:
        self._reading = False

    async def _read_once(self) -> DeviceReading:
        raise NotImplementedError

    async def read_once(self) -> DeviceReading:
        """Execute one documented query without starting the polling loop."""
        reading = await self._read_once()
        self.last_message_at = reading.timestamp
        self._read_count += 1
        return reading

    async def start_reading(self) -> AsyncIterator[DeviceReading]:
        self._reading = True
        logger.info("acquisition started equipment=%s", self.equipment)
        try:
            while self._reading:
                started = monotonic()
                try:
                    reading = await self._read_once()
                except SerialTransportError as exc:
                    self.read_errors += 1
                    logger.warning(
                        "disconnect equipment=%s code=%s; reconnect scheduled",
                        self.equipment,
                        exc.code,
                    )
                    if not self._reading:
                        break
                    try:
                        if self.transport:
                            await self.transport.close()
                        await asyncio.sleep(1)
                        if self._reading:
                            await self.connect()
                            logger.info("reconnect equipment=%s port=%s", self.equipment, self.port)
                    except Exception:
                        logger.exception("reconnect failed equipment=%s", self.equipment)
                        await asyncio.sleep(1)
                    continue
                except Exception:
                    self.read_errors += 1
                    logger.exception("parser error equipment=%s", self.equipment)
                    raise
                self.last_message_at = reading.timestamp
                self._read_count += 1
                yield reading
                remaining = self.expected_interval_seconds - (monotonic() - started)
                if remaining > 0:
                    await asyncio.sleep(remaining)
        finally:
            logger.info("acquisition stopped equipment=%s", self.equipment)

    def parse_message(self, raw: bytes | str) -> DeviceReading:
        payload = raw.encode("ascii") if isinstance(raw, str) else raw
        return self._normalize_payload(payload)

    def _normalize_payload(self, payload: bytes) -> DeviceReading:
        raise NotImplementedError

    async def get_status(self) -> DeviceStatus:
        connected = bool(self.transport and self.transport.is_open)
        elapsed = monotonic() - self._connected_at if self._connected_at else 0
        return DeviceStatus(
            state="connected" if connected else "disconnected",
            connected=connected,
            reading=self._reading,
            last_message_at=self.last_message_at,
            messages_per_second=self._read_count / elapsed if elapsed else 0,
            read_errors=self.read_errors,
        )

    async def get_device_information(self) -> DeviceInformation:
        return DeviceInformation(
            adapter=type(self).__name__,
            manufacturer=self._identity.get("manufacturer", self.manufacturer),
            model=self._identity.get("model", self.model),
            serial_number=self._identity.get("serial_number"),
            firmware_version=self._identity.get("firmware_version")
            or self._identity.get("revision"),
            capabilities={
                "port": self.port,
                "baud_rate": self.baud_rate,
                "expected_interval_seconds": self.expected_interval_seconds,
                "protocol_status": "vendor_documented",
                "physical_validation": "pending",
                "source": self.protocol.identity.source,
            },
        )


class At4532SerialAdapter(_DocumentedProtocolAdapter):
    equipment = "Applent AT4532"
    manufacturer = "Applent Instruments"
    model = "AT4532"
    expected_interval_seconds = 3.0
    protocol = At4532Protocol()
    parser = At4532Parser()
    normalizer = At4532Normalizer()

    def _configuration(self) -> SerialTransportConfiguration:
        if self.baud_rate != 19200:
            raise ValueError("O AT4532 LAB deve usar o baud 19200 confirmado no instrumento.")
        return SerialTransportConfiguration(
            port=self.port or "",
            baud_rate=19200,
            data_bits=8,
            parity="N",
            stop_bits=1,
            timeout_s=1,
            read_timeout_s=2,
            line_terminator="LF (0x0A)",
            framing="SCPI ASCII",
        )

    def _transport(self, configuration: SerialTransportConfiguration) -> SerialTransport:
        return At4532SerialTransport(configuration)

    def _normalize_payload(self, payload: bytes) -> DeviceReading:
        return self.normalizer.normalize(self.parser.parse(payload), payload)

    async def _after_identity(self) -> None:
        await self._transaction(self.protocol.celsius, expect_response=False)

    async def _read_once(self) -> DeviceReading:
        payload = await self._transaction(self.protocol.temperatures, expect_response=True)
        reading = self._normalize_payload(payload)
        self.transactions[-1]["parsed"] = reading.model_dump(mode="json")
        logger.info("parser success equipment=%s command=temperatures", self.equipment)
        return reading


class Gpm8213UsbSerialAdapter(_DocumentedProtocolAdapter):
    equipment = "GW Instek GPM-8213"
    manufacturer = "GW Instek"
    model = "GPM-8213"
    expected_interval_seconds = 1.0
    protocol = Gpm8213Protocol()
    parser = Gpm8213Parser()
    normalizer = Gpm8213Normalizer()

    def __init__(
        self, port: str | None, baud_rate: int | None, transport: SerialTransport | None = None
    ) -> None:
        super().__init__(port, baud_rate, transport)
        self.number_requested = 8
        self.number_reported: int | None = None
        self.headers_requested = list(self.protocol.item_functions)
        self.headers_reported: list[str] = []
        self._headers: list[str] = []

    def _configuration(self) -> SerialTransportConfiguration:
        # USB is documented as CDC and does not expose a baud setting in the USB table.
        # 9600 is the documented RS-232 default and is only a host API placeholder for CDC.
        host_baud = self.baud_rate or 9600
        return SerialTransportConfiguration(
            port=self.port or "",
            baud_rate=host_baud,
            data_bits=8,
            parity="N",
            stop_bits=1,
            timeout_s=1,
            read_timeout_s=2,
            line_terminator="CR+LF (0x0D 0x0A)",
            framing="SCPI ASCII over USB CDC",
        )

    def _transport(self, configuration: SerialTransportConfiguration) -> SerialTransport:
        return Gpm8213SerialTransport(configuration)

    async def _after_identity(self) -> None:
        await self._transaction(self.protocol.number_set, expect_response=False)
        count_payload = await self._transaction(self.protocol.number_query, expect_response=True)
        self.number_reported = self.parser.parse_item_count(count_payload)
        self.transactions[-1]["parsed"] = {
            "number_requested": self.number_requested,
            "number_reported": self.number_reported,
            "headers_requested": self.headers_requested,
        }
        if self.number_reported != self.number_requested:
            raise ProtocolResponseError(
                f"Quantidade NUMERIC não aceita: requested={self.number_requested}, "
                f"reported={self.number_reported}."
            )
        for command in self.protocol.items:
            await self._transaction(command, expect_response=False)
        header_payload = await self._transaction(self.protocol.header_query, expect_response=True)
        self.headers_reported = [
            field.strip() for field in _single_ascii_line(header_payload, b"\r\n").split(",")
        ]
        self._headers = self.parser.parse_headers(header_payload, self.number_reported)
        self.transactions[-1]["parsed"] = {
            "number_requested": self.number_requested,
            "number_reported": self.number_reported,
            "headers_requested": self.headers_requested,
            "headers_reported": self.headers_reported,
            "canonical_headers": self._headers,
        }

    def _response_type(self, payload: bytes) -> str | None:
        return self.parser.classify(payload)

    def _normalize_payload(self, payload: bytes) -> DeviceReading:
        if not self._headers:
            raise ProtocolResponseError("HEADER? deve ser validado antes de VALUE?.")
        parsed = self.parser.parse(payload, self._headers)
        raw_fields = [
            field.strip() for field in _single_ascii_line(payload, b"\r\n").split(",")
        ]
        raw_values = dict(zip(self.headers_reported, raw_fields, strict=True))
        parsed_values = {
            "Vrms": parsed.get("voltage"),
            "Irms": parsed.get("current"),
            "P": parsed.get("power"),
            "VA": parsed.get("apparent_power"),
            "VHz": parsed.get("voltage_frequency"),
            "PF": parsed.get("power_factor"),
            "VAR": parsed.get("reactive_power"),
            "IHz": parsed.get("current_frequency"),
        }
        return self.normalizer.normalize(
            parsed,
            self.parser.units,
            {
                "response_ascii": payload.decode("ascii", "backslashreplace"),
                "response_hex": payload.hex(" ").upper(),
                "number_requested": self.number_requested,
                "number_reported": self.number_reported,
                "headers_requested": self.headers_requested,
                "headers_reported": self.headers_reported,
                "raw_values": raw_values,
                "parsed_values": parsed_values,
            },
        )

    async def _read_once(self) -> DeviceReading:
        payload = await self._transaction(self.protocol.measurements, expect_response=True)
        reading = self._normalize_payload(payload)
        self.transactions[-1]["parsed"] = {
            "number_requested": self.number_requested,
            "number_reported": self.number_reported,
            "headers_requested": self.headers_requested,
            "headers_reported": self.headers_reported,
            "raw_values": reading.raw_payload["raw_values"],
            "parsed_values": reading.raw_payload["parsed_values"],
            "normalized_reading": reading.model_dump(mode="json"),
        }
        values = reading.raw_payload["parsed_values"]
        logger.info(
            "GPM measurement Vrms=%s Irms=%s P=%s VA=%s VHz=%s PF=%s VAR=%s IHz=%s",
            values["Vrms"],
            values["Irms"],
            values["P"],
            values["VA"],
            values["VHz"],
            values["PF"],
            values["VAR"],
            values["IHz"],
        )
        logger.info("parser success equipment=%s command=measurements", self.equipment)
        return reading


At4532Adapter = At4532SerialAdapter
Gpm8213Adapter = Gpm8213UsbSerialAdapter


def transport_configuration_from_metadata(
    port: str, baud_rate: int, metadata: Mapping[str, Any]
) -> SerialTransportConfiguration | None:
    serial_settings = metadata.get("serial", {})
    required = ("data_bits", "parity", "stop_bits", "timeout_s", "read_timeout_s")
    if any(serial_settings.get(key) is None for key in required):
        return None
    return SerialTransportConfiguration(
        port=port,
        baud_rate=baud_rate,
        data_bits=int(serial_settings["data_bits"]),
        parity=str(serial_settings["parity"]),
        stop_bits=float(serial_settings["stop_bits"]),
        timeout_s=float(serial_settings["timeout_s"]),
        read_timeout_s=float(serial_settings["read_timeout_s"]),
        line_terminator=serial_settings.get("line_terminator"),
        framing=serial_settings.get("framing"),
    )
