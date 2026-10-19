import base64
import hashlib
import json
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.services.share_policy import SharePermissions

MAX_SNAPSHOT_BYTES = 25 * 1024 * 1024


class SnapshotDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ResultSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    created_at: AwareDatetime
    token_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    password_hash: str | None = Field(default=None, pattern=r"^\$2[aby]\$12\$[./A-Za-z0-9]{53}$")
    expires_at: AwareDatetime | None = None
    permissions: SharePermissions
    result: dict
    documents: dict[Literal["pdf", "xlsx", "csv"], SnapshotDocument]

    @model_validator(mode="after")
    def validate_result(self):
        allowed = {
            "name",
            "metadata",
            "status",
            "official",
            "analysis_label",
            "permissions",
            "period",
            "statistics",
            "series",
            "selected_channels",
            "channel_labels",
            "annotations",
        }
        if (
            set(self.result) != allowed
            or self.result["permissions"] != self.permissions.model_dump()
        ):
            raise ValueError("Snapshot inválido")
        if not self.permissions.graphs and self.result["series"]:
            raise ValueError("Gráficos não autorizados")
        for kind, document in self.documents.items():
            content = base64.b64decode(document.content, validate=True)
            if (
                not getattr(self.permissions, kind)
                or hashlib.sha256(content).hexdigest() != document.sha256
            ):
                raise ValueError("Documento não autorizado ou corrompido")
        if set(self.documents) != {
            kind for kind in ("pdf", "xlsx", "csv") if getattr(self.permissions, kind)
        }:
            raise ValueError("Documentos incompletos")
        return self


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
