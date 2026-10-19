import base64
import hashlib
import hmac
import io
import json
import secrets
import time
from collections import OrderedDict, deque
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.api.analysis_routes import Db, Operator, session_or_404, utc
from app.api.deps import require_roles
from app.core.config import get_settings
from app.core.security import hash_password
from app.models.entities import SessionShare, User
from app.portal.contracts import MAX_SNAPSHOT_BYTES, ResultSnapshot, canonical_bytes
from app.schemas.contracts import PeriodReportRequest
from app.services.period_documents import render_period_pdf
from app.services.period_reporting import PeriodReportDataService
from app.services.period_workbook import render_period_csv, render_period_xlsx
from app.services.portal_configuration import (
    PortalConfiguration,
    configuration_status,
    save_configuration,
)
from app.services.result_publication import (
    encode_document,
    installation_id,
    portal_origin,
    portal_request,
    publish_snapshot,
    revoke_publication,
    update_publication_permissions,
)
from app.services.share_policy import (
    PRIVATE_HEADERS,
    ShareAccess,
    SharePermissions,
    enforce_share_access,
)


class PrivateSharingRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                # The operational validation handler includes input values. Credentials
                # in sharing/configuration must never be echoed by that handler.
                raise HTTPException(422, "Dados de compartilhamento inválidos") from None

        return private_handler


router = APIRouter(prefix="/api/v1", tags=["sharing"], route_class=PrivateSharingRoute)
Admin = Annotated[User, Depends(require_roles("admin"))]


@router.get("/results-portal/configuration")
def portal_configuration_status(user: Operator, response: Response):
    response.headers.update(PRIVATE_HEADERS)
    return {**configuration_status(), "can_configure": user.role == "admin"}


@router.put("/results-portal/configuration")
def configure_portal(payload: PortalConfiguration, _: Admin, response: Response):
    save_configuration(payload)
    response.headers.update(PRIVATE_HEADERS)
    return {**configuration_status(), "can_configure": True}


@router.post("/results-portal/check")
def check_portal(_: Admin, response: Response):
    result = portal_request(portal_origin(), "GET", "/portal/v1/installation")
    response.headers.update(PRIVATE_HEADERS)
    return result


class ShareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str | None = Field(default=None, min_length=1, max_length=72)
    expires_in_days: Literal[1, 7, 30] | None = 7
    permissions: SharePermissions = Field(default_factory=SharePermissions)
    channels: list[int] | None = Field(default=None, max_length=32)
    include_power: bool = True
    include_open_channels: bool = False
    destination: Literal["local", "portal"] = "local"
    publication_id: UUID | None = None

    @field_validator("channels")
    @classmethod
    def valid_channels(cls, value):
        return PeriodReportRequest.validate_channels(value)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value):
        if value and len(value.encode()) > 72:
            raise ValueError("A senha deve ter até 72 bytes")
        return value


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
    options = row.report_options or {}
    pending = options.get("publication_pending", False)
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
        "path": f"/compartilhado#{token}"
        if recoverable and not row.revoked_at and not pending
        else None,
        "portal_origin": row.portal_origin,
        "public_url": f"{options.get('public_origin', row.portal_origin)}/compartilhado#{token}"
        if row.portal_origin and recoverable and not row.revoked_at and not pending
        else None,
        "permission_update_pending": options.get("permission_update_pending"),
        "allowed_permissions": options.get("allowed_permissions", row.permissions),
        "can_retry": bool(row.publication_payload),
        "status": "revoked"
        if row.revoked_at
        else "expired"
        if row.expires_at and utc(row.expires_at) <= datetime.now(UTC)
        else "pending"
        if pending
        else "active",
    }


