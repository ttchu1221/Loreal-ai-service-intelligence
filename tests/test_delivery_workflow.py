from fastapi.testclient import TestClient

from loreal_ai_service_intelligence.api.application import create_app
from loreal_ai_service_intelligence.infrastructure.repository import MemoryRepository


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
    assert len(second["evidence"]) == 1
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
    card = client.get(f"/v1/agent/conversations/{created['conversation_id']}").json()[
        "empathy_card"
    ]
    assert card["case_revision"] == 2
    assert card["entities"]["product"] == "更正后的粉底"


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


def test_consumer_sees_agent_reply_and_controls_resolution() -> None:
    client = make_client()
    message = "请说明一个不存在的产品功效"
    created = client.post("/v1/conversations", json={"message": message}).json()
    conversation_id = created["conversation_id"]
    event = client.get("/v1/agent/events").json()[0]

    waiting = client.get(f"/v1/conversations/{conversation_id}/ticket").json()
    assert waiting["status"] == "waiting_for_agent"
    assert waiting["latest_agent_reply"] is None

    package = client.get(f"/v1/agent/conversations/{conversation_id}").json()["handoff_package"]
    assert package["original_messages"] == [message]
    assert package["handoff_reason"]
    assert package["case"]["original_statement"] == message

    agent_reply = "请先暂停叠加，五分钟后再上粉底。"
    response = client.post(
        f"/v1/agent/events/{event['event_id']}/actions",
        json={"action": "reply", "parameters": {"note": agent_reply}},
    )
    assert response.status_code == 200
    replied = client.get(f"/v1/conversations/{conversation_id}/ticket").json()
    assert replied["status"] == "agent_replied"
    assert replied["latest_agent_reply"] == agent_reply
    restored = client.get(f"/v1/conversations/{conversation_id}").json()
    assert restored["transcript"][-1]["role"] == "agent"
    assert restored["transcript"][-1]["content"] == agent_reply

    follow_up = "我已经等了五分钟，接下来应该怎么做？"
    forwarded = client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"message": follow_up}
    ).json()
    assert forwarded["state"] == "HANDOFF"
    assert forwarded["message"] == "消息已同步给人工客服，请等待客服回复。"
    package = client.get(f"/v1/agent/conversations/{conversation_id}").json()["handoff_package"]
    assert package["transcript"][-1]["role"] == "user"
    assert package["transcript"][-1]["content"] == follow_up

    blank_reply = client.post(
        f"/v1/agent/events/{event['event_id']}/actions",
        json={"action": "reply", "parameters": {"note": "  "}},
    )
    assert blank_reply.status_code == 422

    resolved = client.post(
        f"/v1/conversations/{conversation_id}/ticket/results",
        json={"event": "user_confirmed_resolved", "note": "消费者确认"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    invalid = client.post(
        f"/v1/conversations/{conversation_id}/ticket/results",
        json={"event": "agent_replied", "note": "消费者不可伪造客服回复"},
    )
    assert invalid.status_code == 422


def test_agent_can_close_conversation_and_consumer_can_reopen_it() -> None:
    client = make_client()
    created = client.post("/v1/conversations", json={"message": "我要人工客服"}).json()
    conversation_id = created["conversation_id"]
    event = client.get("/v1/agent/events").json()[0]

    closed = client.post(
        f"/v1/agent/events/{event['event_id']}/actions",
        json={"action": "close", "parameters": {"note": "本次人工处理完成"}},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "completed"
    assert client.get("/v1/agent/events").json() == []
    assert client.get(f"/v1/conversations/{conversation_id}/ticket").json()["status"] == (
        "action_completed"
    )

    reopened = client.post(
        f"/v1/conversations/{conversation_id}/ticket/results",
        json={"event": "reopened", "note": "消费者仍需处理"},
    )
    assert reopened.status_code == 200
    queue = client.get("/v1/agent/events").json()
    assert len(queue) == 1
    assert queue[0]["status"] == "waiting_for_agent"


def test_agent_intake_aggregates_context_and_returns_assistant_brief() -> None:
    client = make_client()
    response = client.post(
        "/v1/agent/intakes",
        json={
            "customer_id": "customer_demo_001",
            "current_message": "订单还没收到，我很着急，帮我查一下物流",
            "transcript": [
                {
                    "role": "user",
                    "content": "昨天说今天能到",
                    "created_at": "2026-09-14T10:00:00Z",
                }
            ],
            "orders": [
                {
                    "order_id": "order_demo_001",
                    "product_name": "演示粉底液",
                    "status": "shipped",
                    "created_at": "2026-09-13T08:00:00Z",
                }
            ],
            "historical_tickets": [
                {
                    "ticket_id": "ticket_demo_001",
                    "category": "logistics",
                    "status": "closed",
                    "summary": "消费者曾咨询发货时间",
                    "created_at": "2026-09-13T12:00:00Z",
                }
            ],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["event"]["status"] == "processing"
    brief = body["conversation"]["assistant_brief"]
    assert brief["emotion"] == "anxious"
    assert brief["escalation_target"] == "logistics"
    assert {item["source"] for item in brief["service_timeline"]} == {
        "chat",
        "order",
        "ticket",
    }
    assert "核对关联订单状态" in brief["next_actions"]
    assert brief["reply_draft"]
    assert (
        client.get("/v1/agent/events").json()[0]["conversation_id"]
        == body["event"]["conversation_id"]
    )


def test_agent_intake_routes_business_and_safety_escalations() -> None:
    client = make_client()
    scenarios = (
        ("我要投诉，客服一直不处理", "complaint"),
        ("申请退款和退货", "after_sales"),
        ("使用后呼吸困难并持续红肿", "risk_specialist"),
    )
    for index, (message, target) in enumerate(scenarios):
        response = client.post(
            "/v1/agent/intakes",
            json={"customer_id": f"customer-{index}", "current_message": message},
        )
        assert response.status_code == 201
        assert response.json()["conversation"]["assistant_brief"]["escalation_target"] == target


def test_agent_assistance_tracks_sources_feedback_and_risk_lifecycle() -> None:
    client = make_client()
    created = client.post(
        "/v1/agent/intakes",
        json={
            "source_conversation_id": "upstream-1001",
            "customer_id": "customer-1001",
            "current_message": "使用后持续红肿，我很着急",
            "orders": [
                {
                    "order_id": "order-1001",
                    "product_name": "演示产品",
                    "status": "delivered",
                    "created_at": "2026-09-14T08:00:00Z",
                }
            ],
        },
    ).json()
    conversation_id = created["event"]["conversation_id"]
    brief = created["conversation"]["assistant_brief"]

    assert brief["urgency"] == "high"
    assert brief["known_facts"]
    assert {item["source"] for item in brief["source_evidence"]} >= {"chat", "order"}
    assert created["conversation"]["risk_tracking"]["status"] == "open"

    feedback = client.post(
        f"/v1/agent/conversations/{conversation_id}/suggestion-feedback",
        json={"decision": "edited", "final_reply": "已人工调整并发送的安全回复。"},
    )
    assert feedback.status_code == 201
    assert feedback.json()["decision"] == "edited"

    escalated = client.patch(
        f"/v1/agent/conversations/{conversation_id}/risk",
        json={"status": "escalated", "note": "已升级风险专员"},
    )
    assert escalated.status_code == 200
    assert escalated.json()["status"] == "escalated"
    closed_without_note = client.patch(
        f"/v1/agent/conversations/{conversation_id}/risk", json={"status": "closed"}
    )
    assert closed_without_note.status_code == 409
    closed = client.patch(
        f"/v1/agent/conversations/{conversation_id}/risk",
        json={"status": "closed", "note": "消费者确认已获得安全指引"},
    )
    assert closed.status_code == 200
    restored = client.get(f"/v1/agent/conversations/{conversation_id}").json()
    assert restored["risk_tracking"]["status"] == "closed"
    assert restored["suggestion_feedback"][0]["final_reply"] == "已人工调整并发送的安全回复。"


def test_suggestion_feedback_validates_human_decision_details() -> None:
    client = make_client()
    created = client.post(
        "/v1/agent/intakes",
        json={"customer_id": "customer-feedback", "current_message": "查询订单进度"},
    ).json()
    conversation_id = created["event"]["conversation_id"]
    path = f"/v1/agent/conversations/{conversation_id}/suggestion-feedback"

    assert client.post(path, json={"decision": "edited"}).status_code == 422
    assert client.post(path, json={"decision": "rejected"}).status_code == 422
    adopted = client.post(path, json={"decision": "adopted"})
    assert adopted.status_code == 201
    assert adopted.json()["final_reply"] == adopted.json()["original_draft"]


def test_minimum_workspaces_are_available() -> None:
    client = make_client()

    consumer_response = client.get("/workspace/consumer")
    agent_response = client.get("/workspace/agent")
    consumer = consumer_response.text
    agent = agent_response.text
    assert consumer_response.headers["cache-control"] == "no-store"
    assert agent_response.headers["cache-control"] == "no-store"
    assert "L'Oréal 智慧美妆顾问" in consumer
    assert 'aria-label="发送消息"' in consumer
    assert "setSending(true)" in consumer
    assert "const messagesList=document.getElementById('messages')" in consumer
    assert "messagesList.append(bubble)" in consumer
    assert "messageInput.value=''" in consumer
    assert "messageInput.value='';setSending(true)" in consumer
    assert "messageInput.value=text;showError(e)" in consumer
    assert 'id="clearButton"' in consumer
    assert "function clearConversation()" in consumer
    assert "localStorage.removeItem('lorealConversationId')" in consumer
    assert "顾问。\\n可以告诉我" in consumer
    assert "选择人工时，\\n这里会同步" in consumer
    assert "min-height:0;overflow-y:auto" in consumer
    assert "overscroll-behavior-y:contain" in consumer
    assert "touch-action:pan-y" in consumer
    assert "animation:rise .24s ease-out;flex:0 0 auto" in consumer
    assert "flex:0 0 auto;padding:18px 24px" in consumer
    assert "message.value='发生在涂粉底后" not in consumer
    assert "restoreConversation()" in consumer
    assert "if(['HANDOFF','BLOCK'].includes(b.state))startPolling()" in consumer
    assert "历史会话已失效，请重新开始咨询" in consumer
    assert "转人工" in consumer
    assert "人工客服工作台" in agent
    assert "发送回复" in agent
    assert "if(!selected&&b.length)await selectEvent(b[0],false)" in agent
    assert "const eventsList=document.getElementById('events')" in agent
    assert ".join('\\n')" in agent
    assert ".join('\n')" not in agent
    assert "function localTime(value)" in agent
    assert "查看 AI 交接摘要与处理建议" in agent
    assert "关闭会话" in agent
    assert "async function closeConversation()" in agent
    assert "function statusLabel(value)" in agent
    assert "event.key==='Enter'&&!event.shiftKey" in agent
    assert "发送中…" in agent
    assert ">已核对用户使用步骤" not in agent
    assert "await selectEvent(selected,false)" in agent
    assert "人工客服 · 刚刚" in consumer
    assert "addBubble(b.latest_agent_reply,'agent')" in consumer
    assert "同步失败" in agent
    assert "确认已解决" in consumer
    assert "仍需处理" in consumer
    assert "同步最新状态" in agent
