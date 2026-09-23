# ruff: noqa: E501  # 内嵌 workspace HTML/CSS 保持可直接交付的单文件模板。
from __future__ import annotations

from typing import Literal, Optional, Union

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from pymongo.errors import PyMongoError

from loreal_ai_service_intelligence import __version__
from loreal_ai_service_intelligence.api.competition import create_competition_router
from loreal_ai_service_intelligence.api.competition_workspace import competition_workspace_html
from loreal_ai_service_intelligence.api.mock import MockDecisionService, create_mock_router
from loreal_ai_service_intelligence.config import get_settings
from loreal_ai_service_intelligence.domain.models import (
    AgentConversationView,
    AgentIntakeRequest,
    AgentIntakeResponse,
    AttemptCreateRequest,
    AttemptRecord,
    AttemptUpdateRequest,
    CaseRecord,
    CaseRevisionRequest,
    ConsumerConversationView,
    ConsumerResponse,
    ConsumerTicketResultRequest,
    ConsumerTicketView,
    ConversationRequest,
    ConversationTranscriptItem,
    EventSummary,
    FeedbackRequest,
    HandoffDecision,
    InsightMetric,
    InsightsResponse,
    RiskTracking,
    RiskUpdateRequest,
    ServiceActionRequest,
    SuggestionFeedbackRecord,
    SuggestionFeedbackRequest,
    TicketRecord,
    TicketResultRequest,
)
from loreal_ai_service_intelligence.infrastructure.repository import (
    MongoRepository,
    StorageRepository,
)
from loreal_ai_service_intelligence.providers.context import (
    ContextDataProvider,
    UnconfiguredContextDataProvider,
)
from loreal_ai_service_intelligence.providers.factory import (
    create_intent_provider,
    create_response_provider,
)
from loreal_ai_service_intelligence.providers.interfaces import (
    DecisionPolicy,
    IntentProvider,
    KnowledgeProvider,
    ResponseProvider,
)
from loreal_ai_service_intelligence.services.competition import CompetitionP0Service
from loreal_ai_service_intelligence.services.orchestration import ConversationOrchestrator


