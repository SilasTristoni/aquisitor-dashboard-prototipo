"""Bounded persistence retries, separate from physical device recovery."""

import errno
import logging
import sqlite3
from datetime import UTC, datetime
from time import monotonic

from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)
MAX_AUTOMATIC_ATTEMPTS = 8
STORAGE_ERRORS = (SQLAlchemyError, OSError)


def fault_code(exc):
    original = getattr(exc, "orig", exc)
    code = getattr(original, "sqlite_errorcode", 0) & 0xFF
    if code == sqlite3.SQLITE_FULL or getattr(original, "errno", None) in {
        errno.ENOSPC, getattr(errno, "EDQUOT", -1),
    } or "database or disk is full" in str(original).casefold():
        return "storage_full"
    if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        return "storage_busy"
    return "storage_unavailable"


def record_failure(runtime, device_id, exc):
    previous = runtime.storage_fault
    attempts = (previous or {}).get("attempts", 0) + 1
    exhausted = attempts >= MAX_AUTOMATIC_ATTEMPTS
    runtime.storage_fault = {
        "code": fault_code(exc),
        "since": (previous or {}).get("since", datetime.now(UTC).isoformat()),
        "attempts": attempts,
        "retry_at_monotonic": monotonic() + (
            0 if fault_code(exc) == "storage_busy" and attempts == 1
            else min(30, 2 ** min(attempts, 5))
        ),
        "automatic_retry_exhausted": exhausted,
        "message": "Gravação indisponível; amostras pendentes preservadas em memória. "
        "A aquisição aguarda armazenamento; o ensaio possui uma interrupção. "
        "Libere espaço/verifique o banco e tente Pausar/Continuar novamente.",
    }
    # Never stringify SQLAlchemy errors: they can contain the entire raw sample batch.
    if previous is None or (exhausted and not previous["automatic_retry_exhausted"]):
        logger.error("Sample persistence unavailable device_id=%s session_id=%s code=%s "
                     "attempts=%s automatic_retry_exhausted=%s; pending samples retained",
                     device_id, runtime.session_id, runtime.storage_fault["code"],
                     attempts, exhausted)


def retry_due(runtime):
    fault = runtime.storage_fault
    return not fault or (
        not fault["automatic_retry_exhausted"] and monotonic() >= fault["retry_at_monotonic"]
    )
