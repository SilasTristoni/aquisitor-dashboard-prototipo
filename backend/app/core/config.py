from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.release import release_configuration


class Settings(BaseSettings):
    app_name: str = "ThermoPower Monitor API"
    app_version: str = release_configuration.version
    environment: str = "development"
    debug: bool = False
    database_url: str = "sqlite:///./thermopower.db"
    jwt_secret: str = "change-this-development-secret-before-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    demo_admin_email: str = release_configuration.homologation_email
    demo_admin_password: str = release_configuration.homologation_password
    login_prefill_enabled: bool = False
    measurement_batch_size: int = 25
    websocket_queue_size: int = 100
    login_attempts_per_minute: int = 8
    max_upload_bytes: int = 25 * 1024 * 1024
    max_report_period_days: int = 366
    report_preview_max_points: int = 2500
    report_energy_max_gap_seconds: float = 60.0
    report_output_directory: str = "./reports"
    frontend_dist: str | None = None
    virtual_lab_enabled: bool = False
    virtual_lab_mode: bool = False
    app_data_dir: str | None = None
    log_file: str | None = None

    @property
    def lab_api_enabled(self) -> bool:
        return self.virtual_lab_enabled or self.virtual_lab_mode or self.environment in {
            "development",
            "test",
        }

    model_config = SettingsConfigDict(env_file=".env", env_prefix="THERMOPOWER_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
