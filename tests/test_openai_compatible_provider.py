import json

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
            {"message": "听起来你更在意上妆后起屑。先减少妆前用量，再观察粉底是否更服帖。"}
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

    message = provider.generate(ConversationRequest(message="还是会起屑"), card, None)

    assert "更在意上妆后起屑" in message
    payload = observed["payload"]
    assert payload["temperature"] == 0.3
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
        transport=lambda _request, _timeout: _response({"message": "  "}),
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
