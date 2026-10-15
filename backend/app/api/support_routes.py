from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.api.deps import get_current_user
from app.models.entities import User
from app.services.acquisition import acquisition_service

router = APIRouter(prefix="/api/v1")


async def _diagnostic(request, session_id=None, correlation_id=None):
    from app.core.database import engine
    from app.core.physical_trace import journal
    from app.services.diagnostic_snapshot import bounded, runtime_snapshot
    from app.services.protocol_probe import protocol_probe_service
    from app.services.support_collection import export_diagnostic
    from app.services.websocket import websocket_hub

    snapshot = runtime_snapshot(acquisition_service, websocket_hub)
    snapshot["probes"] = bounded(protocol_probe_service.latest_results)
    snapshot["journal"] = journal.status()
    return await export_diagnostic(
        request,
        snapshot,
        engine.url.render_as_string(hide_password=False),
        session_id,
        correlation_id,
    )


@router.get("/support/physical-package")
async def download_physical_package(
    request: Request,
    _: Annotated[User, Depends(get_current_user)],
) -> FileResponse:
    return await _diagnostic(request)


@router.get("/support/package")
async def download_support_package(
    request: Request,
    _: Annotated[User, Depends(get_current_user)],
    session_id: int | None = Query(None, ge=1),
    correlation_id: str | None = Query(None, pattern=r"^TP-[A-Z]+-[A-F0-9]{6,32}$"),
) -> FileResponse:
    return await _diagnostic(request, session_id, correlation_id)


@router.get("/help/user-guide")
def user_guide(_: Annotated[User, Depends(get_current_user)]) -> FileResponse:
    root = (
        Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
    )
    path = (
        root / "help/user-guide.pdf"
        if getattr(sys, "frozen", False)
        else root / "build/user-guide.pdf"
    )
    if not path.is_file():
        raise HTTPException(404, "Guia indisponível nesta instalação. Consulte o suporte.")
    return FileResponse(
        path, media_type="application/pdf", filename="Manual do Usuário - ThermoPower Monitor.pdf"
    )