@router.post("/sessions/{session_id}/shares", status_code=201)
def create_share(session_id: int, payload: ShareInput, db: Db, user: Operator, response: Response):
    session = session_or_404(db, session_id)
    if payload.destination == "portal" and (
        session.status != "finished" or not session.analysis_start
    ):
        raise HTTPException(422, "Finalize a sessão e salve o período oficial antes de publicar.")
    input_hash = hmac.digest(
        get_settings().jwt_secret.encode(),
        canonical_bytes(payload.model_dump(mode="json")),
        "sha256",
    ).hex()
    if payload.destination == "portal" and payload.publication_id:
        existing = db.scalar(
            select(SessionShare).where(SessionShare.publication_id == str(payload.publication_id))
        )
        if existing:
            if (
                existing.session_id != session_id
                or existing.created_by != user.id
                or existing.publication_input_hash != input_hash
            ):
                raise HTTPException(
                    409, "Identificador de publicação já utilizado com outros dados."
                )
            return send_publication(existing, db)
    nonce = secrets.token_urlsafe(32)
    token = share_token(nonce)
    row = SessionShare(
        session_id=session_id,
        publication_id=str(payload.publication_id)
        if payload.destination == "portal" and payload.publication_id
        else None,
        publication_input_hash=input_hash if payload.destination == "portal" else None,
        report_options={
            "channels": payload.channels,
            "include_power": payload.include_power,
            "include_open_channels": payload.include_open_channels,
            "installation_id": installation_id() if payload.destination == "portal" else None,
            "allowed_permissions": payload.permissions.model_dump(),
        },
        portal_origin=portal_origin() if payload.destination == "portal" else None,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_nonce=nonce,
        password_hash=hash_password(payload.password) if payload.password else None,
        permissions=payload.permissions.model_dump(),
        created_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=payload.expires_in_days)
        if payload.expires_in_days
        else None,
    )
    if row.portal_origin:
        period = share_period(row, session)
        try:
            service = PeriodReportDataService(db)
            data = service.collect(period)
            result = public_result(row, session, service.preview_data(data, period))
            sanitize_report(data, session)
            builders = {
                "pdf": render_period_pdf,
                "xlsx": render_period_xlsx,
                "csv": render_period_csv,
            }
            documents = {
                kind: encode_document(builder(data, period))
                for kind, builder in builders.items()
                if row.permissions.get(kind)
            }
        except ValueError as exc:
            raise HTTPException(
                422, "Não há medições disponíveis nos filtros selecionados"
            ) from exc
        snapshot = {
            "schema_version": 1,
            "created_at": datetime.now(UTC),
            "token_hash": row.token_hash,
            "password_hash": row.password_hash,
            "expires_at": row.expires_at,
            "permissions": row.permissions,
            "result": result,
            "documents": documents,
        }
        validated = ResultSnapshot.model_validate(snapshot)
        row.publication_payload = canonical_bytes(validated.model_dump(mode="json"))
        if len(row.publication_payload) > MAX_SNAPSHOT_BYTES:
            raise HTTPException(413, "Resultado excede 25 MiB. Reduza período ou downloads.")
        row.report_options = {**row.report_options, "publication_pending": True}
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                409, "Publicação já iniciada. Consulte a lista e tente novamente."
            ) from None
        response.headers.update(PRIVATE_HEADERS)
        return send_publication(row, db)
    else:
        db.add(row)
        db.commit()
    response.headers.update(PRIVATE_HEADERS)
    return {**share_dict(row, db), "token": token, "path": f"/compartilhado#{token}"}


def ensure_installation(row):
    original = (row.report_options or {}).get("installation_id")
    if original and original != installation_id():
        raise HTTPException(409, "Restaure a identidade da instalação que publicou este resultado.")


def send_publication(row, db):
    if row.revoked_at:
        raise HTTPException(409, "Compartilhamento já revogado.")
    if not (row.report_options or {}).get("publication_pending"):
        return share_dict(row, db)
    ensure_installation(row)
    if not row.publication_payload:
        raise HTTPException(
            409, "Cópia autorizada indisponível. Revogue este link e publique outro."
        )
    share_id, origin, content = row.id, row.portal_origin, row.publication_payload
    db.commit()  # release any read transaction before HTTPS
    receipt = publish_snapshot(origin, json.loads(content))
    db.expire_all()
    row = db.get(SessionShare, share_id)
    if row.revoked_at:
        raise HTTPException(409, "Compartilhamento revogado durante a publicação.")
    row.report_options = {
        **row.report_options,
        "publication_pending": False,
        "public_origin": receipt["public_origin"] if receipt else origin,
    }
    # Retain only pending snapshots locally. Confirmed results live in the portal.
    row.publication_payload = None
    db.commit()
    return {**share_dict(row, db), "token": share_token(row.token_nonce)}


@router.post("/sessions/{session_id}/shares/{share_id}/retry")
def retry_publication(session_id: int, share_id: int, db: Db, _: Operator, response: Response):
    row = db.get(SessionShare, share_id)
    if not row or row.session_id != session_id or not row.portal_origin:
        raise HTTPException(404, "Publicação não encontrada")
    response.headers.update(PRIVATE_HEADERS)
    return send_publication(row, db)


