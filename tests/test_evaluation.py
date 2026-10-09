from __future__ import annotations

import json
from datetime import date

import pytest

from loreal_ai_service_intelligence.evaluation import (
    build_snapshot,
    load_eval_dataset,
    run_eval_dataset,
    write_eval_report,
)


def eval_case(mode: str = "AGENT_ASSIST") -> dict:
    return {
        "case_id": "C-TEST",
        "input": {
            "conversation_id": "conversation-test",
            "cutoff_message_seq": 1,
            "current_message": "我要申请换货",
            "chat_history": [
                {
                    "message_seq": 1,
                    "role": "consumer",
                    "time_local": "10:20:30",
                    "content": "我要申请换货",
                }
            ],
            "linked_records": {"order_ids": [], "ticket_ids": []},
            "data_limitations": ["缺少完整订单对象"],
        },
        "expected": {
            "user_intent": "申请换货",
            "service_mode": mode,
            "response_or_handoff": "人工核对",
            "required_evidence": "当前聊天",
            "prohibited_actions": ["不得承诺已换货"],
        },
        "revision_notes": "测试标准答案不得进入快照",
    }


def dataset(case: dict) -> dict:
    return {
        "schema_version": "1.0",
        "dataset_name": "test-dataset",
        "case_count": 1,
        "cases": [case],
    }


def test_build_snapshot_only_uses_visible_input() -> None:
    snapshot = build_snapshot(eval_case(), date(2026, 9, 30))

    serialized = snapshot.model_dump_json()
    assert snapshot.current_message == "我要申请换货"
    assert snapshot.chat_history[0].created_at.isoformat() == "2026-09-30T10:20:30+00:00"
    assert "不得承诺" not in serialized
    assert "测试标准答案" not in serialized


def test_run_eval_scores_objective_modes_and_marks_manual_metrics() -> None:
    report = run_eval_dataset(dataset(eval_case()), reference_date=date(2026, 9, 30))

    assert report["metrics"]["service_mode_accuracy"] == 1.0
    assert report["metrics"]["input_complete_rate"] == 0.0
    assert report["results"][0]["actual_intent"] == "after_sales"
    assert "intent_accuracy" in report["not_automatically_scored"]


def test_dataset_validation_and_atomic_report_write(tmp_path) -> None:
    source = tmp_path / "dataset.json"
    source.write_text(json.dumps(dataset(eval_case())), encoding="utf-8")
    loaded = load_eval_dataset(source)
    report = run_eval_dataset(loaded, reference_date=date(2026, 9, 30))
    output = tmp_path / "report.json"
    write_eval_report(report, output)

    assert json.loads(output.read_text(encoding="utf-8"))["case_count"] == 1
    assert not output.with_suffix(".json.tmp").exists()


def test_dataset_rejects_count_mismatch(tmp_path) -> None:
    source = tmp_path / "dataset.json"
    invalid = dataset(eval_case())
    invalid["case_count"] = 2
    source.write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(ValueError, match="case_count"):
        load_eval_dataset(source)
