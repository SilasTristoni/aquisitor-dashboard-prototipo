"""Support snapshots contain metadata, never measurement payloads or customer files."""

from __future__ import annotations

import io
import json
import logging
import platform
import zipfile
from datetime import UTC, datetime
from time import monotonic

from sqlalchemy import event, func, select

from app.core.database import SessionLocal
from app.core.observability import (
    build_metadata,
    category_for,
    log_directory,
    new_correlation_id,
    request_context,
    sanitize,
)
from app.models.entities import (
    Device,
    ElectricalSample,
    MeasurementSession,
    SystemEvent,
    TemperatureSample,
)


@event.listens_for(SystemEvent, "before_insert")
def log_system_event(_mapper, _connection, target: SystemEvent) -> None:
    """Observe existing session/hardware events without touching acquisition or serial code."""
    context = request_context.get() or {}
    details = dict(target.details or {})
    code = details.get("correlation_id") or context.get("correlation_id") or new_correlation_id()
    details["correlation_id"] = code
    if target.level == "error":
        details["error_code"] = code
    target.details = sanitize(details)
    category = {
        "login": "AUTH",
        "configuration": "APPLICATION",
        "connection": "SERIAL",
        "connection_error": "SERIAL",
        "disconnection": "SERIAL",
        "disconnection_error": "SERIAL",
        "read_error": "ACQUISITION",
    }.get(target.category, category_for(target.category))
    # New support categories are already normalized; preserve legacy DB/API categories.
    if target.category.isupper():
        category = target.category
    logging.getLogger(__name__).log(
        {"error": logging.ERROR, "warning": logging.WARNING}.get(target.level, logging.INFO),
        target.message,
        extra={
            "category": category,
            "operation": target.category,
            "session_id": target.session_id,
            "device_id": target.device_id,
            "correlation_id": code,
            "error_code": code if target.level == "error" else None,
        },
    )


def audit_event(context: dict, message: str, level: str = "info") -> None:
    """Best effort DB index; rotating files remain usable if the DB is unavailable."""
    try:
        with SessionLocal() as db:
            session_id = context.get("session_id")
            device_id = context.get("device_id")
            db.add(
                SystemEvent(
                    category=context.get("category", "APPLICATION"),
                    level=level,
                    message=message,
                    session_id=session_id
                    if session_id and db.get(MeasurementSession, session_id)
                    else None,
                    device_id=device_id if device_id and db.get(Device, device_id) else None,
                    details=sanitize(context),
                )
            )
            db.commit()
    except Exception:
        logging.getLogger(__name__).exception(
            "Support audit could not be persisted", extra={"category": "DATABASE"}
        )


