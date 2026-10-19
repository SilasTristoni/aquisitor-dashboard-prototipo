"""Authorization shared by local results and the isolated portal; no runtime imports."""

from datetime import UTC, datetime

import bcrypt
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class ShareAccess(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=40, max_length=100)
    password: str | None = Field(default=None, max_length=72)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value):
        if value and len(value.encode()) > 72:
            raise ValueError("A senha deve ter até 72 bytes")
        return value


def enforce_share_access(row, payload: ShareAccess, permission: str | None = None):
    expires = row.expires_at if row else None
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if not row or row.revoked_at or (expires and expires <= datetime.now(UTC)):
        raise HTTPException(404, "Compartilhamento indisponível")
    if row.password_hash:
        try:
            valid = bcrypt.checkpw((payload.password or "").encode(), row.password_hash.encode())
        except ValueError:
            valid = False
        if not valid:
            raise HTTPException(401, "Informe a senha correta do compartilhamento")
    if permission and not row.permissions.get(permission, False):
        raise HTTPException(403, "Download não autorizado neste compartilhamento")
