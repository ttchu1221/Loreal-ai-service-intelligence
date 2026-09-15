from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from loreal_ai_service_intelligence.domain.models import (
    AgentIntakeRequest,
    ConversationState,
    ConversationTranscriptItem,
    Intent,
    RiskLevel,
    RiskTracking,
    ServiceTimelineItem,
    SourceEvidence,
    UrgencyLevel,
)


class MockAttemptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: str = Field(min_length=1, max_length=1000)
    execution_status: Literal["proposed", "executed", "skipped"]
    outcome: Optional[Literal["improved", "unchanged", "worse", "unknown"]] = None


class MockDecisionRequest(BaseModel):
    """3 号 AI contract 的最小、可冻结输入格式。"""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=100)
    schema_version: Literal["1.0"] = "1.0"
    current_message: str = Field(min_length=1, max_length=4000)
    case_revision: int = Field(default=1, ge=1)
    confirmed_facts: dict[str, str] = Field(default_factory=dict)
    unknown_fields: list[str] = Field(default_factory=list)
    attempts: list[MockAttemptInput] = Field(default_factory=list, max_length=20)
    requested_handoff: bool = False


class MockGuide(BaseModel):
    purpose: str
    instruction: str
    observation_target: str
    exit_condition: str


class MockDecisionResponse(BaseModel):
    """可由真实 AI provider 替换、但不能直接执行副作用的输出格式。"""

    request_id: str
    schema_version: str
    state: ConversationState
    risk_level: RiskLevel
    assistant_message: str
    question: Optional[str] = None
    guide: Optional[MockGuide] = None
    handoff_reason: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)
    provider: Literal["deterministic_mock"] = "deterministic_mock"
    rule_version: str
    knowledge_version: str


class MockAgentAssistRequest(BaseModel):
    """人工客服插件的冻结 Mock 输入；context 与正式 intake 使用同一 schema。"""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=100)
    schema_version: Literal["1.0"] = "1.0"
    context: AgentIntakeRequest


class MockAgentEmpathy(BaseModel):
    intent: Intent
    emotion: Literal["neutral", "anxious", "angry"]
    urgency: UrgencyLevel
    known_facts: list[str]
    unknown_fields: list[str]
    historical_promises: list[str]
    unresolved_items: list[str]


class MockAgentSuggestions(BaseModel):
    reply_draft: str
    next_actions: list[str]
    escalation_target: Optional[
        Literal["after_sales", "logistics", "complaint", "risk_specialist"]
    ] = None
    evidence: list[SourceEvidence]


class MockAgentAssistResponse(BaseModel):
    """供 3 号 AI 模块和前端联调的四区域插件输出。"""

    request_id: str
    schema_version: str
    service_trajectory: list[ServiceTimelineItem]
    empathy_understanding: MockAgentEmpathy
    suggestions: MockAgentSuggestions
    risk_tracking: RiskTracking
    provider: Literal["deterministic_agent_mock"] = "deterministic_agent_mock"
    rule_version: str
    knowledge_version: str


