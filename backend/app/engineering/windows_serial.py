"""Engineering-only pyserial Windows open without the implicit PurgeComm.

Based on pyserial 3.5 serialwin32.Serial.open (BSD-3-Clause, Chris Liechti).
Keep its exclusive handle, overlapped I/O and timeout setup; omit only buffer purge.
All subsequent I/O/framing uses the installed production pyserial/AT implementation.
"""

import ctypes

from serial import SerialException, win32
from serial.serialwin32 import Serial


class NoResetSerial(Serial):
    def open(self):
        if self._port is None or self.is_open:
            raise SerialException("Port must be configured and closed before opening")
        port = self.name
        if port.upper().startswith("COM") and port[3:].isdigit() and int(port[3:]) > 8:
            port = "\\\\.\\" + port
        self._port_handle = win32.CreateFile(
            port,
            win32.GENERIC_READ | win32.GENERIC_WRITE,
            0,
            None,
            win32.OPEN_EXISTING,
            win32.FILE_ATTRIBUTE_NORMAL | win32.FILE_FLAG_OVERLAPPED,
            0,
        )
        if self._port_handle == win32.INVALID_HANDLE_VALUE:
            self._port_handle = None
            raise SerialException(f"Could not open {self.portstr}: {ctypes.WinError()}")
        try:
            self._overlapped_read = win32.OVERLAPPED()
            self._overlapped_read.hEvent = win32.CreateEvent(None, 1, 0, None)
            self._overlapped_write = win32.OVERLAPPED()
            self._overlapped_write.hEvent = win32.CreateEvent(None, 0, 0, None)
            win32.SetupComm(self._port_handle, 4096, 4096)
            self._orgTimeouts = win32.COMMTIMEOUTS()
            win32.GetCommTimeouts(self._port_handle, ctypes.byref(self._orgTimeouts))
            self._reconfigure_port()
            # Deliberately NO PurgeComm/reset on this controlled observation handle.
        except BaseException:
            try:
                self._close()
            finally:
                self._port_handle = None
            raise
        self.is_open = True
