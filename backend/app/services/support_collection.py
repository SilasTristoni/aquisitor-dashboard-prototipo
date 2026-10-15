"""Isolate collection from the acquisition event loop, with a killable deadline."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from threading import Lock

from fastapi import HTTPException
from fastapi.responses import FileResponse

EXPORT_TIMEOUT = 12.0
MAX_ARCHIVE_BYTES = 24 * 1024 * 1024
_active = False
_gate = Lock()


def worker_command(job, output):
    args = ["--diagnostic-worker", str(job), str(output)]
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "app.engineering.local_diagnostic", *args]


def stop_worker(process):
    """Bounded termination of our collector, including the Windows venv child interpreter."""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=2)


class DiagnosticResponse(FileResponse):
    def __init__(self, path, directory, release):
        super().__init__(path, media_type="application/zip", filename="ThermoPower-Diagnostico.zip")
        self.directory = directory
        self.release = release

    def cleanup(self):
        try:
            self.directory.cleanup()
        finally:
            self.release()

    async def __call__(self, scope, receive, send):
        try:
            # Also bound stalled/abandoned transfers, including clients not reading the body.
            async with asyncio.timeout(EXPORT_TIMEOUT):
                await super().__call__(scope, receive, send)
        finally:
            self.cleanup()


async def export_diagnostic(request, snapshot, database_url, session_id=None, correlation_id=None):
    global _active
    if not _gate.acquire(blocking=False):
        raise HTTPException(
            429, "Um diagnóstico já está sendo preparado. Aguarde e tente novamente."
        )
    _active = True
    directory = None
    process = None
    released = False

    def release():
        global _active
        nonlocal released
        if released:
            return
        released = True
        _active = False
        _gate.release()

    try:
        from app.core.observability import log_directory
        from app.services.diagnostic_snapshot import bounded

        directory = tempfile.TemporaryDirectory(prefix="thermopower-diagnostic-")
        root = Path(directory.name)
        job, output = root / "job.json", root / "diagnostic.zip"
        # URL stays in the inherited process environment, never in an exported artifact.
        job.write_text(
            json.dumps(
                {
                    "snapshot": bounded(snapshot),
                    "session_id": session_id,
                    "correlation_id": correlation_id,
                    "log_directory": str(log_directory().resolve()),
                },
                default=str,
            ),
            encoding="utf-8",
        )
        environment = dict(os.environ, THERMOPOWER_DATABASE_URL=database_url)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
        # Popen works with Windows SelectorEventLoop too; no blocking wait/communicate.
        process = subprocess.Popen(
            worker_command(job, output),
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        async with asyncio.timeout(EXPORT_TIMEOUT):
            while process.poll() is None:
                if request is not None and await request.is_disconnected():
                    raise HTTPException(499, "Download cancelado pelo cliente.")
                await asyncio.sleep(0.05)
        if process.returncode != 0 or not output.is_file():
            raise HTTPException(503, "Coleta indisponível. Utilize export-local-diagnostic.ps1.")
        if output.stat().st_size > MAX_ARCHIVE_BYTES:
            raise HTTPException(503, "Diagnóstico excedeu o limite. Utilize a coleta local.")
        return DiagnosticResponse(output, directory, release)
    except BaseException as error:
        try:
            if process is not None:
                await asyncio.shield(asyncio.to_thread(stop_worker, process))
        finally:
            try:
                if directory:
                    directory.cleanup()
            finally:
                release()
        if isinstance(error, TimeoutError):
            raise HTTPException(
                504, "Tempo limite do diagnóstico. Utilize export-local-diagnostic.ps1."
            ) from None
        if isinstance(error, OSError):
            raise HTTPException(
                503, "Coleta indisponível. Utilize export-local-diagnostic.ps1."
            ) from None
        raise
