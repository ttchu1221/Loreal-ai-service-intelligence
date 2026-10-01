from fastapi.testclient import TestClient
from pymongo.errors import ConnectionFailure

from loreal_ai_service_intelligence.api.application import create_app
from loreal_ai_service_intelligence.domain.models import ConsumerReplyGeneration
from loreal_ai_service_intelligence.infrastructure.repository import MemoryRepository


def make_client(tmp_path) -> TestClient:
    del tmp_path
    return TestClient(create_app(MemoryRepository()))


class ContextAwareResponseProvider:
    def generate(self, request, card, existing):
        previous = existing.messages[-1] if existing else "首次咨询"
        context = f"我理解你这次说的是“{request.message}”，并结合了“{previous}”"
        return f"{context}（{card.next_state.value}）。"


class FailingResponseProvider:
    def generate(self, request, card, existing):
        del request, card, existing
        raise TimeoutError("model timeout")


class MisalignedChoiceResponseProvider:
    def generate(self, request, card, existing):
        del request, card, existing
        return "请选择 A、B、C 或 D。"


class MediaAwareResponseProvider:
    def generate(self, request, card, existing):
        del card, existing
        return ConsumerReplyGeneration(
            message="可以结合这张选色方向图理解，再在自然光下试色。",
            media_knowledge_ids=["KB-SHADE-001"] if "日常柔和" in request.message else [],
        )


class ClarificationMediaResponseProvider:
    def generate(self, request, card, existing):
        del request, card, existing
        return ConsumerReplyGeneration(
            message=(
                "可以先结合这张选色方向图理解。你更想要哪种效果？"
                "请选择：日常柔和、浓郁有氛围，或暂时不确定。"
            ),
            media_knowledge_ids=["KB-SHADE-001"],
        )


def test_low_risk_usage_question_resolves_with_traceable_evidence(tmp_path) -> None:
    client = make_client(tmp_path)

    response = client.post("/v1/conversations", json={"message": "第一次使用面霜，应该怎么用？"})

    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "RESOLVE"
    assert body["evidence"][0]["knowledge_id"] == "KB-USAGE-001"
    assert "intent" not in body
    assert "risk_level" not in body
    assert body["event_id"] is None
    assert client.get("/v1/agent/events").json() == []


def test_response_provider_uses_current_message_and_conversation_context(tmp_path) -> None:
    del tmp_path
    client = TestClient(
        create_app(MemoryRepository(), response_provider=ContextAwareResponseProvider())
    )
    first = client.post("/v1/conversations", json={"message": "粉底有点搓泥"}).json()
    second = client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "主要发生在涂完防晒之后"},
    ).json()

    assert "主要发生在涂完防晒之后" in second["message"]
    assert "粉底有点搓泥" in second["message"]
    assert second["state"] == "GUIDE"


def test_response_provider_failure_falls_back_without_breaking_flow(tmp_path) -> None:
    del tmp_path
    client = TestClient(create_app(MemoryRepository(), response_provider=FailingResponseProvider()))

    body = client.post("/v1/conversations", json={"message": "第一次使用面霜，应该怎么用？"}).json()

    assert body["state"] == "RESOLVE"
    assert "根据已审核的使用指引" in body["message"]


def test_block_response_never_calls_generative_provider(tmp_path) -> None:
    del tmp_path
    client = TestClient(create_app(MemoryRepository(), response_provider=FailingResponseProvider()))

    body = client.post("/v1/conversations", json={"message": "用了以后呼吸困难"}).json()

    assert body["state"] == "BLOCK"
    assert "停止继续使用" in body["message"]


