import base64
import hashlib
import hmac
import io
import secrets
import time
from collections import OrderedDict, deque
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update

from app.api.analysis_routes import Db, Operator, session_or_404, utc
from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models.entities import SessionShare, User
from app.schemas.contracts import PeriodReportRequest
from app.services.period_documents import render_period_pdf
from app.services.period_reporting import PeriodReportDataService
from app.services.period_workbook import render_period_csv, render_period_xlsx

router = APIRouter(prefix="/api/v1", tags=["sharing"])
PRIVATE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class SharePermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    graphs: bool = True
    pdf: bool = False
    xlsx: bool = False
    csv: bool = False


class ShareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str | None = Field(default=None, min_length=1, max_length=72)
    expires_in_days: Literal[1, 7, 30] | None = 7
    permissions: SharePermissions = Field(default_factory=SharePermissions)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value):
        if value and len(value.encode()) > 72:
            raise ValueError("A senha deve ter até 72 bytes")
        return value


class ShareAccess(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=40, max_length=100)
    password: str | None = Field(default=None, max_length=72)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value):
        return ShareInput.password_bytes(value)


class ShareRateLimiter:
    """Bounded, per-process/IP limiter; never trust a caller-supplied forwarded IP."""

    def __init__(self):
        self.buckets = OrderedDict()
        self.lock = Lock()

    def check(self, key: str):
        now = time.monotonic()
        with self.lock:
            bucket = self.buckets.pop(key, deque())
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            self.buckets[key] = bucket
            while len(self.buckets) > 10000:
                self.buckets.popitem(last=False)
            if len(bucket) >= 30:
                raise HTTPException(429, "Muitas tentativas. Aguarde um minuto.")
            bucket.append(now)


share_limiter = ShareRateLimiter()


def share_token(nonce: str) -> str:
    # A random nonce is not a bearer credential. Reconstructing the token also requires
    # the environment signing key. A database-only disclosure does not reveal links.
    digest = hmac.digest(
        get_settings().jwt_secret.encode(),
        b"thermopower/session-share/v1/" + nonce.encode(),
        "sha256",
    )
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def share_dict(row: SessionShare, db) -> dict:
    creator = db.get(User, row.created_by)
    token = share_token(row.token_nonce)
    recoverable = hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), row.token_hash)
    return {
        "id": row.id,
        "created_by": row.created_by,
        "creator_name": creator.name if creator else None,
        "created_at": utc(row.created_at),
        "expires_at": utc(row.expires_at) if row.expires_at else None,
        "revoked_at": utc(row.revoked_at) if row.revoked_at else None,
        "last_accessed_at": utc(row.last_accessed_at) if row.last_accessed_at else None,
        "access_count": row.access_count,
        "permissions": row.permissions,
        "has_password": bool(row.password_hash),
        "path": f"/compartilhado#{token}" if recoverable and not row.revoked_at else None,
        "status": "revoked"
        if row.revoked_at
        else "expired"
        if row.expires_at and utc(row.expires_at) <= datetime.now(UTC)
        else "active",
    }


@router.post("/sessions/{session_id}/shares", status_code=201)
def create_share(session_id: int, payload: ShareInput, db: Db, user: Operator, response: Response):
    session_or_404(db, session_id)
    nonce = secrets.token_urlsafe(32)
    token = share_token(nonce)
    row = SessionShare(
        session_id=session_id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_nonce=nonce,
        password_hash=hash_password(payload.password) if payload.password else None,
        permissions=payload.permissions.model_dump(),
        created_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=payload.expires_in_days)
        if payload.expires_in_days
        else None,
    )
    db.add(row)
    db.commit()
    response.headers.update(PRIVATE_HEADERS)
    return {**share_dict(row, db), "token": token, "path": f"/compartilhado#{token}"}


