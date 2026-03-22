"""Application configuration loaded from .env via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    secret_key: str
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
    # Disable Swagger UI and ReDoc in production (set DOCS_ENABLED=false)
    docs_enabled: bool = True


settings = Settings()  # type: ignore[call-arg]
