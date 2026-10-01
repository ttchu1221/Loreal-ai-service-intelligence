"""Conservative gate for deciding whether a consumer message needs business evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class EvidenceRequirement(str, Enum):
    REQUIRED = "required"
    NOT_REQUIRED = "not_required"


class EvidenceFreeIntent(str, Enum):
    GREETING = "greeting"
    GRATITUDE = "gratitude"
    ACKNOWLEDGEMENT = "acknowledgement"
    FAREWELL = "farewell"
    CAPABILITY = "capability"
    META_HELP = "meta_help"
    CLARIFICATION = "clarification"


@dataclass(frozen=True)
class EvidenceRequirementDecision:
    requirement: EvidenceRequirement
    evidence_free_intent: EvidenceFreeIntent | None = None
    source: str = "conservative_default"


class RuleBasedEvidenceRequirementPolicy:
    """Only exempt complete, low-risk conversational acts from the evidence gate."""

    _PHRASES = {
        EvidenceFreeIntent.GREETING: {
            "在吗",
            "你好",
            "您好",
            "嗨",
            "哈喽",
            "有人吗",
            "客服在吗",
            "在不在",
        },
        EvidenceFreeIntent.GRATITUDE: {
            "谢谢",
            "谢谢你",
            "谢谢您的帮助",
            "谢谢你的帮助",
            "多谢",
            "感谢",
            "辛苦了",
        },
        EvidenceFreeIntent.ACKNOWLEDGEMENT: {
            "好",
            "好的",
            "好吧",
            "可以",
            "收到",
            "明白了",
            "知道了",
            "了解了",
        },
        EvidenceFreeIntent.FAREWELL: {
            "再见",
            "拜拜",
            "先这样",
            "没问题了",
            "暂时没问题了",
        },
        EvidenceFreeIntent.CAPABILITY: {
            "你是谁",
            "你能做什么",
            "你可以做什么",
            "你是机器人吗",
        },
        EvidenceFreeIntent.META_HELP: {
            "我该怎么描述问题",
            "我应该怎么描述问题",
            "怎么描述问题",
            "我该怎么跟你说",
            "需要我提供什么信息",
            "我要提供什么信息",
        },
        EvidenceFreeIntent.CLARIFICATION: {
            "什么意思",
            "你刚才说的是什么意思",
            "你说的是什么意思",
            "我没听懂",
            "没听明白",
            "可以解释一下吗",
            "能解释一下吗",
        },
    }

    _TERMINAL_PARTICLES = re.compile(r"(?:呀|啊|哦|呢|啦|哈|嘛|哒)+$")
    _PUNCTUATION = re.compile(r"[，。！？!?、；;：:～~…,.]+")

    def classify(self, text: str) -> EvidenceRequirementDecision:
        normalized = self._normalize(text)
        for intent, phrases in self._PHRASES.items():
            if normalized in {self._normalize(phrase) for phrase in phrases}:
                return EvidenceRequirementDecision(
                    requirement=EvidenceRequirement.NOT_REQUIRED,
                    evidence_free_intent=intent,
                    source=f"evidence_free_rules:{intent.value}",
                )
        return EvidenceRequirementDecision(requirement=EvidenceRequirement.REQUIRED)

    @classmethod
    def _normalize(cls, text: str) -> str:
        normalized = cls._PUNCTUATION.sub("", "".join(text.split())).strip()
        return cls._TERMINAL_PARTICLES.sub("", normalized)
