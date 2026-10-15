from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.version import APPLICATION_VERSION


class Settings(BaseSettings):
    app_name: str = "ThermoPower Monitor API"
    app_version: str = APPLICATION_VERSION
    environment: str = "development"
    debug: bool = False
    database_url: str = "sqlite:///./thermopower.db"
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    demo_admin_email: str = "admin@demo.thermopower.com"
    demo_admin_password: str = ""
    initial_admin_name: str = "Administrador local"
    at4532_trigger_interval_seconds: float = Field(default=5.0, ge=5.0, allow_inf_nan=False)
    measurement_batch_size: int = 25
    websocket_queue_size: int = 100
    login_attempts_per_minute: int = 8
    max_upload_bytes: int = 25 * 1024 * 1024
    max_report_period_days: int = 366
    report_preview_max_points: int = 2500
    report_energy_max_gap_seconds: float = 60.0
    report_output_directory: str = "./reports"
    frontend_dist: str | None = None

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        if len(value.encode()) < 32 or value in {
            "change-this-development-secret-before-production",
            "replace-this-before-any-network-exposure",
            "gere-uma-chave-aleatoria-com-pelo-menos-32-bytes",
        }:
            raise ValueError(
                "Configure THERMOPOWER_JWT_SECRET com uma chave aleatória de pelo menos 32 bytes"
            )
        return value

    model_config = SettingsConfigDict(env_file=".env", env_prefix="THERMOPOWER_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
