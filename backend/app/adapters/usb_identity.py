"""Passive USB identity matching. Never probes or opens a serial port."""

import asyncio

from serial.tools import list_ports

from app.adapters.transports import SerialTransportError, serial_io


def identity(port):
    return {
        "vid": getattr(port, "vid", None),
        "pid": getattr(port, "pid", None),
        "serial_number": getattr(port, "serial_number", None),
    }


def complete(value):
    return value.get("vid") is not None and value.get("pid") is not None and bool(
        value.get("serial_number")
    )


class UsbIdentityResolver:
    def __init__(self, expected=None, provider=None):
        self.expected = dict(expected or {})
        self.provider = provider or list_ports.comports
        self.last_available = None
        self._lock = asyncio.Lock()

    async def resolve(self, port, *, recovering):
        async with self._lock:
            # Enumeration is passive, off the event loop, and drained on cancellation
            # so it cannot race another enumeration or leave an abandoned worker.
            ports = await serial_io(lambda: list(self.provider()))
            if not complete(self.expected) and not recovering:
                candidates = [p for p in ports if p.device.casefold() == port.casefold()]
                if len(candidates) == 1 and complete(identity(candidates[0])):
                    observed = identity(candidates[0])
                    if any(self.expected.get(k) is not None and self.expected[k] != observed[k]
                           for k in ("vid", "pid", "serial_number")):
                        raise SerialTransportError(
                            "usb_identity_mismatch", "Identidade USB divergente."
                        )
                    self.expected = observed
            if not complete(self.expected):
                self.last_available = False
                raise SerialTransportError("usb_identity_required",
                    "Reassocie o GPM pela descoberta USB: identidade física completa necessária.")
            matches = [p for p in ports if identity(p) == self.expected]
            self.last_available = len(matches) == 1
            if not matches:
                raise SerialTransportError("port_not_found",
                    "GPM ausente no Windows. Verifique cabo, alimentação e driver USB.")
            if len(matches) != 1:
                raise SerialTransportError("usb_identity_ambiguous",
                    "Identidade USB ambígua; necessária intervenção do operador.")
            return matches[0].device
