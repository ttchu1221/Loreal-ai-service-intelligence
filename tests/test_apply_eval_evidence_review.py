from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "apply_eval_evidence_review.py"
SPEC = importlib.util.spec_from_file_location("apply_eval_evidence_review", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def dataset(mode: str = "AUTO_REPLY") -> dict:
    return {
        "dataset_name": "source",
        "case_count": 1,
        "cases": [
            {
                "case_id": "C-001",
                "expected": {"service_mode": mode},
                "revision_notes": "原记录",
            }
        ],
    }


def review(target: str = "AGENT_ASSIST") -> dict:
    return {
        "review_version": "review-v1",
        "reviewed_at": "2026-09-30T00:00:00+08:00",
        "policy": {"change_scope": "downgrade-only"},
        "reviews": [
            {
                "case_id": "C-001",
                "original_service_mode": "AUTO_REPLY",
                "recommended_service_mode": target,
                "auto_reply_eligible": False,
                "reason": "匿名商品无法唯一匹配",
                "sources": [
                    {
                        "title": "官方来源",
                        "url": "https://example.com/official",
                        "supported_fact": "仅支持通用品类事实",
                    }
                ],
            }
        ],
    }


def test_apply_review_downgrades_and_marks_case() -> None:
    result = MODULE.apply_review(dataset(), review())

    case = result["cases"][0]
    assert case["expected"]["service_mode"] == "AGENT_ASSIST"
    assert "AUTO_REPLY → AGENT_ASSIST" in case["revision_notes"]
    assert case["evidence_review"]["review_version"] == "review-v1"
    assert result["service_mode_distribution"] == {
        "AUTO_REPLY": 0,
        "AGENT_ASSIST": 1,
        "HUMAN_REQUIRED": 0,
    }
    assert result["evidence_review_summary"]["applied_count"] == 1


def test_apply_review_rejects_permission_upgrade() -> None:
    source = dataset("AGENT_ASSIST")
    overlay = review("AUTO_REPLY")
    overlay["reviews"][0]["original_service_mode"] = "AGENT_ASSIST"

    with pytest.raises(ValueError, match="禁止提升自动发送权限"):
        MODULE.apply_review(source, overlay)


def test_apply_review_rejects_unmatched_original_mode() -> None:
    source = dataset("AGENT_ASSIST")

    with pytest.raises(ValueError, match="与 dataset 不一致"):
        MODULE.apply_review(source, review())
