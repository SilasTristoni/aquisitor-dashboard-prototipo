from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.entities import MeasurementSession, SessionAnnotation, User

router = APIRouter(prefix="/api/v1/sessions", tags=["analysis"])
Db = Annotated[Session, Depends(get_db)]
Reader = Annotated[User, Depends(get_current_user)]
Operator = Annotated[User, Depends(require_roles("admin", "operator"))]


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def session_or_404(db: Session, session_id: int) -> MeasurementSession:
    session = db.get(MeasurementSession, session_id)
    if not session:
        raise HTTPException(404, "Sessão não encontrada")
    return session


def validate_timestamp(session: MeasurementSession, timestamp: datetime):
    if not utc(session.started_at) <= timestamp <= utc(session.ended_at or datetime.now(UTC)):
        raise HTTPException(422, "O horário deve estar dentro da sessão")


def analysis_period(session: MeasurementSession) -> dict | None:
    if not session.analysis_start:
        return None
    return {
        "start": utc(session.analysis_start).isoformat(),
        "end": utc(session.analysis_end).isoformat(),
        "label": session.analysis_label,
        "selected_by": session.analysis_selected_by,
        "selected_at": utc(session.analysis_selected_at).isoformat(),
    }


class AnalysisInput(BaseModel):
    start: AwareDatetime
    end: AwareDatetime
    label: str = Field(default="Período oficial", min_length=1, max_length=120)


class AnnotationInput(BaseModel):
    timestamp: AwareDatetime
    kind: Literal["stabilization", "shutdown", "restart", "condition_change", "note"] = "note"
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)


@router.put("/{session_id}/analysis-period")
def save_analysis(session_id: int, payload: AnalysisInput, db: Db, user: Operator):
    session = session_or_404(db, session_id)
    validate_timestamp(session, payload.start)
    validate_timestamp(session, payload.end)
    if payload.start >= payload.end:
        raise HTTPException(422, "O fim deve ser posterior ao início")
    # SQLite drops offsets on DateTime columns; store UTC explicitly for both databases.
    session.analysis_start, session.analysis_end = utc(payload.start), utc(payload.end)
    session.analysis_label = payload.label
    session.analysis_selected_by, session.analysis_selected_at = user.id, datetime.now(UTC)
    db.commit()
    return analysis_period(session)


@router.delete("/{session_id}/analysis-period", status_code=204)
def remove_analysis(session_id: int, db: Db, user: Operator):
    session = session_or_404(db, session_id)
    session.analysis_start = session.analysis_end = None
    session.analysis_label = session.analysis_selected_by = session.analysis_selected_at = None
    db.commit()
    return Response(status_code=204)


def annotation_dict(row: SessionAnnotation, db: Session) -> dict:
    creator = db.get(User, row.created_by)
    return {
        "id": row.id,
        "timestamp": utc(row.timestamp),
        "kind": row.kind,
        "title": row.title,
        "description": row.description,
        "created_by": row.created_by,
        "creator_name": creator.name if creator else None,
        "created_at": utc(row.created_at),
    }


@router.get("/{session_id}/annotations")
def list_annotations(
    session_id: int,
    db: Db,
    _: Reader,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
):
    session_or_404(db, session_id)
    condition = SessionAnnotation.session_id == session_id
    total = db.scalar(select(func.count()).select_from(SessionAnnotation).where(condition)) or 0
    rows = db.scalars(
        select(SessionAnnotation)
        .where(condition)
        .order_by(SessionAnnotation.timestamp, SessionAnnotation.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [annotation_dict(row, db) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.post("/{session_id}/annotations", status_code=201)
def create_annotation(session_id: int, payload: AnnotationInput, db: Db, user: Operator):
    validate_timestamp(session_or_404(db, session_id), payload.timestamp)
    values = {**payload.model_dump(), "timestamp": utc(payload.timestamp)}
    row = SessionAnnotation(session_id=session_id, created_by=user.id, **values)
    db.add(row)
    db.commit()
    return annotation_dict(row, db)


def editable_annotation(db: Session, session_id: int, annotation_id: int, user: User):
    row = db.get(SessionAnnotation, annotation_id)
    if not row or row.session_id != session_id:
        raise HTTPException(404, "Evento não encontrado")
    if user.role != "admin" and row.created_by != user.id:
        raise HTTPException(403, "Somente o autor ou administrador pode editar este evento")
    return row


@router.put("/{session_id}/annotations/{annotation_id}")
def edit_annotation(
    session_id: int, annotation_id: int, payload: AnnotationInput, db: Db, user: Operator
):
    row = editable_annotation(db, session_id, annotation_id, user)
    validate_timestamp(session_or_404(db, session_id), payload.timestamp)
    for key, value in payload.model_dump().items():
        setattr(row, key, utc(value) if key == "timestamp" else value)
    db.commit()
    return annotation_dict(row, db)


@router.delete("/{session_id}/annotations/{annotation_id}", status_code=204)
def delete_annotation(session_id: int, annotation_id: int, db: Db, user: Operator):
    db.delete(editable_annotation(db, session_id, annotation_id, user))
    db.commit()
    return Response(status_code=204)
