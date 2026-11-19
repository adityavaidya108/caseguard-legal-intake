from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gateway_api_key: SecretStr
    anthropic_api_key: SecretStr
    anthropic_model: str
    hubspot_token: SecretStr
    supabase_url: str
    supabase_key: SecretStr
    vault_ttl_minutes: int = 30
    max_upload_mb: int = 10
    max_pdf_pages: int = 10
    backend_url: str = "http://localhost:8000"

    @field_validator("gateway_api_key")
    @classmethod
    def gateway_api_key_must_not_be_empty(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("gateway_api_key must not be empty")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
