from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "L'Oreal AI Service Intelligence"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_reload: bool = False
    data_dir: Path = Path("data")
    mongodb_uri: str = "mongodb://127.0.0.1:27017"
    mongodb_database: str = "loreal_ai_service_intelligence"
    mongodb_timeout_ms: int = 3000
    rule_version: str = "risk-rules-v1"
    knowledge_version: str = "demo-knowledge-v1"
    schema_version: str = "1.0"
    handoff_eta_minutes: int = 30
    intent_minimum_confidence: float = 0.7
    mock_api_enabled: bool = True
    llm_enabled: bool = False
    llm_api_key: Optional[SecretStr] = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = ""
    llm_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    llm_retry_limit: int = Field(default=1, ge=0, le=3)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    env_file = os.getenv("APP_CONFIG_FILE", ".env")
    return Settings(_env_file=env_file)  # type: ignore[call-arg]
