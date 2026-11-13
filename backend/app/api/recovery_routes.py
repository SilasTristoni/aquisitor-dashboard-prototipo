from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.entities import User
from app.services.acquisition import acquisition_service
from app.services.session_recovery import recovery_service

router = APIRouter(prefix="/api/v1/recovery", tags=["recovery"])
Db = Annotated[Session, Depends(get_db)]
Operator = Annotated[User, Depends(require_roles("admin", "operator"))]


class RecoveryDecision(BaseModel):
    action: Literal["resume", "close"]


@router.get("/sessions")
def interrupted_sessions(
    db: Db, _: Operator, page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=50)
):
    return recovery_service.listing(db, page, page_size)


@router.post("/sessions/{session_id}")
async def decide_session(session_id: int, payload: RecoveryDecision, db: Db, user: Operator):
    return await recovery_service.decide(
        db, acquisition_service, session_id, payload.action, user.id
    )


@router.get("/health")
def recovery_health(_: Operator):
    faults = [
        {
            "device_id": device_id,
            "code": runtime.storage_fault["code"],
            "message": runtime.storage_fault["message"],
            "automatic_retry_exhausted": runtime.storage_fault["automatic_retry_exhausted"],
        }
        for device_id, runtime in acquisition_service.runtimes.items()
        if runtime.storage_fault
    ]
    return {
        "supervision_ready": recovery_service.ready,
        "storage": recovery_service.storage,
        "write_faults": faults,
    }
