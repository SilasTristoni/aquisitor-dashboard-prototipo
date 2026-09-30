"""Bench-derived bytes through the real transport, with deterministic USB arrival times."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import serial as pyserial
from test_physical_engineering import _manual_at4532_device

from app.adapters.specific import At4532Parser, At4532SerialAdapter, ProtocolResponseError
from app.adapters.transports import (
    At4532SerialTransport,
    Gpm8213SerialTransport,
    SerialTransportConfiguration,
    SerialTransportError,
)
from app.services.protocol_probe import ProtocolProbeService

pytestmark = pytest.mark.physical_regression_fixtures
PHYSICAL_FRAME = bytes.fromhex(
    (Path(__file__).parent / "fixtures/at4532_tcp32_20260928.hex").read_text()
)


class Clock:
    now = 100.0

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


class ScheduledSerial:
    """read(n) blocks up to timeout; scheduled chunks arrive independently of TX."""

    def __init__(self, clock):
        self.clock = clock
        self.timeout = 2.0
        self.is_open = True
        self.buffer = bytearray()
        self.events = []
        self.writes = []
        self.read_bytes = bytearray()
        self.input_resets = 0
        self.on_write = lambda payload: None

    def schedule(self, delay, data):
        self.events.append((self.clock.now + delay, data))
        self.events.sort(key=lambda item: item[0])

    @property
    def in_waiting(self):
        while self.events and self.events[0][0] <= self.clock.now:
            self.buffer.extend(self.events.pop(0)[1])
        return len(self.buffer)

    def read(self, size):
        if not self.in_waiting:
            deadline = self.clock.now + self.timeout
            self.clock.now = min(deadline, self.events[0][0]) if self.events else deadline
        count = min(size, self.in_waiting)
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        self.read_bytes.extend(data)
        return data

    def write(self, payload):
        self.writes.append((self.clock.now, payload))
        self.on_write(payload)
        return len(payload)

    def flush(self):
        pass

    def reset_input_buffer(self):
        self.input_resets += 1
        self.buffer.clear()

    def reset_output_buffer(self):
        pass

    def close(self):
        self.is_open = False


def frame_for(sequence):
    timestamp = datetime(2026, 9, 28, 17, 3, 52, tzinfo=UTC) + timedelta(seconds=sequence)
    return PHYSICAL_FRAME.replace(
        b"2026/09/28 17:03:52", timestamp.strftime("%Y/%m/%d %H:%M:%S").encode()
    )


def setup_transport(monkeypatch, transport_type=At4532SerialTransport):
    clock = Clock()
    connection = ScheduledSerial(clock)
    monkeypatch.setattr("app.adapters.transports.monotonic", clock.monotonic)
    monkeypatch.setattr("app.adapters.specific.monotonic", clock.monotonic)
    monkeypatch.setattr("app.adapters.specific.asyncio", SimpleNamespace(sleep=clock.sleep))
    monkeypatch.setattr(
        "app.adapters.transports.asyncio",
        SimpleNamespace(**{**vars(asyncio), "sleep": clock.sleep}),
    )
    config = SerialTransportConfiguration("COM_BOUNDARY", 19200, 8, "N", 1, 1, 2)
    transport = transport_type(config, serial_factory=lambda **_: connection)
    return clock, connection, transport


def test_bench_fixture_and_strict_parser():
    assert PHYSICAL_FRAME.startswith(b"TCP-32,")
    assert len(PHYSICAL_FRAME) == 694
    assert hashlib.sha256(PHYSICAL_FRAME).hexdigest() == (
        "43a25e7339ed9ee447e7c6a880b526956cf3afe49c22d545489f00013cd8dff5"
    )
    parsed = At4532Parser().parse(PHYSICAL_FRAME)
    assert len(parsed.channels) == 32
    assert sum(c.quality == "open_sensor" for c in parsed.channels) == 24
    assert parsed.values[24:] == (21.39, 21.20, 20.66, 21.87, 20.82, 21.25, 21.53, 21.67)
    with pytest.raises(ProtocolResponseError):
        At4532Parser().parse(PHYSICAL_FRAME[6:])


@pytest.mark.asyncio
@pytest.mark.parametrize("split", [1, 2, 6, 7, 50, 347, "multiple"])
async def test_pending_frame_is_completed_before_next_tx(monkeypatch, split):
    clock, serial, transport = setup_transport(monkeypatch)
    await transport.open()
    sizes = [1, 2, 3, 44, 297, 347] if split == "multiple" else [split, 694 - split]
    offset = 0
    for index, size in enumerate(sizes):
        serial.schedule(index * 0.1, PHYSICAL_FRAME[offset : offset + size])
        offset += size
    serial.on_write = lambda _: serial.schedule(0.1, frame_for(1))
    try:
        response, _ = await transport.query(b"FETCH?\n", b"\n")
        assert response == frame_for(1)
        event = transport.input_boundary_diagnostics()["recent_resynchronizations"][-1]
        complete = bytes.fromhex(event["frames"][0]["raw_hex"])
        assert complete == PHYSICAL_FRAME
        assert complete.startswith(b"TCP-32,")
        assert len(complete) == 694
        assert len(event["frames"]) == 1
        assert event["bytes_present_before_resync"] == sizes[0]
        assert event["bytes_completed"] == event["full_frame_length"] == 694
        assert event["terminator_found"] and event["boundary_clean"]
        assert serial.writes[0][0] >= 100 + (len(sizes) - 1) * 0.1
        assert bytes(serial.read_bytes) == PHYSICAL_FRAME + frame_for(1)
        assert transport.synchronization_metrics["discarded_partial_bytes"] == 0
        assert transport.synchronization_metrics["discarded_complete_frames"] == 0
        assert len(transport.recovered_frames) == 1
        assert serial.input_resets == 0
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_incomplete_frame_blocks_tx_and_survives_next_resync(monkeypatch):
    clock, serial, transport = setup_transport(monkeypatch)
    await transport.open()
    serial.schedule(0, PHYSICAL_FRAME[:6])
    try:
        with pytest.raises(SerialTransportError) as error:
            await transport.query(b"FETCH?\n", b"\n")
        assert error.value.code == "incomplete_late_frame"
        assert clock.now == pytest.approx(102)
        assert serial.writes == []
        assert transport.last_query_boundary["tx_sent"] is False
        assert transport.input_boundary_diagnostics()["pending_partial_bytes"] == 6
        assert transport.synchronization_metrics["discarded_partial_bytes"] == 0
        serial.schedule(0.1, PHYSICAL_FRAME[6:])
        serial.on_write = lambda _: serial.schedule(0, frame_for(2))
        response, _ = await transport.query(b"FETCH?\n", b"\n")
        assert response == frame_for(2)
        metrics = transport.synchronization_metrics
        assert metrics["late_frames"] == metrics["completed_late_frames"] == 1
        assert metrics["incomplete_late_frames"] == metrics["resynchronization_failures"] == 1
        assert bytes(serial.read_bytes) == PHYSICAL_FRAME + frame_for(2)
    finally:
        await transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("partial,delay", [(False, 0.1), (False, 0.6), (True, 0.1)])
async def test_timeout_late_response_never_becomes_next_fetch(monkeypatch, partial, delay):
    clock, serial, transport = setup_transport(monkeypatch)
    await transport.open()
    count = 0

    def respond(_):
        nonlocal count
        count += 1
        if count == 2:
            serial.schedule(0 if partial else 2 + delay, frame_for(2)[:6])
            serial.schedule(2 + delay + 0.1, frame_for(2)[6:])
        else:
            serial.schedule(0.1, frame_for(count))

    serial.on_write = respond
    try:
        assert (await transport.query(b"FETCH?\n", b"\n"))[0] == frame_for(1)
        with pytest.raises(SerialTransportError) as error:
            await transport.query(b"FETCH?\n", b"\n")
        assert error.value.code == ("incomplete_frame" if partial else "protocol_timeout")
        if delay == 0.1:
            clock.now += 0.15  # Prefix is already queued before the next query.
        assert (await transport.query(b"FETCH?\n", b"\n"))[0] == frame_for(3)
        assert bytes(serial.read_bytes) == frame_for(1) + frame_for(2) + frame_for(3)
        metrics = transport.synchronization_metrics
        assert metrics["completed_late_frames"] == 1
        assert metrics["discarded_complete_frames"] == 0
        assert metrics["discarded_partial_bytes"] == metrics["resynchronization_failures"] == 0
        assert serial.writes[2][0] >= serial.writes[1][0] + 2 + delay + 0.1
        assert serial.is_open and serial.input_resets == 0
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_multiple_late_frames_and_partial_tail_are_not_merged(monkeypatch):
    _, serial, transport = setup_transport(monkeypatch)
    await transport.open()
    serial.schedule(0, PHYSICAL_FRAME + frame_for(1)[:6])
    serial.schedule(0.2, frame_for(1)[6:])
    try:
        assert await transport.synchronize_input_boundary() == [PHYSICAL_FRAME, frame_for(1)]
        assert transport.synchronization_metrics["discarded_complete_frames"] == 0
        assert len(transport.recovered_frames) == 2
        assert serial.writes == []
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_close_after_timeout_finishes_late_frame_without_input_reset(monkeypatch):
    _, serial, transport = setup_transport(monkeypatch)
    await transport.open()
    serial.on_write = lambda _: (
        serial.schedule(2.1, PHYSICAL_FRAME[:6]),
        serial.schedule(2.3, PHYSICAL_FRAME[6:]),
    )
    with pytest.raises(SerialTransportError):
        await transport.query(b"FETCH?\n", b"\n")
    await transport.close()
    assert bytes(serial.read_bytes) == PHYSICAL_FRAME
    assert transport.synchronization_metrics["completed_late_frames"] == 1
    assert transport.synchronization_metrics["discarded_partial_bytes"] == 0
    assert not serial.is_open and serial.input_resets == 0


@pytest.mark.asyncio
async def test_unfinishable_fragment_is_audited_on_explicit_close(monkeypatch):
    _, serial, transport = setup_transport(monkeypatch)
    await transport.open()
    serial.schedule(0, PHYSICAL_FRAME[:6])
    await transport.close()
    metrics = transport.input_boundary_diagnostics()
    assert metrics["discarded_partial_bytes"] == 6
    assert metrics["resynchronization_failures"] == 1
    assert metrics["recent_resynchronizations"][-1]["retained_partial_hex"] == "54 43 50 2D 33 32"
    assert serial.writes == [] and serial.input_resets == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [True, False])
async def test_cancelled_resync_finishes_worker_before_close_without_tx(monkeypatch, complete):
    from threading import Event

    _, serial, transport = setup_transport(monkeypatch)
    await transport.open()
    serial.schedule(0, PHYSICAL_FRAME[:6])
    if complete:
        serial.schedule(0.1, PHYSICAL_FRAME[6:])
    entered, finish = Event(), Event()
    original_read = serial.read

    def read(size):
        entered.set()
        assert finish.wait(5)
        assert serial.is_open
        return original_read(size)

    serial.read = read
    task = asyncio.create_task(transport.query(b"FETCH?\n", b"\n"))
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    closing = asyncio.create_task(transport.close())
    await asyncio.sleep(0)
    assert not closing.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await closing
    assert bytes(serial.read_bytes) == (PHYSICAL_FRAME if complete else PHYSICAL_FRAME[:6])
    assert serial.writes == []
    assert transport.synchronization_metrics["discarded_partial_bytes"] == (0 if complete else 6)


@pytest.mark.asyncio
async def test_open_preserves_pending_frame_instead_of_resetting_input(monkeypatch):
    _, serial, transport = setup_transport(monkeypatch)
    serial.schedule(0, PHYSICAL_FRAME[:6])
    serial.schedule(0.1, PHYSICAL_FRAME[6:])
    await transport.open()
    try:
        assert transport.open_boundary["pending_input_bytes"] == 6
        assert transport.open_boundary["input_buffer_reset"] is False
        assert await transport.synchronize_input_boundary() == [PHYSICAL_FRAME]
        assert serial.input_resets == 0
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_isolated_timeout_after_long_gap_does_not_reopen_port(monkeypatch):
    clock, serial, transport = setup_transport(monkeypatch)
    count = 0

    def respond(payload):
        nonlocal count
        if payload == b"FETCH?\n":
            count += 1
            if count != 2:
                serial.schedule(0.1, frame_for(count))

    serial.on_write = respond
    adapter = At4532SerialAdapter("COM_BOUNDARY", 19200, transport, allow_identity_fallback=True)
    await adapter.connect()
    stream = adapter.start_reading()
    try:
        await anext(stream)
        clock.now += 60
        reading = await anext(stream)
        assert bytes.fromhex(reading.raw_payload["raw_hex"]) == frame_for(3)
        assert adapter.fetch_diagnostics.reconnect_count == 0
        assert adapter.fetch_diagnostics.fetch_timeouts == 1
        assert len([p for _, p in serial.writes if p == b"*IDN?\n"]) == 1
    finally:
        await stream.aclose()
        await adapter.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["read", "full"])
async def test_probe_uses_same_real_transport_boundary(monkeypatch, mode):
    clock, serial, transport = setup_transport(monkeypatch)
    fetches = 0

    def respond(payload):
        nonlocal fetches
        if payload == b"SYST:UNIT CEL\n":
            serial.schedule(0, PHYSICAL_FRAME[:6])
            serial.schedule(0.2, PHYSICAL_FRAME[6:])
        elif payload == b"FETCH?\n":
            fetches += 1
            serial.schedule(0.1, frame_for(fetches))

    serial.on_write = respond
    monkeypatch.setattr(
        "app.services.protocol_probe.At4532SerialAdapter",
        lambda port, baud_rate, **kw: At4532SerialAdapter(
            port, baud_rate, transport=transport, **kw
        ),
    )
    monkeypatch.setattr("app.services.protocol_probe.asyncio", SimpleNamespace(sleep=clock.sleep))
    report = await ProtocolProbeService().run(_manual_at4532_device(), mode)
    assert report["result"] == "passed_with_warning"
    assert report["transport_closed"]
    assert len(report["readings"]) == (2 if mode == "full" else 1)
    metrics = report["input_boundary_diagnostics"]
    assert metrics["completed_late_frames"] == 1
    assert metrics["discarded_partial_bytes"] == 0
    assert report["readings"][0]["raw_payload"]["raw_hex"] == PHYSICAL_FRAME.hex(" ").upper()
    assert fetches == (1 if mode == "full" else 0)
    assert serial.input_resets == 0


@pytest.mark.asyncio
async def test_gpm_crlf_keeps_existing_drain_and_timeout_policy(monkeypatch):
    clock, serial, transport = setup_transport(monkeypatch, Gpm8213SerialTransport)
    await transport.open()
    serial.schedule(0, b"OLD\r\n")
    serial.on_write = lambda _: (serial.schedule(0.1, b"8\r"), serial.schedule(0.2, b"\n"))
    try:
        assert (await transport.query(b"NUMBER?\r\n", b"\r\n"))[0] == b"8\r\n"
        assert transport.last_query_boundary["buffer_drained_bytes"] == 5
        serial.on_write = lambda _: None
        with pytest.raises(SerialTransportError, match="respondeu"):
            await transport.query(b"NUMBER?\r\n", b"\r\n")
        before = clock.now
        serial.on_write = lambda _: serial.schedule(0, b"8\r\n")
        assert (await transport.query(b"NUMBER?\r\n", b"\r\n"))[0] == b"8\r\n"
        assert serial.writes[-1][0] == before
        assert serial.input_resets == 1
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_real_transport_mixed_1000_cycle_soak(monkeypatch, caplog, record_property):
    caplog.set_level("WARNING")
    clock, serial, transport = setup_transport(monkeypatch)
    fetches = 0
    late_sequences = set()
    lost_sequences = set()
    silent_sequences = set()
    duplicate_sequences = set()
    expected_wire = []
    opens = 0

    def open_serial(**_):
        nonlocal opens
        opens += 1
        serial.is_open = True
        return serial

    transport.serial_factory = open_serial

    def respond(payload):
        nonlocal fetches
        if payload != b"FETCH?\n":
            return  # Known IDN timeout, no response to configuration.
        fetches += 1
        frame = frame_for(fetches)
        if fetches == 505:
            lost_sequences.add(fetches)
            serial.is_open = False
            raise pyserial.SerialException("USB disconnected")
        if fetches % 137 == 0:
            silent_sequences.add(fetches)
            return
        expected_wire.append(frame)
        if fetches % 100 == 0:
            late_sequences.add(fetches)
            serial.schedule(2.1, frame[:6])
            serial.schedule(2.3, frame[6:])
        else:
            duration = 0.7 + (fetches % 6) * 0.1
            serial.schedule(0.01, frame[:1])
            serial.schedule(0.05, frame[1:50])
            serial.schedule(duration / 2, frame[50:347])
            serial.schedule(duration, frame[347:])
            if fetches % 73 == 0:
                duplicate_sequences.add(fetches)
                expected_wire.append(frame)
                serial.schedule(duration + 0.1, frame[:7])
                serial.schedule(duration + 0.3, frame[7:])

    serial.on_write = respond
    adapter = At4532SerialAdapter("COM_BOUNDARY", 19200, transport, allow_identity_fallback=True)
    await adapter.connect()
    stream = adapter.start_reading()
    try:
        readings = [await anext(stream) for _ in range(1000)]
        received = [bytes.fromhex(r.raw_payload["raw_hex"]) for r in readings]
        expected = [
            frame_for(i) for i in range(1, fetches + 1)
            if i not in lost_sequences | silent_sequences
        ]
        assert received == expected
        assert len({hashlib.sha256(r).digest() for r in received}) == 1000
        assert all(r.startswith(b"TCP-32,") and len(r) == 694 for r in received)
        assert bytes(serial.read_bytes) == b"".join(expected_wire)
        metrics = adapter.fetch_diagnostics.snapshot(clock.now)
        assert metrics["unknown_responses"] == 0
        assert metrics["reconnect_count"] == 1
        assert opens == 2
        assert metrics["discarded_partial_bytes"] == metrics["resynchronization_failures"] == 0
        assert metrics["completed_late_frames"] == len(late_sequences | duplicate_sequences)
        assert metrics["fetch_timeouts"] == len(late_sequences | silent_sequences)
        assert metrics["recovered_frames_consumed"] == len(late_sequences)
        assert adapter.duplicate_frames == len(duplicate_sequences)
        assert metrics["successful_fetches"] == 1000
        assert len(transport.input_boundary_diagnostics()["recent_resynchronizations"]) <= 32
        record_property(
            "stability_metrics",
            json.dumps(
                {
                    **metrics,
                    "malformed_frames": 0,
                    "unnecessary_reconnects": 0,
                    "necessary_reconnects": 1,
                    "unique_published_frames": len(received),
                    "duplicate_samples": len(received) - len(set(received)),
                    "unknown_response_from_framing": metrics["unknown_responses"],
                    "duplicate_frames_rejected": adapter.duplicate_frames,
                    "silent_timeouts": len(silent_sequences),
                    "response_latency_ms": [700, 800, 900, 1000, 1100, 1200],
                }
            ),
        )
    finally:
        await stream.aclose()
        await adapter.disconnect()
