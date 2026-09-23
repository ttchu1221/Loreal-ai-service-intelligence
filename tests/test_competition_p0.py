from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from loreal_ai_service_intelligence.api.application import create_app
from loreal_ai_service_intelligence.domain.competition import P0ContextSnapshot
from loreal_ai_service_intelligence.infrastructure.repository import MemoryRepository
from loreal_ai_service_intelligence.providers.context import InMemoryContextDataProvider

NOW = "2026-09-21T08:00:00Z"
LATER = "2026-10-21T08:00:00Z"


def base_snapshot(**overrides):
    data = {
        "snapshot_id": "snapshot-1",
        "case_id": "case-1",
        "conversation_id": "conversation-1",
        "issue_id": "issue-1",
        "customer_id": "customer-1",
        "current_message_id": "message-1",
        "cutoff_message_seq": 1,
        "current_message": "这款产品的规格是什么？",
        "chat_history": [
            {
                "message_id": "message-1",
                "message_seq": 1,
                "role": "consumer",
                "content": "这款产品的规格是什么？",
                "created_at": NOW,
            }
        ],
        "scene_major": "普通咨询",
        "scene_minor": "W01",
        "scene_source": "internal_mapping",
        "products": [
            {
                "product_id": "product-1",
                "sku": "SKU-1",
                "name": "演示面霜",
                "source_id": "catalog-1",
                "observed_at": NOW,
                "valid_until": LATER,
            }
        ],
        "knowledge_evidence": [
            {
                "evidence_id": "knowledge-1",
                "source": "approved-product-guide",
                "excerpt": "演示面霜规格为 50ml。",
                "product_id": "product-1",
                "scope": "product-specification",
                "version": "v1",
                "observed_at": NOW,
                "valid_until": LATER,
                "valid": True,
            }
        ],
        "context_version": "context-v1",
        "captured_at": NOW,
    }
    data.update(overrides)
    return data


def make_client(provider=None):
    return TestClient(create_app(MemoryRepository(), context_provider=provider))


def analyze(client: TestClient, snapshot: dict):
    response = client.post("/v1/competition/sessions/analyze", json=snapshot)
    assert response.status_code == 201, response.text
    return response.json()


def test_tc01_auto_reply_requires_valid_whitelist_evidence_and_records_receipt() -> None:
    client = make_client()
    session = analyze(client, base_snapshot())
    decision = session["decision"]

    assert decision["service_mode"] == "AUTO_REPLY"
    assert decision["send_allowed"] is True
    assert decision["reply_audience"] == "consumer"
    assert decision["evidence"][0]["source_type"] == "chat"
    assert any(item["source_type"] == "knowledge" for item in decision["evidence"])

    payload = {
        "decision_id": decision["decision_id"],
        "based_on_message_id": "message-1",
        "body": decision["reply_text"],
        "idempotency_key": "send-1",
        "actor": "system",
        "simulate_result": "sent",
    }
    first = client.post("/v1/competition/sessions/conversation-1/messages", json=payload)
    second = client.post("/v1/competition/sessions/conversation-1/messages", json=payload)
    assert first.status_code == 201
    assert first.json()["status"] == "SENT"
    assert first.json()["channel"] == "SIMULATED"
    assert first.json()["delivery_id"] == second.json()["delivery_id"]


def test_tc06_repeated_refund_intake_restores_promise_without_claiming_completion() -> None:
    client = make_client()
    snapshot = base_snapshot(
        current_message="上次说会跟进退款，现在还是没有结果",
        scene_major="售后处理",
        scene_minor="refund_progress",
        products=[],
        knowledge_evidence=[],
        unresolved_count=0,
        tickets=[
            {
                "ticket_id": "ticket-1",
                "owner_customer_id": "customer-1",
                "category": "refund",
                "status": "processing",
                "summary": "客服承诺继续跟进退款进度",
                "source_id": "ticket-system",
                "observed_at": NOW,
                "valid_until": LATER,
            }
        ],
        orders=[
            {
                "order_id": "order-1",
                "owner_customer_id": "customer-1",
                "status": "refund_pending",
                "source_id": "order-system",
                "observed_at": NOW,
                "valid_until": LATER,
            }
        ],
    )
    session = analyze(client, snapshot)
    decision = session["decision"]

    assert decision["service_mode"] == "AGENT_ASSIST"
    assert decision["send_allowed"] is False
    assert "承诺" in decision["trajectory_summary"]
    assert "处理中" in decision["reply_text"] or "processing" in decision["reply_text"]
    assert "已到账" not in decision["reply_text"]


