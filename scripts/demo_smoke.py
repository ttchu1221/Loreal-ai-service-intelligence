"""使用纯虚构数据验证演示全链路，不连接 MongoDB 或 external service。"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from loreal_ai_service_intelligence.api.application import create_app
from loreal_ai_service_intelligence.infrastructure.repository import MemoryRepository


def run_demo_smoke() -> list[tuple[str, int, str]]:
    client = TestClient(create_app(MemoryRepository()))
    results: list[tuple[str, int, str]] = []

    def call(name: str, method: str, path: str, expected: int = 200, **kwargs: Any) -> Any:
        response = client.request(method, path, **kwargs)
        if response.status_code != expected:
            raise RuntimeError(f"{name}: HTTP {response.status_code}: {response.text}")
        if expected == 204:
            body = None
        elif response.headers.get("content-type", "").startswith("application/json"):
            body = response.json()
        else:
            body = response.text
        state = body.get("state") or body.get("status") if isinstance(body, dict) else "ok"
        results.append((name, response.status_code, str(state or "ok")))
        return body

    mock = call(
        "Mock 首轮决策",
        "POST",
        "/v1/mock/decisions",
        json={"request_id": "demo-001", "current_message": "我的底妆总是搓泥"},
    )
    agent_mock = call(
        "客服插件 Mock",
        "POST",
        "/v1/mock/agent-assists",
        json={
            "request_id": "agent-demo-001",
            "context": {
                "source_conversation_id": "upstream-smoke-001",
                "customer_id": "customer-smoke-001",
                "current_message": "上次承诺今天处理退款，但现在还没完成",
                "historical_tickets": [
                    {
                        "ticket_id": "ticket-smoke-001",
                        "category": "refund",
                        "status": "processing",
                        "summary": "客服承诺今天完成退款",
                        "created_at": "2026-09-14T09:00:00Z",
                    }
                ],
            },
        },
    )
    intake = call(
        "客服进线聚合",
        "POST",
        "/v1/agent/intakes",
        201,
        json={
            "source_conversation_id": "upstream-smoke-002",
            "customer_id": "customer-smoke-001",
            "current_message": "快递还没收到，我很着急",
            "transcript": [],
            "orders": [
                {
                    "order_id": "order-smoke-001",
                    "product_name": "演示粉底",
                    "status": "shipped",
                    "created_at": "2026-09-14T08:00:00Z",
                }
            ],
            "historical_tickets": [],
        },
    )
    intake_conversation_id = intake["event"]["conversation_id"]
    call(
        "采纳 AI 回复草稿",
        "POST",
        f"/v1/agent/conversations/{intake_conversation_id}/suggestion-feedback",
        201,
        json={"decision": "adopted"},
    )
    call(
        "更新风险跟踪",
        "PATCH",
        f"/v1/agent/conversations/{intake_conversation_id}/risk",
        json={"status": "monitoring", "note": "客服已开始核对物流信息"},
    )
    conversation = call(
        "消费者开始排查",
        "POST",
        "/v1/conversations",
        201,
        json={"message": "我的底妆总是搓泥", "product": "演示粉底"},
    )
    conversation_id = conversation["conversation_id"]
    guide = call(
        "消费者补充信息",
        "POST",
        f"/v1/conversations/{conversation_id}/messages",
        json={"message": "发生在涂粉底后，试过换粉扑"},
    )
    case = call(
        "更正 Case",
        "POST",
        f"/v1/conversations/{conversation_id}/case/revisions",
        json={
            "facts": {"pilling_step": "粉底后", "failed_history": "换过粉扑"},
            "unknown_fields": ["skincare_amount"],
            "reason": "演示用户补充",
        },
    )
    attempt = call(
        "创建 Attempt",
        "POST",
        f"/v1/conversations/{conversation_id}/attempts",
        201,
        json={
            "recommendation": "减少底妆前护肤品用量",
            "purpose": "排除用量过多",
            "instructions": "其他条件不变，只减少一半用量",
            "observation_target": "同一区域是否搓泥",
            "exit_condition": "无改善或不适时停止",
        },
    )
    updated_attempt = call(
        "记录 Attempt 结果",
        "PATCH",
        f"/v1/conversations/{conversation_id}/attempts/{attempt['attempt_id']}",
        json={
            "execution_status": "executed",
            "observation": "搓泥减少但未完全消失",
            "outcome": "improved",
        },
    )
    call(
        "记录未解决反馈",
        "POST",
        f"/v1/conversations/{conversation_id}/feedback",
        204,
        json={"result_id": guide["result_id"], "resolved": False, "comment": "希望人工确认"},
    )
    event = call(
        "确认转人工",
        "POST",
        f"/v1/conversations/{conversation_id}/handoff",
        json={"accepted": True, "idempotency_key": "demo-handoff-001"},
    )
    call("读取客服队列", "GET", "/v1/agent/events")
    handoff = call("读取完整交接包", "GET", f"/v1/agent/conversations/{conversation_id}")
    call(
        "发送人工回复",
        "POST",
        f"/v1/agent/events/{event['event_id']}/actions",
        json={"action": "reply", "parameters": {"note": "建议暂停叠加并核对使用顺序"}},
    )
    for name, ticket_event in (
        ("记录动作完成", "action_completed"),
        ("用户确认解决", "user_confirmed_resolved"),
        ("重开 Ticket", "reopened"),
    ):
        call(
            name,
            "POST",
            f"/v1/agent/conversations/{conversation_id}/ticket/results",
            json={"event": ticket_event, "note": name},
        )
    call("读取服务洞察", "GET", "/v1/insights/overview")
    call("消费者工作区", "GET", "/workspace/consumer")
    call("客服工作区", "GET", "/workspace/agent")
    risk = call(
        "风险阻断",
        "POST",
        "/v1/conversations",
        201,
        json={"message": "使用后持续红肿和刺痛"},
    )

    assert mock["state"] == "ASK"
    assert agent_mock["provider"] == "deterministic_agent_mock"
    assert agent_mock["empathy_understanding"]["historical_promises"]
    assert intake["conversation"]["assistant_brief"]["escalation_target"] == "logistics"
    assert conversation["state"] == "ASK" and guide["state"] == "GUIDE"
    assert case["current_revision"] == 2 and updated_attempt["outcome"] == "improved"
    assert handoff["handoff_package"]["ticket"]["status"] == "waiting_for_agent"
    assert risk["state"] == "BLOCK"
    return results


def main() -> None:
    for name, status, state in run_demo_smoke():
        print(f"{name:<20} HTTP {status:<3} {state}")
    print("FULL_CHAIN_OK")


if __name__ == "__main__":
    main()
