"""Persist already accepted samples independently of new device input."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from contextvars import ContextVar
from typing import TYPE_CHECKING

from app.services.storage_health import retry_due

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.services.acquisition import AcquisitionService

logger = logging.getLogger(__name__)
FLUSH_INTERVAL_SECONDS = 2.0
SQLITE_BUSY_TIMEOUT_MS = 25
_bounded_write: ContextVar[bool] = ContextVar("bounded_pending_write", default=False)


@contextmanager
def bounded_pending_writes() -> Iterator[None]:
    """Limit SQLite lock waits for periodic and application-shutdown writes only."""
    token = _bounded_write.set(True)
    try:
        yield
    finally:
        _bounded_write.reset(token)


@contextmanager
def sample_write_session(factory: Callable[[], "Session"]) -> Iterator["Session"]:
    with factory() as db:
        if not _bounded_write.get() or db.get_bind().dialect.name != "sqlite":
            yield db
            return
        # Own the connection until the original timeout is restored. A Session
        # commit must not return it to the pool with our temporary setting.
        with db.get_bind().connect() as connection:
            db.bind = connection
            cursor = connection.connection.driver_connection.cursor()
            original_timeout = cursor.execute("PRAGMA busy_timeout").fetchone()[0]
            try:
                cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
                yield db
            finally:
                db.close()  # Roll back a failed transaction before returning the connection.
                cursor.execute(f"PRAGMA busy_timeout={original_timeout}")
                cursor.close()


async def flush_pending_samples(service: "AcquisitionService") -> None:
    # Run on the acquisition event loop, never in a thread. The existing _flush
    # transaction has no suspension points: commit, buffer removal and counters
    # complete together before another task can flush or change the session.
    for device_id, runtime in list(service.runtimes.items()):
        if not runtime.session_id or not runtime.buffer or not retry_due(runtime):
            continue
        try:
            with bounded_pending_writes():
                await service._flush(device_id, runtime)
        except Exception as exc:
            if runtime.storage_fault:
                continue  # Structured, bounded logging belongs to storage_health.
            # Keep the buffer and retry on the next persistence tick. A DB error
            # must not stop another source or invoke device recovery.
            logger.error(
                "Pending sample persistence failed device_id=%s session_id=%s "
                "error_type=%s; buffered samples retained",
                device_id, runtime.session_id, type(exc).__name__,
            )


@asynccontextmanager
async def pending_sample_persistence(service: "AcquisitionService") -> AsyncIterator[None]:
    async def run() -> None:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            await flush_pending_samples(service)

    task = asyncio.create_task(run(), name="pending-sample-persistence")
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        # Normal device shutdown retains its existing final flush policy.
