import time
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.security import decode_access_token
from app.models.entities import User

bearer = HTTPBearer(auto_error=False)


def validate_websocket_access(token: str) -> int:
    """Validate current access in a short-lived session, outside the event loop."""
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
        expires_at = int(payload["exp"])
        if not 0 < user_id <= 2**63 - 1:
            raise ValueError("Invalid user id")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(status_code=401, detail="Sessão inválida") from exc
    try:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            if not user or not user.active or user.role not in {"admin", "operator", "viewer"}:
                raise HTTPException(status_code=401, detail="Usuário inativo")
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Autorização indisponível") from exc
    if time.time() >= expires_at:
        raise HTTPException(status_code=401, detail="Sessão inválida")
    return expires_at


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticação necessária"
        )
    payload = decode_access_token(credentials.credentials)
    user = db.get(User, int(payload["sub"]))
    if not user or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário inativo")
    if user.role == "viewer":
        path = request.url.path.removeprefix("/api/v1")
        report_read = request.method == "POST" and path.startswith("/reports/period/")
        operational_read = (
            path.startswith(("/hardware/", "/simulator/", "/support/"))
            or path in {"/device-ports", "/diagnostics", "/acquisition/combined-status"}
            or path.endswith(("/acquisition-diagnostics", "/diagnostic-export", "/shares"))
        )
        if operational_read or (request.method not in {"GET", "HEAD"} and not report_read):
            raise HTTPException(status_code=403, detail="Perfil visualizador: somente consulta")
    if context := getattr(request.state, "support_context", None):
        context["user_id"] = user.id
    return user


def require_roles(*roles: str) -> Callable:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Permissão insuficiente"
            )
        return user

    return dependency
