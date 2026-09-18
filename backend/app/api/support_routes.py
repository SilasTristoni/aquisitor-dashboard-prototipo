from __future__ import annotations

import io
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.entities import Device, SystemEvent, User
from app.services.acquisition import acquisition_service
from app.services.support import support_snapshot

router = APIRouter(prefix="/api/v1")


@router.get("/support/package")
async def download_support_package(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    session_id: int | None = Query(None, ge=1),
    correlation_id: str | None = Query(None, pattern=r"^TP-[A-Z]+-[A-F0-9]{6,32}$"),
) -> StreamingResponse:
    if correlation_id and not session_id:
        session_id = db.scalar(
            select(SystemEvent.session_id)
            .where(SystemEvent.details["correlation_id"].as_string() == correlation_id)
            .order_by(SystemEvent.id.desc())
            .limit(1)
        )
    statuses = []
    for device_id in db.scalars(select(Device.id)):
        try:
            statuses.append(await acquisition_service.status(device_id))
        except Exception:
            logging.getLogger(__name__).exception(
                "Runtime status unavailable during support export", extra={"device_id": device_id}
            )
            statuses.append({"device_id": device_id, "state": "unavailable"})
    content = support_snapshot(db, statuses, session_id, correlation_id)
    filename = f"ThermoPower-Diagnostico-{datetime.now(UTC):%Y%m%d-%H%M%S}.zip"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


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