def test_consumer_can_restore_complete_transcript_after_refresh(tmp_path) -> None:
    client = make_client(tmp_path)
    first = client.post("/v1/conversations", json={"message": "我的底妆总是搓泥，怎么办？"}).json()
    second = client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "发生在涂粉底后，我已经试过换粉扑"},
    ).json()

    restored = client.get(f"/v1/conversations/{first['conversation_id']}")

    assert restored.status_code == 200
    body = restored.json()
    assert body["last_result_id"] == second["result_id"]
    assert [item["role"] for item in body["transcript"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert body["transcript"][0]["content"] == "我的底妆总是搓泥，怎么办？"
    assert body["transcript"][-1]["content"] == second["message"]


def test_consumer_restore_returns_404_for_unknown_conversation(tmp_path) -> None:
    client = make_client(tmp_path)

    response = client.get("/v1/conversations/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "conversation not found"}


def test_explicit_human_request_overrides_normal_ai_clarification(tmp_path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/v1/conversations", json={"message": "我的粉底搓泥，但我现在选择人工客服"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "HANDOFF"
    assert body["event_status"] == "waiting_for_agent"
    assert "按你的选择" in body["message"]
    package = client.get(f"/v1/agent/conversations/{body['conversation_id']}").json()[
        "handoff_package"
    ]
    assert package["handoff_reason"] == "用户在对话中明确选择人工客服"


def test_explicit_handoff_decline_does_not_create_ticket(tmp_path) -> None:
    client = make_client(tmp_path)

    response = client.post("/v1/conversations", json={"message": "我暂不转人工，继续让 AI 帮我"})

    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "ASK"
    assert body["event_id"] is None
    assert "暂不转人工" in body["message"]
    assert client.get("/v1/agent/events").json() == []


def test_greeting_stays_in_ai_conversation_without_creating_ticket(tmp_path) -> None:
    client = make_client(tmp_path)

    for message in ("在吗", "您好！", " 客服在吗？ "):
        response = client.post("/v1/conversations", json={"message": message})

        assert response.status_code == 201
        body = response.json()
        assert body["state"] == "ASK"
        assert body["event_id"] is None
        assert "在的" in body["message"]

    assert client.get("/v1/agent/events").json() == []


def test_greeting_with_real_question_still_uses_normal_routing(tmp_path) -> None:
    client = make_client(tmp_path)

    response = client.post("/v1/conversations", json={"message": "你好，面霜应该怎么用？"})

    assert response.status_code == 201
    assert response.json()["state"] == "RESOLVE"
    assert response.json()["evidence"][0]["knowledge_id"] == "KB-USAGE-001"


def test_lipstick_comparison_asks_for_one_decision_dimension_then_recommends(tmp_path) -> None:
    client = make_client(tmp_path)

    first = client.post(
        "/v1/conversations",
        json={"message": "我黄二白，口红选#01赤茶红还是#05枫叶红呀"},
    ).json()

    assert first["state"] == "ASK"
    assert first["event_id"] is None
    assert first["suggested_replies"] == ["日常柔和", "浓郁有氛围", "暂时不确定"]
    assert "黄二白" in first["message"]
    assert "#01 赤茶红" in first["message"]
    assert "#05 枫叶红" in first["message"]
    assert "具体 SKU" in first["message"]

    second = client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "日常柔和"},
    ).json()

    assert second["state"] == "RESOLVE"
    assert second["event_id"] is None
    assert second["suggested_replies"] == []
    assert "#01 赤茶红" in second["message"]
    assert "日常柔和" in second["message"]
    assert "一定显白" not in second["message"]
    assert second["evidence"][0]["image_url"] is None


def test_response_provider_can_choose_retrieved_image_without_always_showing_it(tmp_path) -> None:
    del tmp_path
    client = TestClient(
        create_app(MemoryRepository(), response_provider=MediaAwareResponseProvider())
    )
    first = client.post(
        "/v1/conversations",
        json={"message": "我黄二白，口红选#01赤茶红还是#05枫叶红呀"},
    ).json()

    assert first["state"] == "ASK"
    assert first["evidence"] == []

    second = client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "日常柔和"},
    ).json()

    assert second["state"] == "RESOLVE"
    assert second["evidence"][0]["knowledge_id"] == "KB-SHADE-001"
    assert second["evidence"][0]["image_url"] == "/v1/knowledge/KB-SHADE-001/media"


