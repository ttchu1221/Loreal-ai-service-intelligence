import json

import httpx
import pytest

from loreal_ai_service_intelligence.domain.models import (
    ConversationRequest,
    ConversationState,
    EmpathyCard,
    Intent,
    KnowledgeReference,
    RiskLevel,
)
from loreal_ai_service_intelligence.providers.openai_compatible import (
    OpenAICompatibleIntentProvider,
)


def _response(content: dict) -> bytes:
    return json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode()


def test_validates_structured_intent_and_passes_timeout() -> None:
    observed = {}

    def transport(request, timeout):
        observed["url"] = request.full_url
        observed["timeout"] = timeout
        observed["authorization"] = request.get_header("Authorization")
        return _response({"intent": "usage", "confidence": 0.91})

    provider = OpenAICompatibleIntentProvider(
        api_key="test-secret",
        base_url="https://llm.example/v1/",
        model="demo-model",
        timeout_seconds=2.5,
        retry_limit=0,
        transport=transport,
    )

    result = provider.classify("怎么使用粉底")

    assert result.intent == "usage"
    assert result.source == "openai_compatible:demo-model"
    assert observed == {
        "url": "https://llm.example/v1/chat/completions",
        "timeout": 2.5,
        "authorization": "Bearer test-secret",
    }


def test_retries_timeout_with_a_bounded_limit() -> None:
    attempts = 0

    def transport(_request, _timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("timed out")
        return _response({"intent": "consult", "confidence": 0.8})

    provider = OpenAICompatibleIntentProvider(
        api_key="test-secret",
        base_url="https://llm.example/v1",
        model="demo-model",
        timeout_seconds=1,
        retry_limit=1,
        transport=transport,
    )

    assert provider.classify("咨询").intent == "consult"
    assert attempts == 2


def test_reuses_injected_http_client_without_changing_request_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps({"intent": "consult", "confidence": 0.9})}}
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleIntentProvider(
        api_key="test-secret",
        base_url="https://llm.example/v1",
        model="demo-model",
        timeout_seconds=1,
        retry_limit=0,
        client=client,
    )

    provider.classify("第一次咨询")
    provider.classify("第二次咨询")
    provider.close()

    assert len(requests) == 2
    assert {request.url.path for request in requests} == {"/v1/chat/completions"}
    assert all(request.headers["authorization"] == "Bearer test-secret" for request in requests)
    assert client.is_closed is True


def test_rejects_output_outside_the_frozen_schema() -> None:
    provider = OpenAICompatibleIntentProvider(
        api_key="test-secret",
        base_url="https://llm.example/v1",
        model="demo-model",
        timeout_seconds=1,
        retry_limit=0,
        transport=lambda _request, _timeout: _response(
            {"intent": "medical_diagnosis", "confidence": 2}
        ),
    )

    with pytest.raises(ValueError):
        provider.classify("帮我诊断")


def test_generates_contextual_response_with_fixed_decision_and_evidence() -> None:
    observed = {}

    def transport(request, _timeout):
        observed["payload"] = json.loads(request.data)
        return _response(
            {
                "message": "听起来你更在意上妆后起屑。先减少妆前用量，再观察粉底是否更服帖。",
                "media_knowledge_ids": [],
            }
        )

    provider = OpenAICompatibleIntentProvider(
        api_key="test-secret",
        base_url="https://llm.example/v1",
        model="demo-model",
        timeout_seconds=1,
        retry_limit=0,
        transport=transport,
    )
    card = EmpathyCard(
        conversation_id="conv_1",
        surface_issue="粉底后起屑",
        intent=Intent.USAGE,
        intent_confidence=0.9,
        scenario="product_usage",
        confirmed_facts=["粉底后起屑"],
        risk_level=RiskLevel.LOW,
        knowledge_refs=[
            KnowledgeReference(
                knowledge_id="kb-1",
                version="1",
                excerpt="减少妆前产品用量",
                source="reviewed",
            )
        ],
        next_state=ConversationState.GUIDE,
        schema_version="1.0",
    )

    generated = provider.generate(ConversationRequest(message="还是会起屑"), card, None)

    assert "更在意上妆后起屑" in generated.message
    assert generated.media_knowledge_ids == []
    payload = observed["payload"]
    assert payload["temperature"] == 0.3
    system_prompt = payload["messages"][0]["content"]
    assert "共情/致歉 → 已核实事实或待核实项 → 下一步动作" in system_prompt
    assert "不使用“亲”" in system_prompt
    assert "不索取完整身份证件、银行卡、支付账号" in system_prompt
    context = json.loads(payload["messages"][-1]["content"])
    assert context["fixed_state"] == "GUIDE"
    assert context["approved_evidence"] == ["减少妆前产品用量"]


