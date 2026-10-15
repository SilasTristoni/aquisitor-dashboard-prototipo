"""Bound untrusted file paths and ranges before reaching the filesystem/parser."""

import re

from fastapi import Request
from fastapi.responses import JSONResponse

SINGLE_RANGE = re.compile(r"bytes=(?:[0-9]{1,19}-[0-9]{0,19}|-[0-9]{1,19})", re.ASCII)


async def guard_file_requests(request: Request, call_next):
    # Use the ASGI path, not a URL reconstructed from the untrusted Host header.
    # Windows UNC/device/drive paths must never reach Path.resolve or StaticFiles.
    path = request.scope["path"]
    if (
        not path.startswith("/")
        or path.startswith("//")
        or any(character in path for character in ("\\", ":", "\x00"))
    ):
        return JSONResponse(
            {"error": {"status": 400, "message": "Caminho inválido"}}, status_code=400
        )
    ranges = request.headers.getlist("range")
    # The application downloads whole files or a single range. Reject multi-range
    # and oversized/malformed values before Starlette's quadratic range parser.
    if ranges and (len(ranges) != 1 or not SINGLE_RANGE.fullmatch(ranges[0])):
        return JSONResponse(
            {"error": {"status": 416, "message": "Intervalo de arquivo inválido"}}, status_code=416
        )
    return await call_next(request)
