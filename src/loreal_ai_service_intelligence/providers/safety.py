"""每轮优先执行、不可由普通对话绕过的安全规则。"""

import re
from typing import Protocol

HIGH_RISK_TERMS = ("刺痛", "泛红", "红肿", "呼吸困难", "灼痛", "过敏")
NEGATION_PREFIXES = ("没有", "没", "不", "未", "无")
HYPOTHETICAL_PREFIXES = ("会不会", "是否会", "会否", "怕", "担心")
RESOLVED_TERMS = ("已经好了", "已恢复", "现在好了", "已消退")


class SafetyPolicy(Protocol):
    def active_risk_terms(self, text: str) -> list[str]: ...


class RuleBasedSafetyPolicy:
    """保守的 deterministic safety fallback。"""

    def active_risk_terms(self, text: str) -> list[str]:
        resolved_history = any(term in text for term in RESOLVED_TERMS)
        renewed_symptom = any(term in text for term in ("但是", "但", "不过", "又", "仍", "现在还"))
        if resolved_history and not renewed_symptom:
            return []
        found: list[str] = []
        for term in HIGH_RISK_TERMS:
            index = text.find(term)
            if index < 0:
                continue
            prefix = text[max(0, index - 4) : index]
            if any(
                prefix.endswith(marker) for marker in (*NEGATION_PREFIXES, *HYPOTHETICAL_PREFIXES)
            ):
                continue
            context = text[max(0, index - 12) : index]
            third_party = re.search(
                r"(?:朋友|同事|家人)(?:说|有|出现|使用后|用了以后)?[^，。！？]*$"
                r"|(?:^|[，。！？])(?:他|她)(?:说|有|出现|使用后|用了以后)[^，。！？]*$",
                context,
            )
            if not third_party:
                found.append(term)
        return found
