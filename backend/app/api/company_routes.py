from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.entities import User
from app.services.company_identity import (
    MAX_LOGO_BYTES,
    CompanyIdentity,
    identity_data,
    normalize_logo,
)

router = APIRouter(prefix="/api/v1/company-identity")
Db = Annotated[Session, Depends(get_db)]
Admin = Annotated[User, Depends(require_roles("admin"))]


class IdentityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    company_name: str = Field(max_length=120)
    laboratory: str = Field(default="", max_length=120)


def current_row(db):
    row = db.get(CompanyIdentity, 1)
    if row is None:
        row = CompanyIdentity(id=1)
        db.add(row)
    return row


@router.get("")
def read_identity(db: Db, response: Response, _: Annotated[User, Depends(get_current_user)]):
    response.headers["Cache-Control"] = "no-store"
    return identity_data(db)


@router.put("")
def update_identity(payload: IdentityUpdate, db: Db, _: Admin):
    row = current_row(db)
    row.company_name, row.laboratory = payload.company_name, payload.laboratory
    db.commit()
    return identity_data(db)


@router.put("/logo")
async def upload_logo(request: Request, db: Db, _: Admin):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_LOGO_BYTES:
            raise HTTPException(413, "O logotipo deve ter até 1 MB.")
    try:
        logo = normalize_logo(bytes(raw))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    current_row(db).logo = logo
    db.commit()
    return identity_data(db)


@router.delete("/logo")
def delete_logo(db: Db, _: Admin):
    current_row(db).logo = None
    db.commit()
    return identity_data(db)