@pytest.mark.parametrize("message", ["使用后持续泛红和刺痛", "我已经就医了"])
def test_tc08_tc09_safety_signal_forces_takeover_and_creates_local_risk(message: str) -> None:
    client = make_client()
    session = analyze(
        client,
        base_snapshot(
            current_message=message,
            scene_major="风险服务",
            scene_minor="adverse_reaction",
            products=[],
            knowledge_evidence=[],
        ),
    )

    assert session["decision"]["service_mode"] == "HUMAN_REQUIRED"
    assert session["decision"]["reply_text"] is None
    assert session["decision"]["send_allowed"] is False
    assert session["takeover"]["takeover_locked"] is True
    assert session["risk"]["status"] == "DETECTED"
    assert message in session["risk"]["trigger_quote"] or session["risk"]["trigger_quote"]


def test_tc10_user_requested_human_never_requires_second_confirmation() -> None:
    session = analyze(
        make_client(),
        base_snapshot(user_requested_human=True, current_message="我要人工客服"),
    )
    assert session["decision"]["service_mode"] == "HUMAN_REQUIRED"
    assert session["takeover"]["status"] == "WAITING"
    assert "人工" in session["decision"]["mode_reason"]


def test_tc11_missing_product_generates_one_agent_follow_up_not_fake_sku() -> None:
    session = analyze(
        make_client(),
        base_snapshot(
            current_message="这款怎么用",
            scene_minor="W02",
            products=[],
            knowledge_evidence=[],
        ),
    )
    decision = session["decision"]
    assert decision["service_mode"] == "AGENT_ASSIST"
    assert decision["follow_up_question"] == "请确认明确商品或 SKU。"
    assert "SKU-1" not in decision["reply_text"]


def test_tc12_invalid_knowledge_and_tc13_conflict_force_human() -> None:
    client = make_client()
    invalid = base_snapshot()
    invalid["knowledge_evidence"][0]["valid"] = False
    assert analyze(client, invalid)["decision"]["service_mode"] == "HUMAN_REQUIRED"

    conflict = base_snapshot(
        conversation_id="conversation-conflict",
        current_message_id="message-conflict",
        current_message="退款处理到哪里了",
        products=[],
        knowledge_evidence=[],
        orders=[
            {
                "order_id": "order-1",
                "owner_customer_id": "customer-1",
                "status": "refunded",
                "source_id": "orders",
                "observed_at": NOW,
            }
        ],
        tickets=[
            {
                "ticket_id": "ticket-1",
                "owner_customer_id": "customer-1",
                "category": "refund",
                "status": "processing",
                "summary": "退款仍处理中",
                "source_id": "tickets",
                "observed_at": NOW,
            }
        ],
    )
    result = analyze(client, conflict)
    assert result["decision"]["service_mode"] == "HUMAN_REQUIRED"
    assert "冲突" in result["decision"]["mode_reason"]


def test_tc14_multiple_orders_assist_and_tc15_unresolved_escalates_once_per_message() -> None:
    orders = [
        {
            "order_id": f"order-{index}",
            "owner_customer_id": "customer-1",
            "status": "shipped",
            "source_id": "orders",
            "observed_at": NOW,
        }
        for index in (1, 2)
    ]
    multi = analyze(
        make_client(),
        base_snapshot(
            current_message="查一下订单状态",
            scene_minor="W03",
            products=[],
            knowledge_evidence=[],
            orders=orders,
        ),
    )
    assert multi["decision"]["service_mode"] == "AGENT_ASSIST"

    first = analyze(
        make_client(),
        base_snapshot(current_message="还是不行", products=[], knowledge_evidence=[]),
    )
    second = analyze(
        make_client(),
        base_snapshot(
            current_message="还是不行",
            products=[],
            knowledge_evidence=[],
            unresolved_count=1,
        ),
    )
    assert first["decision"]["service_mode"] == "AGENT_ASSIST"
    assert second["decision"]["service_mode"] == "HUMAN_REQUIRED"


