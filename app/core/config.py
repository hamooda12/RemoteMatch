from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "RemoteMatch"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    database_url: str
    session_secret: str = Field(min_length=32)
    session_cookie_name: str = "remotematch_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 7

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
