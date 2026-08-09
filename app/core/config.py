from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "RemoteMatch"
    app_version: str = "0.1.0"
    environment: Literal[
        "development",
        "test",
        "production",
    ] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    database_url: str

    session_secret: str = Field(min_length=32)
    session_cookie_name: str = "remotematch_session"
    session_max_age_seconds: int = Field(
        default=60 * 60 * 24 * 7,
        ge=300,
        le=60 * 60 * 24 * 30,
    )
    session_cookie_same_site: Literal[
        "lax",
        "strict",
        "none",
    ] = "lax"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    allowed_hosts: str = "localhost,127.0.0.1,testserver"

    job_source_arbeitnow_enabled: bool = True
    job_source_greenhouse_enabled: bool = True
    job_source_himalayas_enabled: bool = True
    job_source_jobicy_enabled: bool = True
    job_source_remoteok_enabled: bool = True

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @model_validator(mode="after")
    def validate_security_settings(self) -> Self:
        origins = self.cors_origin_list
        hosts = self.allowed_host_list

        if not origins:
            raise ValueError(
                "At least one CORS origin is required",
            )

        if "*" in origins:
            raise ValueError(
                "Wildcard CORS origins cannot be used with authenticated requests",
            )

        if not hosts:
            raise ValueError(
                "At least one allowed host is required",
            )

        if self.session_cookie_same_site == "none" and not self.secure_cookies:
            raise ValueError(
                "SameSite=None requires secure production cookies",
            )

        if self.environment == "production":
            if self.debug:
                raise ValueError(
                    "Debug mode cannot be enabled in production",
                )

            if self.session_secret.startswith("replace_"):
                raise ValueError(
                    "A production session secret must be random",
                )

            if any(not origin.startswith("https://") for origin in origins):
                raise ValueError(
                    "Production CORS origins must use HTTPS",
                )

        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
