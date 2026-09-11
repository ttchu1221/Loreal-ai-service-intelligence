from fastapi.testclient import TestClient

from loreal_ai_service_intelligence.main import create_app
from loreal_ai_service_intelligence.repository import MemoryRepository


def make_client() -> TestClient:
    return TestClient(create_app(MemoryRepository()))


def test_pilling_flow_asks_once_then_returns_single_condition_guide() -> None:
    client = make_client()
    first = client.post("/v1/conversations", json={"message": "我的底妆总是搓泥"}).json()

    assert first["state"] == "ASK"
    assert "skip" in first["available_actions"]
    second = client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "发生在涂粉底时，我已经试过换粉扑"},
    ).json()

    assert second["state"] == "GUIDE"
    assert second["evidence"][0]["knowledge_id"] == "KB-PILLING-001"
    assert "只调整一个条件" in second["evidence"][0]["excerpt"]


def test_case_revision_preserves_history_and_unknown_fields() -> None:
    client = make_client()
    created = client.post(
        "/v1/conversations", json={"message": "粉底搓泥", "product": "演示粉底"}
    ).json()
    path = f"/v1/conversations/{created['conversation_id']}/case/revisions"

    revised = client.post(
        path,
        json={
            "facts": {"product": "更正后的粉底", "step": "防晒后"},
            "unknown_fields": ["skincare_amount"],
            "reason": "用户更正产品并补充步骤",
        },
    ).json()

    assert revised["current_revision"] == 2
    assert len(revised["revisions"]) == 2
    assert revised["revisions"][0]["facts"]["product"] == "演示粉底"
    assert revised["revisions"][1]["facts"]["product"] == "更正后的粉底"


def test_attempt_separates_skip_execution_and_observation_and_rejects_duplicate() -> None:
    client = make_client()
    conversation = client.post("/v1/conversations", json={"message": "底妆搓泥"}).json()
    path = f"/v1/conversations/{conversation['conversation_id']}/attempts"
    payload = {
        "recommendation": "减少护肤品用量",
        "purpose": "排除用量过多",
        "instructions": "只减少一半用量，其他条件保持不变",
        "observation_target": "同一区域是否仍起屑",
        "exit_condition": "出现不适或没有改善时停止",
    }

    attempt = client.post(path, json=payload)
    assert attempt.status_code == 201
    duplicate = client.post(path, json=payload)
    assert duplicate.status_code == 409

    attempt_id = attempt.json()["attempt_id"]
    skipped = client.patch(f"{path}/{attempt_id}", json={"execution_status": "skipped"}).json()
    assert skipped["execution_status"] == "skipped"
    assert skipped["outcome"] == "unknown"


def test_executed_attempt_requires_observation() -> None:
    client = make_client()
    conversation = client.post("/v1/conversations", json={"message": "底妆搓泥"}).json()
    path = f"/v1/conversations/{conversation['conversation_id']}/attempts"
    attempt = client.post(
        path,
        json={
            "recommendation": "等待成膜",
            "purpose": "排除层间未成膜",
            "instructions": "等待五分钟",
            "observation_target": "是否仍搓泥",
            "exit_condition": "无改善则停止",
        },
    ).json()

    response = client.patch(
        f"{path}/{attempt['attempt_id']}", json={"execution_status": "executed"}
    )
    assert response.status_code == 422


def test_ticket_result_events_remain_distinct_and_support_reopen() -> None:
    client = make_client()
    blocked = client.post("/v1/conversations", json={"message": "使用后持续红肿"}).json()
    client.post(
        f"/v1/conversations/{blocked['conversation_id']}/handoff",
        json={"accepted": True, "idempotency_key": "ticket-state-test"},
    )
    path = f"/v1/agent/conversations/{blocked['conversation_id']}/ticket/results"

    statuses = []
    for event in (
        "agent_replied",
        "action_completed",
        "user_confirmed_resolved",
        "reopened",
    ):
        response = client.post(path, json={"event": event, "note": event})
        assert response.status_code == 200
        statuses.append(response.json()["status"])

    assert statuses == ["agent_replied", "action_completed", "resolved", "reopened"]
    assert len(response.json()["result_events"]) == 4


def test_minimum_workspaces_are_available() -> None:
    client = make_client()

    assert "底妆搓泥排查" in client.get("/workspace/consumer").text
    assert "人工客服工作台" in client.get("/workspace/agent").text
