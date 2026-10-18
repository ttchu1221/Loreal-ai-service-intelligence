from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "convert_eval_cases.py"
SPEC = importlib.util.spec_from_file_location("convert_eval_cases", SCRIPT_PATH)
assert SPEC and SPEC.loader
CONVERTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONVERTER)
REQUIRED_COLUMNS = CONVERTER.REQUIRED_COLUMNS
convert_file = CONVERTER.convert_file


def write_tsv(path: Path, **overrides: str) -> None:
    row = {
        "case_id": "C-001",
        "conversation_id": "S00001",
        "关联订单号 / 工单号": "订单 6920071889989423403 / 工单 BH123456",
        "cutoff_message_seq": "2",
        "AI 可见输入（cutoff 及之前，不得含标准答案）": (
            "[1] 买家 10:00:00 ▶ 退款在哪里\n[2] 客服 10:00:30 ▶ 我来核实"
        ),
        "① 用户要解决什么": "查询退款进度",
        "② 正确处理模式": "AGENT_ASSIST",
        "③ 应该怎么回答 / 交接": "核实后回复",
        "④ 根据什么": "订单和工单",
        "⑤ 绝对不能做什么": "不得承诺到账；不得虚构状态",
        "本次修正说明（相对 V1.9）": "模式已校准",
    }
    row.update(overrides)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS, delimiter="\t")
        writer.writeheader()
        writer.writerow(row)


def test_convert_file_separates_model_input_from_expected_answer(tmp_path: Path) -> None:
    source = tmp_path / "cases.txt"
    output = tmp_path / "cases.json"
    write_tsv(source)

    dataset = convert_file(source, output)

    case = dataset["cases"][0]
    assert dataset["case_count"] == 1
    assert dataset["service_mode_distribution"] == {"AGENT_ASSIST": 1}
    assert case["input"]["current_message"] == "我来核实"
    assert case["input"]["linked_records"] == {
        "order_ids": ["6920071889989423403"],
        "ticket_ids": ["BH123456"],
        "source_description": "订单 6920071889989423403 / 工单 BH123456",
    }
    assert case["expected"]["prohibited_actions"] == [
        "不得承诺到账",
        "不得虚构状态",
    ]
    assert "expected" not in case["input"]
    assert json.loads(output.read_text(encoding="utf-8")) == dataset


def test_convert_file_rejects_cutoff_after_visible_messages(tmp_path: Path) -> None:
    source = tmp_path / "cases.txt"
    write_tsv(source, cutoff_message_seq="3")

    with pytest.raises(ValueError, match="末条可见消息序号=2"):
        convert_file(source, tmp_path / "cases.json")


def test_convert_file_rejects_unknown_service_mode_without_output(tmp_path: Path) -> None:
    source = tmp_path / "cases.txt"
    output = tmp_path / "cases.json"
    write_tsv(source, **{"② 正确处理模式": "AUTO"})

    with pytest.raises(ValueError, match="不支持的处理模式"):
        convert_file(source, output)
    assert not output.exists()
