"""Offline/read-only diagnostic entry point; never imports the application or drivers."""

import argparse
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def diagnostic_database():
    from sqlalchemy import create_engine, event
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    url = make_url(os.environ["THERMOPOWER_DATABASE_URL"])
    if url.get_backend_name() == "sqlite":
        path = Path(url.database).resolve()

        def connect():
            connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.05)
            connection.execute("PRAGMA query_only=ON")
            deadline = time.monotonic() + 0.5
            connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            # A single read transaction gives consistent counts/metadata. Never a write lock.
            connection.execute("BEGIN")
            return connection

        engine = create_engine("sqlite://", creator=connect, poolclass=NullPool)
    elif url.get_backend_name() == "postgresql":
        engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 1})

        @event.listens_for(engine, "begin")
        def readonly(connection):
            connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '250ms'")
            connection.exec_driver_sql("SET LOCAL lock_timeout = '50ms'")
    else:
        raise ValueError("unsupported diagnostic database")
    try:
        with Session(engine) as db:
            if url.get_backend_name() == "sqlite":
                db.info["diagnostic_database_path"] = str(path)
            yield db
    finally:
        engine.dispose()


def collect(job, output):
    # Only needed for importing the existing ORM models. No auth/server starts here.
    if previous := os.environ.get("THERMOPOWER_JWT_SECRET"):
        os.environ["THERMOPOWER_DIAGNOSTIC_REDACTION_SECRET"] = previous
    os.environ["THERMOPOWER_JWT_SECRET"] = secrets.token_urlsafe(48)
    os.environ["THERMOPOWER_LOG_DIRECTORY"] = job["log_directory"]
    from app.services.physical_diagnostic import physical_diagnostic_zip

    with diagnostic_database() as db:
        snapshot = job["snapshot"]
        content = physical_diagnostic_zip(
            db,
            snapshot.get("states", []),
            snapshot.get("transactions", {}),
            snapshot.get("boundaries", {}),
            snapshot.get("probes", {}),
            snapshot=snapshot,
            session_id=job.get("session_id"),
            correlation_id=job.get("correlation_id"),
        )
    with Path(output).open("xb") as target:
        target.write(content)


def entrypoint(argv=None):
    parser = argparse.ArgumentParser(
        description="Diagnóstico local sem aquisição nem acesso serial"
    )
    parser.add_argument("--diagnostic-worker", nargs=2, metavar=("JOB", "OUTPUT"))
    parser.add_argument("--app-data", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.diagnostic_worker:
        job, output = args.diagnostic_worker
        collect(json.loads(Path(job).read_text(encoding="utf-8")), output)
        return
    if args.output is None or args.app_data is None:
        parser.error("--app-data e --output são obrigatórios")
    if args.output.exists():
        parser.error("O destino já existe; escolha outro nome")
    database = args.database or args.app_data / "data/thermopower.db"
    environment = dict(
        os.environ, THERMOPOWER_DATABASE_URL=f"sqlite:///{database.resolve().as_posix()}"
    )
    from app.services.support_collection import stop_worker, worker_command

    with tempfile.TemporaryDirectory(prefix="thermopower-offline-") as directory:
        job, output = Path(directory) / "job.json", Path(directory) / "diagnostic.zip"
        job.write_text(
            json.dumps(
                {
                    "snapshot": {"unavailable": "API/runtime unavailable: offline export"},
                    "log_directory": str((args.app_data / "logs").resolve()),
                }
            ),
            encoding="utf-8",
        )
        process = subprocess.Popen(
            worker_command(job, output),
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        try:
            code = process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            stop_worker(process)
            code = 1
        if code:
            parser.exit(
                1, "Coleta local indisponível ou excedeu 12 s. Nenhuma aquisição iniciada.\n"
            )
        # Exclusive creation: never replace evidence or an existing user file.
        with args.output.open("xb") as target, output.open("rb") as source:
            import shutil

            shutil.copyfileobj(source, target, length=65536)
    print(f"Diagnóstico salvo em {args.output}")


if __name__ == "__main__":
    entrypoint()
