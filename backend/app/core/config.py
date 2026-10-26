"""Configuração da aplicação, lida exclusivamente de variáveis de ambiente."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DDI_", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "Data Docs Intelligence"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://ddi:ddi@localhost:5442/ddi"

    # Segurança
    secret_key: str = Field(default="dev-insecure-change-me-0123456789abcdef", min_length=32)
    access_token_ttl_minutes: int = 480
    cookie_secure: bool = False
    allow_signup: bool = True
    cors_origins: list[str] = []
    login_max_attempts: int = 8
    login_lockout_seconds: int = 300

    # Armazenamento
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_root: str = "./var/storage"
    s3_bucket: str = ""
    s3_endpoint_url: str | None = None
    s3_region: str | None = None

    # Limites de arquivos
    max_upload_bytes: int = 50 * 1024 * 1024
    max_xlsx_uncompressed_bytes: int = 400 * 1024 * 1024
    max_records_per_file: int = 1_000_000
    file_retention_days: int = 180
    preview_rows: int = 20
    inspection_sample_rows: int = 1000
    mask_sensitive_previews: bool = True

    # Processamento
    job_inline_max_bytes: int = 2 * 1024 * 1024
    job_max_attempts: int = 3
    job_timeout_seconds: int = 900
    job_lock_timeout_seconds: int = 1800
    max_concurrent_jobs_per_org: int = 5
    max_findings_per_rule: int = 5000
    max_comparison_rows_stored: int = 20000
    worker_poll_seconds: float = 2.0

    # IA (opcional). Sem chave, o sistema usa apenas heurísticas determinísticas.
    ai_provider: Literal["none", "anthropic"] = "none"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    ai_server_fallback: bool = True
    ai_timeout_seconds: float = 30.0
    ai_send_sample_values: bool = False
    mapping_confirmation_threshold: float = 0.85

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production and settings.secret_key.startswith("dev-insecure"):
        raise RuntimeError("DDI_SECRET_KEY precisa ser definido em produção")
    return settings
