"""将验收案例 TSV 转换为 input/expected 严格隔离的 Eval JSON。"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REQUIRED_COLUMNS = (
    "case_id",
    "conversation_id",
    "关联订单号 / 工单号",
    "cutoff_message_seq",
    "AI 可见输入（cutoff 及之前，不得含标准答案）",
    "① 用户要解决什么",
    "② 正确处理模式",
    "③ 应该怎么回答 / 交接",
    "④ 根据什么",
    "⑤ 绝对不能做什么",
    "本次修正说明（相对 V1.9）",
)
SERVICE_MODES = {"AUTO_REPLY", "AGENT_ASSIST", "HUMAN_REQUIRED"}
MESSAGE_PATTERN = re.compile(
    r"\[(?P<seq>\d+)\]\s+(?P<speaker>买家|客服)\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+▶\s*(?P<content>.*?)"
    r"(?=\n\[\d+\]\s+(?:买家|客服)\s+\d{2}:\d{2}:\d{2}\s+▶|\Z)",
    re.DOTALL,
)
ORDER_ID_PATTERN = re.compile(r"(?<![A-Za-z0-9])\d{16,20}(?![A-Za-z0-9])")
TICKET_ID_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:BH\d+|BLFY\d+)(?![A-Za-z0-9])")


def unique(values: Iterable[str]) -> list[str]:
    """保留输入顺序并去重。"""

    return list(dict.fromkeys(values))


def parse_messages(case_id: str, visible_input: str, cutoff: int) -> list[dict[str, Any]]:
    """解析一段带序号、角色和本地时间的聊天文本。"""

    messages = [
        {
            "message_seq": int(match.group("seq")),
            "role": "consumer" if match.group("speaker") == "买家" else "agent",
            "time_local": match.group("time"),
            "content": match.group("content").strip(),
        }
        for match in MESSAGE_PATTERN.finditer(visible_input.strip())
    ]
    if not messages:
        raise ValueError(f"{case_id}: 无法解析 AI 可见聊天")
    sequences = [message["message_seq"] for message in messages]
    if sequences != sorted(set(sequences)):
        raise ValueError(f"{case_id}: message_seq 必须唯一且递增")
    if sequences[-1] != cutoff:
        raise ValueError(
            f"{case_id}: cutoff_message_seq={cutoff}，但末条可见消息序号={sequences[-1]}"
        )
    return messages


def validate_columns(fieldnames: list[str] | None) -> None:
    missing = [name for name in REQUIRED_COLUMNS if name not in (fieldnames or [])]
    if missing:
        raise ValueError(f"缺少必要列：{', '.join(missing)}")


def convert_rows(rows: Iterable[dict[str, str]]) -> dict[str, Any]:
    """将 DictReader 行转换为稳定的 Eval dataset contract。"""

    cases: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        case_id = row["case_id"].strip()
        if not case_id:
            raise ValueError(f"第 {row_number} 行：case_id 不能为空")
        if case_id in seen_case_ids:
            raise ValueError(f"第 {row_number} 行：case_id 重复：{case_id}")
        seen_case_ids.add(case_id)

        try:
            cutoff = int(row["cutoff_message_seq"])
        except ValueError as exc:
            raise ValueError(f"{case_id}: cutoff_message_seq 必须为整数") from exc
        if cutoff < 1:
            raise ValueError(f"{case_id}: cutoff_message_seq 必须大于等于 1")

        mode = row["② 正确处理模式"].strip()
        if mode not in SERVICE_MODES:
            raise ValueError(f"{case_id}: 不支持的处理模式：{mode}")

        visible_input = row["AI 可见输入（cutoff 及之前，不得含标准答案）"]
        messages = parse_messages(case_id, visible_input, cutoff)
        references = " ".join((row["关联订单号 / 工单号"], row["④ 根据什么"]))
        prohibited_actions = [
            item.strip()
            for item in re.split(r"[；;]", row["⑤ 绝对不能做什么"].strip())
            if item.strip()
        ]
        cases.append(
            {
                "case_id": case_id,
                "input": {
                    "conversation_id": row["conversation_id"].strip(),
                    "cutoff_message_seq": cutoff,
                    "current_message": messages[-1]["content"],
                    "chat_history": messages,
                    "linked_records": {
                        "order_ids": unique(ORDER_ID_PATTERN.findall(references)),
                        "ticket_ids": unique(TICKET_ID_PATTERN.findall(references)),
                        "source_description": row["关联订单号 / 工单号"].strip(),
                    },
                    "data_limitations": [
                        "原始材料未提供聊天日期，time_local 仅保留时分秒，不推测日期。",
                        "原始材料未提供完整订单和工单对象，linked_records 仅保存可核验编号。",
                    ],
                },
                "expected": {
                    "user_intent": row["① 用户要解决什么"].strip(),
                    "service_mode": mode,
                    "response_or_handoff": row["③ 应该怎么回答 / 交接"].strip(),
                    "required_evidence": row["④ 根据什么"].strip(),
                    "prohibited_actions": prohibited_actions,
                },
                "revision_notes": row["本次修正说明（相对 V1.9）"].strip(),
            }
        )

    if not cases:
        raise ValueError("输入文件没有案例")
    return {
        "schema_version": "1.0",
        "dataset_name": "loreal_ai_eval_cases_v2",
        "source_type": "tab_separated_acceptance_cases",
        "case_count": len(cases),
        "service_mode_distribution": dict(
            Counter(case["expected"]["service_mode"] for case in cases)
        ),
        "separation_rule": (
            "input 为模型可见数据；expected 与 revision_notes 仅供 Eval，不得传入模型。"
        ),
        "cases": cases,
    }


def convert_file(source: Path, output: Path, *, compact: bool = False) -> dict[str, Any]:
    """读取 TSV 并原子化写入 JSON，避免失败时留下半成品。"""

    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        validate_columns(reader.fieldnames)
        dataset = convert_rows(reader)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    indent = None if compact else 2
    temporary.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="原始 TSV/txt 文件路径")
    parser.add_argument("output", type=Path, help="输出 JSON 文件路径")
    parser.add_argument("--compact", action="store_true", help="输出无缩进 JSON")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = convert_file(args.source, args.output, compact=args.compact)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "case_count": dataset["case_count"],
                "service_mode_distribution": dataset["service_mode_distribution"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
