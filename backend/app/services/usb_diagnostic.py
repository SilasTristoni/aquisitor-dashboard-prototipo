from __future__ import annotations

import hashlib
import html
import io
import json
import os
import platform
import re
import subprocess
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.usb_discovery import UsbDeviceDiscoveryService, usb_discovery_service

settings = get_settings()
SENSITIVE_KEYS = {"password", "senha", "secret", "jwt", "token", "authorization"}
SECRET_PATTERN = re.compile(
    r"(?i)(password|senha|secret|jwt|token|authorization)\s*[:=]\s*([^\s,;]+)"
)


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "[REMOVIDO]"
                if any(term in key.casefold() for term in SENSITIVE_KEYS)
                else sanitize(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        cleaned = SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REMOVIDO]", value)
        profile = str(Path.home())
        if profile and profile.casefold() in cleaned.casefold():
            cleaned = re.sub(re.escape(profile), "%USERPROFILE%", cleaned, flags=re.IGNORECASE)
        return cleaned
    return value


@dataclass
class UsbSnapshot:
    id: str
    name: str
    captured_at: str
    application_version: str
    system: dict[str, Any]
    serial_ports: list[dict[str, Any]]
    pnp_devices: list[dict[str, Any]]


@dataclass
class UsbSnapshotDiff:
    previous_snapshot_id: str | None
    current_snapshot_id: str
    added_ports: list[dict[str, Any]] = field(default_factory=list)
    removed_ports: list[dict[str, Any]] = field(default_factory=list)
    changed_devices: list[dict[str, Any]] = field(default_factory=list)
    port_changes_by_serial: list[dict[str, Any]] = field(default_factory=list)


def _stable_key(item: dict[str, Any]) -> str:
    serial_number = item.get("serial_number")
    if serial_number:
        return f"serial:{serial_number}"
    hardware_id = item.get("hardware_id")
    if hardware_id:
        return f"hwid:{hardware_id}"
    return f"port:{item.get('port', '')}"


def compare_snapshots(previous: UsbSnapshot | None, current: UsbSnapshot) -> UsbSnapshotDiff:
    if previous is None:
        return UsbSnapshotDiff(
            previous_snapshot_id=None,
            current_snapshot_id=current.id,
            added_ports=current.serial_ports,
        )
    before = {_stable_key(item): item for item in previous.serial_ports}
    after = {_stable_key(item): item for item in current.serial_ports}
    diff = UsbSnapshotDiff(previous_snapshot_id=previous.id, current_snapshot_id=current.id)
    diff.added_ports = [after[key] for key in after.keys() - before.keys()]
    diff.removed_ports = [before[key] for key in before.keys() - after.keys()]
    for key in before.keys() & after.keys():
        old, new = before[key], after[key]
        changed_fields = {
            field: {"before": old.get(field), "after": new.get(field)}
            for field in sorted(set(old) | set(new))
            if old.get(field) != new.get(field) and field not in {"first_seen_at", "last_seen_at"}
        }
        if changed_fields:
            diff.changed_devices.append({"identity": key, "changes": changed_fields})
        if old.get("serial_number") and old.get("port") != new.get("port"):
            diff.port_changes_by_serial.append(
                {
                    "serial_number": old["serial_number"],
                    "previous_port": old.get("port"),
                    "current_port": new.get("port"),
                }
            )
    return diff


