"""将可审计的证据 review overlay 应用于 Eval dataset。"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

SERVICE_MODES = {"AUTO_REPLY", "AGENT_ASSIST", "HUMAN_REQUIRED"}
DOWNGRADE_RANK = {"AUTO_REPLY": 0, "AGENT_ASSIST": 1, "HUMAN_REQUIRED": 2}


def load_json(path: Path) -> dict[str, Any]:
    """读取 JSON object。"""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是 object：{path}")
    return value


def apply_review(dataset: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    """应用只降级、不提权的证据 review，并保留完整审计标记。"""

    cases = dataset.get("cases")
    reviews = review.get("reviews")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Eval dataset 必须包含非空 cases")
    if not isinstance(reviews, list) or not reviews:
        raise ValueError("evidence review 必须包含非空 reviews")

    result = deepcopy(dataset)
    case_by_id = {item.get("case_id"): item for item in result["cases"]}
    if len(case_by_id) != len(result["cases"]) or None in case_by_id:
        raise ValueError("Eval dataset case_id 缺失或重复")

    applied: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in reviews:
        case_id = item.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError("evidence review case_id 缺失或重复")
        seen.add(case_id)
        case = case_by_id.get(case_id)
        if case is None:
            raise ValueError(f"evidence review 引用了不存在的 case_id：{case_id}")

        original = item.get("original_service_mode")
        recommended = item.get("recommended_service_mode")
        current = case.get("expected", {}).get("service_mode")
        if original not in SERVICE_MODES or recommended not in SERVICE_MODES:
            raise ValueError(f"{case_id}: service_mode 无效")
        if current != original:
            raise ValueError(f"{case_id}: original_service_mode 与 dataset 不一致")
        if DOWNGRADE_RANK[recommended] < DOWNGRADE_RANK[original]:
            raise ValueError(f"{case_id}: review overlay 禁止提升自动发送权限")
        if item.get("auto_reply_eligible") is not False:
            raise ValueError(f"{case_id}: 只有明确不满足 AUTO_REPLY 的记录可以修订")
        reason = item.get("reason")
        sources = item.get("sources")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{case_id}: 缺少修订原因")
        if not isinstance(sources, list) or not sources:
            raise ValueError(f"{case_id}: 缺少来源")
        for source in sources:
            if not all(
                isinstance(source.get(key), str) and source[key].strip()
                for key in ("title", "url", "supported_fact")
            ):
                raise ValueError(f"{case_id}: 来源字段不完整")
            if not source["url"].startswith("https://"):
                raise ValueError(f"{case_id}: 来源 URL 必须使用 HTTPS")

        case["expected"]["service_mode"] = recommended
        marker = (
            f"[{review.get('review_version', 'evidence-review')}] "
            f"{original} → {recommended}：{reason.strip()}"
        )
        previous_notes = case.get("revision_notes", "").strip()
        case["revision_notes"] = f"{previous_notes}\n{marker}".strip()
        case["evidence_review"] = {
            "review_version": review.get("review_version"),
            "reviewed_at": review.get("reviewed_at"),
            "original_service_mode": original,
            "recommended_service_mode": recommended,
            "reason": reason.strip(),
            "sources": deepcopy(sources),
        }
        applied.append(
            {
                "case_id": case_id,
                "from": original,
                "to": recommended,
                "reason": reason.strip(),
            }
        )

    result["dataset_name"] = f"{dataset.get('dataset_name', 'eval')}_evidence_reviewed"
    result["service_mode_distribution"] = {
        mode: sum(case["expected"]["service_mode"] == mode for case in result["cases"])
        for mode in ("AUTO_REPLY", "AGENT_ASSIST", "HUMAN_REQUIRED")
    }
    result["evidence_review_summary"] = {
        "review_version": review.get("review_version"),
        "reviewed_at": review.get("reviewed_at"),
        "applied_count": len(applied),
        "changes": applied,
        "policy": deepcopy(review.get("policy", {})),
    }
    result["case_count"] = len(result["cases"])
    return result


def write_json(value: dict[str, Any], output: Path) -> None:
    """原子写入 JSON。"""

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="原始 Eval JSON")
    parser.add_argument("review", type=Path, help="证据 review overlay JSON")
    parser.add_argument("output", type=Path, help="reviewed Eval JSON")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reviewed = apply_review(load_json(args.dataset), load_json(args.review))
    write_json(reviewed, args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "case_count": reviewed["case_count"],
                "service_mode_distribution": reviewed["service_mode_distribution"],
                "evidence_review_summary": reviewed["evidence_review_summary"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