@router.get("/sessions/{session_id}/shares")
def list_shares(
    session_id: int,
    db: Db,
    _: Operator,
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    session_or_404(db, session_id)
    response.headers.update(PRIVATE_HEADERS)
    condition = SessionShare.session_id == session_id
    total = db.scalar(select(func.count()).select_from(SessionShare).where(condition)) or 0
    rows = db.scalars(
        select(SessionShare)
        .where(condition)
        .order_by(SessionShare.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [share_dict(row, db) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.delete("/sessions/{session_id}/shares/{share_id}", status_code=204)
def revoke_share(session_id: int, share_id: int, db: Db, _: Operator):
    row = db.get(SessionShare, share_id)
    if not row or row.session_id != session_id:
        raise HTTPException(404, "Compartilhamento não encontrado")
    if not row.revoked_at:
        row.revoked_at = datetime.now(UTC)
        db.commit()
    return Response(status_code=204)


def authorize_share(payload: ShareAccess, request: Request, db, permission: str | None = None):
    share_limiter.check(request.client.host if request.client else "unknown")
    row = db.scalar(
        select(SessionShare).where(
            SessionShare.token_hash == hashlib.sha256(payload.token.encode()).hexdigest()
        )
    )
    if not row or row.revoked_at or (row.expires_at and utc(row.expires_at) <= datetime.now(UTC)):
        raise HTTPException(404, "Compartilhamento indisponível")
    if row.password_hash and not verify_password(payload.password or "", row.password_hash):
        raise HTTPException(401, "Informe a senha correta do compartilhamento")
    if permission and not row.permissions.get(permission, False):
        raise HTTPException(403, "Download não autorizado neste compartilhamento")
    session = session_or_404(db, row.session_id)
    period = PeriodReportRequest(
        start=utc(session.analysis_start or session.started_at),
        end=utc(session.analysis_end or session.ended_at or datetime.now(UTC)),
        title=session.name,
        session_ids=[session.id],
        interpolation="none",
        include_alerts=False,
        include_session_list=False,
    )
    return row, session, period


def record_access(db, share_id):
    db.execute(
        update(SessionShare)
        .where(SessionShare.id == share_id)
        .values(access_count=SessionShare.access_count + 1, last_accessed_at=datetime.now(UTC))
    )
    db.commit()


def public_metadata(session):
    return {
        key: value
        for key, value in (session.metadata_json or {}).items()
        if key in {"product", "model", "sample", "code", "nominal_voltage", "setpoint"}
    }


def public_tree(value):
    """Strip source/admin identities from statistics and sampled preview points."""
    if isinstance(value, list):
        return [public_tree(item) for item in value]
    if isinstance(value, dict):
        return {
            key: public_tree(item)
            for key, item in value.items()
            if key
            not in {
                "session_id",
                "device_id",
                "user_id",
                "raw_payload",
                "original_values",
                "original_units",
                "source_quality",
                "created_by",
                "selected_by",
                "creator_name",
            }
        }
    return value


@router.post("/public/shares/access")
def access_share(payload: ShareAccess, request: Request, response: Response, db: Db):
    row, session, period = authorize_share(payload, request, db)
    try:
        preview = PeriodReportDataService(db).preview(period)
    except ValueError as exc:
        raise HTTPException(422, "Não há medições disponíveis no período compartilhado") from exc
    result = {
        "name": session.name,
        "metadata": public_metadata(session),
        "status": session.status,
        "official": bool(session.analysis_start),
        "analysis_label": session.analysis_label,
        "permissions": row.permissions,
        "period": preview["period"],
        "statistics": public_tree(preview["statistics"]),
        "series": public_tree(preview["series"]) if row.permissions.get("graphs") else [],
        "selected_channels": preview["selected_channels"],
        "channel_labels": preview["channel_labels"],
        "annotations": public_tree(preview["annotations"]),
    }
    record_access(db, row.id)
    response.headers.update(PRIVATE_HEADERS)
    return result


@router.post("/public/shares/download/{file_type}")
def download_share(
    file_type: Literal["pdf", "xlsx", "csv"], payload: ShareAccess, request: Request, db: Db
):
    row, session, period = authorize_share(payload, request, db, file_type)
    try:
        data = PeriodReportDataService(db).collect(period)
    except ValueError as exc:
        raise HTTPException(422, "Não há medições disponíveis no período compartilhado") from exc
    # Render only this session's report, with technical equipment/user details removed.
    for item in data["sessions"]:
        item["devices"], item["operator"], item["metadata"] = [], None, public_metadata(session)
    data["statistics"]["general"]["source_quality"] = []
    data["alerts"] = []
    builders = {"pdf": render_period_pdf, "xlsx": render_period_xlsx, "csv": render_period_csv}
    content = builders[file_type](data, period)
    record_access(db, row.id)
    media = {
        "pdf": "application/pdf",
        "csv": "text/csv; charset=utf-8",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media[file_type],
        headers={
            **PRIVATE_HEADERS,
            "Content-Disposition": f'attachment; filename="resultado.{file_type}"',
        },
    )
