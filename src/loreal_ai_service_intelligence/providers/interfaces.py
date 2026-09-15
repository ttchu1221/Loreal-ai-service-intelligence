"""3、4 号共同冻结的 AI provider contracts。"""

from __future__ import annotations

from typing import Protocol

from loreal_ai_service_intelligence.domain.models import (
    ConversationRequest,
    EmpathyCard,
    Intent,
    IntentResult,
    KnowledgeReference,
    StoredConversation,
)


class IntentProvider(Protocol):
    def classify(self, text: str) -> IntentResult: ...


class ResponseProvider(Protocol):
    """在已确定的业务决策边界内生成消费者可见回复。"""

    def generate(
        self,
        request: ConversationRequest,
        card: EmpathyCard,
        existing: StoredConversation | None,
    ) -> str: ...


class KnowledgeProvider(Protocol):
    def search(self, query: str, intent: Intent, limit: int = 3) -> list[KnowledgeReference]: ...


class DecisionPolicy(Protocol):
    """只生成可验证决策，不执行 persistence、建单或其他副作用。"""

    def decide(
        self,
        conversation_id: str,
        request: ConversationRequest,
        existing: StoredConversation | None,
    ) -> EmpathyCard: ...