def create_app(
    repository: Optional[StorageRepository] = None,
    intent_provider: Optional[IntentProvider] = None,
    knowledge_provider: Optional[KnowledgeProvider] = None,
    decision_policy: Optional[DecisionPolicy] = None,
    response_provider: Optional[ResponseProvider] = None,
    context_provider: Optional[ContextDataProvider] = None,
) -> FastAPI:
    settings = get_settings()
    intent_provider = intent_provider or create_intent_provider(settings)
    response_provider = response_provider or create_response_provider(settings)
    repository = repository or MongoRepository(
        settings.mongodb_uri,
        settings.mongodb_database,
        settings.mongodb_timeout_ms,
    )
    orchestrator = ConversationOrchestrator(
        repository,
        settings,
        intent_provider,
        knowledge_provider,
        decision_policy,
        response_provider,
    )
    application = FastAPI(title=settings.app_name, version=__version__)
    application.include_router(
        create_mock_router(
            MockDecisionService(settings.rule_version, settings.knowledge_version),
            enabled=settings.mock_api_enabled,
        )
    )
    application.include_router(
        create_competition_router(
            CompetitionP0Service(repository, settings),
            repository,
            context_provider or UnconfiguredContextDataProvider(),
        )
    )

    @application.exception_handler(PyMongoError)
    async def handle_database_error(_request: Request, _error: PyMongoError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "database temporarily unavailable"},
        )

    @application.get("/health", tags=["system"])
    def health_check() -> dict[str, str]:
        return {"status": "ok", "environment": settings.app_env}

    @application.post(
        "/v1/conversations",
        response_model=ConsumerResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["consumer"],
    )
    def start_conversation(request: ConversationRequest) -> ConsumerResponse:
        return orchestrator.start(request)

    @application.post(
        "/v1/conversations/{conversation_id}/messages",
        response_model=ConsumerResponse,
        tags=["consumer"],
    )
    def continue_conversation(
        conversation_id: str, request: ConversationRequest
    ) -> ConsumerResponse:
        response = orchestrator.continue_conversation(conversation_id, request)
        if response is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return response

    @application.get(
        "/v1/conversations/{conversation_id}",
        response_model=ConsumerConversationView,
        tags=["consumer"],
    )
    def get_consumer_conversation(conversation_id: str) -> ConsumerConversationView:
        conversation = repository.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        transcript = conversation.transcript or [
            ConversationTranscriptItem(
                role="user", content=message, created_at=conversation.created_at
            )
            for message in conversation.messages
        ]
        return ConsumerConversationView(
            conversation_id=conversation.conversation_id,
            state=conversation.state,
            last_result_id=conversation.last_result_id,
            transcript=transcript,
        )

    @application.get(
        "/v1/conversations/{conversation_id}/case", response_model=CaseRecord, tags=["consumer"]
    )
    def get_case(conversation_id: str) -> CaseRecord:
        conversation = repository.get_conversation(conversation_id)
        if conversation is None or conversation.case is None:
            raise HTTPException(status_code=404, detail="case not found")
        return conversation.case

    @application.post(
        "/v1/conversations/{conversation_id}/case/revisions",
        response_model=CaseRecord,
        tags=["consumer"],
    )
    def revise_case(conversation_id: str, request: CaseRevisionRequest) -> CaseRecord:
        case = orchestrator.revise_case(conversation_id, request)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        return case

    @application.get(
        "/v1/conversations/{conversation_id}/attempts",
        response_model=list[AttemptRecord],
        tags=["consumer"],
    )
    def list_attempts(conversation_id: str) -> list[AttemptRecord]:
        conversation = repository.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return conversation.attempts

    @application.post(
        "/v1/conversations/{conversation_id}/attempts",
        response_model=AttemptRecord,
        status_code=status.HTTP_201_CREATED,
        tags=["consumer"],
    )
    def create_attempt(conversation_id: str, request: AttemptCreateRequest) -> AttemptRecord:
        try:
            attempt = orchestrator.create_attempt(conversation_id, request)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if attempt is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return attempt

    @application.patch(
        "/v1/conversations/{conversation_id}/attempts/{attempt_id}",
        response_model=AttemptRecord,
        tags=["consumer"],
    )
    def update_attempt(
        conversation_id: str, attempt_id: str, request: AttemptUpdateRequest
    ) -> AttemptRecord:
        try:
            attempt = orchestrator.update_attempt(conversation_id, attempt_id, request)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if attempt is None:
            raise HTTPException(status_code=404, detail="attempt not found")
        return attempt

    @application.post(
        "/v1/conversations/{conversation_id}/handoff",
        response_model=Union[EventSummary, ConsumerResponse],
        tags=["consumer"],
    )
    def decide_handoff(
        conversation_id: str, decision: HandoffDecision
    ) -> Union[EventSummary, ConsumerResponse]:
        conversation = repository.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        if not decision.accepted:
            repository.add_audit(
                conversation_id, "handoff_declined", {"safety_reminder_retained": True}
            )
            return ConsumerResponse(
                conversation_id=conversation_id,
                result_id=conversation.last_result_id,
                state=conversation.state,
                message=(
                    "已记录你暂不转人工。请继续留意情况；如症状明显、持续或加重，请及时寻求专业医疗帮助。"
                    if conversation.empathy_card.risk_level.value == "high"
                    else (
                        "已记录你暂不转人工。由于当前缺少可靠依据，我不会猜测答案；"
                        "你可以补充更多信息后再试。"
                    )
                ),
            )
        event = orchestrator.create_handoff(conversation_id, decision.idempotency_key)
        if event is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return event

    @application.get("/v1/events/{event_id}", response_model=EventSummary, tags=["consumer"])
    def get_event(event_id: str) -> EventSummary:
        event = repository.get_event(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        return orchestrator._event_summary(event)

    @application.get(
        "/v1/conversations/{conversation_id}/ticket",
        response_model=ConsumerTicketView,
        tags=["consumer"],
    )
    def get_consumer_ticket(conversation_id: str) -> ConsumerTicketView:
        view = orchestrator.consumer_ticket_view(conversation_id)
        if view is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        return view

    @application.post(
        "/v1/conversations/{conversation_id}/ticket/results",
        response_model=TicketRecord,
        tags=["consumer"],
    )
    def record_consumer_ticket_result(
        conversation_id: str, request: ConsumerTicketResultRequest
    ) -> TicketRecord:
        ticket = orchestrator.record_ticket_result(
            conversation_id, TicketResultRequest(event=request.event, note=request.note)
        )
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        event = repository.get_event_for_conversation(conversation_id)
        if event is not None:
            repository.update_event_status(
                str(event["event_id"]),
                "waiting_for_agent" if request.event == "reopened" else "completed",
            )
        return ticket

    @application.post(
        "/v1/conversations/{conversation_id}/feedback",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["consumer"],
    )
    def submit_feedback(conversation_id: str, feedback: FeedbackRequest) -> None:
        conversation = repository.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        if feedback.result_id != conversation.last_result_id:
            raise HTTPException(
                status_code=409, detail="result_id does not match the latest conversation result"
            )
        repository.record_feedback(
            conversation_id, feedback.result_id, feedback.resolved, feedback.comment
        )
        repository.add_audit(
            conversation_id,
            "feedback_recorded",
            {"resolved": feedback.resolved, "training_use": False},
        )

    @application.get("/v1/agent/events", response_model=list[EventSummary], tags=["agent"])
    def list_agent_events() -> list[EventSummary]:
        return [
            orchestrator._event_summary(event)
            for event in repository.list_events()
            if event["status"] != "completed"
        ]

    @application.post(
        "/v1/agent/intakes",
        response_model=AgentIntakeResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["agent"],
    )
    def create_agent_intake(request: AgentIntakeRequest) -> AgentIntakeResponse:
        return orchestrator.start_agent_intake(request)

    @application.get(
        "/v1/agent/conversations/{conversation_id}",
        response_model=AgentConversationView,
        tags=["agent"],
    )
    def get_agent_conversation(conversation_id: str) -> AgentConversationView:
        view = orchestrator.agent_view(conversation_id)
        if view is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return view

    @application.post(
        "/v1/agent/conversations/{conversation_id}/suggestion-feedback",
        response_model=SuggestionFeedbackRecord,
        status_code=status.HTTP_201_CREATED,
        tags=["agent"],
    )
    def record_suggestion_feedback(
        conversation_id: str, request: SuggestionFeedbackRequest
    ) -> SuggestionFeedbackRecord:
        try:
            feedback = orchestrator.record_suggestion_feedback(conversation_id, request)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if feedback is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return feedback

    @application.patch(
        "/v1/agent/conversations/{conversation_id}/risk",
        response_model=RiskTracking,
        tags=["agent"],
    )
    def update_risk(conversation_id: str, request: RiskUpdateRequest) -> RiskTracking:
        try:
            risk = orchestrator.update_risk(conversation_id, request)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if risk is None:
            raise HTTPException(status_code=404, detail="risk tracking not found")
        return risk

    @application.post(
        "/v1/agent/events/{event_id}/actions", response_model=EventSummary, tags=["agent"]
    )
    def execute_service_action(event_id: str, request: ServiceActionRequest) -> EventSummary:
        event = repository.get_event(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        if request.action == "reply":
            note = str(request.parameters.get("note", "")).strip()
            if not note:
                raise HTTPException(status_code=422, detail="reply note is required")
            orchestrator.append_agent_message(str(event["conversation_id"]), note)
        repository.add_service_action(event_id, request.action, request.parameters)
        repository.add_audit(
            str(event["conversation_id"]),
            "service_action",
            {
                "event_id": event_id,
                "action": request.action,
                "parameters": request.parameters,
                "actor": "unauthenticated_agent_api",
            },
        )
        ticket_event = {
            "reply": "agent_replied",
            "create_after_sales": "action_completed",
            "close": "action_completed",
        }.get(request.action)
        if ticket_event:
            orchestrator.record_ticket_result(
                str(event["conversation_id"]),
                TicketResultRequest(event=ticket_event, note=request.parameters.get("note")),
            )
        updated = repository.get_event(event_id)
        assert updated is not None
        return orchestrator._event_summary(updated)

    @application.post(
        "/v1/agent/conversations/{conversation_id}/ticket/results",
        response_model=TicketRecord,
        tags=["agent"],
    )
    def record_ticket_result(conversation_id: str, request: TicketResultRequest) -> TicketRecord:
        ticket = orchestrator.record_ticket_result(conversation_id, request)
        if ticket is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        event = repository.get_event_for_conversation(conversation_id)
        if event is not None:
            if request.event == "reopened":
                repository.update_event_status(str(event["event_id"]), "waiting_for_agent")
            elif request.event == "user_confirmed_resolved":
                repository.update_event_status(str(event["event_id"]), "completed")
        return ticket

    @application.get("/workspace/consumer", response_class=HTMLResponse, tags=["workspace"])
    def consumer_workspace() -> HTMLResponse:
        return HTMLResponse(_consumer_workspace_html(), headers={"Cache-Control": "no-store"})

    @application.get("/workspace/agent", response_class=HTMLResponse, tags=["workspace"])
    def agent_workspace() -> HTMLResponse:
        return HTMLResponse(_agent_workspace_html(), headers={"Cache-Control": "no-store"})

    @application.get("/workspace/competition", response_class=HTMLResponse, tags=["workspace"])
    def competition_workspace() -> HTMLResponse:
        return HTMLResponse(competition_workspace_html(), headers={"Cache-Control": "no-store"})

    @application.get("/v1/insights/overview", response_model=InsightsResponse, tags=["brand"])
    def get_insights(
        data_classification: Literal["demo"] = Query(default="demo"),
    ) -> InsightsResponse:
        conversations = repository.list_conversations()
        feedback = repository.list_feedback()
        count = len(conversations)
        start = min((item.created_at for item in conversations), default=None)
        end = max((item.updated_at for item in conversations), default=None)
        resolved_count = sum(1 for item in feedback if item["resolved"])
        event_count = len(repository.list_events())
        repeat_count = sum(
            1 for item in conversations if len(item.messages) != len(set(item.messages))
        )

        def metric(value: float, sample_size: int) -> InsightMetric:
            return InsightMetric(
                value=value,
                sample_size=sample_size,
                period_start=start,
                period_end=end,
                data_classification=data_classification,
            )

        unresolved: dict[str, int] = {}
        for item in conversations:
            if item.state.value != "RESOLVE":
                key = item.empathy_card.surface_issue
                unresolved[key] = unresolved.get(key, 0) + 1
        return InsightsResponse(
            consultation_count=metric(float(count), count),
            resolution_rate=metric(
                resolved_count / len(feedback) if feedback else 0.0, len(feedback)
            ),
            handoff_rate=metric(event_count / count if count else 0.0, count),
            repeat_question_rate=metric(repeat_count / count if count else 0.0, count),
            top_unresolved_issues=[
                {"issue": key, "count": value}
                for key, value in sorted(
                    unresolved.items(), key=lambda item: item[1], reverse=True
                )[:5]
            ],
        )

    return application


app = create_app()


def _consumer_workspace_html() -> str:
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>L'Oréal 智慧美妆顾问</title><style>
:root{--ink:#171214;--muted:#786d72;--line:#eadfe3;--paper:#fffaf8;--rose:#a51f48;
--rose-soft:#f9e8ed;--shadow:0 24px 70px rgba(67,32,44,.14)}
*{box-sizing:border-box}body{margin:0;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",
sans-serif;color:var(--ink);background:radial-gradient(circle at 15% 0,#f8dfe7 0,transparent 34%),
linear-gradient(145deg,#f7f1ee,#eee5e2);min-height:100vh;padding:24px}
button,input,textarea{font:inherit}button{border:0;cursor:pointer;transition:.2s ease}
button:focus-visible,input:focus-visible,textarea:focus-visible{outline:3px solid #d890a7;outline-offset:2px}
button:disabled{opacity:.4;cursor:not-allowed}.app{width:min(1120px,100%);height:calc(100vh - 48px);
min-height:680px;margin:auto;background:rgba(255,250,248,.94);border:1px solid rgba(255,255,255,.8);
border-radius:28px;box-shadow:var(--shadow);overflow:hidden;display:grid;grid-template-columns:1fr 330px}
.chat{display:flex;flex-direction:column;min-width:0;min-height:0;overflow:hidden}.topbar{height:84px;flex:0 0 84px;padding:18px 28px;border-bottom:1px solid var(--line);
display:flex;align-items:center;justify-content:space-between;background:rgba(255,255,255,.62)}
.identity{display:flex;align-items:center;gap:13px}.avatar{width:46px;height:46px;border-radius:50%;display:grid;
place-items:center;background:var(--ink);color:#fff;font:600 18px Georgia,serif;box-shadow:0 0 0 5px #f5e8ec}
h1,h2,p{margin:0}.identity h1{font:600 17px/1.2 Georgia,"Songti SC",serif}.status{font-size:12px;
color:#657267;margin-top:5px}.status:before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;
background:#45a064;margin-right:6px}.session-actions{display:flex;align-items:center;gap:10px;min-width:0}
.session{font-size:11px;color:var(--muted);max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.clear{padding:7px 11px;border-radius:99px;background:#fff;border:1px solid var(--line);color:#69585e;font-size:12px}
.clear:hover{border-color:var(--rose);color:var(--rose)}.messages{flex:1;min-height:0;overflow-y:auto;overflow-x:hidden;
overscroll-behavior-y:contain;scrollbar-gutter:stable;touch-action:pan-y;-webkit-overflow-scrolling:touch;
padding:28px;display:flex;flex-direction:column;
gap:18px;background:linear-gradient(rgba(255,250,248,.88),rgba(255,250,248,.96))}
.bubble{max-width:76%;padding:13px 16px;border-radius:18px;white-space:pre-wrap;overflow-wrap:anywhere;
animation:rise .24s ease-out;flex:0 0 auto}
.bubble.ai,.bubble.agent{align-self:flex-start;background:#fff;border:1px solid var(--line);border-bottom-left-radius:5px;
box-shadow:0 7px 22px rgba(66,40,49,.06)}.bubble.user{align-self:flex-end;background:var(--ink);
color:#fff;border-bottom-right-radius:5px}.bubble.agent{border-color:#d99aae;background:#fff4f7}.bubble.error{align-self:flex-start;background:#fff4f4;color:#8a2330;
border:1px solid #efc7cc}.bubble small{display:block;margin-top:8px;opacity:.58;font-size:11px}
.composer{flex:0 0 auto;padding:18px 24px 22px;border-top:1px solid var(--line);background:#fff}.product-row{display:flex;
align-items:center;gap:8px;margin-bottom:10px}.product-row label{font-size:12px;color:var(--muted)}input{border:0;
background:#f5efed;border-radius:20px;padding:7px 12px;color:var(--ink)}.input-wrap{display:flex;align-items:flex-end;
gap:10px;background:#f6f1ef;border:1px solid transparent;border-radius:20px;padding:7px 8px 7px 16px}
.input-wrap:focus-within{border-color:#cf9dad;background:#fff}textarea{flex:1;resize:none;border:0;background:transparent;
padding:8px 0;min-height:44px;max-height:120px;outline:0}.send{width:46px;height:46px;border-radius:50%;
background:var(--rose);color:#fff;font-size:20px}.send:hover{transform:translateY(-2px);box-shadow:0 7px 18px #d9a0b2}
.quick{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}.chip{padding:7px 12px;border-radius:99px;
background:#fff;border:1px solid var(--line);color:#5f5055;font-size:12px}.chip:hover{border-color:var(--rose);color:var(--rose)}
.side{padding:28px 24px;background:#201a1c;color:#fff;display:flex;flex-direction:column;gap:22px}.eyebrow{
font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#d6a9b7}.side h2{font:500 24px/1.2 Georgia,
"Songti SC",serif}.progress{position:relative;padding-left:20px}.progress:before{content:"";position:absolute;left:4px;
top:8px;bottom:8px;width:1px;background:#594b50}.step{position:relative;padding:0 0 22px 10px;color:#bfb4b8}
.step:before{content:"";position:absolute;left:-20px;top:5px;width:9px;height:9px;border-radius:50%;
background:#75656a;box-shadow:0 0 0 4px #201a1c}.step.active{color:#fff}.step.active:before{background:#ef9eb8}
.ticket{padding:16px;border:1px solid #44383c;background:#2a2325;border-radius:16px;white-space:pre-wrap;
overflow-wrap:anywhere;
min-height:108px;color:#e6dfe1;font-size:13px}.side-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.side-actions button{padding:10px;border-radius:10px;background:#fff;color:#201a1c}.side-actions .ghost{
background:transparent;color:#fff;border:1px solid #5a4b50}.privacy{margin-top:auto;color:#94878b;font-size:11px}
@keyframes rise{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:none}}
@media(max-width:800px){body{padding:0}.app{height:auto;min-height:100vh;border-radius:0;display:flex;
flex-direction:column;overflow:visible}.chat{height:100vh;min-height:560px;flex:none}.side{min-height:420px}
.session{display:none}.bubble{max-width:88%}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}</style>
<main class="app"><section class="chat"><header class="topbar"><div class="identity"><div class="avatar">L</div>
<div><h1>L'Oréal 智慧美妆顾问</h1><p class="status">AI 顾问在线 · 必要时无缝转人工</p></div></div>
<div class="session-actions"><p id="session" class="session">尚未创建会话</p>
<button id="clearButton" class="clear" onclick="clearConversation()" type="button">清空会话</button></div></header>
<div id="messages" class="messages" aria-live="polite"><div class="bubble ai">你好，我是你的智慧美妆顾问。
可以告诉我遇到的问题，我会逐步帮你排查。<small>AI 顾问 · 刚刚</small></div></div>
<div id="result" hidden>等待开始</div><section class="composer"><div class="product-row"><label for="product">当前产品</label>
<input id="product" value="演示粉底" aria-label="产品名称"></div><div class="input-wrap">
<textarea id="message" rows="2" aria-label="问题描述" placeholder="描述你的问题，或输入“转人工”……">我的底妆总是搓泥</textarea>
<button id="sendButton" class="send" onclick="send()" aria-label="发送消息">↑</button></div>
<div class="quick"><button id="handoffButton" class="chip" onclick="handoff()" disabled>联系人工客服</button>
<button id="resolvedButton" class="chip" onclick="feedback(true)" disabled>问题已解决</button>
<button id="unresolvedButton" class="chip" onclick="feedback(false)" disabled>问题未解决</button></div></section>
</section><aside class="side"><p class="eyebrow">Service journey</p><h2>服务进度</h2><div class="progress">
<div class="step active">描述问题</div><div id="aiStep" class="step">AI 分析与排查</div>
<div id="agentStep" class="step">人工客服跟进</div><div id="doneStep" class="step">用户确认结果</div></div>
<div id="ticketPanel" class="ticket" aria-live="polite">AI 无法可靠回答或你主动选择人工时，
这里会同步客服进度和回复。</div><div class="side-actions">
<button id="confirmButton" onclick="ticketResult('user_confirmed_resolved')" disabled>确认已解决</button>
<button id="reopenButton" class="ghost" onclick="ticketResult('reopened')" disabled>仍需处理</button></div>
<p class="privacy">对话内容仅用于本次服务演示，不会自动用于模型训练。</p></aside></main>
<script>
const messagesList=document.getElementById('messages');const messageInput=document.getElementById('message');
const productInput=document.getElementById('product');const sendButtonEl=document.getElementById('sendButton');
const sessionEl=document.getElementById('session');const handoffButtonEl=document.getElementById('handoffButton');
const resolvedButtonEl=document.getElementById('resolvedButton');
const unresolvedButtonEl=document.getElementById('unresolvedButton');const aiStepEl=document.getElementById('aiStep');
const agentStepEl=document.getElementById('agentStep');const doneStepEl=document.getElementById('doneStep');
const ticketPanelEl=document.getElementById('ticketPanel');const confirmButtonEl=document.getElementById('confirmButton');
const reopenButtonEl=document.getElementById('reopenButton');const clearButtonEl=document.getElementById('clearButton');
let conversationId=localStorage.getItem('lorealConversationId');let resultId=null;
let pollTimer=null;let lastAgentReply=null;
const welcomeText='你好，我是你的智慧美妆顾问。\\n可以告诉我遇到的问题，我会逐步帮你排查。';
async function call(path,options){const r=await fetch(path,options);
const b=r.status===204?{}:await r.json();
if(!r.ok)throw new Error(b.detail||`HTTP ${r.status}`);return b;}
function addBubble(text,type='ai'){const bubble=document.createElement('div');bubble.className=`bubble ${type}`;
bubble.textContent=text;const meta=document.createElement('small');meta.textContent=
type==='user'?'你 · 刚刚':type==='agent'?'人工客服 · 刚刚':type==='error'?'发送失败':'AI 顾问 · 刚刚';bubble.append(meta);
messagesList.append(bubble);messagesList.scrollTop=messagesList.scrollHeight;}
function showError(error){const detail=String(error.message||error);const friendly=
detail==='Failed to fetch'?'网络连接失败，请确认服务正在运行后重试':detail;
addBubble(`暂时无法完成操作：${friendly}`,'error');}
function setSending(active){sendButtonEl.disabled=active;sendButtonEl.textContent=active?'…':'↑';
sendButtonEl.setAttribute('aria-busy',String(active));messageInput.disabled=active;}
function show(b){resultId=b.result_id||resultId;const evidence=b.evidence?.length?
`\n\n参考依据：${b.evidence.map(x=>x.knowledge_id).join(', ')}`:'';addBubble(
`${b.message||'操作成功'}${evidence}`);
sessionEl.textContent=conversationId?`会话：${conversationId}`:'尚未创建会话';
handoffButtonEl.disabled=!conversationId;resolvedButtonEl.disabled=!resultId;
unresolvedButtonEl.disabled=!resultId;
aiStepEl.classList.add('active');if(b.event_id)startPolling();}
async function send(){if(sendButtonEl.disabled)return;const text=messageInput.value.trim();if(!text)return;
messageInput.value='';setSending(true);addBubble(text,'user');try{
const payload={message:text,product:productInput.value||null};
const path=conversationId?`/v1/conversations/${conversationId}/messages`:'/v1/conversations';
const b=await call(path,{method:'POST',headers:{'content-type':'application/json'},
body:JSON.stringify(payload)});conversationId=b.conversation_id;
localStorage.setItem('lorealConversationId',conversationId);show(b);
messageInput.placeholder=b.state==='ASK'?'补充 AI 询问的信息，或直接说“转人工”':'继续输入问题……';
}catch(e){messageInput.value=text;showError(e);}finally{setSending(false);messageInput.focus();}}
function clearConversation(){if(pollTimer){clearInterval(pollTimer);pollTimer=null;}
localStorage.removeItem('lorealConversationId');conversationId=null;resultId=null;messagesList.replaceChildren();
addBubble(welcomeText);sessionEl.textContent='尚未创建会话';messageInput.value='';
messageInput.placeholder='描述你的问题，或输入“转人工”……';handoffButtonEl.disabled=true;
resolvedButtonEl.disabled=true;unresolvedButtonEl.disabled=true;confirmButtonEl.disabled=true;
reopenButtonEl.disabled=true;aiStepEl.classList.remove('active');agentStepEl.classList.remove('active');
doneStepEl.classList.remove('active');ticketPanelEl.textContent='AI 无法可靠回答或你主动选择人工时，\\n这里会同步客服进度和回复。';
messageInput.focus();}
async function handoff(){try{const b=await call(`/v1/conversations/${conversationId}/handoff`,
{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(
{accepted:true,idempotency_key:`demo-${conversationId}`})});show(b);startPolling();}
catch(e){showError(e);}}
async function refreshTicket(){if(!conversationId)return;try{const b=await call(
`/v1/conversations/${conversationId}/ticket`);const labels={waiting_for_agent:'等待客服接入',
agent_replied:'客服已回复',action_completed:'客服动作已完成',resolved:'已解决',reopened:'继续处理中'};
const updatedAt=new Date(b.updated_at).toLocaleString();
ticketPanelEl.textContent=`状态：${labels[b.status]||b.status}\n更新时间：${updatedAt}`+
(b.latest_agent_reply?`\n\n客服回复：${b.latest_agent_reply}`:'');
if(b.latest_agent_reply&&b.latest_agent_reply!==lastAgentReply){lastAgentReply=b.latest_agent_reply;
addBubble(b.latest_agent_reply,'agent');}
agentStepEl.classList.add('active');doneStepEl.classList.toggle('active',b.status==='resolved');
confirmButtonEl.disabled=!['agent_replied','action_completed'].includes(b.status);
reopenButtonEl.disabled=!['agent_replied','action_completed','resolved'].includes(b.status);
}catch(e){if(!String(e.message).includes('ticket not found'))ticketPanelEl.textContent=e.message;}}
function startPolling(){refreshTicket();if(!pollTimer)pollTimer=setInterval(refreshTicket,2000);}
async function ticketResult(event){try{const path=
`/v1/conversations/${conversationId}/ticket/results`;await call(path,
{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({event,
note:event==='user_confirmed_resolved'?'消费者确认已解决':
'消费者反馈仍需处理'})});await refreshTicket();}
catch(e){ticketPanelEl.textContent=e.message;}}
async function feedback(resolved){try{await call(`/v1/conversations/${conversationId}/feedback`,
{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(
{result_id:resultId,resolved,comment:'演示页面反馈'})});
addBubble(`已记录你的反馈：${resolved?'问题已解决':'问题未解决'}`);}
catch(e){addBubble(`操作失败：${e.message}`);}}
async function restoreConversation(){if(!conversationId)return;try{const b=await call(
`/v1/conversations/${conversationId}`);messagesList.replaceChildren();b.transcript.forEach(x=>
addBubble(x.content,x.role==='user'?'user':x.role==='agent'?'agent':'ai'));resultId=b.last_result_id;
const agentMessages=b.transcript.filter(x=>x.role==='agent');lastAgentReply=agentMessages.length?
agentMessages[agentMessages.length-1].content:null;
sessionEl.textContent=`已恢复会话：${conversationId}`;handoffButtonEl.disabled=false;
resolvedButtonEl.disabled=false;unresolvedButtonEl.disabled=false;aiStepEl.classList.add('active');
if(['HANDOFF','BLOCK'].includes(b.state))startPolling();}
catch(e){localStorage.removeItem('lorealConversationId');conversationId=null;resultId=null;
sessionEl.textContent='尚未创建会话';showError(new Error('历史会话已失效，请重新开始咨询'));}}
restoreConversation();
</script></html>"""


def _agent_workspace_html() -> str:
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>L'Oréal 人工客服工作台</title>
<style>:root{--ink:#161315;--muted:#756e71;--line:#e9e5e6;--rose:#a51f48;--soft:#f7f4f5}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
color:var(--ink);background:#eee9e7;height:100vh;overflow:hidden}button,textarea{font:inherit}button{border:0;
cursor:pointer;transition:.18s ease}button:focus-visible,textarea:focus-visible{outline:3px solid #d893a9;
outline-offset:2px}button:disabled{opacity:.38;cursor:not-allowed}.shell{height:100vh;display:grid;
grid-template-rows:66px 1fr}.bar{background:#181416;color:#fff;display:flex;align-items:center;padding:0 24px;
justify-content:space-between}.brand{display:flex;align-items:center;gap:13px}.mark{font:600 24px Georgia,serif;
padding-right:13px;border-right:1px solid #4a4144}.brand h1{font-size:15px;margin:0}.brand p{font-size:11px;
color:#a99da1;margin:2px 0 0}.agent{display:flex;align-items:center;gap:10px;font-size:12px}.agent:before{
content:"CS";display:grid;place-items:center;width:34px;height:34px;border-radius:50%;background:#8e2445}
.workspace{min-height:0;display:grid;grid-template-columns:310px 1fr 350px}.queue{background:#fff;
border-right:1px solid var(--line);display:flex;flex-direction:column;min-width:0}.queue-head{padding:22px 20px 14px;
border-bottom:1px solid var(--line)}.queue-head div{display:flex;justify-content:space-between;align-items:center}
h2,h3,p{margin:0}.queue-head h2{font-size:18px}.queue-head p{color:var(--muted);font-size:12px;margin-top:4px}
.refresh{width:34px;height:34px;border-radius:9px;background:var(--soft);color:#5a5054}.refresh:hover{background:#eee6e9}
#events{list-style:none;padding:10px;margin:0;overflow:auto}.ticket-button{width:100%;text-align:left;padding:14px;
border-radius:12px;background:#fff;border:1px solid transparent;margin-bottom:6px}.ticket-button:hover{background:#faf7f8}
.ticket-button.selected{background:#f9e9ee;border-color:#ebc8d3}.ticket-title{font-weight:650;display:flex;
justify-content:space-between;gap:8px}.badge{font-size:10px;padding:2px 7px;border-radius:99px;background:#f2e7ea;
color:#8d2445}.ticket-meta{font-size:11px;color:var(--muted);margin-top:7px}.main{min-width:0;background:#f8f6f6;
display:flex;flex-direction:column}.case-head{padding:22px 28px;background:#fff;border-bottom:1px solid var(--line);
display:flex;justify-content:space-between;align-items:center}.case-head h2{font:600 20px Georgia,"Songti SC",serif}
.case-head p{font-size:12px;color:var(--muted);margin-top:4px}.case-status{padding:6px 10px;border-radius:99px;
background:#edf7f0;color:#317047;font-size:11px}.panel{padding:28px;overflow:auto;flex:1;min-height:0;
font-size:13px;line-height:1.6;display:flex;flex-direction:column;gap:14px;scroll-behavior:smooth}
.empty{height:100%;display:grid;place-items:center;color:#948a8d;text-align:center}.bubble{max-width:min(76%,680px);
padding:11px 14px;border-radius:16px;background:#fff;border:1px solid var(--line);white-space:pre-wrap;
overflow-wrap:anywhere;box-shadow:0 2px 8px #2d202509}.bubble.user{align-self:flex-start;border-bottom-left-radius:5px}
.bubble.agent{align-self:flex-end;background:var(--rose);border-color:var(--rose);color:#fff;border-bottom-right-radius:5px}
.bubble.ai{align-self:flex-start;background:#f1edef;border-bottom-left-radius:5px}.bubble-meta{font-size:10px;
opacity:.66;margin-bottom:4px}.handoff-card{align-self:stretch;background:#fff;border:1px solid var(--line);border-radius:14px;
padding:13px 15px;color:#665b5f}.handoff-card summary{cursor:pointer;font-weight:650;color:#473b40}
.handoff-card pre{font:12px/1.65 inherit;white-space:pre-wrap;margin:10px 0 0}.notice{align-self:center;
font-size:11px;color:var(--muted);background:#eee9eb;border-radius:99px;padding:5px 11px}
.reply-box{background:#fff;border-top:1px solid var(--line);padding:16px 24px}.reply-box label{font-size:11px;
font-weight:650;color:#6f6267;letter-spacing:.08em}.reply-row{display:flex;gap:10px;align-items:flex-end;margin-top:7px}
textarea{flex:1;resize:none;border:1px solid var(--line);border-radius:12px;padding:11px 13px;min-height:68px}
.primary{background:var(--rose);color:#fff;padding:11px 17px;border-radius:10px}.primary:hover{transform:translateY(-1px)}
.context{background:#fff;border-left:1px solid var(--line);padding:24px;overflow:auto}.context h3{font-size:13px;
margin-bottom:14px}.hint{padding:14px;border-radius:12px;background:#f8eff2;color:#70525d;font-size:12px;
margin-bottom:20px}.actions{display:grid;gap:8px}.actions button{padding:11px;border-radius:10px;background:#f2edef;
color:#493e42;text-align:left}.actions button:hover{background:#eadfe3}.action-label{display:block;font-weight:650}
.action-help{display:block;color:#82767a;font-size:11px;margin-top:2px}.sync{color:#8d8185;font-size:11px;
margin-top:18px}.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#49a56a;margin-right:5px}
.actions .danger{background:#fff0f3;color:#932141;border:1px solid #f1ccd7}.actions .danger:hover{background:#f9dfe7}
@media(max-width:950px){body{overflow:auto}.shell{height:auto;min-height:100vh}.workspace{grid-template-columns:260px 1fr}
.context{grid-column:1/-1;border:0;border-top:1px solid var(--line)}}
@media(max-width:650px){.workspace{display:block}.queue{max-height:300px}.main{min-height:650px}.bar{padding:0 14px}}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}</style>
<main class="shell"><header class="bar"><div class="brand"><span class="mark">L</span><div>
<h1>人工客服工作台</h1><p>Service Intelligence Console</p></div></div><div class="agent">演示客服 · 在线</div></header>
<section class="workspace"><aside class="queue"><div class="queue-head"><div><h2>待处理会话 <span id="queueCount"></span></h2>
<button class="refresh" onclick="load()" aria-label="刷新队列">↻</button></div><p>按风险等级与等待时间排序</p></div>
<ol id="events" aria-live="polite"></ol></aside><section class="main"><header class="case-head"><div>
<h2 id="caseTitle">选择一个消费者会话</h2><p id="caseMeta">AI 交接内容将在这里完整呈现</p></div>
<span id="caseStatus" class="case-status">等待选择</span></header><div id="detail" class="panel" aria-live="polite">
<div class="empty">从左侧队列选择工单<br>查看 AI 与消费者已经沟通的内容</div></div>
<section class="reply-box"><label for="note">回复消费者</label><div class="reply-row">
<textarea id="note" rows="2" placeholder="输入清晰、可执行的人工回复……"></textarea>
<button id="reply" class="primary" onclick="action('reply')" disabled>发送回复</button></div></section></section>
<aside class="context"><h3>处理动作</h3><div class="hint">人工回复会实时同步到消费者端；最终是否解决由消费者确认。</div>
<div class="actions"><button id="complete" onclick="ticket('action_completed')" disabled>
<span class="action-label">✓ 标记动作完成</span><span class="action-help">已完成本次承诺的处理事项</span></button>
<button id="refreshDetail" onclick="refreshSelected()" disabled><span class="action-label">↻ 同步最新状态</span>
<span class="action-help">读取消费者的最新消息与确认结果</span></button>
<button id="closeConversation" class="danger" onclick="closeConversation()" disabled>
<span class="action-label">关闭会话</span><span class="action-help">完成本次人工处理，并从待处理队列移除</span></button></div>
<p id="syncStatus" class="sync"><span class="dot"></span>队列每 3 秒自动同步</p></aside></section></main>
<script>
const eventsList=document.getElementById('events');const queueCount=document.getElementById('queueCount');
const detailPanel=document.getElementById('detail');const caseTitleEl=document.getElementById('caseTitle');
const caseMetaEl=document.getElementById('caseMeta');const caseStatusEl=document.getElementById('caseStatus');
const replyButton=document.getElementById('reply');const completeButton=document.getElementById('complete');
const refreshDetailButton=document.getElementById('refreshDetail');const noteInput=document.getElementById('note');
const closeConversationButton=document.getElementById('closeConversation');
const syncStatus=document.getElementById('syncStatus');let selected=null;let loading=false;
async function call(path,options){const r=await fetch(path,options);
const b=r.status===204?{}:await r.json();
if(!r.ok)throw new Error(b.detail||`HTTP ${r.status}`);return b;}
function showAgentError(error){syncStatus.textContent=`同步失败：${error.message||error}`;
syncStatus.style.color='#a51f48';}
function localTime(value){const normalized=/[zZ]|[+-][0-9][0-9]:[0-9][0-9]$/.test(value)?value:`${value}Z`;
return new Date(normalized).toLocaleString();}
function statusLabel(value){return {waiting_for_agent:'等待客服',processing:'处理中',agent_replied:'已回复',
action_completed:'处理完成',resolved:'消费者已确认',reopened:'再次处理中',completed:'已关闭'}[value]||value;}
async function load(){if(loading)return;loading=true;try{const b=await call('/v1/agent/events');
eventsList.replaceChildren();queueCount.textContent=b.length?`(${b.length})`:'';
b.forEach(x=>{const li=document.createElement('li');const button=document.createElement('button');
button.className='ticket-button'+(selected?.event_id===x.event_id?' selected':'');
const title=document.createElement('div');title.className='ticket-title';title.textContent=
x.reason.length>20?`${x.reason.slice(0,20)}…`:x.reason;const badge=document.createElement('span');
badge.className='badge';badge.textContent=x.priority>=100?'高优先级':'普通';title.append(badge);
const meta=document.createElement('div');meta.className='ticket-meta';meta.textContent=
`${statusLabel(x.status)} · ${localTime(x.created_at)}`;button.append(title,meta);
button.onclick=()=>selectEvent(x);li.append(button);
eventsList.append(li);});if(!b.length)eventsList.textContent='当前没有待处理事件';
syncStatus.innerHTML='<span class="dot"></span>队列已同步 · '+new Date().toLocaleTimeString();
syncStatus.style.color='';if(!selected&&b.length)await selectEvent(b[0],false);
else if(selected&&b.some(x=>x.event_id===selected.event_id))await selectEvent(selected,false);
}catch(e){showAgentError(e);}finally{loading=false;}}
async function selectEvent(event,reload=true){selected=event;const b=await call(
`/v1/agent/conversations/${event.conversation_id}`);const p=b.handoff_package;const brief=b.assistant_brief;
const attempts=p.attempts.length?p.attempts.map((x,i)=>
`${i+1}. ${x.recommendation}｜${x.execution_status}｜${x.observation||'无观察记录'}`).join('\\n'):
'暂无建议执行记录';
detailPanel.replaceChildren();const notice=document.createElement('div');notice.className='notice';
notice.textContent=brief?'AI 坐席辅助已就绪':`AI 已交接 · ${p.handoff_reason}`;detailPanel.append(notice);
if(brief){const assist=document.createElement('details');assist.className='handoff-card';assist.open=true;
const assistTitle=document.createElement('summary');assistTitle.textContent='AI 服务判断与建议';
const assistInfo=document.createElement('pre');const evidence=brief.evidence.map(x=>`${x.source}：${x.excerpt}`).join('\\n')||'暂无可引用依据';
assistInfo.textContent=`意图：${brief.intent}\n情绪：${brief.emotion}\n风险：${brief.risk_level}`+
`\n升级方向：${brief.escalation_target||'无需升级'}\n\n下一步：\n${brief.next_actions.join('\\n')}`+
`\n\n依据：\n${evidence}`;assist.append(assistTitle,assistInfo);detailPanel.append(assist);
if(!noteInput.value.trim())noteInput.value=brief.reply_draft;}
p.transcript.forEach(x=>{const bubble=document.createElement('div');bubble.className=`bubble ${x.role}`;
const meta=document.createElement('div');meta.className='bubble-meta';meta.textContent=
`${x.role==='user'?'消费者':x.role==='agent'?'人工客服':'AI 顾问'} · ${localTime(x.created_at)}`;
const content=document.createElement('div');content.textContent=x.content;bubble.append(meta,content);detailPanel.append(bubble);});
const card=document.createElement('details');card.className='handoff-card';const summary=document.createElement('summary');
summary.textContent='查看 AI 交接摘要与处理建议';const info=document.createElement('pre');info.textContent=
`状态：${p.current_state}\n已确认事实：${p.confirmed_facts.join('\\n')||'暂无'}\n仍缺信息：${p.missing_information.join('\\n')||'暂无'}`+
`\n建议执行情况：${attempts}\n建议下一步：${p.suggested_next_step}`;card.append(summary,info);detailPanel.append(card);
if(brief){const timeline=document.createElement('details');timeline.className='handoff-card';
const timelineTitle=document.createElement('summary');timelineTitle.textContent='查看完整服务轨迹';
const timelineInfo=document.createElement('pre');timelineInfo.textContent=brief.service_timeline.map(x=>
`${localTime(x.occurred_at)} · ${x.title}\n${x.detail}`).join('\\n\\n');timeline.append(timelineTitle,timelineInfo);detailPanel.append(timeline);}
detailPanel.scrollTop=detailPanel.scrollHeight;
caseTitleEl.textContent=p.summary.length>30?`${p.summary.slice(0,30)}…`:p.summary;
caseMetaEl.textContent=`会话 ${p.conversation_id}`;caseStatusEl.textContent=statusLabel(p.ticket?.status||event.status);
[replyButton,completeButton,refreshDetailButton,closeConversationButton].forEach(x=>x.disabled=false);
if(reload)await load();}
async function refreshSelected(){if(selected)await selectEvent(selected);}
async function action(name){if(name==='reply'&&!noteInput.value.trim()){noteInput.focus();
showAgentError(new Error('请输入回复内容'));return false;}const button=name==='reply'?replyButton:closeConversationButton;
button.disabled=true;const originalLabel=button.textContent;button.textContent=name==='reply'?'发送中…':'关闭中…';
try{const b=await call(`/v1/agent/events/${selected.event_id}/actions`,
{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(
{action:name,parameters:{note:noteInput.value}})});if(name==='reply')noteInput.value='';
await load();await refreshSelected();return true;}catch(e){showAgentError(e);return false;}
finally{button.textContent=originalLabel;if(selected)button.disabled=false;}}
async function closeConversation(){if(!selected||!confirm('确认本次人工处理已完成并关闭会话？'))return;
try{if(!await action('close'))return;selected=null;caseTitleEl.textContent='选择一个消费者会话';
caseMetaEl.textContent='已关闭的会话已从待处理队列移除';caseStatusEl.textContent='已关闭';
detailPanel.innerHTML='<div class="empty">会话已关闭<br>可继续处理左侧其他会话</div>';
[replyButton,completeButton,refreshDetailButton,closeConversationButton].forEach(x=>x.disabled=true);await load();}
catch(e){showAgentError(e);}}
async function ticket(event){try{const b=await call(
`/v1/agent/conversations/${selected.conversation_id}/ticket/results`,
{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(
{event,note:noteInput.value})});detailPanel.textContent=`Ticket 已更新\n${JSON.stringify(b,null,2)}`;
await load();await refreshSelected();}catch(e){detailPanel.textContent=e.message;}}
noteInput.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();
if(!replyButton.disabled)action('reply');}});
load();setInterval(load,3000);</script></html>"""
