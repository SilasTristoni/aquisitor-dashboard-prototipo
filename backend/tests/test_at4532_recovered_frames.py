from datetime import datetime

import pytest
from test_at4532_input_boundary import frame_for, setup_transport
from test_physical_engineering import _manual_at4532_device

from app.adapters.specific import At4532SerialAdapter
from app.services.protocol_probe import ProtocolProbeService

pytestmark = pytest.mark.physical_regression_fixtures


async def connected_adapter(monkeypatch, delay=1.031):
    clock, serial, transport = setup_transport(monkeypatch)
    count = 0

    def respond(payload):
        nonlocal count
        if payload == b"SYST:UNIT CEL\n":
            count += 1
            serial.schedule(delay, frame_for(count))

    serial.on_write = respond
    adapter = At4532SerialAdapter("COM_BOUNDARY", 19200, transport, allow_identity_fallback=True)
    await adapter.connect()
    await adapter.read_once()
    return clock, serial, transport, adapter


@pytest.mark.asyncio
async def test_1031_ms_response_has_full_physical_rx_guard(monkeypatch):
    clock, serial, transport, adapter = await connected_adapter(monkeypatch)
    first_rx = transport.last_physical_rx_monotonic
    try:
        await adapter.read_once()
        tx = [t for t, p in serial.writes if p == b"SYST:UNIT CEL\n"][-1]
        assert tx - first_rx >= 1.0
        assert adapter.transactions[-1]["transaction_boundary"]["post_rx_guard_s"] == 1.0
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_resync_during_guard_reanchors_tx(monkeypatch):
    clock, serial, transport, adapter = await connected_adapter(monkeypatch)
    # A duplicate arrives during the guard and must not become another sample.
    serial.schedule(0.5, frame_for(1)[:7])
    serial.schedule(1.2, frame_for(1)[7:])
    expected_rx = clock.now + 1.2
    try:
        reading = await adapter.read_once()
        tx = [t for t, p in serial.writes if p == b"SYST:UNIT CEL\n"][-1]
        assert tx >= expected_rx + 1.0
        assert reading.raw_payload["raw_hex"] == frame_for(2).hex(" ").upper()
        assert adapter.duplicate_frames == 1
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("split", [6, 7])
async def test_timeout_recovers_once_without_new_fetch_or_identity(monkeypatch, split):
    clock, serial, transport, adapter = await connected_adapter(monkeypatch)
    serial.on_write = (
        lambda payload: (
            serial.schedule(2.1, frame_for(2)[:split]),
            serial.schedule(2.3, frame_for(2)[split:]),
        )
        if payload == b"SYST:UNIT CEL\n"
        else None
    )
    try:
        reading = await adapter.read_once()
        assert reading.raw_payload["raw_hex"] == frame_for(2).hex(" ").upper()
        assert reading.temperatures_c[:24] == [None] * 24
        assert reading.raw_payload["response_source"] == "recovered_frame"
        assert adapter.transactions[-1]["tx_sent"] is False
        assert adapter.transactions[-1]["timestamp_tx"] is None
        assert reading.received_timestamp == datetime.fromisoformat(
            transport.last_query_boundary["timestamp_rx"]
        )
        assert len([p for _, p in serial.writes if p == b"SYST:UNIT CEL\n"]) == 2
        assert len([p for _, p in serial.writes if p == b"*IDN?\n"]) == 1
        assert adapter.fetch_diagnostics.reconnect_count == 0
        assert adapter.fetch_diagnostics.fetch_timeouts == 1
        assert not transport.recovered_frames
        serial.schedule(0, frame_for(2))
        serial.on_write = lambda _: serial.schedule(0.1, frame_for(3))
        next_reading = await adapter.read_once()
        assert next_reading.device_timestamp > reading.device_timestamp
        assert adapter.duplicate_frames == 1
        assert transport.synchronization_metrics["discarded_partial_bytes"] == 0
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_freshness_uses_monotonic_age_despite_device_clock_offset(monkeypatch):
    clock, serial, transport, adapter = await connected_adapter(monkeypatch)
    try:
        # The fixture clock is unrelated to the PC wall clock; freshly received is accepted.
        serial.schedule(0, frame_for(2))
        await transport.synchronize_input_boundary()
        physical_rx_at = transport.recovered_frames[0]["timestamp_rx"]
        clock.now += 2
        reading = await adapter.read_once()
        assert reading.received_timestamp.isoformat() == physical_rx_at
        assert reading.raw_payload["response_source"] == "recovered_frame"
        serial.schedule(0, frame_for(3))
        await transport.synchronize_input_boundary()
        clock.now += transport.recovered_frame_max_age_s + 0.1
        serial.on_write = lambda _: serial.schedule(0.1, frame_for(4))
        reading = await adapter.read_once()
        assert reading.raw_payload["raw_hex"] == frame_for(4).hex(" ").upper()
        assert transport.synchronization_metrics["expired_recovered_frames"] == 1
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["read", "full", "identity"])
async def test_probe_logical_recovery_and_identity_semantics(monkeypatch, mode):
    clock, serial, transport = setup_transport(monkeypatch)
    count = 0

    def respond(payload):
        nonlocal count
        if payload == b"SYST:UNIT CEL\n":
            count += 1
            serial.schedule(2.1, frame_for(count)[:6])
            serial.schedule(2.3, frame_for(count)[6:])

    serial.on_write = respond
    monkeypatch.setattr(
        "app.services.protocol_probe.At4532SerialAdapter",
        lambda port, baud_rate, **kw: At4532SerialAdapter(
            port, baud_rate, transport=transport, **kw
        ),
    )
    report = await ProtocolProbeService().run(_manual_at4532_device(), mode)
    assert report["transport_closed"]
    assert len([p for _, p in serial.writes if p == b"*IDN?\n"]) == 1
    if mode == "identity":
        assert report["result"] == "failed"
        assert count == 0
    else:
        assert report["result"] == "passed_with_warning"
        assert len(report["readings"]) == (2 if mode == "full" else 1)
        stamps = [r["device_timestamp"] for r in report["readings"]]
        assert len(set(stamps)) == len(stamps)


