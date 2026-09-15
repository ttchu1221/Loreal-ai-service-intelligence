"""当前可离线回归的 DecisionPolicy 实现。"""

from __future__ import annotations

from loreal_ai_service_intelligence.config import Settings
from loreal_ai_service_intelligence.domain.models import (
    ConversationRequest,
    ConversationState,
    EmpathyCard,
    Intent,
    ProductContext,
    RiskLevel,
    StoredConversation,
)
from loreal_ai_service_intelligence.providers.interfaces import (
    DecisionPolicy,
    IntentProvider,
    KnowledgeProvider,
)
from loreal_ai_service_intelligence.providers.safety import SafetyPolicy


class SafetyFirstDecisionPolicy:
    """在调用任何外部或候选策略前执行不可绕过的安全门。"""

    def __init__(
        self,
        delegate: DecisionPolicy,
        safety_policy: SafetyPolicy,
        schema_version: str,
    ) -> None:
        self.delegate = delegate
        self.safety = safety_policy
        self.schema_version = schema_version

    def decide(
        self,
        conversation_id: str,
        request: ConversationRequest,
        existing: StoredConversation | None,
    ) -> EmpathyCard:
        risk_terms = self.safety.active_risk_terms(request.message)
        if not risk_terms:
            return self.delegate.decide(conversation_id, request, existing)
        confirmed = list(
            dict.fromkeys(
                [*(existing.empathy_card.confirmed_facts if existing else []), request.message]
            )
        )
        entities = dict(existing.empathy_card.entities) if existing else {}
        if request.product:
            entities["product"] = request.product
        return EmpathyCard(
            conversation_id=conversation_id,
            surface_issue=request.message,
            intent=Intent.COMPLAINT,
            intent_confidence=1.0,
            intent_source="safety_rules",
            emotion="concerned",
            scenario="customer_complaint",
            case_revision=existing.case.current_revision if existing and existing.case else 1,
            product_context=ProductContext(product_name=request.product or entities.get("product")),
            entities=entities,
            confirmed_facts=confirmed,
            risk_level=RiskLevel.HIGH,
            risk_reasons=[f"命中高风险症状词：{term}" for term in risk_terms],
            next_state=ConversationState.BLOCK,
            schema_version=self.schema_version,
        )