def test_response_provider_can_choose_retrieved_image_during_clarification(tmp_path) -> None:
    del tmp_path
    client = TestClient(
        create_app(MemoryRepository(), response_provider=ClarificationMediaResponseProvider())
    )

    body = client.post(
        "/v1/conversations",
        json={"message": "我黄二白，口红选#01赤茶红还是#05枫叶红呀"},
    ).json()

    assert body["state"] == "ASK"
    assert body["evidence"][0]["knowledge_id"] == "KB-SHADE-001"
    assert body["evidence"][0]["image_url"] == "/v1/knowledge/KB-SHADE-001/media"


def test_lipstick_comparison_keeps_copy_aligned_with_quick_replies(tmp_path) -> None:
    del tmp_path
    client = TestClient(
        create_app(MemoryRepository(), response_provider=MisalignedChoiceResponseProvider())
    )

    body = client.post(
        "/v1/conversations",
        json={"message": "我黄二白，口红选#01赤茶红还是#05枫叶红呀"},
    ).json()

    assert body["suggested_replies"] == ["日常柔和", "浓郁有氛围", "暂时不确定"]
    assert "日常柔和、浓郁有氛围，或暂时不确定" in body["message"]
    assert "A、B、C 或 D" not in body["message"]


def test_lipstick_comparison_can_recommend_the_atmospheric_direction(tmp_path) -> None:
    client = make_client(tmp_path)
    first = client.post(
        "/v1/conversations",
        json={"message": "我黄二白，口红选#01赤茶红还是#05枫叶红呀"},
    ).json()

    second = client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "浓郁有氛围"},
    ).json()

    assert second["state"] == "RESOLVE"
    assert "#05 枫叶红" in second["message"]
    assert "浓郁氛围" in second["message"]
    assert "一定显白" in second["message"]


def test_unknown_lipstick_texture_gets_generic_guidance_without_product_claim(tmp_path) -> None:
    client = make_client(tmp_path)
    first = client.post(
        "/v1/conversations",
        json={"message": "这个口红会不会拔干？我的唇纹有点深"},
    ).json()

    second = client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "我不知道具体系列"},
    ).json()

    assert first["state"] == "ASK"
    assert second["state"] == "RESOLVE"
    assert second["event_id"] is None
    assert "无法确认这款具体配方" in second["message"]
    assert "雾面妆效" in second["message"]
    assert "实际感受" in second["message"]


def test_known_generic_knowledge_does_not_require_product_identity(tmp_path) -> None:
    client = make_client(tmp_path)

    body = client.post("/v1/conversations", json={"message": "第一次使用面霜，应该怎么用？"}).json()

    assert body["state"] == "RESOLVE"
    assert body["event_id"] is None


def test_official_china_hot_searches_can_support_a_careful_product_shortlist(tmp_path) -> None:
    client = make_client(tmp_path)

    first = client.post(
        "/v1/conversations", json={"message": "欧莱雅有什么热门产品可以推荐？"}
    ).json()

    assert first["state"] == "ASK"
    assert first["suggested_replies"] == [
        "精华类",
        "水乳/面霜类",
        "面膜类",
        "唇妆类",
        "暂时不确定",
    ]

    body = client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "精华类"},
    ).json()
    assert body["state"] == "RESOLVE"
    assert body["event_id"] is None
    assert body["evidence"][0]["knowledge_id"] == "KB-LOREAL-CN-HOT-SERUM-001"
    assert "黑精华第四代" in body["message"]
    assert "小蜜罐" not in body["message"]
    assert "销量排名" in body["message"]
    assert "https://www.lorealparis.com.cn/" in body["evidence"][0]["source"]


def test_official_china_lip_page_supports_a_limited_lip_shortlist(tmp_path) -> None:
    client = make_client(tmp_path)

    body = client.post("/v1/conversations", json={"message": "推荐一支欧莱雅热门口红"}).json()

    assert body["state"] == "ASK"
    assert body["event_id"] is None
    assert body["evidence"] == []
    assert body["suggested_replies"] == ["柔雾轻薄", "水光妆效", "暂时不确定"]