@pytest.mark.asyncio
async def test_recovered_queue_is_bounded_and_overflow_is_counted(monkeypatch):
    _, serial, transport = setup_transport(monkeypatch)
    await transport.open()
    try:
        serial.schedule(0, b"".join(frame_for(i) for i in range(10)))
        await transport.synchronize_input_boundary()
        assert len(transport.recovered_frames) == 8
        assert transport.synchronization_metrics["recovered_queue_overflows"] == 2
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_initial_port_backlog_is_not_a_fresh_measurement(monkeypatch):
    _, serial, transport = setup_transport(monkeypatch)
    serial.schedule(0, frame_for(1)[:6])
    serial.schedule(0.1, frame_for(1)[6:])
    serial.on_write = (
        lambda payload: serial.schedule(0.1, frame_for(2))
        if payload == b"SYST:UNIT CEL\n" else None
    )
    adapter = At4532SerialAdapter("COM_BOUNDARY", 19200, transport, allow_identity_fallback=True)
    try:
        await adapter.connect()
        reading = await adapter.read_once()
        assert reading.raw_payload["raw_hex"] == frame_for(2).hex(" ").upper()
        assert transport.synchronization_metrics["untrusted_recovered_frames"] == 1
        assert transport.synchronization_metrics["discarded_partial_bytes"] == 0
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_dedup_survives_reopen_and_same_timestamp_new_content_is_distinct(monkeypatch):
    _, serial, transport, adapter = await connected_adapter(monkeypatch)

    # Only the serial factory reopens the mock; the adapter retains its deduplication history.
    def reopen(**_):
        serial.is_open = True
        return serial

    transport.serial_factory = reopen
    changed = frame_for(1).replace(b"21.39|", b"22.39|")
    assert changed != frame_for(1)
    fetches = 0

    def respond(payload):
        nonlocal fetches
        if payload == b"SYST:UNIT CEL\n":
            fetches += 1
            serial.schedule(0.1, frame_for(1) if fetches == 1 else changed)

    serial.on_write = respond
    try:
        await adapter._recover_connection()
        reading = await adapter.read_once()
        assert reading.raw_payload["raw_hex"] == changed.hex(" ").upper()
        assert adapter.duplicate_frames == 1
        assert len([p for _, p in serial.writes if p == b"*IDN?\n"]) == 1
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_invalid_recovered_tcp32_does_not_bypass_parser(monkeypatch):
    _, serial, transport, adapter = await connected_adapter(monkeypatch)
    serial.schedule(0, b"TCP-32,invalid\r\n")
    try:
        reading = await adapter.read_once()
        assert reading.raw_payload["raw_hex"] == frame_for(2).hex(" ").upper()
        assert transport.synchronization_metrics["rejected_recovered_frames"] == 1
    finally:
        await adapter.disconnect()


def test_guard_parameter_can_be_increased_but_not_disabled():
    adapter = At4532SerialAdapter("COM5", 19200, post_rx_guard_seconds=1.5)
    assert adapter.continuous_read_guard_seconds == 1.5
    with pytest.raises(ValueError):
        At4532SerialAdapter("COM5", 19200, post_rx_guard_seconds=0.4)
