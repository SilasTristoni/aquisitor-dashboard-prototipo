"""One read-only bench export, including evidence from previous tool/app processes."""

import hashlib
import io
import json
import os
import zipfile
from itertools import islice
from time import monotonic

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.observability import build_metadata, sanitize
from app.core.physical_trace import journal, trace_directory  # noqa: F401 (legacy import contract)
from app.models.entities import ElectricalSample, MeasurementSession, TemperatureSample
from app.services.support import support_snapshot


class UnavailableDatabase:
    def scalars(self, *args):
        return []

    def scalar(self, *args):
        return None

    def get(self, *args):
        return None


def physical_diagnostic_zip(
    db,
    states,
    transactions,
    boundaries,
    probes,
    *,
    snapshot=None,
    session_id=None,
    correlation_id=None,
):
    # Never flush/wait on the runtime logger. Files are bounded snapshots of durable evidence.
    snapshot = snapshot or {}
    files = {}
    errors = []
    sections = {}
    snapshots = []
    serial_lines = []
    directory = trace_directory()
    remaining = 4 * 1024 * 1024
    log_deadline = monotonic() + 2

    def entries(root, maximum):
        try:
            if root.is_symlink():
                raise OSError("linked directory")
            with os.scandir(root) as listing:
                paths = list(islice(listing, maximum + 1))
            if len(paths) > maximum:
                errors.append({"section": root.name, "reason": "file_count_limit"})
            # Bounded enumeration, deterministic retained order. Not a claim of complete history.
            return sorted((root / p.name for p in paths[:maximum]), key=lambda p: p.name)
        except OSError:
            errors.append({"section": root.name, "reason": "directory_unavailable"})
            return []

    def read_bounded(path, tail=True):
        nonlocal remaining
        if path.is_symlink() or not path.is_file():
            raise OSError("not a regular evidence file")
        with path.open("rb") as source:
            size = os.fstat(source.fileno()).st_size
            limit = min(256 * 1024, remaining)
            if size > limit:
                errors.append({"file": path.name, "reason": "size_limit", "original_bytes": size})
                if not tail:
                    return b""
            offset = max(0, size - limit)
            source.seek(offset)
            value = source.read(min(size, limit))
            remaining -= len(value)
        # Discard a partial first record, never parse it as complete evidence.
        return value.partition(b"\n")[2] if offset else value

    def read_jsonl(path):
        rows = []
        value = read_bounded(path)
        for index, line in enumerate(value.splitlines(keepends=True), 1):
            if monotonic() >= log_deadline:
                errors.append({"file": path.name, "reason": "processing_budget"})
                break
            if index > 1024 or len(line) > 65536:
                errors.append({"file": path.name, "reason": "record_limit"})
                break
            try:
                if not line.endswith(b"\n"):
                    raise ValueError("incomplete line")
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("not an event")
                from app.services.diagnostic_snapshot import bounded

                rows.append(sanitize(bounded(row)))
            except (ValueError, UnicodeError, RecursionError):
                errors.append(
                    {
                        "file": path.name,
                        "line": index,
                        "reason": "invalid_or_incomplete_jsonl",
                        "sha256": hashlib.sha256(line).hexdigest(),
                    }
                )
        return rows

    for path in entries(directory, 32):
        if path.suffix != ".jsonl":
            continue
        try:
            rows = read_jsonl(path)
        except OSError:
            errors.append({"file": path.name, "reason": "unreadable"})
            continue
        if path.name.startswith("snapshots-"):
            snapshots.extend(rows)
        else:
            serial_lines.extend(rows)
    serial_lines.sort(
        key=lambda r: (
            str(r.get("utc_timestamp", "")),
            str(r.get("run_id", "")),
            str(r.get("sequence", 0)),
        )
    )
    files["serial-events.jsonl"] = b"".join(
        (json.dumps(row, ensure_ascii=False) + "\n").encode() for row in serial_lines
    )
    captures = directory / "characterizations"
    for capture in entries(captures, 16):
        if not capture.is_dir() or capture.is_symlink():
            continue
        for name in ("events.jsonl", "frames.json", "summary.json", "build-info.json"):
            path = capture / name
            if not path.is_file() or path.is_symlink():
                continue
            try:
                data = (
                    read_jsonl(path)
                    if name.endswith(".jsonl")
                    else sanitize(json.loads(read_bounded(path, tail=False).decode("utf-8-sig")))
                )
                files[f"characterizations/{capture.name}/{name}"] = (
                    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in data)
                    if name.endswith(".jsonl")
                    else json.dumps(data, ensure_ascii=False, indent=2)
                ).encode()
            except (ValueError, OSError, RecursionError):
                errors.append({"file": f"{capture.name}/{name}", "reason": "capture_unreadable"})
    try:
        if correlation_id and not session_id:
            from app.models.entities import SystemEvent

            session_id = db.scalar(
                select(SystemEvent.session_id)
                .where(SystemEvent.details["correlation_id"].as_string() == correlation_id)
                .order_by(SystemEvent.id.desc())
                .limit(1)
            )
        support_content = support_snapshot(
            db, states, session_id, correlation_id, include_logs=False
        )
        sections["database"] = "available"
    except (SQLAlchemyError, OSError):
        db.rollback()
        db = UnavailableDatabase()
        support_content = support_snapshot(db, states, None, correlation_id, include_logs=False)
        sections["database"] = "unavailable: read-only query failed or exceeded time limit"
    with zipfile.ZipFile(io.BytesIO(support_content)) as support:
        files.update({name: support.read(name) for name in support.namelist()})
    sessions = []
    # Metadata/counts only; no customer documents or complete measurement database.
    try:
        for session in db.scalars(
            select(MeasurementSession).order_by(MeasurementSession.id.desc()).limit(10)
        ):
            sessions.append(
                {
                    "session_id": session.id,
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
            )
    except (SQLAlchemyError, OSError):
        db.rollback()
        sections["session_counts"] = "unavailable or partial: database deadline/lock"
    # Release the read transaction before compression, including WAL reader snapshots.
    if not isinstance(db, UnavailableDatabase):
        db.rollback()
    with zipfile.ZipFile(
        io.BytesIO(support_snapshot(UnavailableDatabase(), [], None, None))
    ) as logs:
        files.update(
            {name: logs.read(name) for name in logs.namelist() if name.startswith("logs/")}
        )
    info = build_metadata()
    sections["runtime"] = snapshot.get("unavailable", "available: passive memory snapshot")
    states = list(states)
    runtime_ids = {row["device_id"] for row in states}
    for device in json.loads(files["hardware/devices.json"]):
        if device["id"] not in runtime_ids:
            states.append(
                {
                    "device_id": device["id"],
                    "protocol": device["protocol"],
                    "state": "runtime_absent",
                    "connection_verified": False,
                }
            )
    contents = {
        "acquisition-state.json": states,
        "runtime-state.json": {
            "current": states,
            "snapshot": snapshot,
            "saved_checkpoints": snapshots,
        },
        "transactions.json": {
            "current": transactions,
            "probes": probes,
            "saved_checkpoints": snapshots,
            "retention": "runtime ring: 256; file tails bounded, see evidence-status.json",
        },
        "input-boundary-metrics.json": {"current": boundaries, "saved_checkpoints": snapshots},
        "counters-AT-GPM.json": {"current": states, "saved_checkpoints": snapshots},
        "session-summary.json": sessions,
        "evidence-status.json": {
            "journal": snapshot.get("journal", {"unavailable": "offline process"}),
            "flush_completed": False,
            "flush_policy": "Never wait on runtime journal; queued events may be absent",
            "sections": sections,
            "limits": {
                "physical_bytes": 4 * 1024 * 1024,
                "file_bytes": 256 * 1024,
                "physical_files": 32,
                "captures": 16,
                "sessions": 10,
            },
            "read_errors": errors,
            "serial_event_count": len(serial_lines),
            "timing_reference": "driver write invocation / read completion; not wire time",
            "physical_validation": "pending",
        },
    }
    files["devices.json"] = files["hardware/devices.json"]
    files["last-errors.json"] = files["error-summary.json"]
    files["version.txt"] = (str(info["version"]) + "\n").encode()
    files["commit.txt"] = (str(info["commit"] or "development") + "\n").encode()
    for name, data in contents.items():
        files[name] = json.dumps(sanitize(data), ensure_ascii=False, indent=2, default=str).encode()
    files["README.txt"] = (
        "Diagnóstico físico completo — AT4532/GPM. Evidência não significa homologação.\n"
        "Inclui recortes limitados dos logs e das caracterizações disponíveis nesta instalação.\n"
        "Confira evidence-status.json: perdas/erros de escrita invalidam a completude da captura.\n"
        "Nenhuma porta foi aberta e nenhum comando enviado pela exportação.\n"
    ).encode()
    files["SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(files.items())
    ).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name, content in files.items():
            zipped.writestr(name, content)
    return output.getvalue()
