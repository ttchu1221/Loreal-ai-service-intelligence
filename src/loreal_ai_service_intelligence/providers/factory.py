"""Runtime provider composition without vendor logic in routes or services."""

from __future__ import annotations

from loreal_ai_service_intelligence.config import Settings
from loreal_ai_service_intelligence.providers.interfaces import IntentProvider, ResponseProvider
from loreal_ai_service_intelligence.providers.openai_compatible import (
    OpenAICompatibleIntentProvider,
)


def create_intent_provider(settings: Settings) -> IntentProvider | None:
    if not settings.llm_enabled:
        return None
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
    return OpenAICompatibleIntentProvider(
        api_key=api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        retry_limit=settings.llm_retry_limit,
    )


def create_response_provider(settings: Settings) -> ResponseProvider | None:
    """使用与 intent 相同的 runtime 配置创建上下文回复生成器。"""
    return create_intent_provider(settings)
