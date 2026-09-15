from fastapi import FastAPI
from fastapi.testclient import TestClient

from loreal_ai_service_intelligence.api.application import create_app
from loreal_ai_service_intelligence.api.mock import (
    MockDecisionRequest,
    MockDecisionService,
    create_mock_router,
)
from loreal_ai_service_intelligence.config import Settings
from loreal_ai_service_intelligence.infrastructure.repository import MemoryRepository


def make_client() -> TestClient:
    return TestClient(create_app(MemoryRepository()))


def test_mock_contract_asks_for_one_missing_pilling_detail() -> None:
    response = make_client().post(
        "/v1/mock/decisions",
        json={
            "request_id": "mock-ask-1",
            "current_message": "我的底妆搓泥",
            "confirmed_facts": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "ASK"
    assert body["question"].count("？") == 1
    assert body["provider"] == "deterministic_mock"
    assert body["schema_version"] == "1.0"


def test_mock_contract_returns_structured_single_condition_guide() -> None:
    response = make_client().post(
        "/v1/mock/decisions",
        json={
            "request_id": "mock-guide-1",
            "current_message": "底妆搓泥",
            "confirmed_facts": {"pilling_step": "粉底后"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "GUIDE"
    assert set(body["guide"]) == {
        "purpose",
        "instruction",
        "observation_target",
        "exit_condition",
    }
    assert body["evidence_ids"] == ["KB-PILLING-001"]


def test_mock_contract_prioritizes_risk_and_after_sales() -> None:
    client = make_client()
    blocked = client.post(
        "/v1/mock/decisions",
        json={"request_id": "mock-risk-1", "current_message": "搓泥而且持续刺痛"},
    ).json()
    handed_off = client.post(
        "/v1/mock/decisions",
        json={"request_id": "mock-ho-1", "current_message": "不想排查，直接找客服"},
    ).json()

    assert blocked["state"] == "BLOCK"
    assert blocked["guide"] is None
    assert handed_off["state"] == "HANDOFF"


def test_mock_contract_exits_after_two_failed_attempts() -> None:
    response = make_client().post(
        "/v1/mock/decisions",
        json={
            "request_id": "mock-exit-1",
            "current_message": "底妆还是搓泥",
            "confirmed_facts": {"pilling_step": "粉底后"},
            "attempts": [
                {
                    "recommendation": "减少护肤品用量",
                    "execution_status": "executed",
                    "outcome": "unchanged",
                },
                {
                    "recommendation": "等待成膜",
                    "execution_status": "executed",
                    "outcome": "worse",
                },
            ],
        },
    )

    assert response.json()["state"] == "HANDOFF"
    assert response.json()["handoff_reason"] == "两次尝试无改善"


def test_mock_contract_rejects_unknown_fields() -> None:
    response = make_client().post(
        "/v1/mock/decisions",
        json={
            "request_id": "mock-invalid-1",
            "current_message": "底妆搓泥",
            "unfrozen_field": "must fail",
        },
    )

    assert response.status_code == 422


def test_mock_service_is_callable_without_http() -> None:
    settings = Settings()
    service = MockDecisionService(settings.rule_version, settings.knowledge_version)

    result = service.decide(
        MockDecisionRequest(request_id="python-call-1", current_message="我要直接转人工")
    )

    assert result.state.value == "HANDOFF"


def test_mock_endpoint_can_be_disabled_for_production() -> None:
    application = FastAPI()
    application.include_router(
        create_mock_router(MockDecisionService("risk-rules-v1", "demo-knowledge-v1"), enabled=False)
    )

    response = TestClient(application).post(
        "/v1/mock/decisions",
        json={"request_id": "disabled-1", "current_message": "底妆搓泥"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "mock API is disabled"}
