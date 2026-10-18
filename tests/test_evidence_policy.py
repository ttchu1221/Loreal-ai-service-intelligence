from loreal_ai_service_intelligence.services.evidence_policy import (
    EvidenceFreeIntent,
    EvidenceRequirement,
    RuleBasedEvidenceRequirementPolicy,
)


def test_low_risk_conversational_acts_do_not_require_business_evidence() -> None:
    policy = RuleBasedEvidenceRequirementPolicy()

    examples = {
        "在吗？": EvidenceFreeIntent.GREETING,
        "谢谢你！": EvidenceFreeIntent.GRATITUDE,
        "收到": EvidenceFreeIntent.ACKNOWLEDGEMENT,
        "拜拜": EvidenceFreeIntent.FAREWELL,
        "你能做什么？": EvidenceFreeIntent.CAPABILITY,
        "你好呀": EvidenceFreeIntent.GREETING,
        "在不在呀？": EvidenceFreeIntent.GREETING,
        "好的呢": EvidenceFreeIntent.ACKNOWLEDGEMENT,
        "谢谢你的帮助": EvidenceFreeIntent.GRATITUDE,
        "我该怎么描述问题？": EvidenceFreeIntent.META_HELP,
        "你刚才说的是什么意思？": EvidenceFreeIntent.CLARIFICATION,
    }
    for message, expected_intent in examples.items():
        decision = policy.classify(message)
        assert decision.requirement == EvidenceRequirement.NOT_REQUIRED
        assert decision.evidence_free_intent == expected_intent


def test_business_question_and_mixed_message_require_evidence() -> None:
    policy = RuleBasedEvidenceRequirementPolicy()

    for message in (
        "面霜应该怎么用？",
        "你好呀，面霜应该怎么用？",
        "谢谢你的帮助，退款到账了吗？",
        "好的呢，那这款一定不会拔干吗？",
    ):
        decision = policy.classify(message)
        assert decision.requirement == EvidenceRequirement.REQUIRED
        assert decision.evidence_free_intent is None
