from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_debug: bool = False

    database_url: str = ""

    binance_spot_base_url: str = "https://api.binance.com"
    binance_futures_base_url: str = "https://fapi.binance.com"
    binance_http_timeout_seconds: float = Field(default=10.0, gt=0)

    import_max_rows: int = Field(default=1000, gt=0, le=50_000)

    log_level: str = "INFO"
    project_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[2])

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("app_host")
    @classmethod
    def localhost_only_by_default(cls, value: str) -> str:
        if not value.strip():
            return "127.0.0.1"
        return value.strip()

    @field_validator("binance_spot_base_url", "binance_futures_base_url")
    @classmethod
    def trim_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper().strip()

    @property
    def migrations_dir(self) -> Path:
        return self.project_root / "migrations"

    @property
    def masked_database_url(self) -> str:
        if not self.database_url:
            return ""
        parsed = urlsplit(self.database_url)
        if not parsed.netloc:
            return self.database_url
        username = parsed.username or ""
        hostname = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        auth = f"{username}:***@" if username else ""
        return urlunsplit((parsed.scheme, f"{auth}{hostname}{port}", parsed.path, "", ""))


@lru_cache
def get_settings() -> Settings:
    return Settings()

