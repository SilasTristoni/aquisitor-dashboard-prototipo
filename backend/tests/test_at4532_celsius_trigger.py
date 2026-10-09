"""Real October bench captures; accelerated serial time is explicitly synthetic."""

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import serial
from test_at4532_input_boundary import setup_transport
from test_at4532_repeated_celsius import setup_tool
from test_physical_engineering import _manual_at4532_device

from app.adapters.specific import At4532Parser, At4532SerialAdapter
from app.core.config import Settings
from app.services.protocol_probe import ProtocolProbeService

pytestmark = pytest.mark.physical_regression_fixtures
CAPTURES = json.loads(
    (Path(__file__).parent / "fixtures/at4532_repeated_celsius_20261006.json").read_text()
)
FRAMES = [bytes.fromhex(row["hex"]) for row in CAPTURES]
TRIGGER = b"SYST:UNIT CEL\n"


def test_exact_physical_captures():
    for frame, evidence in zip(FRAMES, CAPTURES, strict=True):
        parsed = At4532Parser().parse(frame)
        assert len(frame) == 694 and frame.endswith(b"\r\n")
        assert hashlib.sha256(frame).hexdigest() == evidence["sha256"]
        assert parsed.device_timestamp_raw == evidence["device_timestamp_original"]
        assert list(parsed.values) == evidence["temperatures_c"]
        assert len(parsed.channels) == 32
    assert len({r["sha256"] for r in CAPTURES}) == 3
    assert len({r["device_timestamp"] for r in CAPTURES}) == 3
    assert len({tuple(r["temperatures_c"]) for r in CAPTURES}) == 3


def test_passive_and_three_physical_responses(monkeypatch):
    _, wire, _, tool = setup_tool(monkeypatch)

    def respond(command):
        assert command == TRIGGER
        index = len(wire.writes) - 1
        frame = FRAMES[index]
        wire.schedule(0.01, frame[:7])
        wire.schedule(CAPTURES[index]["command_to_frame_complete_s"], frame[7:])

    wire.on_write = respond
    tool.run()
    windows = tool.summary()["windows"]
    assert windows[0]["rx_bytes"] == 0 and not windows[0]["frames"]
    assert [w["frames"][0]["sha256"] for w in windows[1:]] == [r["sha256"] for r in CAPTURES]
    assert all(len(w["frames"]) == 1 for w in windows[1:])


@pytest.mark.asyncio
async def test_production_engine_three_distinct_celsius_frames(monkeypatch):
    _, wire, transport = setup_transport(monkeypatch)
    transport.configuration = replace(transport.configuration, read_timeout_s=4)
    sent = 0

    def respond(command):
        nonlocal sent
        if command == b"*IDN?\n":
            return
        assert command == TRIGGER
        frame = FRAMES[sent]
        wire.schedule(0.01, frame[:6])
        wire.schedule(0.6, frame[6:347])
        wire.schedule(CAPTURES[sent]["command_to_frame_complete_s"], frame[347:])
        sent += 1

    wire.on_write = respond
    adapter = At4532SerialAdapter("COM_BOUNDARY", 19200, transport, allow_identity_fallback=True)
    try:
        await adapter.connect()
        readings = [await adapter.read_once() for _ in range(3)]
        assert [bytes(r.raw_payload["raw_bytes"]) for r in readings] == FRAMES
        tx = [t for t, p in wire.writes if p == TRIGGER]
        assert [b - a for a, b in zip(tx, tx[1:], strict=False)] == pytest.approx([5, 5])
        assert wire.input_resets == 0 and adapter.fetch_diagnostics.reconnect_count == 0
        assert all(
            ProtocolProbeService._distinct_at_frames(a, b)
            for a, b in zip(readings, readings[1:], strict=False)
        )
        same_time = readings[1].model_copy(
            update={"device_timestamp": readings[0].device_timestamp}
        )
        same_bytes = readings[1].model_copy(update={"raw_payload": readings[0].raw_payload})
        assert not ProtocolProbeService._distinct_at_frames(readings[0], same_time)
        assert not ProtocolProbeService._distinct_at_frames(readings[0], same_bytes)
    finally:
        await adapter.disconnect()