@router.patch("/sessions/{session_id}/shares/{share_id}/permissions")
def update_share_permissions(
    session_id: int,
    share_id: int,
    payload: SharePermissions,
    db: Db,
    _: Operator,
    response: Response,
):
    row = db.get(SessionShare, share_id)
    if not row or row.session_id != session_id or row.revoked_at:
        raise HTTPException(404, "Compartilhamento indisponível")
    options = row.report_options or {}
    if options.get("publication_pending"):
        raise HTTPException(409, "Confirme a publicação antes de alterar permissões.")
    desired = payload.model_dump()
    allowed = options.get("allowed_permissions", row.permissions)
    if any(enabled and not allowed[key] for key, enabled in desired.items()):
        raise HTTPException(422, "Permissão fora do snapshot autorizado. Publique outro resultado.")
    if row.portal_origin:
        ensure_installation(row)
        pending = options.get("permission_update_pending")
        if pending and pending["permissions"] != desired:
            raise HTTPException(409, "Reenvie a alteração pendente antes de fazer outra.")
        pending = pending or {
            "permissions": desired,
            "revision": options.get("policy_revision", 0) + 1,
        }
        # Compare and swap prevents two concurrent local edits from using one revision.
        changed = db.execute(
            update(SessionShare)
            .where(
                SessionShare.id == row.id,
                SessionShare.mutation_version == row.mutation_version,
                SessionShare.revoked_at.is_(None),
            )
            .values(
                report_options={**options, "permission_update_pending": pending},
                mutation_version=SessionShare.mutation_version + 1,
            )
        )
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "Outra operação está em andamento. Atualize a lista.")
        origin, token_hash, mutation_version = (
            row.portal_origin,
            row.token_hash,
            row.mutation_version,
        )
        db.commit()
        update_publication_permissions(origin, token_hash, pending)
        db.expire_all()
        row = db.get(SessionShare, share_id)
        if row.revoked_at:
            raise HTTPException(409, "Compartilhamento revogado.")
        if row.mutation_version != mutation_version:
            raise HTTPException(409, "Outra sincronização está em andamento. Atualize a lista.")
        row.report_options = {
            **row.report_options,
            "permission_update_pending": None,
            "policy_revision": pending["revision"],
        }
    row.permissions = desired
    db.commit()
    response.headers.update(PRIVATE_HEADERS)
    return share_dict(row, db)


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
        if row.portal_origin:
            ensure_installation(row)
            origin, token_hash = row.portal_origin, row.token_hash
            db.commit()
            revoke_publication(origin, token_hash)
        row.revoked_at = datetime.now(UTC)
        row.publication_payload = None
        db.commit()
    return Response(status_code=204)


def authorize_share(payload: ShareAccess, request: Request, db, permission: str | None = None):
    share_limiter.check(request.client.host if request.client else "unknown")
    row = db.scalar(
        select(SessionShare).where(
            SessionShare.token_hash == hashlib.sha256(payload.token.encode()).hexdigest()
        )
    )
    enforce_share_access(row, payload, permission)
    if row.portal_origin:
        raise HTTPException(409, "Este resultado deve ser consultado no portal publicado.")
    session = session_or_404(db, row.session_id)
    return row, session, share_period(row, session)


def share_period(row, session):
    options = row.report_options or {}
    return PeriodReportRequest(
        start=utc(session.analysis_start or session.started_at),
        end=utc(session.analysis_end or session.ended_at or datetime.now(UTC)),
        title=session.name,
        session_ids=[session.id],
        interpolation="none",
        channels=options.get("channels"),
        include_open_channels=options.get("include_open_channels", False),
        include_power=options.get("include_power", True),
        include_electrical_details=options.get("include_power", True),
        include_alerts=False,
        include_session_list=False,
    )


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
    result = public_result(row, session, preview)
    record_access(db, row.id)
    response.headers.update(PRIVATE_HEADERS)
    return result


def public_result(row, session, preview):
    return {
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


@router.post("/public/shares/download/{file_type}")
def download_share(
    file_type: Literal["pdf", "xlsx", "csv"], payload: ShareAccess, request: Request, db: Db
):
    row, session, period = authorize_share(payload, request, db, file_type)
    try:
        data = PeriodReportDataService(db).collect(period)
    except ValueError as exc:
        raise HTTPException(422, "Não há medições disponíveis no período compartilhado") from exc
    sanitize_report(data, session)
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


def sanitize_report(data, session):
    for item in data["sessions"]:
        item["devices"], item["operator"], item["metadata"] = [], None, public_metadata(session)
    data["statistics"]["general"]["source_quality"] = []
    data["alerts"] = []
