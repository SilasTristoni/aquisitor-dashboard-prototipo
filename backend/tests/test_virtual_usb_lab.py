import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from app.adapters.serial import SerialJsonAdapter
from app.adapters.transports import FakeSerialTransport, PySerialLoopTransport
from app.core.database import SessionLocal
from app.services.usb_diagnostic import UsbDiagnosticService, sanitize
from app.services.usb_discovery import TestPortDiscoveryProvider, UsbDeviceDiscoveryService
from app.services.virtual_usb_lab import VirtualInstrumentAdapter, virtual_usb_lab_service


@pytest.fixture(autouse=True)
def reset_lab():
    virtual_usb_lab_service.reset()
    yield
    virtual_usb_lab_service.reset()


def test_virtual_lab_plug_change_port_busy_driver_and_unplug():
    item = virtual_usb_lab_service.plug("at4532", "COM90")
    assert item["simulated"] is True
    assert item["serial_number"] == "VLAB-AT4532-001"
    assert virtual_usb_lab_service.set_busy("COM90", True)["busy"] is True
    assert virtual_usb_lab_service.set_driver_missing("COM90", True)["driver_missing"] is True
    changed = virtual_usb_lab_service.change_port("COM90", "COM91")
    assert changed["port"] == "COM91"
    assert changed["serial_number"] == item["serial_number"]
    virtual_usb_lab_service.unplug("COM91")
    assert virtual_usb_lab_service.list_ports() == []


@pytest.mark.asyncio
async def test_virtual_at4532_and_gpm8213_generate_distinct_readings():
    virtual_usb_lab_service.plug("at4532", "COM90", options={"interval_seconds": 0.05})
    virtual_usb_lab_service.plug("gpm8213", "COM91", options={"interval_seconds": 0.05})
    temperature = VirtualInstrumentAdapter("COM90", "at4532")
    electrical = VirtualInstrumentAdapter("COM91", "gpm8213")
    await temperature.connect()
    await electrical.connect()
    at_reading = await anext(temperature.start_reading())
    gpm_reading = await anext(electrical.start_reading())
    await temperature.disconnect()
    await electrical.disconnect()
    assert len(at_reading.temperatures_c) == 32
    assert at_reading.ambient_temperature_c is not None
    assert gpm_reading.voltage_v is not None
    assert gpm_reading.current_a is not None
    assert gpm_reading.raw_power_unit in {"mW", "W", "kW"}
    assert at_reading.raw_payload["simulated"] is True
    assert gpm_reading.raw_payload["simulated"] is True


@pytest.mark.asyncio
async def test_fake_transport_handles_partial_and_concatenated_messages():
    first = json.dumps({"power": 1, "powerUnit": "W", "temperatures": [20]}).encode()
    second = json.dumps({"power": 2, "powerUnit": "W", "temperatures": [21]}).encode()
    transport = FakeSerialTransport([first[:10], first[10:] + b"\n" + second + b"\n"])
    adapter = SerialJsonAdapter("fake://", transport=transport)
    await adapter.connect()
    iterator = adapter.start_reading()
    readings = [await anext(iterator), await anext(iterator)]
    await adapter.stop_reading()
    await adapter.disconnect()
    assert [item.power_w for item in readings] == [1, 2]


def test_pyserial_loop_transport_open_write_read_timeout_and_close():
    transport = PySerialLoopTransport(timeout=0.02)
    transport.open()
    assert transport.is_open
    assert transport.write(b"software-only\n") == 14
    assert transport.readline() == b"software-only\n"
    assert transport.read(1) == b""
    transport.close()
    assert not transport.is_open
    assert "não representa equipamento físico" in transport.warning


def test_discovery_provider_marks_virtual_and_never_opens_serial(client):
    opened = []
    port = SimpleNamespace(
        device="COM90",
        profile="at4532",
        description="Virtual AT4532",
        manufacturer="Virtual",
        product="AT4532",
        serial_number=None,
        vid=None,
        pid=None,
        hwid="VIRTUAL",
        location=None,
        busy=False,
        driver_missing=False,
    )
    service = UsbDeviceDiscoveryService(
        TestPortDiscoveryProvider([port]), serial_factory=lambda **_: opened.append(True)
    )
    with SessionLocal() as db:
        row = service.discover(db)[0]
    assert row["source"] == "virtual"
    assert row["simulated"] is True
    assert row["validation_states"]["homologated"] is False
    assert opened == []


def test_snapshot_diff_export_and_secret_masking(client):
    ports = TestPortDiscoveryProvider([])
    service = UsbDiagnosticService(
        UsbDeviceDiscoveryService(ports, serial_factory=lambda **_: None)
    )
    with SessionLocal() as db:
        first = service.capture(db, "Sem equipamentos")
        ports.ports = [
            SimpleNamespace(
                device="COM9",
                description="AT4532",
                manufacturer="Applent",
                product="AT4532",
                serial_number="PHYSICAL-001",
                vid=0x1234,
                pid=0x5678,
                hwid="USB\\VID_1234&PID_5678",
                location="1-2",
            )
        ]

        class PassiveSerial:
            is_open = True

            def close(self):
                self.is_open = False

        service.discovery.serial_factory = lambda **_: PassiveSerial()
        second = service.capture(db, "Com AT4532")
    assert first["snapshot"]["serial_ports"] == []
    assert second["diff"]["added_ports"][0]["port"] == "COM9"
    filename, content = service.export("jwt=abc password=unsafe C:\\Users\\private\\file")
    assert filename.endswith(".zip")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = set(archive.namelist())
        assert {
            "diagnostic-summary.html",
            "diagnostic-summary.pdf",
            "system.json",
            "snapshots.json",
            "snapshot-diff.json",
            "serial-ports.json",
            "pnp-devices.json",
            "application-version.txt",
            "recent-log.txt",
            "README.txt",
            "sha256.txt",
        } <= names
        joined = b"\n".join(archive.read(name) for name in names).lower()
    assert b"unsafe" not in joined
    assert b"jwt=abc" not in joined
    assert sanitize({"password": "x", "safe": "ok"}) == {
        "password": "[REMOVIDO]",
        "safe": "ok",
    }


def test_lab_endpoints_are_role_protected_and_operational(client, auth_headers):
    state = client.get("/api/v1/lab/usb/state", headers=auth_headers)
    assert state.status_code == 200
    plugged = client.post(
        "/api/v1/lab/usb/plug",
        headers=auth_headers,
        json={"profile": "at4532", "port": "COM90"},
    )
    assert plugged.status_code == 200
    assert plugged.json()["simulated"] is True
    unplugged = client.post(
        "/api/v1/lab/usb/unplug", headers=auth_headers, json={"port": "COM90"}
    )
    assert unplugged.status_code == 200
