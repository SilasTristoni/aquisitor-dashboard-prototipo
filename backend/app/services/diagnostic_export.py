from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.core.version import APPLICATION_VERSION
from app.models.entities import Device


def _json_bytes(value: Any) -> bytes:
    return json.dumps(_sanitize_value(value), ensure_ascii=False, indent=2, default=str).encode(
        "utf-8"
    )


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]"
            if any(
                marker in str(key).casefold()
                for marker in ("password", "senha", "token", "secret", "jwt")
            )
            else _sanitize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _sanitized_text(value)
    return value


def _sanitized_text(value: str) -> str:
    value = re.sub(r"(?i)C:\\Users\\[^\\\s]+", r"C:\\Users\\[redacted]", value)
    value = re.sub(r"(?i)(password|senha|jwt|token|secret)\s*[:=]\s*\S+", r"\1=[redacted]", value)
    return value[-200_000:]


def _recent_log() -> str:
    root = os.environ.get("THERMOPOWER_APP_DATA_DIR")
    candidates = [Path(root) / "logs" / "thermopower.log"] if root else []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(
            Path(local_app_data) / "ThermoPower Monitor" / "logs" / "thermopower.log"
        )
    candidates.append(
        Path.home()
        / "AppData"
        / "Local"
        / "ThermoPower Monitor"
        / "logs"
        / "thermopower.log"
    )
    candidates.append(Path("logs") / "thermopower.log")
    for candidate in candidates:
        if candidate.is_file():
            return _sanitized_text(candidate.read_text(encoding="utf-8", errors="replace"))
    return "Log não encontrado no ambiente atual."


def _summary_pdf(lines: list[str]) -> bytes:
    stream = io.BytesIO()
    document = canvas.Canvas(stream, pagesize=A4)
    y = A4[1] - 48
    document.setFont("Helvetica", 9)
    for line in lines:
        document.drawString(48, y, line[:105])
        y -= 14
        if y < 48:
            document.showPage()
            document.setFont("Helvetica", 9)
            y = A4[1] - 48
    document.save()
    return stream.getvalue()


def create_diagnostic_zip(
    device: Device,
    probe: dict[str, Any],
    discoveries: list[dict[str, Any]],
    *,
    integration: dict[str, Any] | None = None,
    devices: list[Device] | None = None,
) -> bytes:
    now = datetime.now(UTC).isoformat()
    def device_dict(item: Device) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "manufacturer": item.manufacturer,
            "model": item.model,
            "serial_number": item.serial_number,
            "port": item.port,
            "baud_rate": item.baud_rate,
            "protocol": item.protocol,
            "metadata": item.metadata_json,
        }

    device_data = device_dict(device)
    relevant = [item for item in discoveries if item.get("port") == device.port]
    summary_lines = [
        f"ThermoPower Monitor {APPLICATION_VERSION}",
        f"Gerado em: {now}",
        f"Equipamento: {device.name}",
        f"Porta: {device.port or 'não encontrada'}",
        f"Resultado do probe: {probe.get('result', 'não executado')}",
        "Validação física: pendente até confirmação no instrumento real.",
    ]
    summary_html = (
        "<!doctype html><meta charset='utf-8'><title>Diagnóstico ThermoPower</title>"
        "<h1>Diagnóstico ThermoPower</h1><ul>"
        + "".join(f"<li>{line}</li>" for line in summary_lines)
        + "</ul><pre>"
        + json.dumps(probe, ensure_ascii=False, indent=2)
        + "</pre>"
    ).encode("utf-8")
    files: dict[str, bytes] = {
        "summary.html": summary_html,
        "summary.pdf": _summary_pdf(summary_lines),
        "application-version.txt": f"{APPLICATION_VERSION}\n".encode(),
        "system.json": _json_bytes(
            {
                "platform": platform.platform(),
                "windows_version": platform.win32_ver(),
                "python": platform.python_version(),
                "timestamp": now,
            }
        ),
        "serial-ports.json": _json_bytes(discoveries),
        "pnp-devices.json": _json_bytes(relevant),
        "drivers.json": _json_bytes(
            [
                {
                    "port": item.get("port"),
                    "status": item.get("driver_status"),
                    "message": item.get("driver_message"),
                    "manufacturer": item.get("manufacturer"),
                }
                for item in relevant
            ]
        ),
        "devices.json": _json_bytes(
            [device_dict(item) for item in devices] if devices else [device_data]
        ),
        "associations.json": _json_bytes(
            [
                {"port": item.get("port"), "association": item.get("association")}
                for item in relevant
            ]
        ),
        "serial-parameters.json": _json_bytes(probe.get("serial_parameters", {})),
        "protocol-results.json": _json_bytes(probe),
        "integration-status.json": _json_bytes(integration or {"status": "not_available"}),
        "recent-log.txt": _recent_log().encode("utf-8"),
        "README.txt": (
            "Pacote de diagnóstico de engenharia. Não contém senhas, JWT, banco de dados "
            "ou arquivos pessoais. TX/RX são comandos SCPI oficiais e respostas do instrumento.\n"
        ).encode(),
    }
    manifest = "".join(
        f"{hashlib.sha256(content).hexdigest().upper()}  {name}\n"
        for name, content in sorted(files.items())
    )
    files["SHA256SUMS.txt"] = manifest.encode("ascii")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return stream.getvalue()
