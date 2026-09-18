"""Bounded JSON logs and request context; never collect request bodies or credentials."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

from app.core.version import APPLICATION_VERSION

request_context: ContextVar[dict | None] = ContextVar("support_context", default=None)
SECRET_KEY = re.compile(
    r"password|senha|token|secret|credential|authorization|cookie|api.?key", re.I
)


def build_metadata() -> dict:
    root = (
        Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
    )
    path = root / "build-info.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        data = {}
    return {
        "version": APPLICATION_VERSION,
        "build": data.get("commit", "development"),
        "commit": data.get("commit"),
        "build_date": data.get("build_date"),
        "environment": os.environ.get("THERMOPOWER_ENVIRONMENT", "development"),
    }


def sanitize(value):
    if isinstance(value, dict):
        return {
            str(k): "[redacted]" if SECRET_KEY.search(str(k)) else sanitize(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [sanitize(v) for v in value]
    if not isinstance(value, str):
        return value
    # Remove exact configured secrets even in otherwise unlabelled exception messages.
    for key, secret in os.environ.items():
        if SECRET_KEY.search(key) and len(secret) >= 4:
            value = value.replace(secret, "[redacted]")
    value = re.sub(r"(?i)Bearer\s+[^\s\"'&,;]+", "Bearer [redacted]", value)
    value = re.sub(
        r"(?i)([\"']?[\w-]*(?:password|senha|token|secret|jwt|authorization|cookie|api[_-]?key)[\w-]*"
        r"[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s&,;]+)",
        r"\1[redacted]",
        value,
    )
    value = re.sub(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+", "[redacted]", value)
    value = re.sub(r"(\w+://)[^/@\s]+:[^/@\s]+@", r"\1[redacted]@", value)
    value = re.sub(r"(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[email redacted]", value)
    return re.sub(r"(?i)([A-Z]:\\Users\\)[^\\\s]+", r"\1[redacted]", value)


def log_directory() -> Path:
    if configured := os.environ.get("THERMOPOWER_LOG_DIRECTORY"):
        return Path(configured)
    if root := os.environ.get("THERMOPOWER_APP_DATA_DIR"):
        return Path(root) / "logs"
    if sys.platform == "win32":
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
            / "ThermoPower Monitor/logs"
        )
    return Path("logs")


def new_correlation_id(category: str = "APP") -> str:
    return f"TP-{category}-{uuid4().hex[:12].upper()}"


def category_for(name: str) -> str:
    for key, category in (
        ("report", "REPORT"),
        ("export", "EXPORT"),
        ("synchron", "SYNCHRONIZATION"),
        ("acquisition", "ACQUISITION"),
        ("adapter", "SERIAL"),
        ("serial", "SERIAL"),
        ("probe", "SERIAL"),
        ("database", "DATABASE"),
        ("sqlalchemy", "DATABASE"),
        ("auth", "AUTH"),
        ("session", "SESSION"),
    ):
        if key in name.lower():
            return category
    return "APPLICATION"


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = request_context.get() or {}
        metadata = build_metadata()
        error = record.exc_info
        data = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "category": getattr(
                record,
                "category",
                category_for(record.name)
                if category_for(record.name) != "APPLICATION"
                else context.get("category", "APPLICATION"),
            ),
            **metadata,
            "operation": getattr(record, "operation", context.get("operation", record.funcName)),
            "endpoint": context.get("endpoint"),
            "session_id": getattr(record, "session_id", context.get("session_id")),
            "device_id": getattr(record, "device_id", context.get("device_id")),
            "user_id": context.get("user_id"),
            "correlation_id": getattr(record, "correlation_id", context.get("correlation_id")),
            "error_code": getattr(record, "error_code", context.get("error_code")),
            "exception_type": type(error[1]).__name__
            if error and error[1]
            else getattr(record, "exception_type", context.get("exception_type")),
            "message": record.getMessage(),
            "logger": record.name,
        }
        for key in ("started_at", "completed_at", "status", "http_status", "file", "report_type"):
            data[key] = getattr(record, key, context.get(key))
        if record.levelno >= logging.ERROR and not data["correlation_id"]:
            if not hasattr(record, "correlation_id"):
                record.correlation_id = new_correlation_id()
            data["correlation_id"] = record.correlation_id
        if record.levelno >= logging.ERROR and not data["error_code"]:
            record.error_code = data["correlation_id"]
            data["error_code"] = record.error_code
        if error:
            data["traceback"] = "".join(traceback.format_exception(*error))
        return json.dumps(sanitize(data), ensure_ascii=False, default=str)


def configure_logging(
    directory: Path | None = None, max_bytes: int = 5_000_000, backup_count: int = 5
) -> None:
    directory = directory or log_directory()
    directory.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Alembic's fileConfig disables loggers created before migrations, including
    # the frozen launcher's __main__. Restore application logging on reconfiguration.
    for name, logger in list(logging.Logger.manager.loggerDict.items()):
        if isinstance(logger, logging.Logger) and (
            name == "__main__" or name == "app" or name.startswith(("app.", "uvicorn"))
        ):
            logger.disabled = False
    for name, level in (("thermopower.log", logging.INFO), ("errors.log", logging.ERROR)):
        path = (directory / name).resolve()
        if any(
            isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == path
            for h in root.handlers
        ):
            continue
        handler = RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        handler.setLevel(level)
        handler.setFormatter(StructuredFormatter())
        root.addHandler(handler)
    # Access logs may contain WebSocket tokens in the query string. Sanitize all output.
    for handler in root.handlers:
        if not isinstance(
            handler, logging.NullHandler
        ) and not handler.__class__.__module__.startswith("_pytest"):
            handler.setFormatter(StructuredFormatter())
    for name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            handler.setFormatter(StructuredFormatter())