def support_snapshot(
    db, statuses: list[dict], session_id: int | None, correlation_id: str | None,
    *, include_logs: bool = True,
) -> bytes:
    now = datetime.now(UTC)
    devices = [
        {
            "id": d.id,
            "model": d.model,
            "protocol": d.protocol,
            "port": d.port,
            "baud_rate": d.baud_rate,
            "active": d.active,
            "serial": {
                key: value
                for key, value in (d.metadata_json or {}).get("serial", {}).items()
                if key in {"data_bits", "parity", "stop_bits", "timeout_s", "read_timeout_s"}
            },
        }
        for d in db.scalars(select(Device).order_by(Device.id).limit(128))
    ]
    allowed = {
        "device_id",
        "session_id",
        "connected",
        "state",
        "protocol",
        "source_role",
        "sample_count",
        "persisted_count",
        "persisted_sample_count",
        "session_sample_count",
        "buffered_measurements",
        "read_errors",
        "expected_interval_ms",
        "observed_interval_ms",
        "cadence_degraded",
        "last_error",
        "last_message_at",
        "acquisition_diagnostics",
        "paused",
        "port",
    }
    acquisition = []
    for status in statuses:
        item = {k: v for k, v in status.items() if k in allowed}
        if isinstance(item.get("acquisition_diagnostics"), dict):
            item["acquisition_diagnostics"] = {
                k: v
                for k, v in item["acquisition_diagnostics"].items()
                if isinstance(v, int | float | bool) or k == "last_successful_fetch_at"
            }
        acquisition.append(item)
    conditions = [SystemEvent.level == "error"]
    if correlation_id:
        conditions.append(SystemEvent.details["correlation_id"].as_string() == correlation_id)
    if session_id:
        conditions.append(SystemEvent.session_id == session_id)
    errors = [
        {
            "timestamp": e.timestamp.isoformat(),
            "message": e.message,
            "session_id": e.session_id,
            "device_id": e.device_id,
            "details": e.details,
        }
        for e in db.scalars(
            select(SystemEvent).where(*conditions).order_by(SystemEvent.id.desc()).limit(100)
        )
    ]
    session = db.get(MeasurementSession, session_id) if session_id else None
    summary = None
    if session:
        summary = {
            "id": session.id,
            "status": session.status,
            "started_at": session.started_at,
            "ended_at": session.ended_at,
            "electrical_samples": db.scalar(
                select(func.count())
                .select_from(ElectricalSample)
                .where(ElectricalSample.session_id == session.id)
            ),
            "temperature_samples": db.scalar(
                select(func.count())
                .select_from(TemperatureSample)
                .where(TemperatureSample.session_id == session.id)
            ),
        }
    contents = {
        "build-info.json": build_metadata(),
        "error-summary.json": {"correlation_id": correlation_id, "errors": errors},
        "system/runtime.json": {
            "timestamp": now.isoformat(),
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "python": platform.python_version(),
        },
        "hardware/devices.json": devices,
        "hardware/acquisition-summary.json": acquisition,
        "session/session-summary.json": summary,
        "lifecycle-events.json": [
            {"timestamp": e.timestamp, "category": e.category, "level": e.level,
             "device_id": e.device_id, "session_id": e.session_id,
             "message": e.message, "details": e.details}
            for e in db.scalars(select(SystemEvent).where(
                SystemEvent.category.in_([
                    "connection", "disconnection", "connection_error", "disconnection_error",
                    "read_error", "session_source_error", "session_start", "session_pause",
                    "session_resume", "session_stop",
                ])
            ).order_by(SystemEvent.id.desc()).limit(100))
        ],
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "README.txt",
            (
                "ThermoPower Monitor — pacote de suporte\n"
                "Informe ao suporte o código do erro e o que estava fazendo.\n"
                "Este pacote contém metadados e logs sanitizados; não inclui banco, séries de "
                "medições, documentos do cliente ou credenciais.\n"
                "Os logs incluem até 256 KiB recentes por arquivo; consulte logs/status.json.\n"
            ).encode(),
        )
        for name, data in contents.items():
            archive.writestr(
                name,
                json.dumps(sanitize(data), ensure_ascii=False, indent=2, default=str).encode(
                    "utf-8"
                ),
            )
        log_status = []
        for name in (("errors.log", "thermopower.log") if include_logs else ()):
            log_deadline = monotonic() + 1.5
            chunks = []
            remaining = 256 * 1024
            for suffix in ("", ".1", ".2", ".3", ".4", ".5"):
                path = log_directory() / (name + suffix)
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    with path.open("rb") as source:
                        source.seek(0, 2)
                        size = source.tell()
                        source.seek(max(0, size - remaining))
                        chunk = source.read(remaining)
                    log_status.append({
                        "file": name + suffix, "source_bytes": size,
                        "included_bytes": len(chunk), "truncated": size > len(chunk),
                    })
                    if size > len(chunk):
                        chunk = chunk.partition(b"\n")[2]
                    chunks.insert(0, chunk)
                    remaining -= len(chunk)
                except OSError:
                    log_status.append({"file": name + suffix, "unavailable": True})
                    continue
                if remaining <= 0:
                    break
            value = b"\n".join(chunks).decode("utf-8", errors="replace")
            lines = []
            for line in reversed(value.splitlines()):
                if monotonic() >= log_deadline or len(lines) >= 512:
                    log_status.append({"file": name, "truncated": True,
                                       "reason": "processing_budget"})
                    break
                if len(line) > 65536:
                    lines.append("[oversize log record omitted]")
                    continue
                try:
                    lines.append(json.dumps(sanitize(json.loads(line)), ensure_ascii=False))
                except (ValueError, RecursionError):
                    # Preserve legacy text logs and a truncated first line safely.
                    lines.append(sanitize(line))
            if not chunks:
                log_status.append({"file": name, "unavailable": True})
            archive.writestr(f"logs/{name}", "\n".join(reversed(lines)).encode("utf-8"))
        if include_logs:
            archive.writestr("logs/status.json", json.dumps(log_status).encode())
    return stream.getvalue()