def test_rejects_blank_generated_response() -> None:
    provider = OpenAICompatibleIntentProvider(
        api_key="test-secret",
        base_url="https://llm.example/v1",
        model="demo-model",
        timeout_seconds=1,
        retry_limit=0,
        transport=lambda _request, _timeout: _response(
            {"message": "  ", "media_knowledge_ids": []}
        ),
    )
    card = EmpathyCard(
        conversation_id="conv_1",
        surface_issue="怎么用",
        intent=Intent.USAGE,
        scenario="product_usage",
        risk_level=RiskLevel.LOW,
        next_state=ConversationState.RESOLVE,
        schema_version="1.0",
    )

    with pytest.raises(ValueError, match="message is invalid"):
        provider.generate(ConversationRequest(message="怎么用"), card, None)


def test_model_selects_only_retrieved_media_when_it_materially_helps() -> None:
    observed = {}

    def transport(request, _timeout):
        observed["payload"] = json.loads(request.data)
        return _response(
            {
                "message": "这张方向图可以帮助你对照冷暖色系，最终仍建议自然光试色。",
                "media_knowledge_ids": ["KB-SHADE-001"],
            }
        )

    provider = OpenAICompatibleIntentProvider(
        api_key="test-secret",
        base_url="https://llm.example/v1",
        model="demo-model",
        timeout_seconds=1,
        retry_limit=0,
        transport=transport,
    )
    card = EmpathyCard(
        conversation_id="conv_media",
        surface_issue="口红颜色怎么选",
        intent=Intent.PURCHASE,
        scenario="product_selection",
        risk_level=RiskLevel.LOW,
        knowledge_refs=[
            KnowledgeReference(
                knowledge_id="KB-SHADE-001",
                version="1",
                excerpt="结合冷暖底调选择试色方向。",
                source="reviewed",
                image_url="/v1/knowledge/KB-SHADE-001/media",
                image_alt="口红冷暖色系参考图",
                media_review_status="pending",
            )
        ],
        next_state=ConversationState.RESOLVE,
        schema_version="1.0",
    )

    generated = provider.generate(ConversationRequest(message="给我看看怎么选色"), card, None)

    assert generated.media_knowledge_ids == ["KB-SHADE-001"]
    context = json.loads(observed["payload"]["messages"][-1]["content"])
    assert context["available_evidence_media"] == [
        {
            "knowledge_id": "KB-SHADE-001",
            "description": "口红冷暖色系参考图",
            "review_status": "pending",
        }
    ]
    assert "不要因为知识有图片就默认附图" in observed["payload"]["messages"][0]["content"]


def test_model_cannot_select_media_outside_retrieved_evidence() -> None:
    provider = OpenAICompatibleIntentProvider(
        api_key="test-secret",
        base_url="https://llm.example/v1",
        model="demo-model",
        timeout_seconds=1,
        retry_limit=0,
        transport=lambda _request, _timeout: _response(
            {"message": "请看图。", "media_knowledge_ids": ["KB-NOT-RETRIEVED"]}
        ),
    )
    card = EmpathyCard(
        conversation_id="conv_media",
        surface_issue="怎么用",
        intent=Intent.USAGE,
        scenario="product_usage",
        risk_level=RiskLevel.LOW,
        next_state=ConversationState.RESOLVE,
        schema_version="1.0",
    )

    with pytest.raises(ValueError, match="unavailable evidence media"):
        provider.generate(ConversationRequest(message="怎么用"), card, None)


def test_direct_recommendation_must_not_return_the_choice_to_the_user() -> None:
    observed = {}

    def transport(request, _timeout):
        observed["payload"] = json.loads(request.data)
        return _response({"message": "有三款候选，您喜欢雾面还是水光？", "media_knowledge_ids": []})

    provider = OpenAICompatibleIntentProvider(
        api_key="test-secret",
        base_url="https://llm.example/v1",
        model="demo-model",
        timeout_seconds=1,
        retry_limit=0,
        transport=transport,
    )
    card = EmpathyCard(
        conversation_id="conv_1",
        surface_issue="想要轻薄雾面的口红",
        # 即使上游 LLM 把推荐误分为 CONSULT，推荐知识卡仍必须触发直接推荐约束。
        intent=Intent.CONSULT,
        scenario="product_selection",
        risk_level=RiskLevel.LOW,
        knowledge_refs=[
            KnowledgeReference(
                knowledge_id="KB-LOREAL-CN-LIP-001",
                version="1",
                excerpt="官网展示印迹唇釉-柔雾小钢笔 129，雾感、轻薄。",
                source="reviewed",
            )
        ],
        next_state=ConversationState.RESOLVE,
        schema_version="1.0",
    )

    with pytest.raises(ValueError, match="must not ask a follow-up question"):
        provider.generate(
            ConversationRequest(message="想要轻薄雾面，推荐一支欧莱雅口红"), card, None
        )

    system_prompt = observed["payload"]["messages"][0]["content"]
    assert "结合 current_message、known_facts" in system_prompt
    assert "不得固定推荐" in system_prompt
    assert "不能反问偏好" in system_prompt


