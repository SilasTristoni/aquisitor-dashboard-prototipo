import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.portal_configuration import validate_origin


def database_url(value: str) -> str:
    # Render supplies postgresql://; use the explicitly installed psycopg 3 driver.
    return re.sub(r"^postgres(?:ql)?://", "postgresql+psycopg://", value)


class Installation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    credential_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    enabled: bool = True


class PortalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="THERMOPOWER_PORTAL_", extra="ignore")
    database_url: str
    installations: dict[str, Installation]
    integrity_key: str = Field(min_length=32, repr=False)
    public_origin: str

    @field_validator("database_url")
    @classmethod
    def normalize_database(cls, value):
        return database_url(value)

    @field_validator("public_origin")
    @classmethod
    def https_origin(cls, value):
        return validate_origin(value)

    @model_validator(mode="after")
    def installation_ids(self):
        if not self.installations or any(
            not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", key) for key in self.installations
        ):
            raise ValueError("Configure instalações válidas")
        return self
