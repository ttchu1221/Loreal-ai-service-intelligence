from __future__ import annotations

import logging
from typing import Optional

from loreal_ai_service_intelligence.domain.models import Intent, IntentResult
from loreal_ai_service_intelligence.providers.interfaces import IntentProvider

logger = logging.getLogger(__name__)


class RuleBasedIntentProvider:
    """Deterministic fallback that remains available without external services."""

    def classify(self, text: str) -> IntentResult:
        if any(term in text for term in ("订单", "退款", "退货", "换货", "售后")):
            return IntentResult(intent=Intent.AFTER_SALES, confidence=0.9, source="rules")
        if any(term in text for term in ("投诉", "骗人", "假货", "服务态度")):
            return IntentResult(intent=Intent.COMPLAINT, confidence=0.9, source="rules")
        if any(term in text for term in ("购买", "色号", "粉底", "试色", "适合买吗")):
            return IntentResult(intent=Intent.PURCHASE, confidence=0.85, source="rules")
        if any(term in text for term in ("使用", "怎么用", "第一次", "首次", "用法")):
            return IntentResult(intent=Intent.USAGE, confidence=0.9, source="rules")
        return IntentResult(intent=Intent.CONSULT, confidence=0.6, source="rules")


class FallbackIntentProvider:
    """Use a primary provider only when it returns a sufficiently confident result."""

    def __init__(
        self,
        primary: Optional[IntentProvider],
        fallback: IntentProvider,
        minimum_confidence: float,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.minimum_confidence = minimum_confidence

    def classify(self, text: str) -> IntentResult:
        if self.primary is not None:
            try:
                result = self.primary.classify(text)
                validated = IntentResult.model_validate(result)
                if validated.confidence >= self.minimum_confidence:
                    return validated
                logger.warning(
                    "intent_provider_fallback reason=low_confidence provider=%s",
                    type(self.primary).__name__,
                )
            except Exception as error:
                # Provider errors are intentionally contained at this trust boundary.
                logger.warning(
                    "intent_provider_fallback reason=provider_error provider=%s error_type=%s",
                    type(self.primary).__name__,
                    type(error).__name__,
                )
        return self.fallback.classify(text)
