from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from loreal_ai_service_intelligence.config import Settings
from loreal_ai_service_intelligence.domain.models import (
    AgentAssistantBrief,
    AgentConversationView,
    AgentIntakeRequest,
    AgentIntakeResponse,
    AgentSourceContext,
    AttemptCreateRequest,
    AttemptRecord,
    AttemptUpdateRequest,
    CaseRecord,
    CaseRevision,
    CaseRevisionRequest,
    ConsumerResponse,
    ConsumerTicketView,
    ConversationRequest,
    ConversationState,
    ConversationTranscriptItem,
    EmpathyCard,
    EventSummary,
    HandoffPackage,
    Intent,
    RiskLevel,
    ServiceTimelineItem,
    StoredConversation,
    TicketRecord,
    TicketResultRequest,
)
from loreal_ai_service_intelligence.infrastructure.repository import StorageRepository, utc_now
from loreal_ai_service_intelligence.providers.intent import (
    FallbackIntentProvider,
    RuleBasedIntentProvider,
)
from loreal_ai_service_intelligence.providers.interfaces import (
    DecisionPolicy,
    IntentProvider,
    KnowledgeProvider,
    ResponseProvider,
)
from loreal_ai_service_intelligence.providers.knowledge import InMemoryKnowledgeBase
from loreal_ai_service_intelligence.providers.safety import RuleBasedSafetyPolicy
from loreal_ai_service_intelligence.services.decision_policy import (
    DeterministicDecisionPolicy,
    SafetyFirstDecisionPolicy,
)


