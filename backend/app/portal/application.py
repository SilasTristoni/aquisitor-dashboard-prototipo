"""Run with uvicorn app.portal.application:create_app --factory (separate database)."""

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from starlette.concurrency import run_in_threadpool

from app.portal.body_limit import BoundedBody
from app.portal.contracts import PolicyUpdate, ResultSnapshot, canonical_bytes
from app.portal.models import PublishedResult, RateBucket
from app.portal.settings import PortalSettings
from app.services.share_policy import PRIVATE_HEADERS, ShareAccess, enforce_share_access


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

    @app.get("/health")
    def health(db=Depends(database)):
        # Also detects unapplied migrations; contains no results or credentials.
        db.execute(select(PublishedResult.token_hash, PublishedResult.policy_revision).limit(1))
        return {"status": "ok"}

    def management(request, db):
        limit(request, db)
        authorization = request.headers.get("authorization", "")
        installation_id, _, secret = authorization.removeprefix("Bearer ").partition(".")
        installation = settings.installations.get(installation_id)
        digest = hashlib.sha256(secret.encode()).hexdigest()
        if (
            not authorization.startswith("Bearer ")
            or not installation
            or not installation.enabled
            or not hmac.compare_digest(digest, installation.credential_sha256)
        ):
            raise HTTPException(401, "Publicação não autorizada")
        return installation.tenant_id, installation_id

    def owned(row, owner):
        if (row.tenant_id, row.installation_id) != owner:
            raise HTTPException(404, "Compartilhamento indisponível")

    def policy_signature(token_hash, owner, permissions, revision):
        value = canonical_bytes(
            {
                "token_hash": token_hash,
                "owner": owner,
                "permissions": permissions,
                "revision": revision,
            }
        )
        return hmac.digest(settings.integrity_key.encode(), value, "sha256").hex()

    def receipt(row):
        return {
            "published": True,
            "token_hash": row.token_hash,
            "public_origin": settings.public_origin,
            "path": "/compartilhado",
            "policy_revision": row.policy_revision,
        }

    def store_snapshot(raw, owner):
        try:
            snapshot = ResultSnapshot.model_validate_json(raw)
            canonical = canonical_bytes(snapshot.model_dump(mode="json"))
        except (ValidationError, ValueError, RecursionError):
            raise HTTPException(422, "Snapshot inválido") from None
        signature = hmac.digest(settings.integrity_key.encode(), canonical, "sha256").hex()
        with factory() as db:
            # Atomic insert avoids duplicate races in both SQLite and PostgreSQL.
            insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
            db.execute(
                insert(PublishedResult)
                .values(
                    token_hash=snapshot.token_hash,
                    tenant_id=owner[0],
                    installation_id=owner[1],
                    password_hash=snapshot.password_hash,
                    permissions=snapshot.permissions.model_dump(),
                    expires_at=snapshot.expires_at,
                    payload=canonical,
                    signature=signature,
                    policy_revision=0,
                    access_count=0,
                    policy_signature=policy_signature(
                        snapshot.token_hash, owner, snapshot.permissions.model_dump(), 0
                    ),
                )
                .on_conflict_do_nothing(index_elements=["token_hash"])
            )
            db.commit()
            existing = db.get(PublishedResult, snapshot.token_hash)
            owned(existing, owner)
            if existing.revoked_at or not hmac.compare_digest(existing.signature, signature):
                raise HTTPException(409, "Resultado já publicado. Crie outro compartilhamento.")
            return receipt(existing)

    @app.post("/portal/v1/results", status_code=201)
    async def publish(request: Request, db=Depends(database)):
        owner = await run_in_threadpool(management, request, db)
        raw = await request.body()  # BoundedBody enforces size and read deadline.
        return await run_in_threadpool(store_snapshot, raw, owner)

    @app.get("/portal/v1/installation")
    def installation_status(request: Request, db=Depends(database)):
        owner = management(request, db)
        return {"installation_id": owner[1], "public_origin": settings.public_origin}

    @app.delete("/portal/v1/results/{token_hash}", status_code=204)
    def revoke(token_hash: str, request: Request, db=Depends(database)):
        owner = management(request, db)
        if len(token_hash) != 64 or any(char not in "0123456789abcdef" for char in token_hash):
            raise HTTPException(422, "Identificador inválido")
        insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
        revoked_at = datetime.now(UTC)
        db.execute(
            insert(PublishedResult)
            .values(
                token_hash=token_hash,
                tenant_id=owner[0],
                installation_id=owner[1],
                password_hash=None,
                permissions={},
                expires_at=None,
                revoked_at=revoked_at,
                payload=b"{}",
                signature="",
                access_count=0,
            )
            .on_conflict_do_nothing(index_elements=["token_hash"])
        )
        row = db.get(PublishedResult, token_hash)
        owned(row, owner)
        db.execute(
            update(PublishedResult)
            .where(PublishedResult.token_hash == token_hash)
            .values(revoked_at=revoked_at)
        )
        db.commit()
        return Response(status_code=204)

    @app.patch("/portal/v1/results/{token_hash}/permissions")
    def permissions(token_hash: str, payload: PolicyUpdate, request: Request, db=Depends(database)):
        owner = management(request, db)
        row = db.get(PublishedResult, token_hash)
        if not row or row.revoked_at:
            raise HTTPException(404, "Compartilhamento indisponível")
        owned(row, owner)
        original = verified_snapshot(row)
        desired = payload.permissions.model_dump()
        if any(enabled and not original["permissions"][key] for key, enabled in desired.items()):
            raise HTTPException(
                422, "Permissão fora do snapshot autorizado. Publique outro resultado."
            )
        if row.policy_revision == payload.revision and row.permissions == desired:
            return {"revision": row.policy_revision}
        changed = db.execute(
            update(PublishedResult)
            .where(
                PublishedResult.token_hash == token_hash,
                PublishedResult.policy_revision == payload.revision - 1,
                PublishedResult.revoked_at.is_(None),
            )
            .values(
                permissions=desired,
                policy_revision=payload.revision,
                policy_signature=policy_signature(token_hash, owner, desired, payload.revision),
            )
        )
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "Permissões desatualizadas. Confira a última operação.")
        db.commit()
        return {"revision": payload.revision}

    def verified_snapshot(row):
        signature = hmac.digest(settings.integrity_key.encode(), row.payload, "sha256").hex()
        policy = policy_signature(
            row.token_hash,
            (row.tenant_id, row.installation_id),
            row.permissions,
            row.policy_revision,
        )
        if (
            not row.tenant_id
            or not hmac.compare_digest(signature, row.signature)
            or not hmac.compare_digest(policy, row.policy_signature or "")
        ):
            raise HTTPException(503, "Integridade do resultado indisponível")
        snapshot = json.loads(row.payload)
        expires = (
            row.expires_at.replace(tzinfo=UTC)
            if row.expires_at and not row.expires_at.tzinfo
            else row.expires_at
        )
        if (
            snapshot["token_hash"] != row.token_hash
            or snapshot["password_hash"] != row.password_hash
            or (datetime.fromisoformat(snapshot["expires_at"]) if snapshot["expires_at"] else None)
            != expires
            or any(
                enabled and not snapshot["permissions"][key]
                for key, enabled in row.permissions.items()
            )
        ):
            raise HTTPException(503, "Integridade do resultado indisponível")
        snapshot["result"]["permissions"] = row.permissions
        if not row.permissions.get("graphs"):
            snapshot["result"]["series"] = []
        return snapshot

    def authorized(payload, request, db, permission=None):
        limit(request, db)
        row = db.get(PublishedResult, hashlib.sha256(payload.token.encode()).hexdigest())
        if row is None or row.revoked_at:
            raise HTTPException(404, "Compartilhamento indisponível")
        snapshot = verified_snapshot(row)
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.public_origin],
        allow_methods=["POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )
    app.add_middleware(BoundedBody)
    return app
