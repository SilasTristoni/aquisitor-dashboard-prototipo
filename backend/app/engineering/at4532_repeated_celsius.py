"""Engineering-only repeated Celsius experiment; never called by acquisition."""

import argparse
import hashlib
import json
import sys
from collections import deque
from pathlib import Path

from app.adapters.specific import At4532Protocol
from app.core.observability import sanitize
from app.core.physical_trace import AtTrace, frame_fields, journal, trace_directory
from app.engineering.at4532_characterization import Characterization, open_observation_serial


class RepeatedCelsiusCharacterization(Characterization):
    def __init__(self, emit, serial_factory=open_observation_serial):
        super().__init__(emit, serial_factory)
        self.events = []
        self.pending = bytearray()
        self.pending_first_rx = None
        self.completed = deque()

    def emit(self, kind, **values):
        if kind == "read" and values["size"]:
            # Mirror observed boundaries for evidence only. Production framing/parser
            # still decides which completed lines are valid TCP-32 frames.
            for byte in bytes.fromhex(values["hex"]):
                if not self.pending:
                    self.pending_first_rx = values["ended"]
                self.pending.append(byte)
                if byte == 10:
                    self.completed.append(
                        {
                            "hex": self.pending.hex(),
                            "first_rx": self.pending_first_rx,
                            "last_rx": values["ended"],
                        }
                    )
                    self.pending.clear()
                    self.pending_first_rx = None
        elif kind == "frame":
            boundary = self.completed.popleft()
            if boundary["hex"] != values["hex"]:
                raise RuntimeError("Observed bytes differ from assembler frame")
            values.update(first_rx=boundary["first_rx"], last_rx=boundary["last_rx"])
            # Preserve exact observed clock values, also for identical consecutive frames.
            values.update(
                first_byte_monotonic=boundary["first_rx"]["monotonic"],
                last_byte_monotonic=boundary["last_rx"]["monotonic"],
                received_timestamp=boundary["last_rx"]["utc"],
            )
            write = next(
                (
                    e
                    for e in reversed(self.events)
                    if e["event"] == "write" and e["window"] == self.window
                ),
                None,
            )
            values["command_to_first_byte_s"] = (
                boundary["first_rx"]["monotonic"] - write["started"]["monotonic"] if write else None
            )
            values["command_to_frame_complete_s"] = (
                boundary["last_rx"]["monotonic"] - write["started"]["monotonic"] if write else None
            )
            self.frames[-1].update(values)
        super().emit(kind, **values)
        # Preserve the same event timestamp as the evidence sink, without a second stamp.

    def run(self, port="COM5"):
        sink = self.emit_event
        trace = AtTrace(port, 19200, lambda: {
            "operation": "repeated_celsius", "window": self.window
        })
        trace.controlled_observation = True

        def record(event):
            self.events.append(event)
            sink(event)
            kind = event["event"]
            if kind == "open_completed":
                trace.emit("AT_OPEN", outcome="opened", input_reset=False)
            elif kind == "write":
                started = event["started"]
                previous = trace.previous_tx
                trace.previous_tx = started["monotonic"]
                trace.command = "SYST:UNIT CEL"
                trace.tx_sent = event["size"] == len(At4532Protocol.celsius.request)
                trace.emit(
                    "AT_TX",
                    monotonic_timestamp=started["monotonic"],
                    utc_timestamp=started["utc"],
                    raw_byte_count=event["size"],
                    write_completed_monotonic=event["ended"]["monotonic"],
                    interval_since_previous_tx=started["monotonic"] - previous
                    if previous is not None
                    else None,
                    interval_since_previous_rx=event["since_last_rx_s"],
                )
            elif kind == "frame":
                data = {
                    **frame_fields(bytes.fromhex(event["hex"])),
                    "response_source": "controlled_observation",
                    "window": event["window"],
                    "device_timestamp_original": (
                        event.get("device_timestamp_original") if event["valid"] else None
                    ),
                    "received_timestamp": event["received_timestamp"],
                    "first_byte_monotonic": event["first_byte_monotonic"],
                    "last_byte_monotonic": event["last_byte_monotonic"],
                    "first_byte_utc": event["first_rx"]["utc"],
                    "last_byte_utc": event["last_rx"]["utc"],
                    "temperatures_c": event.get("temperatures_c"),
                    "command_to_first_byte_s": event["command_to_first_byte_s"],
                    "command_to_frame_complete_s": event["command_to_frame_complete_s"],
                }
                trace.emit(
                    "AT_FRAME_ACCEPTED" if event["valid"] else "AT_FRAME_REJECTED",
                    dedupe_result="not_applied_observation_only",
                    **data,
                )
            elif kind == "closed":
                trace.emit("AT_CLOSE", outcome="closed")
            elif kind == "error":
                trace.emit(
                    "AT_STATE", current_state="experiment_failed", reason=event.get("error_type")
                )

            if self.transport:
                # The SAME assembler emits RX first/complete events during observation.
                self.transport.trace = trace

        self.emit_event = record
        return super().run(port, passive_seconds=5)

    def write(self, payload):
        if payload != At4532Protocol.celsius.request:
            raise ValueError("Only SYST:UNIT CEL is allowed in this experiment")
        return super().write(payload)

    def run_sequence(self, passive_seconds):
        self.window = "passive"
        self.observe(5)
        for index in range(1, 4):
            self.window = f"after_celsius_{index}"
            if not self.write(At4532Protocol.celsius.request):
                raise RuntimeError("Experiment stopped: no safe input boundary; no retry")
            self.observe(5)

    def summary(self):
        windows = []
        for window in ["passive", *(f"after_celsius_{i}" for i in range(1, 4))]:
            events = [e for e in self.events if e["window"] == window]
            write = next((e for e in events if e["event"] == "write"), None)
            reads = [e for e in events if e["event"] == "read" and e["size"]]
            finished = next((e for e in events if e["event"] == "window_finished"), None)
            frames = [f for f in self.frames if f["window"] == window]
            first_rx = reads[0]["ended"] if reads else None
            last_rx = reads[-1]["ended"] if reads else None
            windows.append(
                {
                    "window": window,
                    "write_started": write["started"] if write else None,
                    "write_ended": write["ended"] if write else None,
                    "write_size": write["size"] if write else None,
                    "observation_completed": finished is not None,
                    "first_rx": first_rx,
                    "last_rx": last_rx,
                    "rx_bytes": sum(e["size"] for e in reads),
                    "command_to_first_byte_s": (
                        first_rx["monotonic"] - write["started"]["monotonic"]
                        if write and first_rx
                        else None
                    ),
                    "partial_hex_at_end": finished["partial_hex"] if finished else None,
                    "frames": frames,
                }
            )
        valid = [f for f in self.frames if f["valid"]]
        comparisons = []
        for previous, current in zip(valid, valid[1:], strict=False):
            comparisons.append(
                {
                    "previous_window": previous["window"],
                    "current_window": current["window"],
                    "same_sha256": previous["sha256"] == current["sha256"],
                    "same_device_timestamp": previous["device_timestamp"]
                    == current["device_timestamp"],
                    "same_temperatures": previous["temperatures_c"] == current["temperatures_c"],
                    "changed_channels": [
                        i
                        for i, (a, b) in enumerate(
                            zip(previous["temperatures_c"], current["temperatures_c"], strict=True),
                            1,
                        )
                        if a != b
                    ],
                }
            )
        return {
            "experiment": "passive_5s_three_celsius_5s",
            "timing_reference": "driver read completion / write start; not electrical wire timing",
            "physical_conclusion": "pending_engineering_review",
            "windows": windows,
            "adjacent_valid_frame_comparisons": comparisons,
            "all_frames_including_pre_tx": self.frames,
            "pending_hex": self.pending.hex(),
        }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="AT4532: passive 5 s + three Celsius writes, 5 s each"
    )
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.output is None:
        from datetime import UTC, datetime
        from uuid import uuid4

        args.output = trace_directory() / "characterizations" / (
            datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
        )
    args.output.mkdir(parents=True, exist_ok=False)
    runtime = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parents[3]
    metadata = runtime / "build-info.json"
    (args.output / "build-info.json").write_text(
        metadata.read_text(encoding="utf-8-sig")
        if metadata.exists()
        else json.dumps({"purpose": "internal_engineering_only", "build": "development"}),
        encoding="utf-8",
    )
    with (args.output / "events.jsonl").open("x", encoding="utf-8") as output:

        def emit(event):
            output.write(json.dumps(sanitize(event), ensure_ascii=False) + "\n")
            if event["event"] != "read":
                output.flush()

        tool = RepeatedCelsiusCharacterization(emit)
        try:
            tool.run(args.port)
        except BaseException as exc:
            tool.emit("error", error_type=type(exc).__name__, message=str(exc))
            raise
        finally:
            output.flush()
            for name, data in (("frames.json", tool.frames), ("summary.json", tool.summary())):
                (args.output / name).write_text(
                    json.dumps(sanitize(data), ensure_ascii=False, indent=2), encoding="utf-8"
                )
            (args.output / "SHA256SUMS.txt").write_text("\n".join(
                f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
                for p in sorted(args.output.iterdir()) if p.is_file() and p.name != "SHA256SUMS.txt"
            ) + "\n", encoding="utf-8")
            journal.flush()
    # Hash after closing events.jsonl so its persisted bytes are final on Windows.
    return 0


def entrypoint(argv=None):
    # Finalize evidence even when opening, writing, reading, or Ctrl+C fails.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output", type=Path)
    args, _ = parser.parse_known_args(argv)
    existed = args.output.exists() if args.output else True
    try:
        return main(argv)
    finally:
        if args.output and not existed and args.output.is_dir():
            hashes = [
                f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
                for p in sorted(args.output.iterdir())
                if p.is_file() and p.name != "SHA256SUMS.txt"
            ]
            (args.output / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="utf-8")


if __name__ == "__main__":
    entrypoint()