def test_lip_recommendation_matches_the_users_stated_finish(tmp_path) -> None:
    client = make_client(tmp_path)

    body = client.post(
        "/v1/conversations", json={"message": "我想要水光妆效，推荐一支欧莱雅口红"}
    ).json()

    assert body["state"] == "RESOLVE"
    assert body["evidence"][0]["knowledge_id"] == "KB-LOREAL-CN-LIP-001"
    assert "印迹唇釉 129（水光）" in body["message"]
    assert "柔雾小钢笔" not in body["message"]


def test_lip_recommendation_uses_preference_from_previous_turn(tmp_path) -> None:
    client = make_client(tmp_path)
    first = client.post("/v1/conversations", json={"message": "推荐一支欧莱雅口红"}).json()

    body = client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "柔雾轻薄"},
    ).json()

    assert body["state"] == "RESOLVE"
    assert "柔雾小钢笔 129" in body["message"]
    assert "水光妆效" not in body["message"]


def test_lip_category_can_be_selected_from_general_recommendations(tmp_path) -> None:
    client = make_client(tmp_path)

    first = client.post("/v1/conversations", json={"message": "欧莱雅有什么产品可以推荐？"}).json()
    body = client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "唇妆类"},
    ).json()

    assert body["state"] == "ASK"
    assert body["suggested_replies"] == ["柔雾轻薄", "水光妆效", "暂时不确定"]


def test_other_evidence_free_intents_reply_without_creating_ticket(tmp_path) -> None:
    client = make_client(tmp_path)

    examples = {
        "谢谢": "不客气",
        "收到": "好的",
        "再见": "再见",
        "你是谁？": "智慧美妆顾问",
        "你好呀": "在的",
        "在不在呀": "在的",
        "好的呢": "好的",
        "谢谢你的帮助": "不客气",
        "我该怎么描述问题": "遇到的现象",
        "你刚才说的是什么意思": "哪一句",
    }
    for message, expected_reply in examples.items():
        body = client.post("/v1/conversations", json={"message": message}).json()
        assert body["state"] in {"ASK", "RESOLVE"}
        assert body["evidence"] == []
        assert body["event_id"] is None
        assert expected_reply in body["message"]

    assert client.get("/v1/agent/events").json() == []


def test_evidence_free_intent_uses_llm_when_configured(tmp_path) -> None:
    del tmp_path
    client = TestClient(
        create_app(MemoryRepository(), response_provider=ContextAwareResponseProvider())
    )

    body = client.post("/v1/conversations", json={"message": "你好呀"}).json()

    assert body["state"] == "ASK"
    assert "你好呀" in body["message"]
    assert body["event_id"] is None


def test_evidence_free_llm_failure_uses_safe_template(tmp_path) -> None:
    del tmp_path
    client = TestClient(create_app(MemoryRepository(), response_provider=FailingResponseProvider()))

    body = client.post("/v1/conversations", json={"message": "谢谢你的帮助"}).json()

    assert body["state"] == "RESOLVE"
    assert body["message"] == "不客气。如果还有其他问题，可以继续告诉我。"
    assert body["event_id"] is None


def test_shade_question_asks_once_then_resolves_without_repeating_fact(tmp_path) -> None:
    client = make_client(tmp_path)
    first = client.post("/v1/conversations", json={"message": "我想选粉底色号"}).json()

    assert first["state"] == "ASK"
    assert first["message"].count("？") <= 1

    second = client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "我是暖调肤色，想要自然妆效"},
    )
    assert second.status_code == 200
    assert second.json()["state"] == "RESOLVE"

    agent_view = client.get(f"/v1/agent/conversations/{first['conversation_id']}").json()
    facts = agent_view["empathy_card"]["confirmed_facts"]
    assert facts == ["我想选粉底色号", "我是暖调肤色，想要自然妆效"]


