from loreal_ai_service_intelligence.domain.models import Intent
from loreal_ai_service_intelligence.providers.knowledge import (
    InMemoryKnowledgeBase,
    load_lipstick_selection_guide,
)


def test_chinese_lipstick_guide_has_source_and_safety_boundaries() -> None:
    guide = load_lipstick_selection_guide()

    assert guide["language"] == "zh-CN"
    assert guide["source_market"] == "美国"
    assert str(guide["source_url"]).startswith("https://www.lorealparisusa.com/")
    assert len(guide["knowledge_points"]) >= 7
    assert any("中国大陆具体 SKU" in item for item in guide["prohibited_inferences"])
    assert any("自然光试色" in item for item in guide["answering_rules"])
    assert guide["supporting_media"]["review_status"] == "pending"
    assert "不作为品牌官方色号" in guide["supporting_media"]["usage_boundary"]


def test_lipstick_selection_questions_retrieve_the_chinese_guide() -> None:
    knowledge = InMemoryKnowledgeBase("test-version")

    refs = knowledge.search("我黄二白，口红色号怎么选", Intent.PURCHASE)

    assert refs[0].knowledge_id == "KB-SHADE-001"
    assert "肤色明暗、冷暖底调、整体妆容和期望妆效" in refs[0].excerpt
    assert "核验日期：2026-10-01" in refs[0].source
    assert refs[0].image_url == "/v1/knowledge/KB-SHADE-001/media"
    assert refs[0].media_review_status == "pending"
    assert "口红颜色方向" in refs[0].image_alt