class UsbDiagnosticService:
    def __init__(self, discovery: UsbDeviceDiscoveryService | None = None) -> None:
        self.discovery = discovery or usb_discovery_service
        self.snapshots: list[UsbSnapshot] = []
        self.diffs: list[UsbSnapshotDiff] = []
        self._load()

    def capture(self, db: Session, name: str, busy_ports: set[str] | None = None) -> dict[str, Any]:
        ports = self.discovery.discover(db, busy_ports)
        snapshot = UsbSnapshot(
            id=datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ"),
            name=name,
            captured_at=datetime.now(UTC).isoformat(),
            application_version=settings.app_version,
            system=self._system_information(),
            serial_ports=sanitize(ports),
            pnp_devices=sanitize(self._pnp_devices()),
        )
        previous = self.snapshots[-1] if self.snapshots else None
        diff = compare_snapshots(previous, snapshot)
        self.snapshots.append(snapshot)
        self.diffs.append(diff)
        self._save()
        return {"snapshot": asdict(snapshot), "diff": asdict(diff)}

    def preview(self) -> dict[str, Any]:
        return sanitize(
            {
                "consent": (
                    "Este pacote contém apenas informações técnicas dos dispositivos "
                    "e do aplicativo."
                ),
                "snapshots": [asdict(item) for item in self.snapshots],
                "diffs": [asdict(item) for item in self.diffs],
                "excluded": [
                    "senhas e tokens",
                    "banco de dados",
                    "medições completas",
                    "arquivos pessoais e inventário de rede",
                ],
            }
        )

    def reset(self) -> None:
        self.snapshots.clear()
        self.diffs.clear()
        self._save()

    @staticmethod
    def _storage_path() -> Path | None:
        if not settings.app_data_dir:
            return None
        return Path(settings.app_data_dir) / "diagnostics" / "snapshots.json"

    def _load(self) -> None:
        path = self._storage_path()
        if not path or not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.snapshots = [UsbSnapshot(**item) for item in data.get("snapshots", [])]
            self.diffs = [UsbSnapshotDiff(**item) for item in data.get("diffs", [])]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.snapshots = []
            self.diffs = []

    def _save(self) -> None:
        path = self._storage_path()
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "snapshots": [asdict(item) for item in self.snapshots],
                        "diffs": [asdict(item) for item in self.diffs],
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
        except OSError:
            return

    def export(self, recent_log: str = "") -> tuple[str, bytes]:
        preview = self.preview()
        snapshots = preview["snapshots"]
        diffs = preview["diffs"]
        latest_ports = snapshots[-1]["serial_ports"] if snapshots else []
        latest_pnp = snapshots[-1]["pnp_devices"] if snapshots else []
        system = snapshots[-1]["system"] if snapshots else self._system_information()
        created = datetime.now().astimezone()
        filename = f"ThermoPower-Diagnostico-{created:%Y-%m-%d-%H%M}.zip"
        files: dict[str, bytes] = {
            "diagnostic-summary.html": self._html(preview).encode("utf-8"),
            "diagnostic-summary.pdf": self._pdf(preview),
            "system.json": self._json_bytes(system),
            "snapshots.json": self._json_bytes(snapshots),
            "snapshot-diff.json": self._json_bytes(diffs),
            "serial-ports.json": self._json_bytes(latest_ports),
            "pnp-devices.json": self._json_bytes(latest_pnp),
            "application-version.txt": f"{settings.app_version}\n".encode(),
            "recent-log.txt": sanitize(recent_log)[-100_000:].encode("utf-8"),
            "README.txt": (
                "Pacote técnico do ThermoPower Monitor.\n"
                "Contém somente os dados exibidos na prévia e não contém banco ou medições.\n"
                "A detecção do Windows não comprova protocolo ou homologação do instrumento.\n"
            ).encode(),
        }
        manifest = "".join(
            f"{hashlib.sha256(content).hexdigest()}  {name}\n"
            for name, content in sorted(files.items())
        )
        files["sha256.txt"] = manifest.encode("ascii")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        return filename, output.getvalue()

    @staticmethod
    def _json_bytes(value: Any) -> bytes:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")

    @staticmethod
    def _system_information() -> dict[str, Any]:
        return {
            "captured_at": datetime.now(UTC).isoformat(),
            "application_version": settings.app_version,
            "operating_system": platform.platform(),
            "windows_version": platform.win32_ver()[0] or None,
            "architecture": platform.machine(),
            "python_runtime_bundled": True,
            "environment": settings.environment,
        }

    @staticmethod
    def _pnp_devices() -> list[dict[str, Any]]:
        if os.name != "nt":
            return []
        command = (
            "$p=Get-CimInstance Win32_PnPEntity | Where-Object "
            "{$_.PNPClass -in @('Ports','USB')};"
            "$d=Get-CimInstance Win32_PnPSignedDriver;"
            "$p | ForEach-Object {$x=$_;$r=$d | Where-Object DeviceID -eq $x.PNPDeviceID | "
            "Select-Object -First 1;[pscustomobject]@{Status=$x.Status;"
            "InstanceId=$x.PNPDeviceID;FriendlyName=$x.Name;Class=$x.PNPClass;"
            "Manufacturer=$x.Manufacturer;DriverProvider=$r.DriverProviderName;"
            "DriverVersion=$r.DriverVersion;DriverDate=$r.DriverDate}} | ConvertTo-Json -Compress"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode or not result.stdout.strip():
                return []
            rows = json.loads(result.stdout)
            if isinstance(rows, dict):
                rows = [rows]
            return [
                {
                    "status": row.get("Status"),
                    "instance_id": row.get("InstanceId"),
                    "friendly_name": row.get("FriendlyName"),
                    "class": row.get("Class"),
                    "manufacturer": row.get("Manufacturer"),
                    "driver_provider": row.get("DriverProvider"),
                    "driver_version": row.get("DriverVersion"),
                    "driver_date": row.get("DriverDate"),
                }
                for row in rows
            ]
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
            return []

    @staticmethod
    def _html(preview: dict[str, Any]) -> str:
        rows = []
        for snapshot in preview["snapshots"]:
            rows.append(
                f"<tr><td>{html.escape(snapshot['name'])}</td>"
                f"<td>{html.escape(snapshot['captured_at'])}</td>"
                f"<td>{len(snapshot['serial_ports'])}</td></tr>"
            )
        return (
            "<!doctype html><html lang='pt-BR'><meta charset='utf-8'>"
            "<title>Diagnóstico ThermoPower</title><style>body{font:14px Segoe UI,Arial;"
            "margin:40px;color:#172033}table{border-collapse:collapse;width:100%}"
            "td,th{border:1px solid #ccd3df;padding:8px;text-align:left}</style>"
            "<h1>ThermoPower Monitor — diagnóstico USB</h1>"
            f"<p>{html.escape(preview['consent'])}</p>"
            "<p>A detecção não confirma leitura ou homologação do instrumento.</p>"
            "<table><thead><tr><th>Captura</th><th>Data</th><th>Portas</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></html>"
        )

    @staticmethod
    def _pdf(preview: dict[str, Any]) -> bytes:
        output = io.BytesIO()
        document = canvas.Canvas(output, pagesize=A4)
        _, height = A4
        document.setTitle("Diagnóstico USB ThermoPower")
        document.setFont("Helvetica-Bold", 16)
        document.drawString(50, height - 60, "ThermoPower Monitor - Diagnostico USB")
        document.setFont("Helvetica", 9)
        document.drawString(50, height - 82, "Deteccao nao confirma leitura ou homologacao fisica.")
        y = height - 115
        for snapshot in preview["snapshots"]:
            line = (
                f"{snapshot['name']} | {snapshot['captured_at']} | "
                f"{len(snapshot['serial_ports'])} porta(s)"
            )
            document.drawString(50, y, line)
            y -= 18
            if y < 60:
                document.showPage()
                y = height - 60
        document.save()
        return output.getvalue()


def read_recent_log() -> str:
    candidates = []
    if settings.log_file:
        candidates.append(Path(settings.log_file))
    if settings.app_data_dir:
        candidates.append(Path(settings.app_data_dir) / "logs" / "thermopower.log")
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8", errors="replace")[-100_000:]
        except OSError:
            continue
    return ""


usb_diagnostic_service = UsbDiagnosticService()
