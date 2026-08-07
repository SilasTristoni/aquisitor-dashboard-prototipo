from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from typing import Any

import serial


class SerialTransport(ABC):
    """Byte transport boundary; it carries no instrument-specific commands."""

    @property
    @abstractmethod
    def is_open(self) -> bool: ...

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def write(self, payload: bytes) -> int: ...

    @abstractmethod
    def read(self, size: int = 1) -> bytes: ...

    @abstractmethod
    def readline(self) -> bytes: ...


class RealSerialTransport(SerialTransport):
    def __init__(self, port: str, baud_rate: int = 115200, timeout: float = 1) -> None:
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.connection: serial.Serial | None = None

    @property
    def is_open(self) -> bool:
        return bool(self.connection and self.connection.is_open)

    def open(self) -> None:
        if not self.connection:
            self.connection = serial.Serial(
                port=self.port, baudrate=self.baud_rate, timeout=self.timeout
            )

    def close(self) -> None:
        if self.connection and self.connection.is_open:
            self.connection.close()
        self.connection = None

    def write(self, payload: bytes) -> int:
        if not self.connection:
            raise serial.PortNotOpenError()
        return self.connection.write(payload)

    def read(self, size: int = 1) -> bytes:
        if not self.connection:
            raise serial.PortNotOpenError()
        return self.connection.read(size)

    def readline(self) -> bytes:
        if not self.connection:
            raise serial.PortNotOpenError()
        return self.connection.readline()


class PySerialLoopTransport(SerialTransport):
    """Software loopback. It is never exposed by USB discovery."""

    warning = "Canal serial em loopback — teste de software, não representa equipamento físico"

    def __init__(self, timeout: float = 0.1) -> None:
        self.timeout = timeout
        self.connection: Any | None = None

    @property
    def is_open(self) -> bool:
        return bool(self.connection and self.connection.is_open)

    def open(self) -> None:
        if not self.connection:
            self.connection = serial.serial_for_url("loop://", timeout=self.timeout)

    def close(self) -> None:
        if self.connection and self.connection.is_open:
            self.connection.close()
        self.connection = None

    def write(self, payload: bytes) -> int:
        if not self.connection:
            raise serial.PortNotOpenError()
        return self.connection.write(payload)

    def read(self, size: int = 1) -> bytes:
        if not self.connection:
            raise serial.PortNotOpenError()
        return self.connection.read(size)

    def readline(self) -> bytes:
        if not self.connection:
            raise serial.PortNotOpenError()
        return self.connection.readline()


class FakeSerialTransport(SerialTransport):
    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self._open = False
        self._chunks = deque(chunks or [])
        self.written: list[bytes] = []
        self.fail_reads = False

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def write(self, payload: bytes) -> int:
        if not self._open:
            raise serial.PortNotOpenError()
        self.written.append(payload)
        return len(payload)

    def read(self, size: int = 1) -> bytes:
        if self.fail_reads:
            raise serial.SerialException("Simulated disconnection")
        if not self._open or not self._chunks:
            return b""
        chunk = self._chunks.popleft()
        if len(chunk) > size:
            self._chunks.appendleft(chunk[size:])
            return chunk[:size]
        return chunk

    def readline(self) -> bytes:
        if self.fail_reads:
            raise serial.SerialException("Simulated disconnection")
        if not self._open or not self._chunks:
            return b""
        data = bytearray()
        while self._chunks:
            chunk = self._chunks.popleft()
            data.extend(chunk)
            if b"\n" in chunk:
                break
        return bytes(data)

    def feed(self, *chunks: bytes) -> None:
        self._chunks.extend(chunks)
