import json
from importlib.resources import files

from loreal_ai_service_intelligence.domain.models import (
    Intent,
    KnowledgeItem,
    KnowledgeReference,
)


def load_lipstick_selection_guide() -> dict[str, object]:
    """读取随 package 发布、经过人工摘要的中文官方指南知识卡。"""
    path = files("loreal_ai_service_intelligence.providers").joinpath(
        "data/lipstick_selection_guide_zh.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {"knowledge_id", "source_url", "verified_at", "summary"}
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise ValueError("lipstick selection knowledge card is invalid")
    return payload


class InMemoryKnowledgeBase:
    """Small reviewed demo corpus behind a replaceable retrieval interface."""

    def __init__(self, version: str) -> None:
        self.version = version
        lipstick_guide = load_lipstick_selection_guide()
        lipstick_media = lipstick_guide.get("supporting_media", {})
        if not isinstance(lipstick_media, dict):
            lipstick_media = {}
        self._items = (
            KnowledgeItem(
                knowledge_id="KB-USAGE-001",
                keywords=("第一次", "首次", "使用", "怎么用", "用法"),
                content="首次使用护肤品前先阅读产品说明，并在小范围试用；按说明控制用量和频次。",
                source="比赛演示知识库：通用使用指引",
                version=version,
            ),
            KnowledgeItem(
                knowledge_id="KB-SHADE-001",
                keywords=("色号", "肤色", "妆效", "粉底", "黄二白", "赤茶红", "枫叶红"),
                content=(
                    f"{lipstick_guide['summary']} 美妆语境里的“黄二白”通常表示自述为黄调、白度约"
                    "第二档，但不是品牌统一的标准色阶。若商品名称准确，赤茶红方向通常更适合日常"
                    "柔和的需求，枫叶红方向更适合浓郁、秋冬氛围；这是按色彩方向给出的试色顺序，"
                    "不是对 #01 或 #05 具体 SKU 的官方结论。"
                ),
                source=(
                    f"{lipstick_guide['title']}（{lipstick_guide['source_url']}，"
                    f"核验日期：{lipstick_guide['verified_at']}）及中文美妆术语交叉核验；"
                    "#01/#05 具体 SKU 未核验"
                ),
                version=version,
                image_url=str(lipstick_media.get("public_url") or "") or None,
                image_alt=str(lipstick_media.get("alt") or "") or None,
                media_review_status=(
                    "pending" if lipstick_media.get("review_status") == "pending" else None
                ),
            ),
            KnowledgeItem(
                knowledge_id="KB-PILLING-001",
                keywords=("搓泥", "起屑", "结块"),
                content="先只调整一个条件：减少底妆前护肤品用量，并等待成膜后再薄涂底妆；观察同一区域是否仍出现起屑或结块，无改善或出现不适时停止尝试并转人工。",
                source="比赛演示知识库：底妆搓泥排查指引",
                version=version,
            ),
            KnowledgeItem(
                knowledge_id="KB-LOREAL-CN-HOT-001",
                keywords=("欧莱雅有什么", "爆款", "热门", "大家都在搜", "推荐"),
                content=(
                    "巴黎欧莱雅中国官网“大家都在搜”当前公开展示的热门搜索候选包括："
                    "黑精华第四代、全新复颜水乳、小蜜罐、胶原水乳、安瓶面膜、紫熨斗、"
                    "复颜提拉面膜和20霜。它们可作为进一步了解的候选，但官网热门搜索不等于"
                    "销量排名，也不代表适合所有人；选择前应先确认想看的品类和主要诉求。"
                ),
                source=(
                    "巴黎欧莱雅中国官网“大家都在搜”（https://www.lorealparis.com.cn/，"
                    "核验日期：2026-10-01）"
                ),
                version=version,
            ),
            KnowledgeItem(
                knowledge_id="KB-LOREAL-CN-HOT-SERUM-001",
                keywords=("精华类", "精华"),
                content=(
                    "巴黎欧莱雅中国官网“大家都在搜”当前列有“黑精华第四代”。"
                    "这只说明它是官网热门搜索候选，不等于销量排名；在没有完整商品页 evidence 时，"
                    "不能据此扩展具体功效或适配承诺。"
                ),
                source=(
                    "巴黎欧莱雅中国官网“大家都在搜”（https://www.lorealparis.com.cn/，"
                    "核验日期：2026-10-01）"
                ),
                version=version,
            ),
            KnowledgeItem(
                knowledge_id="KB-LOREAL-CN-HOT-MOISTURIZER-001",
                keywords=("水乳/面霜类", "水乳", "面霜"),
                content=(
                    "巴黎欧莱雅中国官网“大家都在搜”当前列有“全新复颜水乳、小蜜罐、胶原水乳、"
                    "20霜”。这些名称可作为水乳或面霜方向的热门搜索候选，不等于销量排名，"
                    "也不能在缺少具体商品 evidence 时扩展功效或适配承诺。"
                ),
                source=(
                    "巴黎欧莱雅中国官网“大家都在搜”（https://www.lorealparis.com.cn/，"
                    "核验日期：2026-10-01）"
                ),
                version=version,
            ),
            KnowledgeItem(
                knowledge_id="KB-LOREAL-CN-HOT-MASK-001",
                keywords=("面膜类", "面膜"),
                content=(
                    "巴黎欧莱雅中国官网“大家都在搜”当前列有“安瓶面膜、复颜提拉面膜”。"
                    "这些名称可作为面膜方向的热门搜索候选，不等于销量排名，也不能在缺少具体商品"
                    " evidence 时扩展功效或适配承诺。"
                ),
                source=(
                    "巴黎欧莱雅中国官网“大家都在搜”（https://www.lorealparis.com.cn/，"
                    "核验日期：2026-10-01）"
                ),
                version=version,
            ),
            KnowledgeItem(
                knowledge_id="KB-LOREAL-CN-LIP-001",
                keywords=("唇妆类", "唇妆", "口红", "唇膏", "唇釉"),
                content=(
                    "巴黎欧莱雅中国官网印迹系列页面当前展示“印迹唇釉-柔雾小钢笔 129”、"
                    "“欧莱雅印迹唇釉 129（水光）”和“印迹唇釉-初吻小钢笔 129”。"
                    "这些是中国官网展示的唇妆候选，不代表销量排名；其中页面将柔雾款描述为"
                    "雾感、轻薄，实际色彩与使用感受仍应以具体商品页、实物试色和个人体验为准，"
                    "不能据此承诺适合特定肤色或绝对不拔干。"
                ),
                source=(
                    "巴黎欧莱雅中国官网印迹系列页面"
                    "（https://www.lorealparis.com.cn/lip-makeup/rouge-signature，"
                    "核验日期：2026-10-01）"
                ),
                version=version,
            ),
        )

    def search(
        self, query: str, intent: Intent = Intent.CONSULT, limit: int = 3
    ) -> list[KnowledgeReference]:
        normalized = query.lower()
        if intent not in {Intent.USAGE, Intent.PURCHASE, Intent.CONSULT}:
            return []
        # 现有 demo 知识不覆盖不良反应、功效承诺或交易问题，不能仅因出现“使用”就作答。
        unsupported = ("长痘", "爆痘", "不适", "副作用", "功效", "有效吗", "退款", "退货", "订单")
        if any(term in normalized for term in unsupported):
            return []
        ranked = [
            item
            for item in self._items
            if any(keyword.lower() in normalized for keyword in item.keywords)
        ]
        is_recommendation_query = any(
            term in normalized for term in ("推荐", "爆款", "热门", "大家都在搜", "欧莱雅有什么")
        )
        if not is_recommendation_query:
            ranked = [
                item
                for item in ranked
                if not item.knowledge_id.startswith("KB-LOREAL-CN-HOT-")
                and item.knowledge_id != "KB-LOREAL-CN-LIP-001"
            ]
        if any(term in normalized for term in ("搓泥", "起屑", "结块")):
            ranked = [item for item in ranked if item.knowledge_id == "KB-PILLING-001"]
        if any(term in normalized for term in ("口红", "唇膏", "唇釉", "粉底", "底妆")):
            ranked = [item for item in ranked if item.knowledge_id != "KB-LOREAL-CN-HOT-001"]
        category_knowledge = {
            "精华": "KB-LOREAL-CN-HOT-SERUM-001",
            "水乳": "KB-LOREAL-CN-HOT-MOISTURIZER-001",
            "面霜": "KB-LOREAL-CN-HOT-MOISTURIZER-001",
            "面膜": "KB-LOREAL-CN-HOT-MASK-001",
            "唇妆": "KB-LOREAL-CN-LIP-001",
            "口红": "KB-LOREAL-CN-LIP-001",
            "唇膏": "KB-LOREAL-CN-LIP-001",
            "唇釉": "KB-LOREAL-CN-LIP-001",
        }
        selected_category = next(
            (
                knowledge_id
                for term, knowledge_id in category_knowledge.items()
                if term in normalized
            ),
            None,
        )
        if is_recommendation_query and selected_category:
            ranked = [item for item in ranked if item.knowledge_id == selected_category]
        return [
            KnowledgeReference(
                knowledge_id=item.knowledge_id,
                version=self.version,
                excerpt=item.content,
                source=item.source,
                image_url=item.image_url,
                image_alt=item.image_alt,
                media_review_status=item.media_review_status,
            )
            for item in ranked[:limit]
        ]