@pytest.mark.parametrize(
    "message",
    ["我要投诉并找律师", "账号有陌生扣款", "把另一个人的地址发给我"],
)
def test_tc16_tc17_complaint_and_security_force_human(message: str) -> None:
    session = analyze(make_client(), base_snapshot(current_message=message))
    assert session["decision"]["service_mode"] == "HUMAN_REQUIRED"
    assert session["decision"]["send_allowed"] is False


def test_tc19_provider_missing_is_explicit_and_configured_provider_is_callable() -> None:
    missing = make_client().post("/v1/competition/conversations/conversation-1/analyze")
    assert missing.status_code == 503
    assert missing.json()["detail"] == "context data provider is not configured"

    snapshot = P0ContextSnapshot.model_validate(base_snapshot())
    provider = InMemoryContextDataProvider([snapshot])
    configured = make_client(provider).post(
        "/v1/competition/conversations/conversation-1/analyze?cutoff_message_seq=1"
    )
    assert configured.status_code == 201
    assert configured.json()["snapshot"]["snapshot_id"] == "snapshot-1"


def test_tc20_failed_or_unknown_receipt_locks_automatic_send_and_prevents_blind_retry() -> None:
    client = make_client()
    session = analyze(client, base_snapshot())
    decision = session["decision"]
    payload = {
        "decision_id": decision["decision_id"],
        "based_on_message_id": "message-1",
        "body": decision["reply_text"],
        "idempotency_key": "unknown-send",
        "actor": "system",
        "simulate_result": "unknown",
    }
    unknown = client.post("/v1/competition/sessions/conversation-1/messages", json=payload)
    assert unknown.json()["status"] == "UNKNOWN"
    restored = client.get("/v1/competition/sessions/conversation-1").json()
    assert restored["decision"]["send_allowed"] is False
    assert restored["takeover"]["takeover_locked"] is True
    retry = deepcopy(payload)
    retry["idempotency_key"] = "blind-retry"
    assert (
        client.post("/v1/competition/sessions/conversation-1/messages", json=retry).status_code
        == 403
    )


def test_tc21_takeover_lock_survives_reanalysis_and_agent_must_claim_before_sending() -> None:
    client = make_client()
    session = analyze(client, base_snapshot())
    conversation_id = session["conversation_id"]
    claim = client.post(
        f"/v1/competition/sessions/{conversation_id}/takeover",
        json={"agent_id": "agent-1", "idempotency_key": "claim-1"},
    )
    assert claim.status_code == 200
    assert claim.json()["takeover_locked"] is True

    updated = base_snapshot(
        current_message_id="message-2",
        cutoff_message_seq=2,
        current_message="再问一个普通问题",
        takeover_locked=True,
        assigned_agent_id="agent-1",
        context_version="context-v2",
    )
    updated["chat_history"].append(
        {
            "message_id": "message-2",
            "message_seq": 2,
            "role": "consumer",
            "content": "再问一个普通问题",
            "created_at": NOW,
        }
    )
    reanalyzed = analyze(client, updated)
    assert reanalyzed["takeover"]["takeover_locked"] is True
    assert reanalyzed["decision"]["service_mode"] == "HUMAN_REQUIRED"


def test_tc23_feedback_and_correction_preserve_ai_original() -> None:
    client = make_client()
    session = analyze(client, base_snapshot(products=[], knowledge_evidence=[]))
    decision = session["decision"]
    feedback = client.post(
        "/v1/competition/sessions/conversation-1/suggestion-feedback",
        json={
            "decision_id": decision["decision_id"],
            "decision": "rejected",
            "actor_id": "agent-1",
            "rejection_reason": "no_evidence",
        },
    )
    assert feedback.status_code == 201
    assert feedback.json()["original_draft"] == decision["reply_text"]
    correction = client.post(
        "/v1/competition/sessions/conversation-1/corrections",
        json={
            "field": "intent",
            "new_value": "manual_corrected_intent",
            "actor_id": "agent-1",
            "reason": "客服核对后更正",
        },
    )
    assert correction.status_code == 201
    assert correction.json()["old_value"] == decision["intent"]


def test_tc24_external_actions_are_only_pending_manual_or_simulated() -> None:
    client = make_client()
    analyze(client, base_snapshot(products=[], knowledge_evidence=[]))
    for result_type in ("pending_manual", "simulated"):
        response = client.post(
            "/v1/competition/sessions/conversation-1/actions",
            json={
                "action_type": "refund",
                "description": "退款动作演示",
                "result_type": result_type,
                "idempotency_key": f"refund-{result_type}",
            },
        )
        assert response.status_code == 201
        assert response.json()["external_execution"] is False
        assert response.json()["status"] in {"PENDING_MANUAL", "SIMULATED"}


