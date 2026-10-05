"""Application configuration loaded from environment variables.

Defaults are suitable for local development. Deployment secrets and the database
URL must be supplied by the hosting platform.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings shared by the API, database, and security modules."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "SLSEA Solar Generation API"
    app_env: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./solar_api.db"
    database_echo: bool = False

    jwt_secret: SecretStr = SecretStr(
        "replace-with-a-long-random-secret-before-deployment"
    )
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = "slsea-solar-api"
    jwt_audience: str = "slsea-api-clients"
    access_token_minutes: int = Field(default=60, ge=1, le=24 * 60)

    # OWASP's current PBKDF2-HMAC-SHA256 work factor. Tests may override it
    # through the environment when they need faster fixture creation.
    pbkdf2_iterations: int = Field(default=600_000, ge=100_000, le=10_000_000)
    cors_origins: list[str] = Field(default_factory=list)

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        """Keep route prefixes predictable and avoid a trailing slash."""

        if not value.startswith("/"):
            raise ValueError("API_PREFIX must start with '/'")
        if value != "/" and value.endswith("/"):
            value = value.rstrip("/")
        return value

    @model_validator(mode="after")
    def reject_development_secret_in_production(self) -> "Settings":
        """Prevent an accidental deployment with the documented sample key."""

        secret = self.jwt_secret.get_secret_value()
        if self.app_env == "production" and secret.startswith("replace-with-"):
            raise ValueError("JWT_SECRET must be changed for production")
        if len(secret) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-by-convention settings object per process."""

    return Settings()
