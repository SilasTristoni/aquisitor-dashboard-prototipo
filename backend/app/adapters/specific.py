"""Reviewed AT4532 and GPM-8213 serial integrations.

Commands remain vendor documented. Response handling also covers the physically observed GPM
SCPI abbreviation and the AT4532 TCP-32 CP936 frame without lossy decoding. Final homologation of
values on the client instruments remains an explicit engineering step.
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
from zoneinfo import ZoneInfo

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
        expected_response_type="identity_response",
        purpose="Identificar modelo, revisão, número de série e fabricante.",
    )
    temperatures = DocumentedCommand(
        name="temperatures",
        request=b"FETCH?\n",
        response_terminator=b"\n",
        source=AT4532_MANUAL_URL,
        section="9.1 e 9.5.3.1",
        expected_response_type="temperature_measurement",
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


def _single_line_body(payload: bytes, terminator: bytes) -> bytes:
    if not payload.endswith(terminator):
        raise ProtocolResponseError("Resposta parcial: terminador oficial não recebido.")
    body = payload[: -len(terminator)]
    # The guide specifies LF. Some serial stacks expose a preceding CR; accept
    # that transport variation without accepting additional frames.
    if terminator == b"\n" and body.endswith(b"\r"):
        body = body[:-1]
    if b"\r" in body or b"\n" in body:
        raise ProtocolResponseError("Foram recebidos múltiplos frames em uma única resposta.")
    if any(byte < 0x20 and byte != 0x09 for byte in body):
        raise ProtocolResponseError("Resposta contém caractere de controle inválido.")
    return body


def _single_ascii_line(payload: bytes, terminator: bytes) -> str:
    body = _single_line_body(payload, terminator)
    try:
        return body.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ProtocolResponseError("Resposta não é ASCII, como exige o protocolo.") from exc


def _wire_diagnostics(payload: bytes) -> dict[str, Any]:
    if payload.endswith(b"\r\n"):
        terminator = "CRLF (0x0D 0x0A)"
    elif payload.endswith(b"\n"):
        terminator = "LF (0x0A)"
    elif payload.endswith(b"\r"):
        terminator = "CR (0x0D)"
    else:
        terminator = "none"
    frame_count = payload.count(b"\n")
    if payload and not payload.endswith(b"\n"):
        frame_count += 1
    return {"observed_terminator": terminator, "frame_count": frame_count}


AT4532_CHANNEL_COUNT = 32
AT4532_TCP32_FIELD_COUNT = 69
AT4532_TCP32_CHANNEL_START = 3
AT4532_DEVICE_TIMEZONE = ZoneInfo("America/Sao_Paulo")
_AT4532_TCP32_TIMESTAMP = re.compile(r"T:(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})")


@dataclass(frozen=True)
class At4532ChannelToken:
    position: int
    raw_token: str
    temperature_c: float | None
    quality: str
    thermocouple_type: str | None = None
    unit: str | None = None


@dataclass(frozen=True)
class At4532ParsedFrame(Sequence[float | None]):
    """Lossless, structurally validated representation of one AT4532 response frame."""

    values: tuple[float | None, ...]
    channels: tuple[At4532ChannelToken, ...]
    raw_bytes: bytes
    raw_text: str
    wire_encoding: str
    frame_type: str
    field_count: int
    metadata_fields_raw: tuple[str, ...] = ()
    device_timestamp_raw: str | None = None
    device_timestamp: datetime | None = None
    ambient_temperature_raw: str | None = None
    ambient_temperature_c: float | None = None
    auxiliary_fields_raw: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.values)

    def __getitem__(self, index: int | slice) -> float | None | tuple[float | None, ...]:
        return self.values[index]

    @property
    def raw_hex(self) -> str:
        return self.raw_bytes.hex(" ").upper()


class At4532Parser:
    @staticmethod
    def decode_line(payload: bytes) -> tuple[str, str]:
        """Decode strictly, allowing CP936 only for an unambiguous TCP-32 candidate."""

        body = _single_line_body(payload, b"\n")
        try:
            return body.decode("ascii"), "ascii"
        except UnicodeDecodeError as ascii_error:
            if not body.startswith(b"TCP-32,"):
                raise ProtocolResponseError(
                    "Resposta simples do AT4532 deve usar ASCII estrito."
                ) from ascii_error
            try:
                return body.decode("cp936"), "cp936"
            except UnicodeDecodeError as cp936_error:
                raise ProtocolResponseError(
                    "Frame TCP-32 não pode ser decodificado estritamente como CP936."
                ) from cp936_error

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

    def classify(self, payload: bytes) -> str:
        try:
            self.parse_identity(payload)
            return "identity_response"
        except ProtocolResponseError:
            pass
        try:
            self.parse(payload)
            return "temperature_measurement"
        except ProtocolResponseError:
            return "unknown_response"

    def parse(self, payload: bytes) -> At4532ParsedFrame:
        line, wire_encoding = self.decode_line(payload)
        if line.lstrip().startswith("TCP-32,"):
            return self._parse_tcp32(payload, line, wire_encoding)
        return self._parse_simple(payload, line, wire_encoding)

    def _parse_simple(self, payload: bytes, line: str, wire_encoding: str) -> At4532ParsedFrame:
        fields = line.strip().split(",")
        if not 1 <= len(fields) <= 32:
            raise ProtocolResponseError("FETCH? deve retornar entre 1 e 32 campos.")
        values: list[float | None] = []
        channels: list[At4532ChannelToken] = []
        for position, field in enumerate(fields, 1):
            raw_token = field
            try:
                value = float(field.strip())
            except ValueError:
                value = None
            normalized = value if value is not None and math.isfinite(value) else None
            values.append(normalized)
            channels.append(
                At4532ChannelToken(
                    position=position,
                    raw_token=raw_token,
                    temperature_c=normalized,
                    quality="good" if normalized is not None else "unknown_unavailable",
                )
            )
        if not any(value is not None for value in values):
            raise ProtocolResponseError(
                "FETCH? simples deve conter ao menos uma temperatura numérica finita."
            )
        return At4532ParsedFrame(
            values=tuple(values),
            channels=tuple(channels),
            raw_bytes=payload,
            raw_text=line,
            wire_encoding=wire_encoding,
            frame_type="simple",
            field_count=len(fields),
        )

    def _parse_tcp32(self, payload: bytes, line: str, wire_encoding: str) -> At4532ParsedFrame:
        fields = line.split(",")
        if len(fields) != AT4532_TCP32_FIELD_COUNT:
            raise ProtocolResponseError(
                "Frame TCP-32 deve conter exatamente 69 campos conceituais."
            )
        if fields[0].strip() != "TCP-32":
            raise ProtocolResponseError("Prefixo do frame TCP-32 inválido.")

        device_timestamp_raw = fields[1].strip()
        timestamp_match = _AT4532_TCP32_TIMESTAMP.fullmatch(device_timestamp_raw)
        if not timestamp_match:
            raise ProtocolResponseError("Timestamp estrutural do frame TCP-32 inválido.")
        try:
            local_timestamp = datetime.strptime(
                timestamp_match.group(1), "%Y/%m/%d %H:%M:%S"
            ).replace(tzinfo=AT4532_DEVICE_TIMEZONE)
        except ValueError as exc:
            raise ProtocolResponseError("Timestamp do frame TCP-32 não é uma data válida.") from exc
        device_timestamp = local_timestamp.astimezone(UTC)

        ambient_temperature_raw = fields[2].strip()
        try:
            ambient_temperature_c = float(ambient_temperature_raw)
        except ValueError as exc:
            raise ProtocolResponseError(
                "Metadado ambiente do frame TCP-32 não é numérico."
            ) from exc
        if not math.isfinite(ambient_temperature_c):
            raise ProtocolResponseError("Metadado ambiente do frame TCP-32 não é finito.")

        primary_fields = fields[
            AT4532_TCP32_CHANNEL_START : AT4532_TCP32_CHANNEL_START + AT4532_CHANNEL_COUNT
        ]
        if len(primary_fields) != AT4532_CHANNEL_COUNT:
            raise ProtocolResponseError("Bloco primário TCP-32 não contém 32 canais.")

        channels: list[At4532ChannelToken] = []
        values: list[float | None] = []
        valid_channels = 0
        for position, raw_token in enumerate(primary_fields, 1):
            token_fields = raw_token.split("|")
            if len(token_fields) != 3:
                raise ProtocolResponseError(
                    f"Token TCP-32 CH{position:02d} não possui valor, tipo e unidade."
                )
            value_text, thermocouple_type, unit = (item.strip() for item in token_fields)
            if thermocouple_type != "K":
                raise ProtocolResponseError(
                    f"Token TCP-32 CH{position:02d} não usa o tipo de termopar K comprovado."
                )
            if unit != "℃":
                raise ProtocolResponseError(
                    f"Token TCP-32 CH{position:02d} não informa a unidade Celsius comprovada."
                )
            if value_text.casefold() == "open":
                value = None
                quality = "open_sensor"
            else:
                try:
                    value = float(value_text)
                except ValueError as exc:
                    raise ProtocolResponseError(
                        f"Valor TCP-32 CH{position:02d} não é numérico nem Open."
                    ) from exc
                if not math.isfinite(value):
                    raise ProtocolResponseError(f"Valor TCP-32 CH{position:02d} não é finito.")
                quality = "good" if -200 <= value <= 1800 else "invalid_out_of_range"
                if quality == "good":
                    valid_channels += 1
            values.append(value)
            channels.append(
                At4532ChannelToken(
                    position=position,
                    raw_token=raw_token,
                    temperature_c=value,
                    quality=quality,
                    thermocouple_type=thermocouple_type,
                    unit=unit,
                )
            )
        if valid_channels < 1:
            raise ProtocolResponseError(
                "Frame TCP-32 deve conter ao menos uma temperatura numérica válida."
            )

        return At4532ParsedFrame(
            values=tuple(values),
            channels=tuple(channels),
            raw_bytes=payload,
            raw_text=line,
            wire_encoding=wire_encoding,
            frame_type="TCP-32",
            field_count=len(fields),
            metadata_fields_raw=tuple(fields[:AT4532_TCP32_CHANNEL_START]),
            device_timestamp_raw=device_timestamp_raw,
            device_timestamp=device_timestamp,
            ambient_temperature_raw=ambient_temperature_raw,
            ambient_temperature_c=ambient_temperature_c,
            auxiliary_fields_raw=tuple(fields[AT4532_TCP32_CHANNEL_START + AT4532_CHANNEL_COUNT :]),
        )


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
        match = re.fullmatch(
            r"(?:(?::NUMERIC:NORMAL:NUMBER|:NUM:NORM:NUMB)\s+)?(\d+)",
            line,
            re.IGNORECASE,
        )
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

    def parse(self, payload: bytes, headers: Sequence[str]) -> Mapping[str, float | None]:
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
    def normalize(
        self,
        values: At4532ParsedFrame | Sequence[float | None],
        raw_payload: bytes | None = None,
    ) -> DeviceReading:
        received_timestamp = datetime.now(UTC)
        if not 1 <= len(values) <= 32:
            raise ValueError("O AT4532 deve fornecer de 1 a 32 canais decodificados.")
        parsed_frame = values if isinstance(values, At4532ParsedFrame) else None
        if parsed_frame is not None:
            raw_payload = parsed_frame.raw_bytes
            source_channels = list(parsed_frame.channels)
            raw_tokens = [channel.raw_token for channel in source_channels]
        else:
            source_channels = []
            raw_tokens: list[str] = []
            if raw_payload:
                try:
                    candidate_tokens = _single_ascii_line(raw_payload, b"\n").split(",")
                    if len(candidate_tokens) == len(values):
                        raw_tokens = candidate_tokens
                except ProtocolResponseError:
                    pass
            if not raw_tokens:
                raw_tokens = ["" if value is None else str(value) for value in values]
            source_channels = [
                At4532ChannelToken(
                    position=index,
                    raw_token=raw_token,
                    temperature_c=value,
                    quality="good" if value is not None else "unknown_unavailable",
                )
                for index, (value, raw_token) in enumerate(zip(values, raw_tokens, strict=True), 1)
            ]

        temperatures: list[float | None] = []
        qualities: list[str] = []
        channels: list[dict[str, Any]] = []
        unknown_tokens: list[dict[str, Any]] = []
        open_channels: list[str] = []
        for source_channel in source_channels:
            index = source_channel.position
            value = source_channel.temperature_c
            channel_name = f"CH{index:02d}"
            if value is None:
                normalized = None
                quality = source_channel.quality
                if quality == "open_sensor":
                    open_channels.append(channel_name)
                else:
                    quality = "unknown_unavailable"
                    unknown_tokens.append(
                        {"channel": channel_name, "raw_token": source_channel.raw_token}
                    )
            elif -200 <= value <= 1800:
                normalized = float(value)
                quality = "good"
            else:
                # The AT45xx manual does not define the open-sensor sentinel.
                normalized = None
                quality = "invalid_out_of_range"
            temperatures.append(normalized)
            qualities.append(quality)
            channels.append(
                {
                    "channel": channel_name,
                    "position": index,
                    "raw_token": source_channel.raw_token,
                    "temperature_c": normalized,
                    "quality": quality,
                    "thermocouple_type": source_channel.thermocouple_type,
                    "unit": source_channel.unit,
                }
            )
        missing = 32 - len(temperatures)
        temperatures.extend([None] * missing)
        qualities.extend(["missing"] * missing)
        for index in range(len(channels) + 1, 33):
            channels.append(
                {
                    "channel": f"CH{index:02d}",
                    "position": index,
                    "raw_token": None,
                    "temperature_c": None,
                    "quality": "missing",
                    "thermocouple_type": None,
                    "unit": None,
                }
            )
        valid_channels = sum(value is not None for value in temperatures)
        payload = raw_payload or b""
        if parsed_frame is not None:
            response_text = payload.decode(parsed_frame.wire_encoding)
            wire_encoding = parsed_frame.wire_encoding
        else:
            try:
                response_text = payload.decode("ascii")
                wire_encoding = "ascii"
            except UnicodeDecodeError:
                response_text = payload.decode("ascii", "backslashreplace")
                wire_encoding = "undecodable"
        raw_data = {
            "response_ascii": response_text,
            "response_text": response_text,
            "response_bytes": list(payload),
            "raw_bytes": list(payload),
            "response_hex": payload.hex(" ").upper(),
            "raw_hex": payload.hex(" ").upper(),
            "wire_encoding": wire_encoding,
            "frame_type": parsed_frame.frame_type if parsed_frame else "simple",
            "total_fields": parsed_frame.field_count if parsed_frame else len(values),
            "metadata_fields_raw": list(parsed_frame.metadata_fields_raw) if parsed_frame else [],
            "device_timestamp_raw": parsed_frame.device_timestamp_raw if parsed_frame else None,
            "device_timestamp_iso": parsed_frame.device_timestamp.isoformat()
            if parsed_frame and parsed_frame.device_timestamp
            else None,
            "device_timestamp_timezone_assumption": "America/Sao_Paulo"
            if parsed_frame and parsed_frame.device_timestamp
            else None,
            "ambient_temperature_raw": parsed_frame.ambient_temperature_raw
            if parsed_frame
            else None,
            "ambient_temperature_c": parsed_frame.ambient_temperature_c if parsed_frame else None,
            "primary_channel_fields_raw": raw_tokens,
            "auxiliary_fields_raw": list(parsed_frame.auxiliary_fields_raw) if parsed_frame else [],
            "channel_count_requested": 32,
            "channel_count_received": len(values),
            "token_count": len(raw_tokens),
            "tokens": raw_tokens,
            "valid_channels": valid_channels,
            "unavailable_channels": 32 - valid_channels,
            "open_channels": open_channels,
            "channels": channels,
            "valid_channel_results": {
                channel["channel"]: channel
                for channel in channels
                if channel["temperature_c"] is not None
            },
            "unknown_tokens": unknown_tokens,
            "open_sensor_encoding": (
                "verified_tcp32_open_token"
                if parsed_frame and parsed_frame.frame_type == "TCP-32"
                else "protocol_documentation_required"
            ),
            **_wire_diagnostics(payload),
        }
        return DeviceReading(
            timestamp=(
                parsed_frame.device_timestamp
                if parsed_frame and parsed_frame.device_timestamp
                else received_timestamp
            ),
            device_timestamp=(parsed_frame.device_timestamp if parsed_frame else None),
            received_timestamp=received_timestamp,
            raw_power=None,
            raw_power_unit="W",
            power_w=None,
            temperatures_c=temperatures,
            channel_quality=qualities,
            ambient_temperature_c=(
                parsed_frame.ambient_temperature_c if parsed_frame else None
            ),
            quality="good" if valid_channels else "unavailable",
            raw_payload=raw_data,
        )


class Gpm8213Normalizer:
    def normalize(
        self,
        values: Mapping[str, float | None],
        units: Mapping[str, str],
        raw_payload: Mapping[str, Any] | None = None,
    ) -> DeviceReading:
        received_timestamp = datetime.now(UTC)
        power = values.get("power")
        raw_power_unit = units["power"]
        factor = {"mW": 0.001, "W": 1.0, "kW": 1000.0}.get(raw_power_unit)
        if factor is None:
            raise ProtocolResponseError(f"Unidade de potência inesperada: {raw_power_unit}")
        return DeviceReading(
            timestamp=received_timestamp,
            received_timestamp=received_timestamp,
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
        self.identity_status = "not_attempted"
        self.protocol_status = "not_verified"
        self.identity_error: dict[str, Any] | None = None

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
        transaction_started = monotonic()
        previous_command = self.transactions[-1]["command_name"] if self.transactions else None
        logger.info("protocol TX equipment=%s command=%s", self.equipment, command.name)
        try:
            if expect_response:
                response, elapsed_ms = await self.transport.query(
                    command.request, command.response_terminator
                )
            else:
                _, elapsed_ms = await self.transport.write(command.request)
                response = b""
        except SerialTransportError as exc:
            elapsed_ms = (monotonic() - transaction_started) * 1000
            boundary = dict(getattr(self.transport, "last_query_boundary", {}))
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
                "rx_ascii": "",
                "rx_bytes": [],
                "rx_hex": "",
                "timestamp_rx": datetime.now(UTC).isoformat(),
                "elapsed_ms": round(elapsed_ms, 3),
                "bytes_received": 0,
                "previous_command": previous_command,
                "transaction_boundary": boundary,
                "expected_for_command": command.expected_response_type,
                "actual_response_type": "no_response",
                "observed_terminator": "none",
                "frame_count": 0,
                "error": {"code": exc.code, "message": str(exc)},
            }
            self.transactions.append(transaction)
            logger.warning(
                "protocol timeout/error equipment=%s command=%s code=%s elapsed_ms=%.2f",
                self.equipment,
                command.name,
                exc.code,
                elapsed_ms,
            )
            raise
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
            "tx_ascii": command.request.decode("ascii").replace("\r", "\\r").replace("\n", "\\n"),
            "tx_hex": command.request.hex(" ").upper(),
            "timestamp_tx": timestamp.isoformat(),
            "rx_ascii": response.decode("ascii", "backslashreplace")
            .replace("\r", "\\r")
            .replace("\n", "\\n"),
            "rx_bytes": list(response),
            "rx_hex": response.hex(" ").upper(),
            "timestamp_rx": datetime.now(UTC).isoformat(),
            "elapsed_ms": round(elapsed_ms, 3),
            "bytes_received": len(response),
            "previous_command": previous_command,
            **_wire_diagnostics(response),
            **self._wire_response_diagnostics(response),
        }
        if expect_response:
            boundary = dict(getattr(self.transport, "last_query_boundary", {}))
            transaction["transaction_boundary"] = boundary
            actual_response_type = self._response_type(response)
            transaction["expected_for_command"] = command.expected_response_type
            transaction["actual_response_type"] = actual_response_type
            parser_error = getattr(self, "_last_response_parser_error", None)
            if parser_error:
                transaction["parser_error"] = parser_error
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

    def _wire_response_diagnostics(self, payload: bytes) -> dict[str, Any]:
        return {}

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
            self._identity = {}
            self.identity_status = "not_attempted"
            self.protocol_status = "not_verified"
            self.identity_error = None
            try:
                payload = await self._transaction(self.protocol.identity, expect_response=True)
                self._identity = self.parser.parse_identity(payload)
                self.identity_status = "confirmed"
                self.protocol_status = "identity_verified"
                logger.info("parser success equipment=%s command=identity", self.equipment)
            except SerialTransportError as exc:
                self.identity_status = "unconfirmed"
                self.identity_error = {"code": exc.code, "message": str(exc)}
                if not await self._continue_after_identity_error(exc):
                    raise
                logger.warning(
                    "identity unconfirmed; documented measurement verification allowed "
                    "equipment=%s port=%s",
                    self.equipment,
                    self.port,
                )
            await self._after_identity()
        except Exception:
            logger.exception("parser/protocol error equipment=%s command=identity", self.equipment)
            await self.disconnect()
            raise

    async def _continue_after_identity_error(self, exc: SerialTransportError) -> bool:
        return False

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
        self.last_message_at = reading.received_timestamp
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
                self.last_message_at = reading.received_timestamp
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
                "connection_protocol_status": self.protocol_status,
                "identity_status": self.identity_status,
                "identity_error": self.identity_error,
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

    def __init__(
        self,
        port: str | None,
        baud_rate: int | None,
        transport: SerialTransport | None = None,
        *,
        allow_identity_fallback: bool = False,
        association_source: str | None = None,
    ) -> None:
        super().__init__(port, baud_rate, transport)
        self.allow_identity_fallback = allow_identity_fallback
        self.association_source = association_source
        self._primed_reading: DeviceReading | None = None

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
            framing="SCPI ASCII TX; ASCII simple or TCP-32 CP936 RX",
        )

    def _transport(self, configuration: SerialTransportConfiguration) -> SerialTransport:
        return At4532SerialTransport(configuration)

    def _response_type(self, payload: bytes) -> str | None:
        self._last_response_parser_error = None
        try:
            self.parser.parse_identity(payload)
            return "identity_response"
        except ProtocolResponseError:
            pass
        try:
            self.parser.parse(payload)
            return "temperature_measurement"
        except ProtocolResponseError as exc:
            self._last_response_parser_error = {"code": exc.code, "message": str(exc)}
            return "unknown_response"

    def _wire_response_diagnostics(self, payload: bytes) -> dict[str, Any]:
        try:
            decoded, encoding = self.parser.decode_line(payload)
        except ProtocolResponseError as exc:
            return {
                "wire_encoding": "undecodable",
                "wire_decode_error": {"code": exc.code, "message": str(exc)},
            }
        return {
            "wire_encoding": encoding,
            "rx_text": decoded.replace("\r", "\\r").replace("\n", "\\n"),
        }

    async def _continue_after_identity_error(self, exc: SerialTransportError) -> bool:
        return self.allow_identity_fallback and exc.code == "protocol_timeout"

    def _normalize_payload(self, payload: bytes) -> DeviceReading:
        return self.normalizer.normalize(self.parser.parse(payload), payload)

    async def _after_identity(self) -> None:
        self._primed_reading = None
        await self._transaction(self.protocol.celsius, expect_response=False)

        if self.identity_status == "unconfirmed":
            reading = await self._query_reading()
            received = reading.raw_payload["channel_count_received"]
            valid = reading.raw_payload["valid_channels"]
            if received != 32 or valid < 1:
                raise ProtocolResponseError(
                    "Fallback de identidade exige FETCH? válido com 32 canais e ao menos "
                    "uma temperatura numérica."
                )
            self.protocol_status = "verified_by_measurement"
            self._primed_reading = reading

    async def _query_reading(self) -> DeviceReading:
        payload = await self._transaction(self.protocol.temperatures, expect_response=True)
        reading = self._normalize_payload(payload)
        raw = reading.raw_payload
        if raw["channel_count_received"] == 32 and raw["valid_channels"] >= 1:
            self.protocol_status = "verified_by_measurement"
        self.transactions[-1].update(
            {
                "wire_encoding": raw["wire_encoding"],
                "rx_text": raw["response_text"].replace("\r", "\\r").replace("\n", "\\n"),
                "frame_type": raw["frame_type"],
                "total_fields": raw["total_fields"],
            }
        )
        self.transactions[-1]["parsed"] = {
            "channel_count_requested": 32,
            "channel_count_received": raw["channel_count_received"],
            "token_count": raw["token_count"],
            "tokens": raw["tokens"],
            "valid_channels": raw["valid_channels"],
            "unavailable_channels": raw["unavailable_channels"],
            "open_channels": raw["open_channels"],
            "channels": raw["channels"],
            "valid_channel_results": raw["valid_channel_results"],
            "unknown_tokens": raw["unknown_tokens"],
            "wire_encoding": raw["wire_encoding"],
            "frame_type": raw["frame_type"],
            "total_fields": raw["total_fields"],
            "metadata_fields_raw": raw["metadata_fields_raw"],
            "device_timestamp_raw": raw["device_timestamp_raw"],
            "device_timestamp_iso": raw["device_timestamp_iso"],
            "ambient_temperature_raw": raw["ambient_temperature_raw"],
            "ambient_temperature_c": raw["ambient_temperature_c"],
            "primary_channel_fields_raw": raw["primary_channel_fields_raw"],
            "auxiliary_fields_raw": raw["auxiliary_fields_raw"],
            "raw_bytes": raw["raw_bytes"],
            "raw_hex": raw["raw_hex"],
            "observed_terminator": raw["observed_terminator"],
            "frame_count": raw["frame_count"],
            "normalized_reading": reading.model_dump(mode="json"),
        }
        logger.info("parser success equipment=%s command=temperatures", self.equipment)
        return reading

    async def _read_once(self) -> DeviceReading:
        if self._primed_reading is not None:
            reading = self._primed_reading
            self._primed_reading = None
            return reading
        return await self._query_reading()

    async def get_device_information(self) -> DeviceInformation:
        information = await super().get_device_information()
        information.capabilities.update(
            {
                "identity_fallback_allowed": self.allow_identity_fallback,
                "association_source": self.association_source,
            }
        )
        return information


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
        raw_fields = [field.strip() for field in _single_ascii_line(payload, b"\r\n").split(",")]
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
