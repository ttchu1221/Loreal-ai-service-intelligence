import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "L'Oreal AI Service Intelligence"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_reload: bool = False
    data_dir: Path = Path("data")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    env_file = os.getenv("APP_CONFIG_FILE", ".env")
    return Settings(_env_file=env_file)  # type: ignore[call-arg]
