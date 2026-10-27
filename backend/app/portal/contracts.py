import base64
import hashlib
import json
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.services.share_policy import SharePermissions

MAX_SNAPSHOT_BYTES = 25 * 1024 * 1024


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, le=2147483647)
    permissions: SharePermissions


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
        def validate_tree(value, depth=0):
            if depth > 24:
                raise ValueError("Estrutura de resultado inválida")
            if isinstance(value, dict):
                if set(value) & {
                    "device_id",
                    "session_id",
                    "user_id",
                    "raw_payload",
                    "original_values",
                    "original_units",
                    "source_quality",
                    "created_by",
                    "selected_by",
                    "creator_name",
                    "password",
                    "credential",
                    "serial_port",
                }:
                    raise ValueError("Dados internos não autorizados")
                for item in value.values():
                    validate_tree(item, depth + 1)
            elif isinstance(value, list):
                for item in value:
                    validate_tree(item, depth + 1)

        validate_tree(self.result)
        # Optional extension inside a v1 series: old snapshots remain valid.
        from pydantic import TypeAdapter

        clock = TypeAdapter(AwareDatetime)
        for stream in self.result.get("series", []):
            intervals = stream.get("availability", [])
            if not isinstance(intervals, list) or len(intervals) > 10000:
                raise ValueError("Intervalos de disponibilidade inválidos")
            for item in intervals:
                if (
                    not isinstance(item, dict)
                    or set(item)
                    != {"start", "confirmed_until", "end", "end_reason", "source", "evidence"}
                    or item["source"] != "electrical"
                    or item["evidence"] != "backend_observed_v1"
                ):
                    raise ValueError("Evidência de disponibilidade inválida")
                start, until = (
                    clock.validate_python(item["start"]),
                    clock.validate_python(item["confirmed_until"]),
                )
                finish = clock.validate_python(item["end"]) if item["end"] else None
                if until < start or (finish and not start <= finish <= until):
                    raise ValueError("Intervalo de disponibilidade invertido")
                if item["end_reason"] not in {
                    None,
                    "reading_resumed",
                    "paused",
                    "observation_ended",
                }:
                    raise ValueError("Fim de disponibilidade inválido")
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
            set(self.result) - {"company_identity"} != allowed
            or self.result["permissions"] != self.permissions.model_dump()
        ):
            raise ValueError("Snapshot inválido")
        if "company_identity" in self.result:
            identity = self.result["company_identity"]
            if not isinstance(identity, dict) or set(identity) != {
                "identity_id",
                "company_name",
                "laboratory",
                "logo",
            }:
                raise ValueError("Identidade corporativa inválida")
            from uuid import UUID

            if identity["identity_id"] is not None:
                if not isinstance(identity["identity_id"], str):
                    raise ValueError("Invalid identity ID")
                UUID(identity["identity_id"])
            for key in ("company_name", "laboratory"):
                if not isinstance(identity[key], str) or len(identity[key]) > 120:
                    raise ValueError("Identidade corporativa inválida")
            if identity["logo"] is not None:
                import io

                from PIL import Image

                logo = identity["logo"]
                if not isinstance(logo, str) or not logo.startswith("data:image/png;base64,"):
                    raise ValueError("Logotipo inválido")
                if len(logo) > 1400000:
                    raise ValueError("Logotipo excede o limite")
                raw = base64.b64decode(logo.split(",", 1)[1], validate=True)
                try:
                    with Image.open(io.BytesIO(raw)) as image:
                        if (
                            image.format != "PNG"
                            or not (16 <= image.width <= 2048 and 16 <= image.height <= 1024)
                            or getattr(image, "n_frames", 1) != 1
                        ):
                            raise ValueError("Logotipo inválido")
                        image.verify()
                except (OSError, Image.DecompressionBombError) as exc:
                    raise ValueError("Invalid logo") from exc
        if not self.permissions.graphs and self.result["series"]:
            raise ValueError("Gráficos não autorizados")
        if self.result["status"] != "finished" or self.result["official"] is not True:
            raise ValueError("Resultado não finalizado")
        metadata = self.result["metadata"]
        if not isinstance(metadata, dict) or set(metadata) - {
            "product",
            "model",
            "sample",
            "code",
            "nominal_voltage",
            "setpoint",
        }:
            raise ValueError("Metadados não autorizados")
        channels = self.result["selected_channels"]
        if (
            not isinstance(channels, list)
            or len(channels) > 32
            or any(type(channel) is not int or not 1 <= channel <= 32 for channel in channels)
            or len(set(channels)) != len(channels)
        ):
            raise ValueError("Seleção de canais inválida")
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