class DeterministicDecisionPolicy:
    """冻结 Mock 行为；后续由 3 号候选实现替换，不包含任何业务副作用。"""

    def __init__(
        self,
        settings: Settings,
        intent_provider: IntentProvider,
        knowledge_provider: KnowledgeProvider,
        safety_policy: SafetyPolicy,
    ) -> None:
        self.settings = settings
        self.intent_provider = intent_provider
        self.knowledge = knowledge_provider
        self.safety = safety_policy

    def decide(
        self,
        conversation_id: str,
        request: ConversationRequest,
        existing: StoredConversation | None,
    ) -> EmpathyCard:
        text = request.message
        declined_handoff = self._declines_human_service(text)
        risk_terms = self.safety.active_risk_terms(text)
        confirmed = list(
            dict.fromkeys(
                [*(existing.empathy_card.confirmed_facts if existing else []), request.message]
            )
        )
        entities = dict(existing.empathy_card.entities) if existing else {}
        if request.product:
            entities["product"] = request.product
        if request.order_reference:
            entities["order_reference"] = request.order_reference

        if self._requests_human_service(text) and not declined_handoff:
            state = ConversationState.HANDOFF
            risk = RiskLevel.LOW
            missing = []
            refs = []
            intent = Intent.AFTER_SALES
            intent_confidence = 1.0
            intent_source = "user_handoff_rules"
        elif request.attachments:
            state = ConversationState.HANDOFF
            risk = RiskLevel.LOW
            missing = ["可读取的附件内容"]
            refs = []
            intent_result = self.intent_provider.classify(text)
            intent = intent_result.intent
            intent_confidence = intent_result.confidence
            intent_source = intent_result.source
        elif risk_terms:
            state = ConversationState.BLOCK
            risk = RiskLevel.HIGH
            missing = []
            refs = []
            intent = Intent.COMPLAINT
            intent_confidence = 1.0
            intent_source = "safety_rules"
        elif self._needs_pilling_details(text, existing):
            state = ConversationState.ASK
            risk = RiskLevel.LOW
            missing = ["搓泥发生步骤或已经尝试过的方法"]
            refs = []
            intent = Intent.USAGE
            intent_confidence = 1.0
            intent_source = "pilling_clarification_rules"
        elif self._needs_shade_details(text, existing):
            state = ConversationState.ASK
            risk = RiskLevel.LOW
            missing = ["肤色冷暖调或期望妆效"]
            refs = []
            intent = Intent.PURCHASE
            intent_confidence = 1.0
            intent_source = "clarification_rules"
        else:
            intent_result = self.intent_provider.classify(text)
            if (
                existing
                and intent_result.intent == Intent.CONSULT
                and intent_result.confidence < self.settings.intent_minimum_confidence
            ):
                intent = existing.empathy_card.intent
                intent_confidence = existing.empathy_card.intent_confidence
                intent_source = f"context:{existing.empathy_card.intent_source}"
            else:
                intent = intent_result.intent
                intent_confidence = intent_result.confidence
                intent_source = intent_result.source
            if self._is_pilling_context(text, existing) and existing:
                refs = self.knowledge.search(
                    f"{existing.case.original_statement} {text}", Intent.USAGE
                )
            else:
                refs = self.knowledge.search(text, intent)
            if not refs and existing and existing.empathy_card.intent == Intent.PURCHASE:
                refs = self.knowledge.search(
                    f"{existing.empathy_card.surface_issue} {text}", Intent.PURCHASE
                )
            missing = []
            risk = RiskLevel.LOW
            if refs and self._is_pilling_context(text, existing):
                state = ConversationState.GUIDE
            elif refs:
                state = ConversationState.RESOLVE
            elif declined_handoff:
                state = ConversationState.ASK
                missing = ["希望 AI 继续处理的具体问题"]
                intent_source = "user_decline_handoff_rules"
            else:
                state = ConversationState.HANDOFF

        return EmpathyCard(
            conversation_id=conversation_id,
            surface_issue=request.message,
            intent=intent,
            intent_confidence=intent_confidence,
            intent_source=intent_source,
            emotion="concerned" if risk_terms else None,
            scenario=self._scenario(intent),
            case_revision=existing.case.current_revision if existing and existing.case else 1,
            product_context=ProductContext(product_name=request.product or entities.get("product")),
            entities=entities,
            confirmed_facts=confirmed,
            missing_information=missing,
            risk_level=risk,
            risk_reasons=[f"命中高风险症状词：{term}" for term in risk_terms],
            knowledge_refs=refs,
            next_state=state,
            schema_version=self.settings.schema_version,
        )

    @staticmethod
    def _requests_human_service(text: str) -> bool:
        return any(
            term in text
            for term in ("转人工", "人工客服", "真人客服", "找客服", "联系客服", "人工服务")
        )

    @staticmethod
    def _declines_human_service(text: str) -> bool:
        return any(
            term in text
            for term in (
                "不转人工",
                "不要人工",
                "不需要人工",
                "不用人工",
                "先不找客服",
                "暂不转人工",
            )
        )

    @staticmethod
    def _is_pilling_context(text: str, existing: StoredConversation | None) -> bool:
        return any(term in text for term in ("搓泥", "起屑", "结块")) or bool(
            existing
            and any(term in existing.case.original_statement for term in ("搓泥", "起屑", "结块"))
        )

    def _needs_pilling_details(self, text: str, existing: StoredConversation | None) -> bool:
        if not self._is_pilling_context(text, existing) or existing is not None:
            return False
        detail_terms = ("防晒后", "护肤后", "妆前后", "试过", "减少", "等待", "发生在")
        return not any(term in text for term in detail_terms)

    @staticmethod
    def _needs_shade_details(text: str, existing: StoredConversation | None) -> bool:
        shade_context = "色号" in text or bool(
            existing and existing.empathy_card.intent == Intent.PURCHASE
        )
        if not shade_context:
            return False
        informative = (
            "冷调",
            "暖调",
            "中性调",
            "黄一白",
            "黄二白",
            "粉一白",
            "自然",
            "白皙",
            "遮瑕",
        )
        return not any(term in text for term in informative) or any(
            term in text for term in ("不知道", "不清楚", "不会判断")
        )

    @staticmethod
    def _scenario(intent: Intent) -> str:
        return {
            Intent.AFTER_SALES: "after_sales_service",
            Intent.PURCHASE: "product_selection",
            Intent.USAGE: "product_usage",
            Intent.COMPLAINT: "customer_complaint",
        }.get(intent, "product_consultation")
