from fastapi.testclient import TestClient

from loreal_ai_service_intelligence.api.application import create_app
from loreal_ai_service_intelligence.domain.models import Intent, IntentResult
from loreal_ai_service_intelligence.infrastructure.repository import MemoryRepository


class SuccessfulProvider:
    def classify(self, text: str) -> IntentResult:
        del text
        return IntentResult(intent=Intent.AFTER_SALES, confidence=0.95, source="test_llm")


class FailingProvider:
    def classify(self, text: str) -> IntentResult:
        del text
        raise TimeoutError("provider timed out")


class LowConfidenceProvider:
    def classify(self, text: str) -> IntentResult:
        del text
        return IntentResult(intent=Intent.OTHER, confidence=0.2, source="test_llm")


class MustNotRunPolicy:
    def decide(self, conversation_id, request, existing):
        del conversation_id, request, existing
        raise AssertionError("candidate policy must not run before the safety gate")


def _agent_card(client: TestClient, message: str) -> dict:
    response = client.post("/v1/conversations", json={"message": message}).json()
    return client.get(f"/v1/agent/conversations/{response['conversation_id']}").json()[
        "empathy_card"
    ]


def test_uses_valid_confident_primary_intent() -> None:
    client = TestClient(create_app(MemoryRepository(), SuccessfulProvider()))
    card = _agent_card(client, "帮我查询相关问题")
    assert card["intent"] == "after_sales"
    assert card["intent_source"] == "test_llm"


def test_provider_timeout_falls_back_to_rules(caplog) -> None:
    client = TestClient(create_app(MemoryRepository(), FailingProvider()))
    card = _agent_card(client, "第一次使用面霜")
    assert card["intent"] == "usage"
    assert card["intent_source"] == "rules"
    assert "error_type=TimeoutError" in caplog.text


def test_low_confidence_falls_back_to_rules() -> None:
    client = TestClient(create_app(MemoryRepository(), LowConfidenceProvider()))
    card = _agent_card(client, "订单退款怎么处理")
    assert card["intent"] == "after_sales"
    assert card["intent_source"] == "rules"


def test_safety_rules_run_before_primary_provider() -> None:
    client = TestClient(create_app(MemoryRepository(), SuccessfulProvider()))
    card = _agent_card(client, "使用后呼吸困难")
    assert card["intent"] == "complaint"
    assert card["intent_source"] == "safety_rules"
    assert card["next_state"] == "BLOCK"


def test_safety_gate_cannot_be_bypassed_by_injected_decision_policy() -> None:
    client = TestClient(create_app(MemoryRepository(), decision_policy=MustNotRunPolicy()))

    response = client.post("/v1/conversations", json={"message": "使用后呼吸困难"})

    assert response.status_code == 201
    assert response.json()["state"] == "BLOCK"
