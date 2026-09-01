from __future__ import annotations

import logging
import os
import secrets
import socket
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

_APPLICATION_MUTEX = None


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def _application_directory() -> Path:
    configured = os.environ.get("THERMOPOWER_APP_DATA_DIR")
    if configured:
        path = Path(configured)
        path.mkdir(parents=True, exist_ok=True)
        return path
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    path = base / "ThermoPower Monitor"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _persistent_secret(directory: Path) -> str:
    path = directory / "jwt-secret.key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(48)
    path.write_text(value, encoding="utf-8")
    return value


def _free_port(start: int = 8765, attempts: int = 40) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            try:
                candidate.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("Não foi encontrada uma porta local livre para iniciar o ThermoPower")


def _configure_environment(runtime: Path, application: Path) -> None:
    data = application / "data"
    logs = application / "logs"
    reports = application / "reports"
    for path in (data, logs, reports):
        path.mkdir(parents=True, exist_ok=True)
    os.environ["THERMOPOWER_APP_DATA_DIR"] = str(application.resolve())
    os.environ.setdefault("THERMOPOWER_ENVIRONMENT", "physical-alpha")
    database_url = f"sqlite:///{(data / 'thermopower.db').as_posix()}"
    os.environ.setdefault("THERMOPOWER_DATABASE_URL", database_url)
    os.environ.setdefault("THERMOPOWER_REPORT_OUTPUT_DIRECTORY", str(reports))
    os.environ.setdefault("THERMOPOWER_FRONTEND_DIST", str(runtime / "frontend"))
    os.environ.setdefault("THERMOPOWER_JWT_SECRET", _persistent_secret(application))
    os.environ.setdefault("THERMOPOWER_DEMO_ADMIN_EMAIL", "homologacao@demo.thermopower.com")
    os.environ.setdefault("THERMOPOWER_DEMO_ADMIN_PASSWORD", "ThermoPower-HML@2026")
    _configure_file_logging(runtime, application)


def _configure_file_logging(runtime: Path, application: Path) -> None:
    log_path = application / "logs" / "thermopower.log"
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    handlers = [
        handler
        for handler in root_logger.handlers
        if isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename).resolve() == log_path.resolve()
    ]
    if not handlers:
        handler = logging.FileHandler(log_path, encoding="utf-8", delay=False)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root_logger.addHandler(handler)
        handlers.append(handler)
    root_logger.info("launcher configured application=%s runtime=%s", application, runtime)
    for handler in handlers:
        handler.flush()


def _acquire_single_instance(name: str = "ThermoPowerMonitorRunning", kernel32=None) -> bool:
    global _APPLICATION_MUTEX
    if sys.platform != "win32" and kernel32 is None:
        return True
    if kernel32 is None:
        import ctypes

        kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise OSError("Não foi possível criar o mutex da aplicação")
    if kernel32.GetLastError() == 183:
        kernel32.CloseHandle(handle)
        return False
    _APPLICATION_MUTEX = handle
    return True


def _release_single_instance(kernel32=None) -> None:
    global _APPLICATION_MUTEX
    if not _APPLICATION_MUTEX:
        return
    if kernel32 is None:
        import ctypes

        kernel32 = ctypes.windll.kernel32
    kernel32.CloseHandle(_APPLICATION_MUTEX)
    _APPLICATION_MUTEX = None


def _apply_migrations(runtime: Path) -> None:
    from alembic import command
    from alembic.config import Config

    configuration = Config(str(runtime / "alembic.ini"))
    configuration.set_main_option("script_location", str(runtime / "alembic"))
    configuration.set_main_option("sqlalchemy.url", os.environ["THERMOPOWER_DATABASE_URL"])
    command.upgrade(configuration, "head")


def main() -> None:
    mutex_name = os.environ.get("THERMOPOWER_MUTEX_NAME", "ThermoPowerMonitorRunning")
    if not _acquire_single_instance(mutex_name):
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0,
            "O ThermoPower Monitor já está em execução.",
            "ThermoPower Monitor",
            0x40,
        )
        return
    runtime = _runtime_root()
    application = _application_directory()
    _configure_environment(runtime, application)
    _apply_migrations(runtime)
    # Alembic's logging configuration may replace root handlers while applying migrations.
    _configure_file_logging(runtime, application)
    port = _free_port()
    address = f"http://127.0.0.1:{port}"
    if os.environ.get("THERMOPOWER_NO_BROWSER", "").casefold() not in {"1", "true", "yes"}:
        threading.Timer(1.2, lambda: webbrowser.open(address)).start()

    import uvicorn

    try:
        uvicorn.run(
            "app.main:app",
            host="127.0.0.1",
            port=port,
            log_level="info",
            log_config=None,
        )
    finally:
        logging.getLogger(__name__).info("launcher stopping")
        logging.shutdown()
        _release_single_instance()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        application = _application_directory()
        crash_log = application / "logs" / "thermopower-crash.log"
        crash_log.parent.mkdir(parents=True, exist_ok=True)
        crash_log.write_text(traceback.format_exc(), encoding="utf-8")
        if os.environ.get("THERMOPOWER_NO_BROWSER", "").casefold() not in {"1", "true", "yes"}:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0,
                f"Não foi possível iniciar o ThermoPower Monitor.\n\n{exc}\n\nLog: {crash_log}",
                "ThermoPower Monitor",
                0x10,
            )
        raise
