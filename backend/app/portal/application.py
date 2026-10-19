"""Run with uvicorn app.portal.application:create_app --factory (separate database)."""

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from starlette.concurrency import run_in_threadpool

from app.portal.body_limit import BoundedBody
from app.portal.contracts import MAX_SNAPSHOT_BYTES, ResultSnapshot, canonical_bytes
from app.portal.models import PublishedResult, RateBucket
from app.services.share_policy import PRIVATE_HEADERS, ShareAccess, enforce_share_access


class PortalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="THERMOPOWER_PORTAL_", extra="ignore")
    database_url: str
    publish_key: str = Field(min_length=32)
    integrity_key: str = Field(min_length=32)


def create_app(settings=None, factory=None):
    settings = settings or PortalSettings()
    engine = None
    if factory is None:
        engine = create_engine(
            settings.database_url,
            connect_args={"timeout": 2}
            if settings.database_url.startswith("sqlite")
            else {"connect_timeout": 5},
        )
        factory = sessionmaker(engine)
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        yield
        if engine:
            engine.dispose()

    app = FastAPI(
        title="ThermoPower Results",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def private_headers(request, call_next):
        # No request bodies or credentials in logs. Proxy logs must omit queries too.
        response = await call_next(request)
        response.headers.update(PRIVATE_HEADERS)
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse(
            {"detail": "Solicitação inválida"}, status_code=422, headers=PRIVATE_HEADERS
        )

    @app.exception_handler(SQLAlchemyError)
    async def storage_failure(request, exc):
        return JSONResponse(
            {"detail": "Portal temporariamente indisponível. Tente novamente."},
            status_code=503,
            headers=PRIVATE_HEADERS,
        )

    def database():
        with factory() as db:
            yield db

    def limit(request, db):
        window = int(time.time()) // 60
        host = request.client.host if request.client else "unknown"
        # Persistent, atomic buckets work across workers/restarts. Ignore forwarded headers.
        insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
        counts = []
        for scope, maximum in [(host, 30), ("portal-global", 600)]:
            key = hmac.digest(settings.integrity_key.encode(), scope.encode(), "sha256").hex()
            statement = insert(RateBucket).values(key=key, window=window, count=1)
            statement = statement.on_conflict_do_update(
                index_elements=["key", "window"], set_={"count": RateBucket.count + 1}
            ).returning(RateBucket.count)
            counts.append((db.scalar(statement), maximum))
        db.execute(delete(RateBucket).where(RateBucket.window < window - 2))
        db.commit()
        if any(count > maximum for count, maximum in counts):
            raise HTTPException(
                429, "Muitas tentativas. Aguarde um minuto.", headers={"Retry-After": "60"}
            )

    def management(request):
        if not hmac.compare_digest(
            request.headers.get("authorization", ""), "Bearer " + settings.publish_key
        ):
            raise HTTPException(401, "Publicação não autorizada")

    def store_snapshot(raw):
        try:
            snapshot = ResultSnapshot.model_validate_json(raw)
        except (ValidationError, ValueError):
            raise HTTPException(422, "Snapshot inválido") from None
        canonical = canonical_bytes(snapshot.model_dump(mode="json"))
        signature = hmac.digest(settings.integrity_key.encode(), canonical, "sha256").hex()
        with factory() as db:
            existing = db.get(PublishedResult, snapshot.token_hash)
            if existing:
                # Immutable, idempotent publication. A revoked link can never be resurrected.
                if existing.revoked_at or not hmac.compare_digest(existing.signature, signature):
                    raise HTTPException(409, "Resultado já publicado. Crie outro compartilhamento.")
                return {"published": True}
            db.add(
                PublishedResult(
                    token_hash=snapshot.token_hash,
                    password_hash=snapshot.password_hash,
                    permissions=snapshot.permissions.model_dump(),
                    expires_at=snapshot.expires_at,
                    payload=canonical,
                    signature=signature,
                )
            )
            db.commit()
        return {"published": True}

    @app.post("/portal/v1/results", status_code=201)
    async def publish(request: Request):
        management(request)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_SNAPSHOT_BYTES:
                raise HTTPException(413, "Snapshot excede 25 MiB")
        return await run_in_threadpool(store_snapshot, bytes(raw))

    @app.delete("/portal/v1/results/{token_hash}", status_code=204)
    def revoke(token_hash: str, request: Request, db=Depends(database)):
        management(request)
        if len(token_hash) != 64 or any(char not in "0123456789abcdef" for char in token_hash):
            raise HTTPException(422, "Identificador inválido")
        insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
        revoked_at = datetime.now(UTC)
        statement = insert(PublishedResult).values(
            token_hash=token_hash,
            password_hash=None,
            permissions={},
            expires_at=None,
            revoked_at=revoked_at,
            payload=b"{}",
            signature="",
            access_count=0,
        )
        db.execute(
            statement.on_conflict_do_update(
                index_elements=["token_hash"], set_={"revoked_at": revoked_at}
            )
        )
        db.commit()
        return Response(status_code=204)

    def authorized(payload, request, db, permission=None):
        limit(request, db)
        row = db.get(PublishedResult, hashlib.sha256(payload.token.encode()).hexdigest())
        if row is None or row.revoked_at:
            raise HTTPException(404, "Compartilhamento indisponível")
        if row is not None:
            signature = hmac.digest(settings.integrity_key.encode(), row.payload, "sha256").hex()
            if not hmac.compare_digest(signature, row.signature):
                raise HTTPException(503, "Integridade do resultado indisponível")
            snapshot = json.loads(row.payload)
            # Authorization metadata must match the authenticated immutable snapshot.
            expires = (
                row.expires_at.replace(tzinfo=UTC)
                if row.expires_at and not row.expires_at.tzinfo
                else row.expires_at
            )
            if (
                snapshot["token_hash"] != row.token_hash
                or snapshot["permissions"] != row.permissions
                or snapshot["password_hash"] != row.password_hash
                or (
                    datetime.fromisoformat(snapshot["expires_at"])
                    if snapshot["expires_at"]
                    else None
                )
                != expires
            ):
                raise HTTPException(503, "Integridade do resultado indisponível")
        enforce_share_access(row, payload, permission)
        db.execute(
            update(PublishedResult)
            .where(PublishedResult.token_hash == row.token_hash)
            .values(access_count=PublishedResult.access_count + 1)
        )
        db.commit()
        return snapshot

    @app.post("/api/v1/public/shares/access")
    def access(payload: ShareAccess, request: Request, db=Depends(database)):
        return authorized(payload, request, db)["result"]

    @app.post("/api/v1/public/shares/download/{kind}")
    def download(kind: str, payload: ShareAccess, request: Request, db=Depends(database)):
        if kind not in {"pdf", "csv", "xlsx"}:
            raise HTTPException(404)
        snapshot = authorized(payload, request, db, kind)
        content = base64.b64decode(snapshot["documents"][kind]["content"])
        media = {
            "pdf": "application/pdf",
            "csv": "text/csv; charset=utf-8",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        return Response(
            content,
            media_type=media[kind],
            headers={
                **PRIVATE_HEADERS,
                "Content-Disposition": f'attachment; filename="resultado.{kind}"',
            },
        )

    app.add_middleware(BoundedBody)
    return app