class MockDecisionService:
    """无 network、无 persistence 副作用的 deterministic Mock decision provider。"""

    _risk_terms = ("刺痛", "泛红", "红肿", "呼吸困难", "灼痛", "过敏")
    _after_sales_terms = ("退款", "退货", "换货", "售后", "人工", "客服")
    _pilling_terms = ("搓泥", "起屑", "结块")

    def __init__(self, rule_version: str, knowledge_version: str) -> None:
        self.rule_version = rule_version
        self.knowledge_version = knowledge_version

    def decide(self, request: MockDecisionRequest) -> MockDecisionResponse:
        text = request.current_message.strip()
        base = {
            "request_id": request.request_id,
            "schema_version": request.schema_version,
            "rule_version": self.rule_version,
            "knowledge_version": self.knowledge_version,
        }
        risk_terms = [term for term in self._risk_terms if term in text]
        if risk_terms:
            return MockDecisionResponse(
                **base,
                state=ConversationState.BLOCK,
                risk_level=RiskLevel.HIGH,
                assistant_message="请先停止继续使用；如症状明显、持续或加重，请及时寻求专业医疗帮助。",
                handoff_reason=f"命中风险信号：{','.join(risk_terms)}",
            )

        if request.requested_handoff or any(term in text for term in self._after_sales_terms):
            return MockDecisionResponse(
                **base,
                state=ConversationState.HANDOFF,
                risk_level=RiskLevel.LOW,
                assistant_message="已准备转人工，请在用户确认后由业务服务创建 Ticket。",
                handoff_reason="用户主动请求人工或售后",
            )

        pilling_context = any(term in text for term in self._pilling_terms) or any(
            any(term in value for term in self._pilling_terms)
            for value in request.confirmed_facts.values()
        )
        failed = [
            attempt
            for attempt in request.attempts
            if attempt.execution_status == "executed" and attempt.outcome in {"unchanged", "worse"}
        ]
        if pilling_context and len(failed) >= 2:
            return MockDecisionResponse(
                **base,
                state=ConversationState.HANDOFF,
                risk_level=RiskLevel.LOW,
                assistant_message="连续两次单条件尝试没有改善，建议停止继续试错并转人工。",
                handoff_reason="两次尝试无改善",
            )

        has_step = any(key in request.confirmed_facts for key in ("pilling_step", "failed_history"))
        if pilling_context and not has_step and not request.attempts:
            question = "搓泥发生在哪一步，以及你已经试过什么方法？不确定可以跳过。"
            return MockDecisionResponse(
                **base,
                state=ConversationState.ASK,
                risk_level=RiskLevel.LOW,
                assistant_message=question,
                question=question,
            )

        if pilling_context:
            used = " ".join(attempt.recommendation for attempt in request.attempts)
            if "减少" not in used:
                guide = MockGuide(
                    purpose="排除底妆前产品用量过多",
                    instruction="其他条件保持不变，只把底妆前护肤品用量减少一半。",
                    observation_target="观察同一区域是否仍起屑或结块。",
                    exit_condition="无改善、情况变差或出现不适时停止并选择转人工。",
                )
            else:
                guide = MockGuide(
                    purpose="排除层间未充分成膜",
                    instruction="其他条件保持不变，底妆前等待五分钟再薄涂。",
                    observation_target="观察同一区域是否仍起屑或结块。",
                    exit_condition="无改善、情况变差或出现不适时停止并选择转人工。",
                )
            return MockDecisionResponse(
                **base,
                state=ConversationState.GUIDE,
                risk_level=RiskLevel.LOW,
                assistant_message=guide.instruction,
                guide=guide,
                evidence_ids=["KB-PILLING-001"],
            )

        return MockDecisionResponse(
            **base,
            state=ConversationState.HANDOFF,
            risk_level=RiskLevel.LOW,
            assistant_message="Mock 接口没有足够的已审核依据，建议转人工。",
            handoff_reason="无审核证据",
        )

    def assist_agent(self, request: MockAgentAssistRequest) -> MockAgentAssistResponse:
        """Return deterministic, side-effect-free agent assistance for integration tests."""
        context = request.context
        now = datetime.now(timezone.utc)
        transcript = list(context.transcript)
        if not transcript or transcript[-1].content != context.current_message:
            transcript.append(
                ConversationTranscriptItem(
                    role="user", content=context.current_message, created_at=now
                )
            )
        timeline = [
            ServiceTimelineItem(
                source="chat",
                occurred_at=item.created_at,
                title={"user": "消费者消息", "assistant": "AI 消息", "agent": "客服回复"}[
                    item.role
                ],
                detail=item.content,
            )
            for item in transcript
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
        text = " ".join(item.content for item in transcript)
        risk_terms = [term for term in self._risk_terms if term in text]
        risk_level = RiskLevel.HIGH if risk_terms else RiskLevel.LOW
        emotion = (
            "angry"
            if any(term in text for term in ("投诉", "气死", "欺骗", "太差"))
            else "anxious"
            if any(term in text for term in ("着急", "怎么办", "严重", "红肿", "刺痛"))
            else "neutral"
        )
        urgency = (
            UrgencyLevel.HIGH
            if risk_terms or any(term in text for term in ("马上", "立刻", "今天必须"))
            else UrgencyLevel.MEDIUM
            if emotion != "neutral"
            else UrgencyLevel.LOW
        )
        intent = (
            Intent.COMPLAINT
            if "投诉" in text
            else Intent.AFTER_SALES
            if any(term in text for term in ("退款", "退货", "换货", "售后"))
            else Intent.CONSULT
        )
        evidence = [
            SourceEvidence(
                source="chat", source_id=f"chat-{index + 1}", field="content", value=item.content
            )
            for index, item in enumerate(transcript)
        ]
        evidence.extend(
            SourceEvidence(
                source="order", source_id=item.order_id, field="status", value=item.status
            )
            for item in context.orders
        )
        evidence.extend(
            SourceEvidence(
                source="ticket", source_id=item.ticket_id, field="summary", value=item.summary
            )
            for item in context.historical_tickets
        )
        unresolved = [
            f"{item.ticket_id}：{item.summary}"
            for item in context.historical_tickets
            if item.status.lower() not in {"closed", "resolved", "completed"}
        ]
        promises = [
            item.summary
            for item in context.historical_tickets
            if any(term in item.summary for term in ("承诺", "答应", "预计", "保证"))
        ]
        escalation = (
            "risk_specialist"
            if risk_level == RiskLevel.HIGH
            else "complaint"
            if intent == Intent.COMPLAINT
            else "after_sales"
            if intent == Intent.AFTER_SALES
            else None
        )
        draft = (
            "很抱歉让你担心了。请先停止使用相关产品；我会立即为你升级风险专员跟进。"
            if risk_level == RiskLevel.HIGH
            else "我已看到你的诉求和历史记录，会先核对关联订单与未完成事项，避免让你重复说明。"
        )
        return MockAgentAssistResponse(
            request_id=request.request_id,
            schema_version=request.schema_version,
            service_trajectory=sorted(timeline, key=lambda item: item.occurred_at),
            empathy_understanding=MockAgentEmpathy(
                intent=intent,
                emotion=emotion,
                urgency=urgency,
                known_facts=[item.content for item in transcript],
                unknown_fields=[] if context.orders else ["关联订单"],
                historical_promises=promises,
                unresolved_items=unresolved,
            ),
            suggestions=MockAgentSuggestions(
                reply_draft=draft,
                next_actions=[
                    "核对历史会话、订单和工单",
                    f"升级至 {escalation}" if escalation else "人工审核后回复",
                ],
                escalation_target=escalation,
                evidence=evidence,
            ),
            risk_tracking=RiskTracking(
                risk_type="safety" if risk_level == RiskLevel.HIGH else "service",
                level=risk_level,
                reasons=[f"命中风险信号：{','.join(risk_terms)}"] if risk_terms else [],
                close_condition=(
                    "风险专员已跟进且消费者确认获得安全指引"
                    if risk_level == RiskLevel.HIGH
                    else "客服完成处理且消费者确认结果"
                ),
                updated_at=now,
            ),
            rule_version=self.rule_version,
            knowledge_version=self.knowledge_version,
        )


def create_mock_router(service: MockDecisionService, *, enabled: bool) -> APIRouter:
    router = APIRouter(prefix="/v1/mock", tags=["mock"])

    @router.post("/decisions", response_model=MockDecisionResponse)
    def create_mock_decision(request: MockDecisionRequest) -> MockDecisionResponse:
        if not enabled:
            raise HTTPException(status_code=404, detail="mock API is disabled")
        return service.decide(request)

    @router.post("/agent-assists", response_model=MockAgentAssistResponse)
    def create_mock_agent_assist(request: MockAgentAssistRequest) -> MockAgentAssistResponse:
        if not enabled:
            raise HTTPException(status_code=404, detail="mock API is disabled")
        return service.assist_agent(request)

    return router