class ConversationOrchestrator:
    def __init__(
        self,
        repository: StorageRepository,
        settings: Settings,
        intent_provider: IntentProvider | None = None,
        knowledge_provider: KnowledgeProvider | None = None,
        decision_policy: DecisionPolicy | None = None,
        response_provider: ResponseProvider | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        knowledge = knowledge_provider or InMemoryKnowledgeBase(settings.knowledge_version)
        intent = FallbackIntentProvider(
            intent_provider,
            RuleBasedIntentProvider(),
            settings.intent_minimum_confidence,
        )
        safety = RuleBasedSafetyPolicy()
        delegate = decision_policy or DeterministicDecisionPolicy(
            settings, intent, knowledge, safety
        )
        self.decision_policy = SafetyFirstDecisionPolicy(delegate, safety, settings.schema_version)
        self.response_provider = response_provider

    def start(self, request: ConversationRequest) -> ConsumerResponse:
        conversation_id = f"conv_{uuid4().hex}"
        return self._process(conversation_id, request, None)

    def start_agent_intake(self, intake: AgentIntakeRequest) -> AgentIntakeResponse:
        """Create an agent-owned service case from aggregated upstream context."""
        now = utc_now()
        conversation_id = f"conv_{uuid4().hex}"
        request = ConversationRequest(
            message=intake.current_message,
            product=intake.orders[0].product_name if intake.orders else None,
            order_reference=intake.orders[0].order_id if intake.orders else None,
        )
        card = EmpathyCard.model_validate(
            self.decision_policy.decide(conversation_id, request, None)
        )
        transcript = list(intake.transcript)
        if not transcript or transcript[-1].content != intake.current_message:
            transcript.append(
                ConversationTranscriptItem(
                    role="user", content=intake.current_message, created_at=now
                )
            )
        stored = StoredConversation(
            conversation_id=conversation_id,
            state=card.next_state,
            messages=[item.content for item in transcript if item.role == "user"],
            transcript=transcript,
            empathy_card=card,
            last_result_id=f"result_{uuid4().hex}",
            case=self._initial_case(conversation_id, request),
            source_context=AgentSourceContext(
                customer_id=intake.customer_id,
                orders=intake.orders,
                historical_tickets=intake.historical_tickets,
            ),
            created_at=now,
            updated_at=now,
        )
        self.repository.save_conversation(stored)
        eta = now + timedelta(minutes=self.settings.handoff_eta_minutes)
        event_row = self.repository.create_event(
            {
                "event_id": f"evt_{uuid4().hex}",
                "conversation_id": conversation_id,
                "status": "processing",
                "priority": 100 if card.risk_level == RiskLevel.HIGH else 50,
                "reason": f"消费者进线 · {card.intent.value}",
                "estimated_response_at": eta.isoformat(),
            },
            f"agent-intake:{conversation_id}",
        )
        stored.ticket = TicketRecord(
            ticket_id=str(event_row["event_id"]),
            conversation_id=conversation_id,
            status="waiting_for_agent",
            created_at=now,
            updated_at=now,
        )
        self.repository.save_conversation(stored)
        self.repository.add_audit(
            conversation_id,
            "agent_intake_created",
            {
                "customer_id": intake.customer_id,
                "chat_count": len(transcript),
                "order_count": len(intake.orders),
                "historical_ticket_count": len(intake.historical_tickets),
            },
        )
        view = self.agent_view(conversation_id)
        assert view is not None
        return AgentIntakeResponse(event=self._event_summary(event_row), conversation=view)

    def continue_conversation(
        self, conversation_id: str, request: ConversationRequest
    ) -> ConsumerResponse | None:
        existing = self.repository.get_conversation(conversation_id)
        if existing is None:
            return None
        if existing.ticket is not None and existing.ticket.status != "resolved":
            return self._continue_agent_conversation(existing, request)
        return self._process(conversation_id, request, existing)

    def _continue_agent_conversation(
        self, conversation: StoredConversation, request: ConversationRequest
    ) -> ConsumerResponse:
        now = utc_now()
        result_id = f"result_{uuid4().hex}"
        conversation.messages.append(request.message)
        conversation.transcript.append(
            ConversationTranscriptItem(role="user", content=request.message, created_at=now)
        )
        retained_state = (
            ConversationState.BLOCK
            if conversation.state == ConversationState.BLOCK
            else ConversationState.HANDOFF
        )
        conversation.state = retained_state
        conversation.empathy_card.next_state = retained_state
        conversation.last_result_id = result_id
        conversation.ticket.status = "waiting_for_agent"
        conversation.ticket.updated_at = now
        conversation.updated_at = now
        self.repository.save_conversation(conversation)
        self.repository.add_audit(
            conversation.conversation_id,
            "consumer_message_forwarded",
            {"ticket_id": conversation.ticket.ticket_id},
        )
        event = self.repository.get_event_for_conversation(conversation.conversation_id)
        return ConsumerResponse(
            conversation_id=conversation.conversation_id,
            result_id=result_id,
            state=retained_state,
            message="消息已同步给人工客服，请等待客服回复。",
            available_actions=["view_ticket", "reply"],
            event_id=str(event["event_id"]) if event else None,
            event_status="waiting_for_agent",
        )

    def _process(
        self,
        conversation_id: str,
        request: ConversationRequest,
        existing: StoredConversation | None,
    ) -> ConsumerResponse:
        now = utc_now()
        messages = [*existing.messages, request.message] if existing else [request.message]
        card = EmpathyCard.model_validate(
            self.decision_policy.decide(conversation_id, request, existing)
        )
        result_id = f"result_{uuid4().hex}"
        fallback_text, actions = self._consumer_copy(card)
        response_text = fallback_text
        if self.response_provider is not None and card.next_state in {
            ConversationState.ASK,
            ConversationState.GUIDE,
            ConversationState.RESOLVE,
        }:
            try:
                response_text = self.response_provider.generate(request, card, existing)
            except Exception as error:  # provider 失败不得中断消费者主链路
                self.repository.add_audit(
                    conversation_id,
                    "response_provider_fallback",
                    {"error_type": type(error).__name__},
                )
        transcript = list(existing.transcript) if existing else []
        transcript.extend(
            [
                ConversationTranscriptItem(role="user", content=request.message, created_at=now),
                ConversationTranscriptItem(role="assistant", content=response_text, created_at=now),
            ]
        )
        stored = StoredConversation(
            conversation_id=conversation_id,
            state=card.next_state,
            messages=messages,
            transcript=transcript,
            empathy_card=card,
            last_result_id=result_id,
            unresolved_attempts=(existing.unresolved_attempts if existing else 0)
            + int(card.next_state not in {ConversationState.RESOLVE, ConversationState.GUIDE}),
            case=existing.case if existing else self._initial_case(conversation_id, request),
            attempts=list(existing.attempts) if existing else [],
            ticket=existing.ticket if existing else None,
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
        event = None
        if card.next_state in {ConversationState.HANDOFF, ConversationState.BLOCK}:
            event = self.create_handoff(conversation_id, "automatic-ai-handoff")
        return ConsumerResponse(
            conversation_id=conversation_id,
            result_id=result_id,
            state=card.next_state,
            message=response_text,
            evidence=(
                card.knowledge_refs
                if card.next_state in {ConversationState.RESOLVE, ConversationState.GUIDE}
                else []
            ),
            available_actions=actions,
            event_id=event.event_id if event else None,
            event_status=event.status if event else None,
            estimated_response_at=event.estimated_response_at if event else None,
        )

    @staticmethod
    def _consumer_copy(card: EmpathyCard) -> tuple[str, list[str]]:
        if card.next_state == ConversationState.BLOCK:
            return (
                "你提到的情况需要谨慎处理。请先停止继续使用相关产品，避免自行叠加其他刺激性产品；"
                "如症状明显、持续或加重，请及时寻求专业医疗帮助。现有沟通内容已自动提交给人工客服跟进。",
                ["view_ticket"],
            )
        if card.next_state == ConversationState.ASK:
            if card.intent_source == "user_decline_handoff_rules":
                return "好的，暂不转人工。请继续描述你希望 AI 帮你解决的具体问题。", ["reply"]
            if "搓泥发生步骤或已经尝试过的方法" in card.missing_information:
                return (
                    "为了只调整一个条件，请告诉我搓泥发生在哪一步，以及你已经试过什么方法；不确定也可以跳过。",
                    [
                        "reply",
                        "skip",
                        "confirm_handoff",
                    ],
                )
            return "为了更准确地给出建议，请告诉我你的肤色冷暖调，或你偏好的妆效。", ["reply"]
        if card.next_state == ConversationState.HANDOFF:
            if card.intent_source == "user_handoff_rules":
                return "已按你的选择转接人工客服，之前的沟通内容会一并同步。", ["view_ticket"]
            if "可读取的附件内容" in card.missing_information:
                message = (
                    "我目前无法读取你上传的附件内容，因此不会根据文件名猜测。"
                    "现有沟通内容已自动提交给人工客服查看并跟进。"
                )
                return message, [
                    "view_ticket",
                ]
            return "当前没有足够的已审核依据来安全回答，现有沟通内容已自动提交给人工客服跟进。", [
                "view_ticket",
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
    def _initial_case(conversation_id: str, request: ConversationRequest) -> CaseRecord:
        now = utc_now()
        facts = {"product": request.product} if request.product else {}
        revision = CaseRevision(
            revision=1,
            facts=facts,
            unknown_fields=["product"] if not request.product else [],
            reason="initial_statement",
            created_at=now,
        )
        return CaseRecord(
            case_id=f"case_{uuid4().hex}",
            conversation_id=conversation_id,
            original_statement=request.message,
            revisions=[revision],
        )

    def revise_case(self, conversation_id: str, request: CaseRevisionRequest) -> CaseRecord | None:
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None or conversation.case is None:
            return None
        previous = conversation.case.revisions[-1]
        revision = CaseRevision(
            revision=conversation.case.current_revision + 1,
            facts={**previous.facts, **request.facts},
            unknown_fields=request.unknown_fields,
            reason=request.reason,
            created_at=utc_now(),
        )
        conversation.case.revisions.append(revision)
        conversation.case.current_revision = revision.revision
        conversation.empathy_card.case_revision = revision.revision
        conversation.empathy_card.entities.update(request.facts)
        conversation.updated_at = utc_now()
        self.repository.save_conversation(conversation)
        self.repository.add_audit(
            conversation_id,
            "case_revised",
            {"revision": revision.revision, "reason": request.reason},
        )
        return conversation.case

    def create_attempt(
        self, conversation_id: str, request: AttemptCreateRequest
    ) -> AttemptRecord | None:
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None:
            return None
        normalized = "".join(request.recommendation.lower().split())
        if any(
            "".join(item.recommendation.lower().split()) == normalized
            for item in conversation.attempts
        ):
            raise ValueError("duplicate attempt")
        now = utc_now()
        attempt = AttemptRecord(
            attempt_id=f"attempt_{uuid4().hex}",
            conversation_id=conversation_id,
            created_at=now,
            updated_at=now,
            **request.model_dump(),
        )
        conversation.attempts.append(attempt)
        conversation.updated_at = now
        self.repository.save_conversation(conversation)
        self.repository.add_audit(
            conversation_id, "attempt_proposed", {"attempt_id": attempt.attempt_id}
        )
        return attempt

    def update_attempt(
        self, conversation_id: str, attempt_id: str, request: AttemptUpdateRequest
    ) -> AttemptRecord | None:
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None:
            return None
        attempt = next(
            (item for item in conversation.attempts if item.attempt_id == attempt_id), None
        )
        if attempt is None:
            return None
        if request.execution_status == "executed" and not request.observation:
            raise ValueError("observation is required when an attempt was executed")
        attempt.execution_status = request.execution_status
        attempt.observation = request.observation
        attempt.outcome = request.outcome or (
            "unknown" if request.execution_status == "skipped" else None
        )
        attempt.updated_at = utc_now()
        conversation.updated_at = attempt.updated_at
        self.repository.save_conversation(conversation)
        self.repository.add_audit(
            conversation_id,
            "attempt_updated",
            {"attempt_id": attempt_id, "execution_status": request.execution_status},
        )
        return attempt

    def record_ticket_result(
        self, conversation_id: str, request: TicketResultRequest
    ) -> TicketRecord | None:
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None or conversation.ticket is None:
            return None
        status_map = {
            "agent_replied": "agent_replied",
            "action_completed": "action_completed",
            "user_confirmed_resolved": "resolved",
            "reopened": "reopened",
        }
        now = utc_now()
        conversation.ticket.status = status_map[request.event]
        conversation.ticket.version += 1
        conversation.ticket.updated_at = now
        conversation.ticket.result_events.append(
            {"event": request.event, "note": request.note, "created_at": now.isoformat()}
        )
        conversation.updated_at = now
        self.repository.save_conversation(conversation)
        self.repository.add_audit(
            conversation_id,
            "ticket_result",
            {"event": request.event, "ticket_version": conversation.ticket.version},
        )
        return conversation.ticket

    def consumer_ticket_view(self, conversation_id: str) -> ConsumerTicketView | None:
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None or conversation.ticket is None:
            return None
        replies = [
            item.get("note")
            for item in conversation.ticket.result_events
            if item.get("event") == "agent_replied" and item.get("note")
        ]
        return ConsumerTicketView(
            conversation_id=conversation_id,
            status=conversation.ticket.status,
            latest_agent_reply=str(replies[-1]) if replies else None,
            updated_at=conversation.ticket.updated_at,
        )

    def append_agent_message(self, conversation_id: str, message: str) -> bool:
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None or conversation.ticket is None or not message.strip():
            return False
        now = utc_now()
        conversation.transcript.append(
            ConversationTranscriptItem(role="agent", content=message.strip(), created_at=now)
        )
        conversation.updated_at = now
        self.repository.save_conversation(conversation)
        return True

    def create_handoff(self, conversation_id: str, idempotency_key: str) -> EventSummary | None:
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None:
            return None
        if conversation.ticket is not None:
            existing_event = self.repository.get_event_for_conversation(conversation_id)
            return self._event_summary(existing_event) if existing_event else None
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
        if conversation.state != ConversationState.BLOCK:
            conversation.state = ConversationState.HANDOFF
            conversation.empathy_card.next_state = ConversationState.HANDOFF
        conversation.updated_at = utc_now()
        if conversation.ticket is None:
            now = utc_now()
            conversation.ticket = TicketRecord(
                ticket_id=str(event["event_id"]),
                conversation_id=conversation_id,
                status="waiting_for_agent",
                created_at=now,
                updated_at=now,
            )
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
            transcript=conversation.transcript,
            summary=" → ".join(conversation.messages),
            handoff_reason=(
                "用户在对话中明确选择人工客服"
                if card.intent_source == "user_handoff_rules"
                else "；".join(card.risk_reasons or card.missing_information)
                or "AI 无法基于当前已审核知识可靠回答"
            ),
            case=conversation.case,
            attempts=conversation.attempts,
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
            ticket=conversation.ticket,
        )
        return AgentConversationView(
            handoff_package=package,
            empathy_card=card,
            audit_trail=self.repository.get_audit(conversation_id),
            assistant_brief=self._agent_assistant_brief(conversation),
        )

    def _agent_assistant_brief(
        self, conversation: StoredConversation
    ) -> AgentAssistantBrief | None:
        context = conversation.source_context
        if context is None:
            return None
        card = conversation.empathy_card
        timeline = [
            ServiceTimelineItem(
                source="chat",
                occurred_at=item.created_at,
                title={"user": "消费者消息", "assistant": "AI 消息", "agent": "客服回复"}[
                    item.role
                ],
                detail=item.content,
            )
            for item in conversation.transcript
        ]
        timeline.extend(
            ServiceTimelineItem(
                source="order",
                occurred_at=item.created_at,
                title=f"订单 {item.order_id} · {item.status}",
                detail=item.product_name,
            )
            for item in context.orders
        )
        timeline.extend(
            ServiceTimelineItem(
                source="ticket",
                occurred_at=item.created_at,
                title=f"历史工单 {item.ticket_id} · {item.status}",
                detail=f"{item.category}：{item.summary}",
            )
            for item in context.historical_tickets
        )
        messages = " ".join(conversation.messages)
        emotion = (
            "angry"
            if any(word in messages for word in ("投诉", "气死", "太差", "欺骗"))
            else "anxious"
            if any(word in messages for word in ("着急", "怎么办", "严重", "红肿", "刺痛"))
            else "neutral"
        )
        escalation_target = None
        if card.risk_level == RiskLevel.HIGH:
            escalation_target = "risk_specialist"
        elif card.intent == Intent.COMPLAINT:
            escalation_target = "complaint"
        elif any(word in messages for word in ("物流", "快递", "没收到")):
            escalation_target = "logistics"
        elif card.intent == Intent.AFTER_SALES:
            escalation_target = "after_sales"
        draft, _ = self._consumer_copy(card)
        next_actions = ["核对消费者当前诉求与已知事实"]
        if context.orders:
            next_actions.append("核对关联订单状态")
        if context.historical_tickets:
            next_actions.append("避免重复询问历史工单已有信息")
        next_actions.append(
            f"升级至 {escalation_target}" if escalation_target else "审核并发送回复草稿"
        )
        return AgentAssistantBrief(
            service_timeline=sorted(timeline, key=lambda item: item.occurred_at),
            intent=card.intent,
            emotion=emotion,
            risk_level=card.risk_level,
            risk_reasons=card.risk_reasons,
            reply_draft=draft,
            evidence=card.knowledge_refs,
            next_actions=next_actions,
            escalation_target=escalation_target,
        )
