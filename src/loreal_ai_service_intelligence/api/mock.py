from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from loreal_ai_service_intelligence.domain.models import ConversationState, RiskLevel


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


def create_mock_router(service: MockDecisionService, *, enabled: bool) -> APIRouter:
    router = APIRouter(prefix="/v1/mock", tags=["mock"])

    @router.post("/decisions", response_model=MockDecisionResponse)
    def create_mock_decision(request: MockDecisionRequest) -> MockDecisionResponse:
        if not enabled:
            raise HTTPException(status_code=404, detail="mock API is disabled")
        return service.decide(request)

    return router
