"""比赛版模型、检索与运行记录的可替换边界。"""

from __future__ import annotations

from typing import Protocol

from loreal_ai_service_intelligence.domain.competition import (
    P0ContextSnapshot,
    P0Decision,
    P0KnowledgeEvidence,
)


class CompetitionModelProvider(Protocol):
    """只生成话术，不得修改模式、门禁、风险或业务状态。"""

    def generate_reply(self, snapshot: P0ContextSnapshot, decision: P0Decision) -> str: ...


class CompetitionRetrievalProvider(Protocol):
    """补充经过来源标记的知识证据。"""

    def retrieve(self, snapshot: P0ContextSnapshot) -> list[P0KnowledgeEvidence]: ...


class CompetitionOperationRecorder(Protocol):
    """将运行事件写入可观测系统；失败不得伪装成记录成功。"""

    def record(self, event_type: str, payload: dict[str, object]) -> None: ...
