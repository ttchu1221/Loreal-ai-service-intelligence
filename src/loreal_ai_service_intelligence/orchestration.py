from __future__ import annotations

import re
from datetime import timedelta
from uuid import uuid4

from loreal_ai_service_intelligence.config import Settings
from loreal_ai_service_intelligence.intent import (
    FallbackIntentProvider,
    IntentProvider,
    RuleBasedIntentProvider,
)
from loreal_ai_service_intelligence.knowledge import InMemoryKnowledgeBase, KnowledgeProvider
from loreal_ai_service_intelligence.models import (
    AgentConversationView,
    ConsumerResponse,
    ConversationRequest,
    ConversationState,
    EmpathyCard,
    EventSummary,
    HandoffPackage,
    Intent,
    RiskLevel,
    StoredConversation,
)
from loreal_ai_service_intelligence.repository import StorageRepository, utc_now

HIGH_RISK_TERMS = ("刺痛", "泛红", "红肿", "呼吸困难", "灼痛", "过敏")
NEGATION_PREFIXES = ("没有", "没", "不", "未", "无")
HYPOTHETICAL_PREFIXES = ("会不会", "是否会", "会否", "怕", "担心")
RESOLVED_TERMS = ("已经好了", "已恢复", "现在好了", "已消退")


class ConversationOrchestrator:
    def __init__(
        self,
        repository: StorageRepository,
        settings: Settings,
        intent_provider: IntentProvider | None = None,
        knowledge_provider: KnowledgeProvider | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.knowledge = knowledge_provider or InMemoryKnowledgeBase(settings.knowledge_version)
        self.intent_provider = FallbackIntentProvider(
            intent_provider,
            RuleBasedIntentProvider(),
            settings.intent_minimum_confidence,
        )

    def start(self, request: ConversationRequest) -> ConsumerResponse:
        conversation_id = f"conv_{uuid4().hex}"
        return self._process(conversation_id, request, None)

    def continue_conversation(
        self, conversation_id: str, request: ConversationRequest
    ) -> ConsumerResponse | None:
        existing = self.repository.get_conversation(conversation_id)
        if existing is None:
            return None
        return self._process(conversation_id, request, existing)

    def _process(
        self,
        conversation_id: str,
        request: ConversationRequest,
        existing: StoredConversation | None,
    ) -> ConsumerResponse:
        now = utc_now()
        messages = [*existing.messages, request.message] if existing else [request.message]
        card = self._build_card(conversation_id, request, existing)
        result_id = f"result_{uuid4().hex}"
        response_text, actions = self._consumer_copy(card)
        stored = StoredConversation(
            conversation_id=conversation_id,
            state=card.next_state,
            messages=messages,
            empathy_card=card,
            last_result_id=result_id,
            unresolved_attempts=(existing.unresolved_attempts if existing else 0)
            + int(card.next_state != ConversationState.RESOLVE),
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self.repository.save_conversation(stored)
        self.repository.add_audit(
            conversation_id,
            "state_transition",
            {
                "from_state": existing.state.value if existing else None,
                "to_state": card.next_state.value,
                "trigger": card.risk_reasons or card.missing_information or ["knowledge_available"],
                "rule_version": self.settings.rule_version,
                "knowledge_version": self.settings.knowledge_version,
                "result_id": result_id,
            },
        )
        return ConsumerResponse(
            conversation_id=conversation_id,
            result_id=result_id,
            state=card.next_state,
            message=response_text,
            evidence=card.knowledge_refs if card.next_state == ConversationState.RESOLVE else [],
            available_actions=actions,
        )

    def _build_card(
        self,
        conversation_id: str,
        request: ConversationRequest,
        existing: StoredConversation | None,
    ) -> EmpathyCard:
        text = request.message
        risk_terms = self._active_risk_terms(text)
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

        if request.attachments:
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
            missing: list[str] = []
            refs = []
            intent = Intent.COMPLAINT
            intent_confidence = 1.0
            intent_source = "safety_rules"
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
            refs = self.knowledge.search(text, intent)
            if not refs and existing and existing.empathy_card.intent == Intent.PURCHASE:
                context_query = f"{existing.empathy_card.surface_issue} {text}"
                refs = self.knowledge.search(context_query, Intent.PURCHASE)
            missing = []
            risk = RiskLevel.LOW
            state = ConversationState.RESOLVE if refs else ConversationState.HANDOFF

        return EmpathyCard(
            conversation_id=conversation_id,
            surface_issue=request.message,
            intent=intent,
            intent_confidence=intent_confidence,
            intent_source=intent_source,
            emotion="concerned" if risk_terms else None,
            scenario=self._scenario(intent),
            entities=entities,
            confirmed_facts=confirmed,
            inferences=[],
            missing_information=missing,
            risk_level=risk,
            risk_reasons=[f"命中高风险症状词：{term}" for term in risk_terms],
            knowledge_refs=refs,
            next_state=state,
            schema_version=self.settings.schema_version,
        )

    @staticmethod
    def _consumer_copy(card: EmpathyCard) -> tuple[str, list[str]]:
        if card.next_state == ConversationState.BLOCK:
            return (
                "你提到的情况需要谨慎处理。请先停止继续使用相关产品，避免自行叠加其他刺激性产品；如症状明显、持续或加重，请及时寻求专业医疗帮助。是否同意我将现有信息提交给人工客服跟进？",
                ["confirm_handoff", "decline_handoff"],
            )
        if card.next_state == ConversationState.ASK:
            return "为了更准确地给出建议，请告诉我你的肤色冷暖调，或你偏好的妆效。", ["reply"]
        if card.next_state == ConversationState.HANDOFF:
            if "可读取的附件内容" in card.missing_information:
                message = (
                    "我目前无法读取你上传的附件内容，因此不会根据文件名猜测。"
                    "是否同意转人工客服查看并跟进？"
                )
                return message, [
                    "confirm_handoff",
                    "decline_handoff",
                ]
            return "当前没有足够的已审核依据来安全回答。是否同意我将现有信息提交给人工客服跟进？", [
                "confirm_handoff",
                "decline_handoff",
            ]
        labels = {
            Intent.USAGE: "使用指引",
            Intent.PURCHASE: "选购指引",
            Intent.CONSULT: "产品指引",
        }
        label = labels.get(card.intent, "服务指引")
        evidence_text = " ".join(ref.excerpt for ref in card.knowledge_refs)
        return f"根据已审核的{label}：{evidence_text}", [
            "feedback",
            "new_question",
        ]

    @staticmethod
    def _active_risk_terms(text: str) -> list[str]:
        resolved_history = any(term in text for term in RESOLVED_TERMS)
        renewed_symptom = any(term in text for term in ("但是", "但", "不过", "又", "仍", "现在还"))
        if resolved_history and not renewed_symptom:
            return []
        found: list[str] = []
        for term in HIGH_RISK_TERMS:
            index = text.find(term)
            if index < 0:
                continue
            prefix = text[max(0, index - 4) : index]
            non_assertive = (*NEGATION_PREFIXES, *HYPOTHETICAL_PREFIXES)
            if any(prefix.endswith(marker) for marker in non_assertive):
                continue
            context = text[max(0, index - 12) : index]
            third_party = re.search(
                r"(?:朋友|同事|家人)(?:说|有|出现|使用后|用了以后)?[^，。！？]*$"
                r"|(?:^|[，。！？])(?:他|她)(?:说|有|出现|使用后|用了以后)[^，。！？]*$",
                context,
            )
            if third_party:
                continue
            found.append(term)
        return found

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
        unknown = ("不知道", "不清楚", "不会判断")
        has_details = any(term in text for term in informative)
        explicitly_unknown = any(term in text for term in unknown)
        return not has_details or explicitly_unknown

    @staticmethod
    def _scenario(intent: Intent) -> str:
        return {
            Intent.AFTER_SALES: "after_sales_service",
            Intent.PURCHASE: "product_selection",
            Intent.USAGE: "product_usage",
            Intent.COMPLAINT: "customer_complaint",
        }.get(intent, "product_consultation")

    def create_handoff(self, conversation_id: str, idempotency_key: str) -> EventSummary | None:
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None:
            return None
        eta = utc_now() + timedelta(minutes=self.settings.handoff_eta_minutes)
        event = self.repository.create_event(
            {
                "event_id": f"evt_{uuid4().hex}",
                "conversation_id": conversation_id,
                "status": "waiting_for_agent",
                "priority": 100 if conversation.empathy_card.risk_level == RiskLevel.HIGH else 50,
                "reason": "; ".join(conversation.empathy_card.risk_reasons)
                or "依据不足或用户请求人工",
                "estimated_response_at": eta.isoformat(),
            },
            idempotency_key,
        )
        conversation.state = ConversationState.HANDOFF
        conversation.empathy_card.next_state = ConversationState.HANDOFF
        conversation.updated_at = utc_now()
        self.repository.save_conversation(conversation)
        self.repository.add_audit(
            conversation_id,
            "handoff_created",
            {"event_id": event["event_id"], "rule_version": self.settings.rule_version},
        )
        return self._event_summary(event)

    @staticmethod
    def _event_summary(event: dict[str, object]) -> EventSummary:
        return EventSummary(
            event_id=str(event["event_id"]),
            conversation_id=str(event["conversation_id"]),
            status=str(event["status"]),
            priority=int(event["priority"]),
            reason=str(event["reason"]),
            created_at=str(event["created_at"]),
            estimated_response_at=str(event["estimated_response_at"]),
        )

    def agent_view(self, conversation_id: str) -> AgentConversationView | None:
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None:
            return None
        event_row = self.repository.get_event_for_conversation(conversation_id)
        event = self._event_summary(event_row) if event_row else None
        actions = self.repository.get_service_actions(event.event_id) if event else []
        card = conversation.empathy_card
        package = HandoffPackage(
            conversation_id=conversation_id,
            original_messages=conversation.messages,
            summary=card.surface_issue,
            confirmed_facts=card.confirmed_facts,
            inferences=card.inferences,
            missing_information=card.missing_information,
            risk_level=card.risk_level,
            risk_reasons=card.risk_reasons,
            knowledge_refs=card.knowledge_refs,
            executed_actions=actions,
            suggested_next_step="优先核实症状与使用情况，并按授权范围跟进"
            if card.risk_level == RiskLevel.HIGH
            else "核实诉求并补充可靠依据",
            event=event,
            current_state=conversation.state,
            schema_version=self.settings.schema_version,
            rule_version=self.settings.rule_version,
            knowledge_version=self.settings.knowledge_version,
        )
        return AgentConversationView(
            handoff_package=package,
            empathy_card=card,
            audit_trail=self.repository.get_audit(conversation_id),
        )
