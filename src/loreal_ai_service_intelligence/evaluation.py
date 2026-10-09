"""离线运行比赛 Eval 数据集，且严格隔离模型输入与标准答案。"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from loreal_ai_service_intelligence.config import Settings
from loreal_ai_service_intelligence.domain.competition import P0ContextSnapshot
from loreal_ai_service_intelligence.infrastructure.repository import MemoryRepository
from loreal_ai_service_intelligence.services.competition import CompetitionP0Service

SUPPORTED_SCHEMA_VERSION = "1.0"


def load_eval_dataset(path: Path) -> dict[str, Any]:
    """读取并校验转换后的 Eval dataset。"""

    dataset = json.loads(path.read_text(encoding="utf-8"))
    if dataset.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise ValueError("unsupported Eval dataset schema_version")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Eval dataset must contain at least one case")
    if dataset.get("case_count") != len(cases):
        raise ValueError("Eval dataset case_count does not match cases")
    return dataset


def build_snapshot(case: dict[str, Any], reference_date: date) -> P0ContextSnapshot:
    """只使用 case.input 构造运行快照，不读取 expected 或 revision_notes。"""

    case_input = case["input"]
    messages = case_input["chat_history"]
    normalized_messages = [
        {
            "message_id": f"{case['case_id']}-message-{item['message_seq']}",
            "message_seq": item["message_seq"],
            "role": item["role"],
            "content": item["content"],
            "created_at": datetime.combine(
                reference_date,
                datetime.strptime(item["time_local"], "%H:%M:%S").time(),
                tzinfo=timezone.utc,
            ),
        }
        for item in messages
    ]
    current = normalized_messages[-1]
    return P0ContextSnapshot(
        snapshot_id=f"eval-{case['case_id']}",
        case_id=case["case_id"],
        conversation_id=case_input["conversation_id"],
        issue_id=f"eval-issue-{case['case_id']}",
        customer_id=f"eval-customer-{case['case_id']}",
        current_message_id=current["message_id"],
        cutoff_message_seq=case_input["cutoff_message_seq"],
        current_message=case_input["current_message"],
        chat_history=normalized_messages,
        scene_missing_reason="Eval 原始数据未提供官方场景标签",
        context_version=f"eval-{SUPPORTED_SCHEMA_VERSION}",
        captured_at=current["created_at"],
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def run_eval_dataset(
    dataset: dict[str, Any],
    *,
    reference_date: date,
    service: CompetitionP0Service | None = None,
) -> dict[str, Any]:
    """运行 deterministic baseline 并计算可客观判定的指标。"""

    eval_service = service or CompetitionP0Service(
        MemoryRepository(),
        Settings(_env_file=None, app_env="test", llm_enabled=False),  # type: ignore[call-arg]
    )
    results: list[dict[str, Any]] = []
    for case in dataset["cases"]:
        snapshot = build_snapshot(case, reference_date)
        session = eval_service.analyze(snapshot)
        expected_mode = case["expected"]["service_mode"]
        actual_mode = session.decision.service_mode.value
        results.append(
            {
                "case_id": case["case_id"],
                "expected_service_mode": expected_mode,
                "actual_service_mode": actual_mode,
                "service_mode_pass": actual_mode == expected_mode,
                "expected_user_intent": case["expected"]["user_intent"],
                "actual_intent": session.decision.intent,
                "risk_type": session.decision.risk_type,
                "send_allowed": session.decision.send_allowed,
                "reply_text": session.decision.reply_text,
                "evidence_count": len(session.decision.evidence),
                "input_complete": not bool(case["input"].get("data_limitations")),
                "manual_review": {
                    "response_or_handoff": case["expected"]["response_or_handoff"],
                    "required_evidence": case["expected"]["required_evidence"],
                    "prohibited_actions": case["expected"]["prohibited_actions"],
                },
            }
        )

    total = len(results)
    correct = sum(item["service_mode_pass"] for item in results)
    expected_human = [item for item in results if item["expected_service_mode"] == "HUMAN_REQUIRED"]
    actual_auto = [item for item in results if item["actual_service_mode"] == "AUTO_REPLY"]
    human_recalled = sum(item["actual_service_mode"] == "HUMAN_REQUIRED" for item in expected_human)
    auto_correct = sum(item["expected_service_mode"] == "AUTO_REPLY" for item in actual_auto)
    return {
        "schema_version": "1.0",
        "dataset_name": dataset["dataset_name"],
        "evaluation_mode": "deterministic_baseline",
        "reference_date": reference_date.isoformat(),
        "case_count": total,
        "metrics": {
            "service_mode_accuracy": _ratio(correct, total),
            "human_required_recall": _ratio(human_recalled, len(expected_human)),
            "auto_reply_precision": _ratio(auto_correct, len(actual_auto)),
            "input_complete_rate": _ratio(sum(item["input_complete"] for item in results), total),
            "expected_mode_distribution": dict(
                Counter(item["expected_service_mode"] for item in results)
            ),
            "actual_mode_distribution": dict(
                Counter(item["actual_service_mode"] for item in results)
            ),
        },
        "not_automatically_scored": {
            "intent_accuracy": "expected.user_intent 是自然语言目标，不是 taxonomy label",
            "response_quality": "需要人工或独立 LLM judge 按 response_or_handoff 评分",
            "evidence_completeness": "原始数据只有引用编号，没有完整订单、工单与知识对象",
            "prohibited_action_violation_rate": "禁止项为自然语言规则，当前没有可审计 rubric",
        },
        "results": results,
    }


def write_eval_report(report: dict[str, Any], output: Path) -> None:
    """原子写入 Eval 报告。"""

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
