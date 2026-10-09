"""One read-only bench export, including evidence from previous tool/app processes."""

import hashlib
import io
import json
import zipfile

from sqlalchemy import func, select

from app.core.observability import build_metadata, sanitize
from app.core.physical_trace import journal, trace_directory
from app.models.entities import ElectricalSample, MeasurementSession, TemperatureSample
from app.services.support import support_snapshot


def physical_diagnostic_zip(db, states, transactions, boundaries, probes):
    flushed = journal.flush()
    files = {}
    errors = []
    snapshots = []
    serial_lines = []
    directory = trace_directory()

    def read_jsonl(path):
        rows = []
        # Snapshot a byte boundary; concurrent later events belong to the next export.
        with path.open("rb") as source:
            size = path.stat().st_size
            value = source.read(size)
        for index, line in enumerate(value.splitlines(), 1):
            try:
                rows.append(sanitize(json.loads(line)))
            except (ValueError, UnicodeError):
                errors.append(
                    {
                        "file": path.name,
                        "line": index,
                        "reason": "invalid_or_incomplete_jsonl",
                        "sha256": hashlib.sha256(line).hexdigest(),
                    }
                )
        return rows

    for path in sorted(directory.glob("*.jsonl")):
        rows = read_jsonl(path)
        if path.name.startswith("snapshots-"):
            snapshots.extend(rows)
        else:
            serial_lines.extend(rows)
    serial_lines.sort(
        key=lambda r: (r.get("utc_timestamp", ""), r.get("run_id", ""), r.get("sequence", 0))
    )
    files["serial-events.jsonl"] = b"".join(
        (json.dumps(row, ensure_ascii=False) + "\n").encode() for row in serial_lines
    )
    captures = directory / "characterizations"
    for capture in sorted(captures.glob("*")):
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
                    else sanitize(json.loads(path.read_text(encoding="utf-8-sig")))
                )
                files[f"characterizations/{capture.name}/{name}"] = (
                    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in data)
                    if name.endswith(".jsonl")
                    else json.dumps(data, ensure_ascii=False, indent=2)
                ).encode()
            except (ValueError, OSError):
                errors.append({"file": f"{capture.name}/{name}", "reason": "capture_unreadable"})
    with zipfile.ZipFile(io.BytesIO(support_snapshot(db, states, None, None))) as support:
        files.update({name: support.read(name) for name in support.namelist()})
    sessions = []
    # Metadata/counts only; no customer documents or complete measurement database.
    for session in db.scalars(select(MeasurementSession).order_by(MeasurementSession.id)):
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
    info = build_metadata()
    contents = {
        "acquisition-state.json": states,
        "runtime-state.json": {"current": states, "saved_checkpoints": snapshots},
        "transactions.json": {
            "current": transactions,
            "probes": probes,
            "saved_checkpoints": snapshots,
            "retention": "runtime transaction ring: 256; serial-events retains the full AT history",
        },
        "input-boundary-metrics.json": {"current": boundaries, "saved_checkpoints": snapshots},
        "counters-AT-GPM.json": {"current": states, "saved_checkpoints": snapshots},
        "session-summary.json": sessions,
        "evidence-status.json": {
            **journal.status(),
            "flush_completed": flushed,
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
        "Inclui caracterizações Celsius salvas automaticamente nesta instalação e histórico AT.\n"
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