def test_high_risk_flow_blocks_recommendation_and_creates_idempotent_handoff(tmp_path) -> None:
    client = make_client(tmp_path)
    blocked = client.post("/v1/conversations", json={"message": "使用三天后一直泛红和刺痛"}).json()

    assert blocked["state"] == "BLOCK"
    assert blocked["evidence"] == []
    assert "停止继续使用" in blocked["message"]
    assert blocked["available_actions"] == ["view_ticket"]
    assert blocked["event_status"] == "waiting_for_agent"

    path = f"/v1/conversations/{blocked['conversation_id']}/handoff"
    payload = {"accepted": True, "idempotency_key": "risk-case-001"}
    first_event = client.post(path, json=payload)
    repeated_event = client.post(path, json=payload)

    assert first_event.status_code == 200
    assert first_event.json()["event_id"] == repeated_event.json()["event_id"]
    assert first_event.json()["priority"] == 100

    agent_view = client.get(f"/v1/agent/conversations/{blocked['conversation_id']}").json()
    handoff = agent_view["handoff_package"]
    assert handoff["original_messages"] == ["使用三天后一直泛红和刺痛"]
    assert handoff["confirmed_facts"]
    assert handoff["handoff_reason"]
    assert handoff["risk_level"] == "high"
    assert handoff["rule_version"] == "risk-rules-v1"


def test_unknown_knowledge_fails_explicitly_to_handoff(tmp_path) -> None:
    client = make_client(tmp_path)

    response = client.post("/v1/conversations", json={"message": "告诉我一个不存在的产品功效"})

    assert response.status_code == 201
    assert response.json()["state"] == "HANDOFF"
    assert "需要进一步核实" in response.json()["message"]
    assert "无需重复说明" in response.json()["message"]
    assert "审核依据" not in response.json()["message"]
    assert response.json()["event_status"] == "waiting_for_agent"


def test_feedback_service_action_and_insights_are_auditable(tmp_path) -> None:
    client = make_client(tmp_path)
    resolved = client.post("/v1/conversations", json={"message": "第一次使用产品怎么用？"}).json()
    feedback_response = client.post(
        f"/v1/conversations/{resolved['conversation_id']}/feedback",
        json={"result_id": resolved["result_id"], "resolved": True, "comment": "已解决"},
    )
    assert feedback_response.status_code == 204

    blocked = client.post("/v1/conversations", json={"message": "使用后持续红肿"}).json()
    event = client.post(
        f"/v1/conversations/{blocked['conversation_id']}/handoff",
        json={"accepted": True, "idempotency_key": "service-action-001"},
    ).json()
    action_response = client.post(
        f"/v1/agent/events/{event['event_id']}/actions",
        json={"action": "close", "parameters": {"note": "人工已完成跟进"}},
    )
    assert action_response.json()["status"] == "completed"

    insights = client.get("/v1/insights/overview").json()
    assert insights["consultation_count"]["value"] == 2
    assert insights["consultation_count"]["sample_size"] == 2
    assert insights["consultation_count"]["data_classification"] == "demo"
    assert insights["resolution_rate"]["value"] == 1.0


def test_rejects_blank_input_and_unknown_resources(tmp_path) -> None:
    client = make_client(tmp_path)

    assert client.post("/v1/conversations", json={"message": "   "}).status_code == 422
    assert client.get("/v1/events/missing").status_code == 404
    assert client.get("/v1/insights/overview?data_classification=real").status_code == 422
    assert (
        client.post("/v1/conversations/missing/messages", json={"message": "补充信息"}).status_code
        == 404
    )


