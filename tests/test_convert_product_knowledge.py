from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "convert_product_knowledge.py"
SPEC = importlib.util.spec_from_file_location("convert_product_knowledge", SCRIPT_PATH)
assert SPEC and SPEC.loader
CONVERTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONVERTER)


def sample_sheets() -> dict[str, list[list[str]]]:
    product_header = list(CONVERTER.PRODUCT_COLUMNS)
    question_header = list(CONVERTER.QUESTION_COLUMNS)
    semantic_header = list(CONVERTER.SEMANTIC_RULE_COLUMNS)
    keyword_header = list(CONVERTER.KEYWORD_COLUMNS)
    conflict_header = list(CONVERTER.CONFLICT_COLUMNS)
    review_header = list(CONVERTER.REVIEW_COLUMNS)
    negative_header = list(CONVERTER.NEGATIVE_COLUMNS)
    return {
        "00_使用说明与口径": [["版本 / 日期", "V1.0 / 2026-09-30"]],
        "01_产品知识卡": [
            product_header,
            [
                "P-001",
                "商品别名",
                "标识信息",
                "官方产品名",
                "正式产品名",
                "官方来源",
                "L1",
                "已登记",
                "是",
                "—",
                "",
            ],
            [
                "P-001",
                "商品别名",
                "标识信息",
                "备案号",
                "待核验号码",
                "渠道镜像",
                "L2",
                "待核验",
                "是（仅可原样播报号码）",
                "转人工",
                "",
            ],
        ],
        "02_顾客问题清单": [
            question_header,
            [
                "Q-1",
                "规格",
                "多少毫升",
                "P-001",
                "S01",
                "W01",
                "AUTO_REPLY",
                "回答",
                "知识",
                "不得编造",
            ],
        ],
        "03_三情景语义库": [
            semantic_header,
            *[
                [
                    f"AR-0{index}",
                    "AUTO_REPLY",
                    "P3",
                    f"W0{index} 白名单",
                    f"触发词{index} ｜ 同义词{index}",
                    "关键词包含匹配",
                    "全部三款",
                    "示例",
                    "低风险",
                    "回复",
                    "不得编造",
                ]
                for index in range(1, 5)
            ],
        ],
        "04_关键词总表": [
            keyword_header,
            *[
                [
                    str(index),
                    f"触发词{index}",
                    "AUTO_REPLY",
                    f"AR-0{index}",
                    "P3",
                    f"W0{index} 白名单",
                    "全部三款",
                    "关键词包含匹配",
                ]
                for index in range(1, 5)
            ],
        ],
        "05_判定顺序与冲突规则": [
            conflict_header,
            ["1", "优先级", "HUMAN_REQUIRED 优先", "投诉时转人工"],
        ],
        "06_待核验与红线": [
            review_header,
            ["1", "红线", "不得编造成分", "全部", "转人工", "全体"],
        ],
        "07_网络传言与不可引用": [
            negative_header,
            ["1", "错误宣称", "自媒体", "无官方依据", "禁止入库"],
        ],
    }


def test_build_bundle_only_accepts_strictly_verified_knowledge() -> None:
    bundle = CONVERTER.build_bundle(sample_sheets())

    assert bundle["products"][0]["name"] == "正式产品名"
    assert bundle["knowledge_evidence"] == [
        {
            "evidence_id": "KB-P-001-0002",
            "source": "官方来源",
            "excerpt": "正式产品名",
            "product_id": "P-001",
            "scope": "product_name",
            "version": "V1.0",
            "observed_at": "2026-09-30T00:00:00+08:00",
            "valid_until": None,
            "valid": True,
        }
    ]
    assert bundle["excluded_knowledge"][0]["attribute"] == "备案号"
    assert bundle["excluded_knowledge"][0]["reason"] == "核验状态为 待核验"
    assert bundle["audit"]["auto_reply_rule_count"] == 4
    assert bundle["audit"]["auto_reply_keyword_count"] == 4


def test_build_bundle_rejects_keyword_mode_conflict() -> None:
    sheets = sample_sheets()
    sheets["04_关键词总表"][1][2] = "HUMAN_REQUIRED"

    with pytest.raises(ValueError, match="目标模式与语义库不一致"):
        CONVERTER.build_bundle(sheets)


def test_convert_file_writes_json_atomically_from_workbook(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    output = tmp_path / "bundle.json"
    write_inline_string_workbook(source, sample_sheets())

    bundle = CONVERTER.convert_file(source, output)

    assert json.loads(output.read_text(encoding="utf-8")) == bundle
    assert bundle["audit"]["accepted_knowledge_count"] == 1
    assert bundle["audit"]["excluded_knowledge_count"] == 1


def write_inline_string_workbook(path: Path, sheets: dict[str, list[list[str]]]) -> None:
    workbook_sheets = []
    relationships = []
    content_overrides = []
    worksheet_files: dict[str, str] = {}
    for index, (name, rows) in enumerate(sheets.items(), start=1):
        workbook_sheets.append(
            f'<sheet name="{xml_escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
        )
        relationships.append(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
        content_overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        row_xml = []
        for row_number, row in enumerate(rows, start=1):
            cells = []
            for column_number, value in enumerate(row, start=1):
                reference = f"{column_name(column_number)}{row_number}"
                cells.append(
                    f'<c r="{reference}" t="inlineStr"><is><t>{xml_escape(value)}</t></is></c>'
                )
            row_xml.append(f'<row r="{row_number}">{"".join(cells)}</row>')
        worksheet_files[f"xl/worksheets/sheet{index}.xml"] = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{''.join(row_xml)}</sheetData></worksheet>"
        )

    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{''.join(workbook_sheets)}</sheets></workbook>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(relationships)}</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        f"{''.join(content_overrides)}</Types>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        for name, content in worksheet_files.items():
            archive.writestr(name, content)


def column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def xml_escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