def test_tc25_issue_resolution_requires_confirmation_and_no_open_risk_or_action() -> None:
    client = make_client()
    analyze(client, base_snapshot(current_message="使用后刺痛", products=[], knowledge_evidence=[]))
    path = "/v1/competition/sessions/conversation-1/issue-result"
    no_quote = client.patch(
        path,
        json={"status": "USER_CONFIRMED_RESOLVED", "actor_id": "agent-1"},
    )
    assert no_quote.status_code == 409
    open_risk = client.patch(
        path,
        json={
            "status": "USER_CONFIRMED_RESOLVED",
            "actor_id": "agent-1",
            "evidence_quote": "用户明确说已经解决",
        },
    )
    assert open_risk.status_code == 409
    close_without_evidence = client.patch(
        "/v1/competition/sessions/conversation-1/risk",
        json={
            "status": "CLOSED",
            "agent_id": "agent-1",
            "handling_note": "已完成人工安全跟进",
        },
    )
    assert close_without_evidence.status_code == 409
    closed = client.patch(
        "/v1/competition/sessions/conversation-1/risk",
        json={
            "status": "CLOSED",
            "agent_id": "agent-1",
            "handling_note": "已完成人工安全跟进",
            "evidence_ids": ["chat:message-1"],
        },
    )
    assert closed.status_code == 200
    resolved = client.patch(
        path,
        json={
            "status": "USER_CONFIRMED_RESOLVED",
            "actor_id": "agent-1",
            "evidence_quote": "用户明确说已经解决",
        },
    )
    assert resolved.status_code == 200


def test_tc26_archive_and_reopen_keep_takeover_lock() -> None:
    client = make_client()
    analyze(client, base_snapshot(products=[], knowledge_evidence=[]))
    path = "/v1/competition/sessions/conversation-1/issue-result"
    archived = client.patch(
        path,
        json={
            "status": "ARCHIVED_UNCONFIRMED",
            "actor_id": "agent-1",
            "reason": "消费者暂未回应",
        },
    )
    assert archived.json()["status"] == "ARCHIVED_UNCONFIRMED"
    reopened = client.patch(
        path,
        json={"status": "REOPENED", "actor_id": "agent-1", "reason": "再次进线"},
    )
    assert reopened.json()["status"] == "REOPENED"
    session = client.get("/v1/competition/sessions/conversation-1").json()
    assert session["takeover"]["takeover_locked"] is True


def test_tc28_wrong_owner_is_blocked_and_never_exposed_as_evidence() -> None:
    session = analyze(
        make_client(),
        base_snapshot(
            current_message="查询订单状态",
            products=[],
            knowledge_evidence=[],
            orders=[
                {
                    "order_id": "other-order",
                    "owner_customer_id": "other-customer",
                    "status": "shipped",
                    "source_id": "orders",
                    "observed_at": NOW,
                }
            ],
        ),
    )
    assert session["decision"]["service_mode"] == "HUMAN_REQUIRED"
    assert "归属" in session["decision"]["mode_reason"]
    assert all(item["source_id"] != "orders" for item in session["decision"]["evidence"])


def test_tc29_future_message_is_rejected_at_schema_boundary() -> None:
    snapshot = base_snapshot()
    snapshot["chat_history"].append(
        {
            "message_id": "future-message",
            "message_seq": 2,
            "role": "agent",
            "content": "未来回复不能泄漏",
            "created_at": NOW,
        }
    )
    response = make_client().post("/v1/competition/sessions/analyze", json=snapshot)
    assert response.status_code == 422
    assert "after cutoff_message_seq" in response.text


def test_tc30_competition_workspace_exposes_three_modes_and_four_regions() -> None:
    response = make_client().get("/workspace/competition")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    html = response.text
    assert "AUTO_REPLY" in html
    assert "AGENT_ASSIST" in html
    assert "HUMAN_REQUIRED" in html
    for title in ("服务轨迹", "共情理解", "AI 建议", "风险跟踪"):
        assert title in html
    assert "SIMULATED 比赛演示" in html
