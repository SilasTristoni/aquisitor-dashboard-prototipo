"""AT runtime evidence. Disk I/O and sanitization run outside the serial worker.

No sampling or rotation: retain the entire bench history until explicitly archived.
Overflow/I/O failures are counted and exported, never hidden or fed into acquisition.
"""

import atexit
import copy
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from queue import Full, Queue
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from app.core.observability import log_directory, sanitize
from app.core.version import APPLICATION_VERSION

EVENTS = frozenset(
    {
        "AT_STATE",
        "AT_OPEN",
        "AT_CLOSE",
        "AT_TX",
        "AT_RX_FIRST_BYTE",
        "AT_RX_COMPLETE",
        "AT_FRAME_ACCEPTED",
        "AT_FRAME_RECOVERED",
        "AT_FRAME_DUPLICATE",
        "AT_FRAME_REJECTED",
        "AT_TIMEOUT",
        "AT_RESYNC",
        "AT_RECOVERY",
        "AT_RECONNECT",
        "AT_SAMPLE_PUBLISHED",
    }
)


def trace_directory() -> Path:
    return log_directory() / "physical"


def frame_fields(payload: bytes) -> dict:
    return {
        "raw_byte_count": len(payload),
        "frame_length": len(payload),
        "prefix": "TCP-32" if payload.startswith(b"TCP-32") else "other",
        "terminator": "CRLF"
        if payload.endswith(b"\r\n")
        else "LF"
        if payload.endswith(b"\n")
        else None,
        "frame_sha256": hashlib.sha256(payload).hexdigest(),
    }


class PhysicalJournal:
    def __init__(self):
        self.queue = Queue(maxsize=20000)
        self.lock = Lock()
        self.worker = None
        self.run_id = uuid4().hex
        self.sequence = 0
        self.dropped_events = 0
        self.write_errors = 0

    def emit(self, event: str, **fields):
        if (
            os.environ.get(
                "THERMOPOWER_PHYSICAL_TRACE",
                "1" if "engineering-AT4532" in APPLICATION_VERSION else "0",
            )
            != "1"
        ):
            return
        try:
            if event not in EVENTS:
                raise ValueError("Unknown physical event")
            with self.lock:
                if self.worker is None:
                    self.worker = Thread(target=self._write, daemon=True, name="physical-journal")
                    self.worker.start()
                self.sequence += 1
                record = {
                    "event": event,
                    "run_id": self.run_id,
                    "sequence": self.sequence,
                    "monotonic_timestamp": monotonic(),
                    "utc_timestamp": datetime.now(UTC).isoformat(),
                    "session_id": None,
                    "device_id": None,
                    **fields,
                }
                self.queue.put_nowait((trace_directory() / f"{self.run_id}.jsonl", record))
        except Full:
            self.dropped_events += 1
        except Exception:
            # Instrumentation must never turn a healthy physical read into a failure.
            self.write_errors += 1

    def _write(self):
        while True:
            path, record = self.queue.get()
            try:
                if isinstance(record, Event):
                    record.set()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("a", encoding="utf-8") as target:
                        target.write(
                            json.dumps(sanitize(record), ensure_ascii=False, default=str) + "\n"
                        )
            except Exception:
                self.write_errors += 1
            finally:
                self.queue.task_done()

    def flush(self, timeout=10) -> bool:
        if self.worker is None:
            return True
        completed = Event()
        try:
            self.queue.put((None, completed), timeout=timeout)
            return completed.wait(timeout)
        except Full:
            return False

    def snapshot(self, **data):
        if (
            os.environ.get(
                "THERMOPOWER_PHYSICAL_TRACE",
                "1" if "engineering-AT4532" in APPLICATION_VERSION else "0",
            )
            != "1"
        ):
            return
        # Called at probe completion/teardown, never in the per-byte read loop.
        try:
            with self.lock:
                if self.worker is None:
                    self.worker = Thread(target=self._write, daemon=True, name="physical-journal")
                    self.worker.start()
            self.queue.put_nowait(
                (
                    trace_directory() / f"snapshots-{self.run_id}.jsonl",
                    copy.deepcopy(
                        {
                            "utc_timestamp": datetime.now(UTC).isoformat(),
                            "run_id": self.run_id,
                            **data,
                        }
                    ),
                )
            )
        except Full:
            self.dropped_events += 1
        except Exception:
            self.write_errors += 1

    def status(self):
        return {
            "run_id": self.run_id,
            "queued_events": self.queue.qsize(),
            "dropped_events": self.dropped_events,
            "write_errors": self.write_errors,
        }


journal = PhysicalJournal()
atexit.register(journal.flush)


class AtTrace:
    def __init__(self, port, baud, context=None):
        self.port, self.baud = port, baud
        self.context = context or (lambda: {})
        self.connection_id = uuid4().hex
        self.command = None
        self.tx_sent = False
        self.previous_tx = None
        self.previous_rx = None
        self.first_rx = None
        self.first_rx_utc = None
        self.last_rx = None
        self.last_rx_utc = None
        self.response_source = "query"
        self.controlled_observation = False

    def emit(self, event, **fields):
        try:
            context = self.context()
            if self.controlled_observation:
                fields["response_source"] = "controlled_observation"
                fields["tx_sent"] = self.tx_sent
            journal.emit(
                event,
                **{
                    "COM": self.port,
                    "baud": self.baud,
                    "connection_id": self.connection_id,
                    "command": self.command,
                    "tx_sent": self.tx_sent,
                    "first_byte_monotonic": self.first_rx,
                    "first_byte_utc": self.first_rx_utc,
                    "last_byte_monotonic": self.last_rx,
                    "last_byte_utc": self.last_rx_utc,
                    "response_source": self.response_source,
                    **context,
                    **fields,
                },
            )
        except Exception:
            journal.write_errors += 1

    def received(self, chunk, now, utc, first, source):
        self.response_source = source
        if source == "recovered_frame" and not self.controlled_observation:
            self.tx_sent = False
        if first:
            self.first_rx, self.first_rx_utc = now, utc
            self.last_rx, self.last_rx_utc = now, utc
            self.emit(
                "AT_RX_FIRST_BYTE",
                monotonic_timestamp=now,
                utc_timestamp=utc,
                raw_byte_count=len(chunk),
                interval_since_previous_rx=now - self.previous_rx
                if self.previous_rx is not None
                else None,
            )
        self.last_rx, self.last_rx_utc = now, utc
        self.previous_rx = now

    def write(self, connection, payload, clock=monotonic):
        # This function is called in the serial worker at the actual driver write.
        self.command = (
            payload.decode("ascii", "replace").strip()
            if payload in {b"*IDN?\n", b"SYST:UNIT CEL\n", b"FETCH?\n"}
            else "[unrecognized command]"
        )
        now, utc = clock(), datetime.now(UTC).isoformat()
        previous = self.previous_tx
        self.previous_tx = now
        self.first_rx = self.last_rx = self.first_rx_utc = self.last_rx_utc = None
        self.response_source = "query"
        written = None
        try:
            written = connection.write(payload)
            return written
        finally:
            self.tx_sent = written == len(payload) if written is not None else None
            self.emit(
                "AT_TX",
                monotonic_timestamp=now,
                utc_timestamp=utc,
                write_completed_monotonic=clock(),
                raw_byte_count=written,
                requested_byte_count=len(payload),
                interval_since_previous_tx=now - previous if previous is not None else None,
                interval_since_previous_rx=now - self.previous_rx
                if self.previous_rx is not None
                else None,
            )
