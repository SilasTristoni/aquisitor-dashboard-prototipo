import hashlib
import json

import pytest
from test_at4532_input_boundary import Clock, ScheduledSerial, frame_for

from app.engineering import at4532_repeated_celsius as module


def setup_tool(monkeypatch):
    clock = Clock()
    connection = ScheduledSerial(clock)
    monkeypatch.setattr("app.adapters.transports.monotonic", clock.monotonic)
    monkeypatch.setattr("app.engineering.at4532_characterization.monotonic", clock.monotonic)
    connection.reset_output_buffer = lambda: pytest.fail("Output reset forbidden")
    events = []
    tool = module.RepeatedCelsiusCharacterization(events.append, lambda **_: connection)
    return clock, connection, events, tool


def test_three_commands_fragmented_frames_and_actual_latencies(monkeypatch):
    clock, connection, events, tool = setup_tool(monkeypatch)

    def respond(payload):
        frame = frame_for(len(connection.writes))
        connection.schedule(0.016, frame[:6])
        connection.schedule(0.36, frame[6:])

    connection.on_write = respond
    tool.run()
    assert connection.writes == [
        (105, b"SYST:UNIT CEL\n"),
        (110, b"SYST:UNIT CEL\n"),
        (115, b"SYST:UNIT CEL\n"),
    ]
    assert clock.now == 120
    assert connection.input_resets == 0 and not connection.is_open
    assert [e["duration_s"] for e in events if e["event"] == "window_started"] == [5] * 4
    report = tool.summary()
    assert report["windows"][0]["rx_bytes"] == 0
    for index, window in enumerate(report["windows"][1:], 1):
        frame = window["frames"][0]
        assert window["rx_bytes"] == frame["size"] == 694
        assert window["write_started"]["monotonic"] == 100 + index * 5
        assert window["write_ended"] and window["first_rx"] and window["last_rx"]
        assert frame["valid"] and len(frame["temperatures_c"]) == 32
        assert frame["device_timestamp"] and frame["terminator"] == "CRLF"
        assert frame["sha256"] == hashlib.sha256(frame_for(index)).hexdigest()
        assert frame["command_to_first_byte_s"] == pytest.approx(0.016)
        assert frame["command_to_frame_complete_s"] == pytest.approx(0.36)
    assert all(not c["same_device_timestamp"] for c in report["adjacent_valid_frame_comparisons"])
    # Changing only a timestamp is not evidence of changing temperatures/acquisition.
    assert all(c["same_temperatures"] for c in report["adjacent_valid_frame_comparisons"])
    assert report["physical_conclusion"] == "pending_engineering_review"


def test_identical_frames_keep_separate_rx_boundaries(monkeypatch):
    _, connection, _, tool = setup_tool(monkeypatch)
    connection.on_write = lambda _: (
        connection.schedule(0.1, frame_for(1)),
        connection.schedule(0.2, frame_for(1)),
    )
    tool.run()
    assert len(tool.frames) == 6
    assert tool.frames[0]["last_byte_monotonic"] == pytest.approx(105.1)
    assert tool.frames[1]["last_byte_monotonic"] == pytest.approx(105.2)
    assert all(
        c["same_sha256"] and c["same_device_timestamp"] and c["same_temperatures"]
        for c in tool.summary()["adjacent_valid_frame_comparisons"]
    )


@pytest.mark.parametrize("response", [b"", b"TCP-32,broken\r\n", frame_for(1)[:7]])
def test_silence_invalid_and_partial_are_preserved(monkeypatch, response):
    _, connection, _, tool = setup_tool(monkeypatch)
    connection.on_write = lambda _: connection.schedule(0.1, response)
    if response and not response.endswith(b"\n"):
        with pytest.raises(RuntimeError, match="no safe input boundary"):
            tool.run()
        assert len(connection.writes) == 1
        assert tool.summary()["pending_hex"] == response.hex()
    else:
        tool.run()
        assert len(connection.writes) == 3
        assert all(not f["valid"] for f in tool.frames)
        assert len(tool.frames) == (3 if response else 0)
    assert connection.input_resets == 0 and not connection.is_open


def test_passive_frame_and_guard_are_not_attributed_to_command(monkeypatch):
    _, connection, events, tool = setup_tool(monkeypatch)
    connection.schedule(4.9, frame_for(1))
    tool.run()
    assert tool.frames[0]["window"] == "passive"
    assert tool.frames[0]["command_to_first_byte_s"] is None
    assert connection.writes[0][0] >= 105.9
    assert any(e["window"].endswith("_pre_tx") for e in events)


def test_short_write_stops_without_retry(monkeypatch):
    _, connection, events, tool = setup_tool(monkeypatch)
    connection.write = lambda _: 2
    with pytest.raises(OSError, match="Incomplete write"):
        tool.run()
    assert len([e for e in events if e["event"] == "write"]) == 1
    assert not connection.is_open


def test_other_commands_are_rejected_before_serial_access(monkeypatch):
    _, _, _, tool = setup_tool(monkeypatch)
    with pytest.raises(ValueError, match="Only SYST:UNIT CEL"):
        tool.write(b"FETCH?\n")


def test_entrypoint_failure_retains_summary_and_verified_manifest(monkeypatch, tmp_path):
    def fail(self, port):
        raise OSError("Fake missing port")

    monkeypatch.setattr(module.RepeatedCelsiusCharacterization, "run", fail)
    destination = tmp_path / "capture"
    with pytest.raises(OSError):
        module.entrypoint(["--output", str(destination)])
    assert (
        json.loads((destination / "summary.json").read_text())["windows"][1]["write_started"]
        is None
    )
    assert '"event": "error"' in (destination / "events.jsonl").read_text()
    manifest = (destination / "SHA256SUMS.txt").read_text()
    for line in manifest.splitlines():
        expected, name = line.split("  ")
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == expected
    with pytest.raises(FileExistsError):
        module.entrypoint(["--output", str(destination)])
    assert (destination / "SHA256SUMS.txt").read_text() == manifest
