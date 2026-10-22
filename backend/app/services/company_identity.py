"""Installation-owned identity, embedded in authorized snapshots; no remote image URLs."""

import base64
import io
import warnings
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

MAX_LOGO_BYTES = 1024 * 1024


class CompanyIdentity(Base):
    __tablename__ = "company_identity"
    id: Mapped[int] = mapped_column(primary_key=True)
    identity_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()))
    company_name: Mapped[str] = mapped_column(String(120), default="")
    laboratory: Mapped[str] = mapped_column(String(120), default="")
    logo: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


def normalize_logo(raw: bytes) -> bytes:
    if not raw or len(raw) > MAX_LOGO_BYTES:
        raise ValueError("O logotipo deve ter até 1 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {"PNG", "JPEG"} or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Utilize PNG ou JPEG estático.")
                width, height = image.size
                if not (16 <= width <= 2048 and 16 <= height <= 1024):
                    raise ValueError("Dimensões permitidas: 16 a 2048 px por 16 a 1024 px.")
                image.load()
                output = io.BytesIO()
                image.convert("RGBA").save(output, format="PNG")
                result = output.getvalue()
                if len(result) > MAX_LOGO_BYTES:
                    raise ValueError("Imagem normalizada excede 1 MB.")
                return result
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("Arquivo de imagem inválido.") from exc


def identity_data(db):
    row = db.get(CompanyIdentity, 1)
    if not row:
        return {"identity_id": None, "company_name": "", "laboratory": "", "logo": None}
    return {
        "identity_id": row.identity_id,
        "company_name": row.company_name,
        "laboratory": row.laboratory,
        "logo": "data:image/png;base64," + base64.b64encode(row.logo).decode()
        if row.logo
        else None,
    }
