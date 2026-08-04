import csv
import io
import re
from datetime import UTC, date, datetime, time

from app.domain.readings import ElectricalReading, normalize_value
from app.importers.common import ImportIssue, ImportResult, ensure_aware

ALIASES = {
    "timestamp": ("timestamp", "datetime", "data hora", "date time"),
    "date": ("date", "data"),
    "time": ("time", "hora"),
    "voltage": ("voltage", "tensao", "tensão", "vrms", "v rms"),
    "current": ("current", "corrente", "irms", "i rms"),
    "active_power": ("active power", "potencia ativa", "potência ativa", "watt", "p"),
    "apparent_power": ("apparent power", "potencia aparente", "potência aparente", "va", "s"),
    "reactive_power": ("reactive power", "potencia reativa", "potência reativa", "var", "q"),
    "power_factor": ("power factor", "fator de potencia", "fator de potência", "pf"),
    "voltage_frequency": ("voltage frequency", "frequencia tensao", "frequência tensão", "vfreq"),
    "current_frequency": (
        "current frequency",
        "frequencia corrente",
        "frequência corrente",
        "ifreq",
    ),
}

DEFAULT_UNITS = {
    "voltage": "V",
    "current": "A",
    "active_power": "W",
    "apparent_power": "VA",
    "reactive_power": "var",
    "voltage_frequency": "Hz",
    "current_frequency": "Hz",
}


def _clean_header(value: str) -> tuple[str, str | None]:
    unit_match = re.search(r"[\[(]\s*([^\])]+)\s*[\])]", value)
    unit = unit_match.group(1).strip() if unit_match else None
    name = re.sub(r"[\[(].*?[\])]", "", value).strip().lower()
    name = re.sub(r"\s+", " ", name)
    return name, unit


def _number(value: str) -> float | None:
    text = value.strip()
    if not text or text.lower() in {"nan", "null", "--", "ol", "overload"}:
        return None
    text = text.replace(" ", "")
    if text.count(",") == 1 and "." not in text:
        text = text.replace(",", ".")
    return float(text)


def _timestamp(row: dict[str, str], mapping: dict[str, str]) -> datetime:
    if "timestamp" in mapping:
        raw = row[mapping["timestamp"]].strip()
        try:
            return ensure_aware(datetime.fromisoformat(raw.replace("Z", "+00:00")))
        except ValueError:
            for pattern in ("%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                try:
                    return ensure_aware(datetime.strptime(raw, pattern))
                except ValueError:
                    continue
    if "date" in mapping and "time" in mapping:
        raw = f"{row[mapping['date']].strip()} {row[mapping['time']].strip()}"
        for pattern in (
            "%d/%m/%Y %H:%M:%S.%f",
            "%d/%m/%Y %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                return ensure_aware(datetime.strptime(raw, pattern))
            except ValueError:
                continue
    if "time" in mapping:
        parsed = time.fromisoformat(row[mapping["time"]].strip())
        return datetime.combine(date.today(), parsed, tzinfo=UTC)
    raise ValueError("data/hora não reconhecida")


class Gpm8213TxtImporter:
    max_rows = 1_000_000

    def parse(self, payload: bytes) -> ImportResult[ElectricalReading]:
        if b"\x00" in payload:
            raise ValueError("TXT contém bytes nulos")
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = payload.decode("latin-1")
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            raise ValueError("Arquivo TXT vazio")
        header_index, delimiter = self._find_header(lines)
        reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])), delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError("Cabeçalho do GPM-8213 não encontrado")
        mapping, units = self._mapping(reader.fieldnames)
        if "active_power" not in mapping and not ({"voltage", "current"} <= mapping.keys()):
            raise ValueError("Cabeçalho não contém potência ativa nem tensão/corrente")
        result: ImportResult[ElectricalReading] = ImportResult(mapping=mapping)
        for index, row in enumerate(reader, header_index + 2):
            if index - header_index > self.max_rows:
                raise ValueError("Arquivo excede o limite de linhas")
            try:
                timestamp = _timestamp(row, mapping)
                original = {
                    key: _number(row[column])
                    for key, column in mapping.items()
                    if key not in {"timestamp", "date", "time"}
                }
                canonical = {
                    key: normalize_value(
                        original.get(key), units.get(key, DEFAULT_UNITS[key]), expected
                    )
                    for key, expected in (
                        ("voltage", "V"),
                        ("current", "A"),
                        ("active_power", "W"),
                        ("apparent_power", "VA"),
                        ("reactive_power", "var"),
                        ("voltage_frequency", "Hz"),
                        ("current_frequency", "Hz"),
                    )
                    if key in mapping
                }
                result.readings.append(
                    ElectricalReading(
                        device_timestamp=timestamp,
                        received_timestamp=timestamp,
                        voltage_v=canonical.get("voltage"),
                        current_a=canonical.get("current"),
                        active_power_w=canonical.get("active_power"),
                        apparent_power_va=canonical.get("apparent_power"),
                        reactive_power_var=canonical.get("reactive_power"),
                        power_factor=original.get("power_factor"),
                        voltage_frequency_hz=canonical.get("voltage_frequency"),
                        current_frequency_hz=canonical.get("current_frequency"),
                        original_values=original,
                        original_units={
                            key: units.get(key, DEFAULT_UNITS.get(key, "")) for key in original
                        },
                        raw_payload={key: value for key, value in row.items() if key is not None},
                    )
                )
            except (ValueError, TypeError) as exc:
                result.errors.append(ImportIssue(index, "row", str(exc)))
        return result

    def _find_header(self, lines: list[str]) -> tuple[int, str]:
        for index, line in enumerate(lines[:80]):
            for delimiter in ("\t", ";", ","):
                parts = next(csv.reader([line], delimiter=delimiter))
                recognized = sum(self._canonical(part)[0] is not None for part in parts)
                if recognized >= 2:
                    return index, delimiter
        raise ValueError("Cabeçalho do GPM-8213 não reconhecido")

    def _canonical(self, header: str) -> tuple[str | None, str | None]:
        name, unit = _clean_header(header)
        for canonical, aliases in ALIASES.items():
            if name in aliases:
                return canonical, unit
        return None, unit

    def _mapping(self, headers: list[str]) -> tuple[dict[str, str], dict[str, str]]:
        mapping: dict[str, str] = {}
        units: dict[str, str] = {}
        for header in headers:
            canonical, unit = self._canonical(header)
            if canonical:
                mapping[canonical] = header
                if unit:
                    units[canonical] = unit
        return mapping, units
