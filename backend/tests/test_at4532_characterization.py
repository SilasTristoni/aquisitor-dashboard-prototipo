import sys

import pytest
from test_at4532_input_boundary import Clock, ScheduledSerial, frame_for

from app.engineering.at4532_characterization import Characterization


@pytest.mark.parametrize("split", [6, 7])
def test_four_windows_use_production_framing_without_resets_or_identity(monkeypatch, split):
    clock = Clock()
    connection = ScheduledSerial(clock)
    monkeypatch.setattr("app.adapters.transports.monotonic", clock.monotonic)
    monkeypatch.setattr("app.engineering.at4532_characterization.monotonic", clock.monotonic)
    connection.schedule(1, frame_for(1)[:split])
    connection.schedule(1.4, frame_for(1)[split:])
    sequence = 1

    def write(payload):
        nonlocal sequence
        sequence += 1
        connection.schedule(0.5, frame_for(sequence))

    connection.on_write = write
    connection.reset_output_buffer = lambda: pytest.fail("output reset")
    events = []
    tool = Characterization(events.append, lambda **_: connection)
    tool.run()
    assert [p for _, p in connection.writes] == [b"SYST:UNIT CEL\n", b"FETCH?\n", b"FETCH?\n"]
    assert connection.input_resets == 0 and not connection.is_open
    assert [f["window"] for f in tool.frames] == [
        "passive",
        "after_celsius",
        "after_fetch_1",
        "after_fetch_2",
    ]
    assert all(f["valid"] and f["size"] == 694 for f in tool.frames)
    assert tool.frames[0]["first_byte_monotonic"] < tool.frames[0]["last_byte_monotonic"]
    assert bytes.fromhex(tool.frames[0]["hex"]) == frame_for(1)
    assert len([e for e in events if e["event"] == "read" and e["size"]]) == 694 * 4
    assert all(e["since_last_rx_s"] >= 1 for e in events if e["event"] == "write")


def test_config_only_response_does_not_enable_second_fetch(monkeypatch):
    clock = Clock()
    connection = ScheduledSerial(clock)
    monkeypatch.setattr("app.adapters.transports.monotonic", clock.monotonic)
    monkeypatch.setattr("app.engineering.at4532_characterization.monotonic", clock.monotonic)
    connection.on_write = (
        lambda p: connection.schedule(0.2, frame_for(1)) if p.startswith(b"SYST") else None
    )
    events = []
    tool = Characterization(events.append, lambda **_: connection)
    tool.run(passive_seconds=5)
    assert [p for _, p in connection.writes] == [b"SYST:UNIT CEL\n", b"FETCH?\n"]
    assert len(tool.frames) == 1
    assert any(e["event"] == "window_skipped" for e in events)
    assert connection.input_resets == 0


def test_partial_boundary_is_preserved_and_blocks_transmission(monkeypatch):
    clock = Clock()
    connection = ScheduledSerial(clock)
    connection.schedule(4.9, frame_for(1)[:7])
    monkeypatch.setattr("app.adapters.transports.monotonic", clock.monotonic)
    monkeypatch.setattr("app.engineering.at4532_characterization.monotonic", clock.monotonic)
    events = []
    tool = Characterization(events.append, lambda **_: connection)
    tool.run(passive_seconds=5)
    assert connection.writes == [] and connection.input_resets == 0
    assert bytes(tool.transport._partial_input) == frame_for(1)[:7]
    assert any(e["event"] == "write_skipped" for e in events)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows driver boundary")
def test_windows_open_does_not_purge_buffers(monkeypatch):
    from app.engineering.windows_serial import NoResetSerial, win32

    opened = []
    monkeypatch.setattr(win32, "CreateFile", lambda *args: opened.append(args) or 123)
    monkeypatch.setattr(win32, "CreateEvent", lambda *args: 456)
    monkeypatch.setattr(win32, "SetupComm", lambda *args: True)
    monkeypatch.setattr(win32, "GetCommTimeouts", lambda *args: True)
    monkeypatch.setattr(
        win32, "PurgeComm", lambda *args: pytest.fail("Implicit driver buffer reset")
    )
    monkeypatch.setattr(NoResetSerial, "_reconfigure_port", lambda self: None)
    monkeypatch.setattr(NoResetSerial, "_close", lambda self: None)
    connection = NoResetSerial(port="COM5", baudrate=19200)
    try:
        assert connection.is_open
        assert opened[0][0] == "COM5" and opened[0][2] == 0  # Exclusive ownership.
    finally:
        connection.close()


def test_failed_observation_keeps_error_and_hash_manifest(monkeypatch, tmp_path):
    import hashlib
    import json

    from app.engineering import at4532_characterization as module

    def fail(self, *args):
        raise OSError("Physical port absent")

    monkeypatch.setattr(module.Characterization, "run", fail)
    destination = tmp_path / "capture"
    with pytest.raises(OSError):
        module.main(["--output", str(destination)])
    events = [json.loads(line) for line in (destination / "events.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "error"
    for line in (destination / "SHA256SUMS.txt").read_text().splitlines():
        expected, name = line.split("  ")
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == expected
