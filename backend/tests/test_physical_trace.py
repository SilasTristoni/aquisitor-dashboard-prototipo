import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from test_at4532_input_boundary import frame_for, setup_transport
from test_at4532_repeated_celsius import setup_tool

from app.adapters.specific import At4532SerialAdapter
from app.core import physical_trace
from app.services.acquisition import AcquisitionService, DeviceRuntime


@pytest.fixture
def journal(monkeypatch, tmp_path):
    monkeypatch.setenv("THERMOPOWER_LOG_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("THERMOPOWER_PHYSICAL_TRACE", "1")
    recorder = physical_trace.PhysicalJournal()
    monkeypatch.setattr(physical_trace, "journal", recorder)
    yield recorder
    assert recorder.flush()


def events(journal):
    assert journal.flush()
    return [
        json.loads(line)
        for path in physical_trace.trace_directory().glob("*.jsonl")
        if not path.name.startswith("snapshots-")
        for line in path.read_text().splitlines()
    ]


@pytest.mark.asyncio
async def test_real_runtime_events_recovery_dedupe_reconnect_and_publication(monkeypatch, journal):
    clock, wire, transport = setup_transport(monkeypatch)
    sequence = 0

    def respond(payload):
        nonlocal sequence
        if payload == b"SYST:UNIT CEL\n":
            sequence += 1
            wire.schedule(0.016, frame_for(sequence)[:6])
            wire.schedule(0.36, frame_for(sequence)[6:])

    wire.on_write = respond
    adapter = At4532SerialAdapter("COM_BOUNDARY", 19200, transport, allow_identity_fallback=True)
    adapter.diagnostic_context = lambda: {"device_id": 12, "session_id": 41}
    await adapter.connect()
    await adapter.read_once()
    # A repeated prior frame is rejected, then a genuinely new one is accepted.
    wire.schedule(0, frame_for(1))
    reading = await adapter.read_once()
    service = AcquisitionService()
    runtime = DeviceRuntime(adapter, "AT", "at4532_serial", "temperature", session_id=41)
    await service._publish_reading(12, runtime, reading)

    # Delayed fragmented response traverses real timeout/resync/recovered queue.
    def delayed(payload):
        if payload == b"SYST:UNIT CEL\n":
            wire.schedule(2.1, frame_for(3)[:7])
            wire.schedule(2.3, frame_for(3)[7:])

    wire.on_write = delayed
    recovered = await adapter.read_once()
    assert recovered.raw_payload["response_source"] == "recovered_frame"
    wire.schedule(0, b"TCP-32,invalid\r\n")
    wire.on_write = respond
    sequence = 3
    await adapter.read_once()

    def reopen(**_):
        wire.is_open = True
        return wire

    transport.serial_factory = reopen
    await adapter._recover_connection()
    await adapter.disconnect()
    rows = events(journal)
    assert physical_trace.EVENTS <= {row["event"] for row in rows}
    tx = [r for r in rows if r["event"] == "AT_TX"]
    assert len(tx) == len(wire.writes)
    assert [r["monotonic_timestamp"] for r in tx] == [t for t, _ in wire.writes]
    accepted = next(
        r
        for r in rows
        if r["event"] == "AT_FRAME_ACCEPTED"
        and r["frame_sha256"] == hashlib.sha256(frame_for(1)).hexdigest()
    )
    assert accepted["frame_length"] == 694 and accepted["terminator"] == "CRLF"
    assert accepted["last_byte_monotonic"] - accepted["first_byte_monotonic"] == pytest.approx(
        0.344
    )
    assert accepted["device_timestamp_original"] == "T:2026/09/28 17:03:53"
    assert accepted["temperatures_c"][:24] == [None] * 24
    assert accepted["device_id"] == 12 and accepted["session_id"] == 41
    recovered_row = next(
        r
        for r in rows
        if r["event"] == "AT_FRAME_ACCEPTED" and r["response_source"] == "recovered_frame"
    )
    assert recovered_row["tx_sent"] is False
    assert recovered_row["received_timestamp"] == recovered.received_timestamp.isoformat()
    assert journal.status()["dropped_events"] == journal.status()["write_errors"] == 0


@pytest.mark.asyncio
async def test_trace_sink_failure_does_not_change_command_sequence_or_reading(monkeypatch, journal):
    _, wire, transport = setup_transport(monkeypatch)
    wire.on_write = lambda p: wire.schedule(0.1, frame_for(1)) if p == b"SYST:UNIT CEL\n" else None
    monkeypatch.setattr(
        journal, "emit", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk failure"))
    )
    adapter = At4532SerialAdapter("COM_BOUNDARY", 19200, transport, allow_identity_fallback=True)
    await adapter.connect()
    assert (await adapter.read_once()).temperatures_c[-1] == 21.67
    await adapter.disconnect()
    assert [p for _, p in wire.writes] == [b"*IDN?\n", b"SYST:UNIT CEL\n"]
    assert journal.write_errors > 0


def test_repeated_celsius_uses_same_frame_code_and_records_distinct_frames(monkeypatch, journal):
    _, wire, _, tool = setup_tool(monkeypatch)
    wire.on_write = lambda _: wire.schedule(0.016, frame_for(len(wire.writes)))
    tool.run()
    rows = events(journal)
    tx = [r for r in rows if r["event"] == "AT_TX"]
    assert len(tx) == 3 and {r["command"] for r in tx} == {"SYST:UNIT CEL"}
    accepted = [r for r in rows if r["event"] == "AT_FRAME_ACCEPTED"]
    assert len({r["frame_sha256"] for r in accepted}) == 3
    assert all(r["command_to_first_byte_s"] == pytest.approx(0.016) for r in accepted)
    assert all(r["response_source"] == "controlled_observation" for r in accepted)


def test_full_export_includes_previous_capture_and_redacts_secrets(
    client, auth_headers, monkeypatch, journal
):
    from app.services import physical_diagnostic
    from app.services.acquisition import acquisition_service
    from app.services.protocol_probe import protocol_probe_service

    monkeypatch.setattr(physical_diagnostic, "journal", journal)
    monkeypatch.setattr(
        protocol_probe_service, "run", lambda *a: pytest.fail("Export must not probe")
    )
    journal.emit(
        "AT_STATE",
        current_state="connected",
        password="do-not-export",
        message="Bearer forbidden-value",
    )
    journal.snapshot(kind="disconnected_runtime", device_id=12, status={"sample_count": 123})
    capture = physical_trace.trace_directory() / "characterizations/celsius-test"
    capture.mkdir(parents=True)
    (capture / "summary.json").write_text(
        json.dumps({"experiment": "three_celsius", "token": "hidden"})
    )
    assert journal.flush()
    response = client.get("/api/v1/support/physical-package", headers=auth_headers)
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        required = {
            "serial-events.jsonl",
            "acquisition-state.json",
            "devices.json",
            "transactions.json",
            "input-boundary-metrics.json",
            "runtime-state.json",
            "build-info.json",
            "version.txt",
            "commit.txt",
            "session-summary.json",
            "last-errors.json",
            "counters-AT-GPM.json",
            "characterizations/celsius-test/summary.json",
            "evidence-status.json",
        }
        assert required <= set(archive.namelist())
        for name in archive.namelist():
            data = archive.read(name)
            assert b"do-not-export" not in data and b"forbidden-value" not in data
        assert b'"token": "[redacted]"' in archive.read(
            "characterizations/celsius-test/summary.json"
        )
        runtime = json.loads(archive.read("runtime-state.json"))
        assert runtime["saved_checkpoints"][0]["status"]["sample_count"] == 123
        for line in archive.read("SHA256SUMS.txt").decode().splitlines():
            expected, name = line.split("  ", 1)
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected
    assert not acquisition_service.runtimes


def test_queue_and_disk_failure_are_visible_without_raising(monkeypatch, tmp_path):
    from queue import Queue

    monkeypatch.setenv("THERMOPOWER_PHYSICAL_TRACE", "1")
    recorder = physical_trace.PhysicalJournal()
    recorder.worker = SimpleNamespace()  # Hold consumer to force a bounded queue overflow.
    recorder.queue = Queue(maxsize=1)
    recorder.emit("AT_STATE", current_state="connected")
    recorder.emit("AT_STATE", current_state="disconnected")
    assert recorder.dropped_events == 1
    directory = tmp_path / "not-a-directory"
    directory.write_text("occupied")
    monkeypatch.setenv("THERMOPOWER_LOG_DIRECTORY", str(directory))
    recorder = physical_trace.PhysicalJournal()
    recorder.emit("AT_OPEN")
    assert recorder.flush() and recorder.write_errors == 1