def test_generates_evidence_free_reply_without_business_claims() -> None:
    observed = {}

    def transport(request, _timeout):
        observed["payload"] = json.loads(request.data)
        return _response({"message": "在的，请直接告诉我想咨询的问题。", "media_knowledge_ids": []})

    provider = OpenAICompatibleIntentProvider(
        api_key="test-secret",
        base_url="https://llm.example/v1",
        model="demo-model",
        timeout_seconds=1,
        retry_limit=0,
        transport=transport,
    )
    card = EmpathyCard(
        conversation_id="conv_1",
        surface_issue="你好呀",
        intent=Intent.CONSULT,
        intent_source="evidence_free_rules:greeting",
        scenario="product_consultation",
        missing_information=["具体咨询问题"],
        risk_level=RiskLevel.LOW,
        next_state=ConversationState.ASK,
        schema_version="1.0",
    )

    generated = provider.generate(ConversationRequest(message="你好呀"), card, None)

    assert generated.message == "在的，请直接告诉我想咨询的问题。"
    assert generated.media_knowledge_ids == []
    payload = observed["payload"]
    assert "不得新增产品、功效、订单" in payload["messages"][0]["content"]
    context = json.loads(payload["messages"][-1]["content"])
    assert context["business_evidence_required"] is False
    assert context["approved_evidence"] == []


def test_generates_generic_guidance_without_presenting_it_as_product_fact() -> None:
    observed = {}

    def transport(request, _timeout):
        observed["payload"] = json.loads(request.data)
        return _response(
            {
                "message": "无法确认这款配方；可以先少量试涂并观察唇部感受。",
                "media_knowledge_ids": [],
            }
        )

    provider = OpenAICompatibleIntentProvider(
        api_key="test-secret",
        base_url="https://llm.example/v1",
        model="demo-model",
        timeout_seconds=1,
        retry_limit=0,
        transport=transport,
    )
    card = EmpathyCard(
        conversation_id="conv_1",
        surface_issue="不知道具体系列",
        intent=Intent.PURCHASE,
        intent_source="generic_product_guidance_rules",
        scenario="product_selection",
        confirmed_facts=["这个口红会不会拔干", "不知道具体系列"],
        missing_information=["具体商品身份仍未确认"],
        risk_level=RiskLevel.LOW,
        next_state=ConversationState.RESOLVE,
        schema_version="1.0",
    )

    provider.generate(ConversationRequest(message="不知道具体系列"), card, None)

    payload = observed["payload"]
    assert "仍需回答用户问题" in payload["messages"][0]["content"]
    assert "不得表述成该商品的官方结论" in payload["messages"][0]["content"]
    context = json.loads(payload["messages"][-1]["content"])
    assert context["business_evidence_required"] is False


def test_rejects_ask_response_with_multiple_questions() -> None:
    provider = OpenAICompatibleIntentProvider(
        api_key="test-secret",
        base_url="https://llm.example/v1",
        model="demo-model",
        timeout_seconds=1,
        retry_limit=0,
        transport=lambda _request, _timeout: _response(
            {"message": "你的肤色偏黄吗？还是偏粉？", "media_knowledge_ids": []}
        ),
    )
    card = EmpathyCard(
        conversation_id="conv_1",
        surface_issue="选择粉底色号",
        intent=Intent.PURCHASE,
        scenario="purchase_consultation",
        risk_level=RiskLevel.LOW,
        next_state=ConversationState.ASK,
        schema_version="1.0",
    )

    with pytest.raises(ValueError, match="at most one question"):
        provider.generate(ConversationRequest(message="怎么选色号"), card, None)


def test_ask_response_must_match_runtime_suggested_replies() -> None:
    observed = {}

    def transport(request, _timeout):
        observed["payload"] = json.loads(request.data)
        return _response(
            {
                "message": "您想选日常通勤、秋冬氛围、突出唇妆，还是不确定？",
                "media_knowledge_ids": [],
            }
        )

    provider = OpenAICompatibleIntentProvider(
        api_key="test-secret",
        base_url="https://llm.example/v1",
        model="demo-model",
        timeout_seconds=1,
        retry_limit=0,
        transport=transport,
    )
    card = EmpathyCard(
        conversation_id="conv_1",
        surface_issue="赤茶红还是枫叶红",
        intent=Intent.PURCHASE,
        scenario="product_selection",
        missing_information=["期望的口红风格"],
        risk_level=RiskLevel.LOW,
        next_state=ConversationState.ASK,
        schema_version="1.0",
    )

    with pytest.raises(ValueError, match="allowed suggested replies"):
        provider.generate(ConversationRequest(message="两个色号怎么选"), card, None)

    context = json.loads(observed["payload"]["messages"][-1]["content"])
    assert context["allowed_suggested_replies"] == ["日常柔和", "浓郁有氛围", "暂时不确定"]
    assert "不使用“亲”" in observed["payload"]["messages"][0]["content"]