def test_configured_cadence_never_assumes_one_hz(monkeypatch):
    monkeypatch.setenv("THERMOPOWER_AT4532_TRIGGER_INTERVAL_SECONDS", "7")
    assert Settings().at4532_trigger_interval_seconds == 7
    assert (
        At4532SerialAdapter("COM_TEST", 19200, trigger_interval_seconds=7).expected_interval_seconds
        == 7
    )
    with pytest.raises(ValueError):
        At4532SerialAdapter("COM_TEST", 19200, trigger_interval_seconds=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("same_timestamp", [False, True])
async def test_full_probe_requires_distinct_physical_timestamp_and_hash(
    monkeypatch, same_timestamp
):
    _, wire, transport = setup_transport(monkeypatch)
    count = 0

    def respond(command):
        nonlocal count
        if command == b"*IDN?\n":
            return
        assert command == TRIGGER
        frame = FRAMES[min(count, 1)]
        if same_timestamp and count:
            frame = frame.replace(b"18:58:57", b"18:58:52")
        wire.schedule(1.6, frame)
        count += 1

    wire.on_write = respond
    monkeypatch.setattr(
        "app.services.protocol_probe.At4532SerialAdapter",
        lambda port, baud_rate, **kwargs: At4532SerialAdapter(
            port, baud_rate, transport=transport, **kwargs
        ),
    )
    report = await ProtocolProbeService().run(_manual_at4532_device(), "full")
    assert report["result"] == ("failed" if same_timestamp else "passed_with_warning")
    assert report["transport_closed"] and count == 2
    if same_timestamp:
        assert report["errors"][0]["code"] == "duplicate_frame"
    else:
        assert len(report["readings"]) == 2


@pytest.mark.asyncio
async def test_one_hour_celsius_soak_real_transport(monkeypatch, caplog, record_property):
    caplog.set_level("ERROR")
    clock, wire, transport = setup_transport(monkeypatch)
    transport.configuration = replace(transport.configuration, read_timeout_s=4)
    count, opens = 0, 0
    expected = []

    def open_serial(**_):
        nonlocal opens
        opens += 1
        wire.is_open = True
        return wire

    def respond(command):
        nonlocal count
        if command == b"*IDN?\n":
            return
        assert command == TRIGGER, "Normal runtime must never send FETCH"
        count += 1
        if count == 400:
            wire.is_open = False
            raise serial.SerialException("Synthetic COM removal")
        if count in {140, 610}:
            return
        # Derived fixture ONLY in this simulated soak; never used as production data.
        stamp = datetime(2026, 10, 6, 18, 58, 52) + timedelta(seconds=count * 5)
        frame = FRAMES[0].replace(
            b"2026/10/06 18:58:52", stamp.strftime("%Y/%m/%d %H:%M:%S").encode()
        )
        expected.append(frame)
        duration = 1.4 + (count % 7) * 0.1
        wire.schedule(0.009 + (count % 5) * 0.001, frame[:1])
        wire.schedule(duration / 3, frame[1:7])
        wire.schedule(duration / 2, frame[7:347])
        wire.schedule(duration, frame[347:])

    transport.serial_factory = open_serial
    wire.on_write = respond
    adapter = At4532SerialAdapter("COM_BOUNDARY", 19200, transport, allow_identity_fallback=True)
    started = clock.now
    await adapter.connect()
    stream = adapter.start_reading()
    try:
        readings = [await anext(stream) for _ in range(720)]
        received = [bytes(r.raw_payload["raw_bytes"]) for r in readings]
        tx = [t for t, p in wire.writes if p == TRIGGER]
        assert clock.now - started >= 3600
        assert received == expected and len(set(received)) == 720
        assert all(b - a >= 5 - 1e-8 for a, b in zip(tx, tx[1:], strict=False))
        assert all(At4532Parser().parse(r).frame_type == "TCP-32" for r in received)
        assert adapter.fetch_diagnostics.fetch_timeouts == 2
        assert adapter.fetch_diagnostics.reconnect_count == 1 and opens == 2
        assert [p for _, p in wire.writes].count(b"*IDN?\n") == 1
        assert transport.synchronization_metrics["discarded_partial_bytes"] == 0
        assert wire.input_resets == 0 and adapter.fetch_diagnostics.unknown_responses == 0
        record_property(
            "celsius_soak",
            json.dumps(
                {
                    "simulated_seconds": clock.now - started,
                    "cycles": count,
                    "samples": len(received),
                    "trigger_interval_seconds": 5,
                    "frame_duration_seconds": [1.4, 2.0],
                    "isolated_timeouts": 2,
                    "necessary_reconnects": 1,
                    "unnecessary_reconnects": 0,
                    "malformed_frames": 0,
                    "discarded_partial_bytes": 0,
                    "duplicate_samples": 0,
                    "unknown_response_from_framing": 0,
                }
            ),
        )
    finally:
        await stream.aclose()
        await adapter.disconnect()
