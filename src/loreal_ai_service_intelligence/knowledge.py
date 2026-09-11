from dataclasses import dataclass
from typing import Protocol

from loreal_ai_service_intelligence.models import Intent, KnowledgeReference


@dataclass(frozen=True)
class KnowledgeItem:
    knowledge_id: str
    keywords: tuple[str, ...]
    content: str
    source: str


class KnowledgeProvider(Protocol):
    """可替换的审核知识检索边界；provider 只返回足以直接回答的依据。"""

    def search(self, query: str, intent: Intent, limit: int = 3) -> list[KnowledgeReference]: ...


class InMemoryKnowledgeBase:
    """Small reviewed demo corpus behind a replaceable retrieval interface."""

    def __init__(self, version: str) -> None:
        self.version = version
        self._items = (
            KnowledgeItem(
                "KB-USAGE-001",
                ("第一次", "首次", "使用", "怎么用", "用法"),
                "首次使用护肤品前先阅读产品说明，并在小范围试用；按说明控制用量和频次。",
                "比赛演示知识库：通用使用指引",
            ),
            KnowledgeItem(
                "KB-SHADE-001",
                ("色号", "肤色", "妆效", "粉底"),
                "选择底妆色号时应结合肤色深浅、冷暖调与期望妆效，并优先线下试色。",
                "比赛演示知识库：底妆选购指引",
            ),
            KnowledgeItem(
                "KB-PILLING-001",
                ("搓泥", "起屑", "结块"),
                "先只调整一个条件：减少底妆前护肤品用量，并等待成膜后再薄涂底妆；观察同一区域是否仍出现起屑或结块，无改善或出现不适时停止尝试并转人工。",
                "比赛演示知识库：底妆搓泥排查指引",
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
        if any(term in normalized for term in ("搓泥", "起屑", "结块")):
            ranked.sort(key=lambda item: item.knowledge_id != "KB-PILLING-001")
        return [
            KnowledgeReference(
                knowledge_id=item.knowledge_id,
                version=self.version,
                excerpt=item.content,
                source=item.source,
            )
            for item in ranked[:limit]
        ]
