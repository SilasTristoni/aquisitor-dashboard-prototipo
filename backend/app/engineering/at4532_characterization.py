"""Controlled AT4532 observation using production framing, without recovery/polling."""

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import serial

from app.adapters.specific import At4532Parser, At4532Protocol
from app.adapters.transports import (
    At4532SerialTransport,
    SerialTransportConfiguration,
    SerialTransportError,
)


def stamp():
    return {"utc": datetime.now(UTC).isoformat(), "monotonic": monotonic()}


def open_observation_serial(**kwargs):
    if sys.platform == "win32":
        from app.engineering.windows_serial import NoResetSerial

        return NoResetSerial(**kwargs)
    return serial.Serial(**kwargs)


class ObservedSerial:
    """Record reads at the driver boundary; never claim electrical wire timestamps."""

    def __init__(self, connection, emit):
        self.connection = connection
        self.emit = emit
        self.last_rx = None

    def __getattr__(self, name):
        return getattr(self.connection, name)

    @property
    def timeout(self):
        return self.connection.timeout

    @timeout.setter
    def timeout(self, value):
        self.connection.timeout = value

    def read(self, size):
        before = self.connection.in_waiting
        started = stamp()
        data = self.connection.read(size)
        ended = stamp()
        self.emit(
            "read",
            started=started,
            ended=ended,
            in_waiting_before=before,
            in_waiting_after=self.connection.in_waiting,
            size=len(data),
            hex=data.hex(),
            since_last_rx_s=(ended["monotonic"] - self.last_rx)
            if self.last_rx is not None
            else None,
        )
        if data:
            self.last_rx = ended["monotonic"]
        return data