def test_handoff_idempotency_key_is_scoped_to_conversation(tmp_path) -> None:
    client = make_client(tmp_path)
    conversations = [
        client.post("/v1/conversations", json={"message": message}).json()
        for message in ("使用后刺痛", "使用后红肿")
    ]

    events = [
        client.post(
            f"/v1/conversations/{conversation['conversation_id']}/handoff",
            json={"accepted": True, "idempotency_key": "same-client-key"},
        ).json()
        for conversation in conversations
    ]

    assert events[0]["event_id"] != events[1]["event_id"]
    assert events[0]["conversation_id"] != events[1]["conversation_id"]


def test_database_failure_returns_safe_actionable_error(tmp_path) -> None:
    del tmp_path

    class FailingRepository(MemoryRepository):
        def save_conversation(self, conversation) -> None:
            del conversation
            raise ConnectionFailure("secret-host.example:27017 unavailable")

    client = TestClient(create_app(FailingRepository()))
    response = client.post("/v1/conversations", json={"message": "第一次使用怎么用？"})

    assert response.status_code == 503
    assert response.json() == {"detail": "database temporarily unavailable"}
    assert "secret-host" not in response.text


def test_blocked_conversation_forwards_new_message_without_removing_safety_block(tmp_path) -> None:
    client = make_client(tmp_path)
    first = client.post("/v1/conversations", json={"message": "使用后刺痛"}).json()

    second = client.post(
        f"/v1/conversations/{first['conversation_id']}/messages",
        json={"message": "我现在想问订单退款"},
    ).json()

    assert second["state"] == "BLOCK"
    view = client.get(f"/v1/agent/conversations/{first['conversation_id']}").json()
    assert view["empathy_card"]["intent"] == "complaint"
    assert view["empathy_card"]["risk_level"] == "high"
    assert view["handoff_package"]["transcript"][-1]["content"] == "我现在想问订单退款"


def test_negated_hypothetical_and_third_party_symptoms_do_not_false_block(tmp_path) -> None:
    client = make_client(tmp_path)

    for message in ("我没有过敏，只想问怎么用", "这个会不会过敏？", "我朋友使用后红肿"):
        body = client.post("/v1/conversations", json={"message": message}).json()
        assert body["state"] != "BLOCK", message


def test_safety_qualifiers_do_not_hide_a_new_active_symptom(tmp_path) -> None:
    client = make_client(tmp_path)

    for message in ("其他产品让我刺痛", "之前泛红已经好了，但现在又刺痛"):
        body = client.post("/v1/conversations", json={"message": message}).json()
        assert body["state"] == "BLOCK", message


def test_adverse_reaction_is_not_answered_by_generic_usage_article(tmp_path) -> None:
    client = make_client(tmp_path)

    body = client.post("/v1/conversations", json={"message": "使用后长痘怎么办"}).json()

    assert body["state"] == "HANDOFF"
    assert body["evidence"] == []


def test_overlapping_after_sales_intent_has_priority(tmp_path) -> None:
    client = make_client(tmp_path)
    body = client.post("/v1/conversations", json={"message": "粉底买错了怎么退货"}).json()
    card = client.get(f"/v1/agent/conversations/{body['conversation_id']}").json()["empathy_card"]

    assert card["intent"] == "after_sales"
    assert card["scenario"] == "after_sales_service"
    assert body["state"] == "HANDOFF"


def test_attachment_is_explicitly_not_treated_as_processed(tmp_path) -> None:
    client = make_client(tmp_path)
    body = client.post(
        "/v1/conversations",
        json={
            "message": "帮我看看这张图",
            "attachments": [{"kind": "product_image", "filename": "photo.jpg"}],
        },
    ).json()

    assert body["state"] == "HANDOFF"
    assert "无法读取" in body["message"]


def test_declining_non_risk_handoff_does_not_show_medical_warning(tmp_path) -> None:
    client = make_client(tmp_path)
    conversation = client.post("/v1/conversations", json={"message": "查询一个未知产品"}).json()
    response = client.post(
        f"/v1/conversations/{conversation['conversation_id']}/handoff",
        json={"accepted": False, "idempotency_key": "decline-unknown"},
    ).json()

    assert "医疗" not in response["message"]
    assert "缺少可靠依据" in response["message"]