class Characterization:
    def __init__(self, emit, serial_factory=open_observation_serial):
        self.emit_event = emit
        self.serial_factory = serial_factory
        self.window = "opening"
        self.frames = []
        self.connection = None
        self.transport = None

    def emit(self, kind, **values):
        self.emit_event({"event": kind, "window": self.window, **stamp(), **values})

    def observe(self, seconds):
        deadline = monotonic() + seconds
        self.emit("window_started", duration_s=seconds, in_waiting=self.connection.in_waiting)
        while monotonic() < deadline:
            # Reuse ONLY the production assembler: it retains partial TCP-32 bytes
            # across calls. No open/query/write/recovery method is invoked.
            self.transport.resynchronization_timeout_s = min(0.25, deadline - monotonic())
            self.transport._settle_required = True
            try:
                self.transport._synchronize_frames(b"\n", 65_536)
            except SerialTransportError as exc:
                if exc.code != "incomplete_late_frame":
                    raise
            event = self.transport._resynchronization_history[-1]
            queued = list(self.transport.recovered_frames)
            self.transport.recovered_frames.clear()
            for frame in event["frames"]:
                payload = bytes.fromhex(frame["raw_hex"])
                boundary = next((f for f in queued if f["payload"] == payload), {})
                details = {
                    "size": len(payload),
                    "hex": payload.hex(),
                    "prefix": payload[:32].decode("ascii", "backslashreplace"),
                    "terminator": "CRLF" if payload.endswith(b"\r\n") else "LF",
                    "first_byte_monotonic": boundary.get("first_byte_monotonic"),
                    "last_byte_monotonic": boundary.get("rx_monotonic"),
                    "received_timestamp": boundary.get("timestamp_rx"),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                try:
                    parsed = At4532Parser().parse(payload, allow_all_open=True)
                    details.update(
                        valid=True,
                        device_timestamp=(
                            parsed.device_timestamp.isoformat() if parsed.device_timestamp else None
                        ),
                        temperatures_c=list(parsed),
                    )
                except Exception as exc:
                    details.update(valid=False, error=str(exc))
                self.frames.append({"window": self.window, **details})
                self.emit("frame", **details)
        self.emit(
            "window_finished",
            in_waiting=self.connection.in_waiting,
            partial_hex=bytes(self.transport._partial_input).hex(),
        )

    def write(self, payload):
        # Observe while waiting: do not discard bytes or inject TX into an unfinished frame.
        previous_window = self.window
        self.window = previous_window + "_pre_tx"
        deadline = monotonic() + 10
        while (
            self.transport._partial_input
            or self.connection.in_waiting
            or self.connection.last_rx is not None
            and monotonic() - self.connection.last_rx < 1.0
        ):
            if monotonic() >= deadline:
                self.emit("write_skipped", reason="No clean boundary with 1 s post-RX guard")
                self.window = previous_window
                return False
            self.observe(min(0.25, deadline - monotonic()))
        self.window = previous_window
        waiting = self.connection.in_waiting
        started = stamp()
        count = self.connection.write(payload)
        ended = stamp()
        self.emit(
            "write",
            started=started,
            ended=ended,
            hex=payload.hex(),
            size=count,
            in_waiting_before=waiting,
            in_waiting_after=self.connection.in_waiting,
            since_last_rx_s=(started["monotonic"] - self.connection.last_rx)
            if self.connection.last_rx is not None
            else None,
        )
        if count != len(payload):
            raise OSError("Incomplete write; observation stopped without retry")
        self.connection.flush()  # Wait for output completion; never reset either buffer.
        self.emit("write_flush_completed")
        return True

    def run(self, port="COM5", passive_seconds=10):
        config = SerialTransportConfiguration(port, 19200, 8, "N", 1, 0.25, 0.25)
        self.emit(
            "open_started",
            configuration=config.public_dict(),
            input_reset=False,
            output_reset=False,
            recovery=False,
        )
        try:
            raw = self.serial_factory(
                port=port,
                baudrate=19200,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=0.25,
                write_timeout=2,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            self.connection = ObservedSerial(raw, self.emit)
            self.emit(
                "open_completed",
                in_waiting=raw.in_waiting,
                dtr=getattr(raw, "dtr", None),
                rts=getattr(raw, "rts", None),
            )
            self.transport = At4532SerialTransport(config)
            self.transport.connection = self.connection
            self.run_sequence(passive_seconds)
        finally:
            if self.connection is not None:
                try:
                    self.emit(
                        "closing",
                        partial_hex=(
                            bytes(self.transport._partial_input).hex() if self.transport else ""
                        ),
                        in_waiting=self.connection.in_waiting,
                    )
                finally:
                    self.connection.close()
                    self.emit("closed")

    def run_sequence(self, passive_seconds):
        self.window = "passive"
        self.observe(passive_seconds)
        self.window = "after_celsius"
        if not self.write(At4532Protocol.celsius.request):
            return
        self.observe(10)
        self.window = "after_fetch_1"
        if not self.write(At4532Protocol.temperatures.request):
            return
        self.observe(10)
        eligible = any(
            f["window"] == "after_fetch_1"
            and f["valid"]
            and any(v is not None for v in f["temperatures_c"])
            for f in self.frames
        )
        self.window = "after_fetch_2"
        if eligible and self.write(At4532Protocol.temperatures.request):
            self.observe(10)
        elif not eligible:
            self.emit("window_skipped", reason="No healthy valid frame after first FETCH")


def main(argv=None):
    parser = argparse.ArgumentParser(description="AT4532 controlled engineering observation")
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--passive-seconds", type=int, choices=range(5, 11), default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    runtime = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parents[3]
    build_info = runtime / "build-info.json"
    (args.output / "build-info.json").write_text(
        build_info.read_text(encoding="utf-8-sig")
        if build_info.exists()
        else json.dumps({"build": "development", "source": str(Path(__file__).resolve())}),
        encoding="utf-8",
    )
    events_path = args.output / "events.jsonl"
    with events_path.open("x", encoding="utf-8") as output:

        def emit(event):
            output.write(json.dumps(event, ensure_ascii=False) + "\n")
            if event["event"] != "read":
                output.flush()

        tool = Characterization(emit)
        try:
            tool.run(args.port, args.passive_seconds)
        except BaseException as exc:
            tool.emit("error", error_type=type(exc).__name__, message=str(exc))
            raise
        finally:
            output.flush()
            (args.output / "frames.json").write_text(
                json.dumps(tool.frames, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            hashes = [
                f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
                for p in sorted(args.output.iterdir())
                if p.is_file()
            ]
            (args.output / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
