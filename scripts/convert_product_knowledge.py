"""将三产品知识库与三情景语义库 XLSX 转换为可审计 JSON。"""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

REQUIRED_SHEETS = {
    "00_使用说明与口径",
    "01_产品知识卡",
    "02_顾客问题清单",
    "03_三情景语义库",
    "04_关键词总表",
    "05_判定顺序与冲突规则",
    "06_待核验与红线",
    "07_网络传言与不可引用",
}
PRODUCT_COLUMNS = (
    "产品编号",
    "天猫商品名（用户提供）",
    "属性类别",
    "属性项",
    "属性值（官方口径原文/摘要）",
    "来源",
    "来源分级",
    "核验状态",
    "是否允许 AUTO_REPLY 引用",
    "不能自动回复时怎么办",
    "备注",
)
QUESTION_COLUMNS = (
    "问题编号",
    "问题分组",
    "顾客典型问法（线上真实口语）",
    "涉及产品",
    "官方场景 S",
    "白名单 W",
    "预期模式",
    "应答要点 / 交接方向",
    "依据",
    "绝对禁止",
)
SEMANTIC_RULE_COLUMNS = (
    "规则编号",
    "目标模式",
    "优先级",
    "规则层级",
    "触发词 / 触发短语（命中任一即触发）",
    "匹配方式",
    "适用产品",
    "顾客原话示例",
    "判定理由",
    "命中后动作",
    "安全边界（命中后禁止做什么）",
)
KEYWORD_COLUMNS = (
    "序号",
    "关键词 / 短语",
    "目标模式",
    "来源规则编号",
    "优先级",
    "规则层级",
    "适用产品",
    "匹配方式",
)
CONFLICT_COLUMNS = ("序号", "规则类别", "规则内容", "示例 / 说明")
REVIEW_COLUMNS = ("序号", "类型", "事项", "影响范围", "建议处理", "责任人")
NEGATIVE_COLUMNS = ("序号", "传言内容", "出处类型", "与本库核实结果的冲突", "处置结论")
SERVICE_MODES = {"AUTO_REPLY", "AGENT_ASSIST", "HUMAN_REQUIRED"}
AUTO_SCENES = {"W01", "W02", "W03", "W04"}
ATTRIBUTE_SCOPES = {
    "官方产品名": "product_name",
    "备案号（备案编号）": "registration_number",
    "注册证号 / 备案号": "registration_number",
    "注册人 / 备案人": "registrant",
    "生产企业 / 生产许可证号": "manufacturer",
    "净含量": "net_content",
    "套装档位": "package_configuration",
    "色号体系": "shade_range",
    "色号命名规则": "shade_naming",
    "适合肤质": "official_skin_type_claim",
    "核心功效宣称": "official_efficacy_claim",
    "技术 / 成分宣称": "official_technology_claim",
    "是否特殊用途化妆品": "special_cosmetic_status",
    "是否含防晒": "sunscreen_status",
    "全成分表": "ingredient_list",
    "使用方法": "product_usage",
    "保存与注意事项": "storage_and_cautions",
    "保质期": "shelf_life",
    "官方渠道": "official_channels",
}
XML_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XML_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _split_phrases(value: str) -> list[str]:
    return [item.strip() for item in value.split("｜") if item.strip()]


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference)
    if not letters:
        raise ValueError(f"无法解析单元格坐标：{reference}")
    result = 0
    for char in letters.group(0):
        result = result * 26 + ord(char) - ord("A") + 1
    return result - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [
        "".join(node.text or "" for node in item.iter(f"{{{XML_MAIN}}}t"))
        for item in root.findall(f"{{{XML_MAIN}}}si")
    ]


def _sheet_paths(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        item.attrib["Id"]: item.attrib["Target"]
        for item in relations.findall(f"{{{XML_PACKAGE_REL}}}Relationship")
    }
    result: dict[str, str] = {}
    for sheet in workbook.findall(f".//{{{XML_MAIN}}}sheet"):
        target = targets[sheet.attrib[f"{{{XML_REL}}}id"]]
        path = target.lstrip("/") if target.startswith("/") else str(PurePosixPath("xl") / target)
        result[sheet.attrib["name"]] = path
    return result


def read_xlsx(source: Path) -> dict[str, list[list[str]]]:
    """仅用 standard library 读取转换所需的 XLSX 单元格值。"""

    if not source.is_file():
        raise ValueError(f"输入文件不存在：{source}")
    try:
        with zipfile.ZipFile(source) as archive:
            shared = _shared_strings(archive)
            sheets: dict[str, list[list[str]]] = {}
            for name, path in _sheet_paths(archive).items():
                root = ET.fromstring(archive.read(path))
                output: list[list[str]] = []
                for row in root.findall(f".//{{{XML_MAIN}}}sheetData/{{{XML_MAIN}}}row"):
                    values: dict[int, str] = {}
                    for cell in row.findall(f"{{{XML_MAIN}}}c"):
                        index = _column_index(cell.attrib["r"])
                        cell_type = cell.attrib.get("t")
                        if cell_type == "inlineStr":
                            value = "".join(
                                item.text or "" for item in cell.iter(f"{{{XML_MAIN}}}t")
                            )
                        else:
                            raw = cell.findtext(f"{{{XML_MAIN}}}v", default="")
                            if cell_type == "s" and raw:
                                value = shared[int(raw)]
                            elif cell_type == "b":
                                value = "true" if raw == "1" else "false"
                            else:
                                value = raw
                        values[index] = value.strip()
                    if values:
                        width = max(values) + 1
                        output.append([values.get(index, "") for index in range(width)])
                sheets[name] = output
    except (zipfile.BadZipFile, ET.ParseError, KeyError, IndexError) as exc:
        raise ValueError(f"无法读取 XLSX：{source}") from exc
    missing = sorted(REQUIRED_SHEETS - sheets.keys())
    if missing:
        raise ValueError(f"缺少必要工作表：{', '.join(missing)}")
    return sheets


def _table(
    rows: list[list[str]], required_columns: tuple[str, ...], sheet_name: str
) -> list[dict[str, str]]:
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if set(required_columns).issubset({_text(item) for item in row})
        ),
        None,
    )
    if header_index is None:
        raise ValueError(f"{sheet_name}: 找不到必要表头")
    header = [_text(item) for item in rows[header_index]]
    result: list[dict[str, str]] = []
    for source_row, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        padded = [*row, *([""] * max(0, len(header) - len(row)))]
        record = {column: _text(padded[header.index(column)]) for column in required_columns}
        if record[required_columns[0]]:
            record["_source_row"] = str(source_row)
            result.append(record)
    return result


def _source_version(rows: list[list[str]]) -> tuple[str, str]:
    for row in rows:
        if row and _text(row[0]) == "版本 / 日期" and len(row) > 1:
            match = re.match(r"\s*([^/]+?)\s*/\s*(\d{4}-\d{2}-\d{2})\s*$", _text(row[1]))
            if match:
                return match.group(1).strip(), match.group(2)
    raise ValueError("00_使用说明与口径: 无法解析版本 / 日期")


def _knowledge_exclusion_reason(record: dict[str, str]) -> str | None:
    if record["核验状态"] != "已登记":
        return f"核验状态为 {record['核验状态'] or '空'}"
    permission = record["是否允许 AUTO_REPLY 引用"]
    if not permission.startswith("是"):
        return f"AUTO_REPLY 引用权限为 {permission or '空'}"
    if "仅限禁止" in permission:
        return "该行仅描述禁止项，不能作为正向回答证据"
    if not record["属性值（官方口径原文/摘要）"]:
        return "知识正文为空"
    if record["来源"] in {"", "—", "-"}:
        return "来源不可追踪"
    return None


def build_bundle(sheets: dict[str, list[list[str]]]) -> dict[str, Any]:
    """把已解析工作表转换成稳定、可审计的知识与 routing bundle。"""

    version, source_date = _source_version(sheets["00_使用说明与口径"])
    observed_at = f"{source_date}T00:00:00+08:00"
    product_rows = _table(sheets["01_产品知识卡"], PRODUCT_COLUMNS, "01_产品知识卡")
    question_rows = _table(sheets["02_顾客问题清单"], QUESTION_COLUMNS, "02_顾客问题清单")
    semantic_rows = _table(sheets["03_三情景语义库"], SEMANTIC_RULE_COLUMNS, "03_三情景语义库")
    keyword_rows = _table(sheets["04_关键词总表"], KEYWORD_COLUMNS, "04_关键词总表")
    conflict_rows = _table(
        sheets["05_判定顺序与冲突规则"], CONFLICT_COLUMNS, "05_判定顺序与冲突规则"
    )
    review_rows = _table(sheets["06_待核验与红线"], REVIEW_COLUMNS, "06_待核验与红线")
    negative_rows = _table(
        sheets["07_网络传言与不可引用"], NEGATIVE_COLUMNS, "07_网络传言与不可引用"
    )

    product_ids = sorted({item["产品编号"] for item in product_rows})
    products: list[dict[str, Any]] = []
    aliases: dict[str, list[str]] = {}
    for product_id in product_ids:
        matching = [item for item in product_rows if item["产品编号"] == product_id]
        official = next(
            (
                item["属性值（官方口径原文/摘要）"]
                for item in matching
                if item["属性项"] == "官方产品名" and not _knowledge_exclusion_reason(item)
            ),
            None,
        )
        if not official:
            raise ValueError(f"{product_id}: 缺少已登记且允许引用的官方产品名")
        products.append(
            {
                "product_id": product_id,
                "sku": None,
                "name": official,
                "source_id": "three-product-knowledge-workbook",
                "observed_at": observed_at,
                "valid_until": None,
            }
        )
        aliases[product_id] = list(
            dict.fromkeys(item["天猫商品名（用户提供）"] for item in matching)
        )

    knowledge: list[dict[str, Any]] = []
    constraints: dict[str, dict[str, Any]] = {}
    excluded: list[dict[str, Any]] = []
    for item in product_rows:
        reason = _knowledge_exclusion_reason(item)
        source_row = int(item["_source_row"])
        if reason:
            excluded.append(
                {
                    "product_id": item["产品编号"],
                    "attribute": item["属性项"],
                    "verification_status": item["核验状态"],
                    "auto_reply_permission": item["是否允许 AUTO_REPLY 引用"],
                    "reason": reason,
                    "fallback": item["不能自动回复时怎么办"],
                    "source_ref": {"sheet": "01_产品知识卡", "row": source_row},
                }
            )
            continue
        evidence_id = f"KB-{item['产品编号']}-{source_row:04d}"
        scope = ATTRIBUTE_SCOPES.get(item["属性项"], f"source_row_{source_row}")
        knowledge.append(
            {
                "evidence_id": evidence_id,
                "source": item["来源"],
                "excerpt": item["属性值（官方口径原文/摘要）"],
                "product_id": item["产品编号"],
                "scope": scope,
                "version": version,
                "observed_at": observed_at,
                "valid_until": None,
                "valid": True,
            }
        )
        constraints[evidence_id] = {
            "attribute_category": item["属性类别"],
            "attribute": item["属性项"],
            "source_level": item["来源分级"],
            "usage_constraint": item["是否允许 AUTO_REPLY 引用"],
            "fallback": item["不能自动回复时怎么办"],
            "notes": item["备注"],
            "source_ref": {"sheet": "01_产品知识卡", "row": source_row},
        }

    semantic_rules = []
    rule_ids: set[str] = set()
    for item in semantic_rows:
        rule_id = item["规则编号"]
        mode = item["目标模式"]
        if rule_id in rule_ids:
            raise ValueError(f"03_三情景语义库: 规则编号重复：{rule_id}")
        if mode not in SERVICE_MODES:
            raise ValueError(f"{rule_id}: 不支持的目标模式：{mode}")
        rule_ids.add(rule_id)
        semantic_rules.append(
            {
                "rule_id": rule_id,
                "target_mode": mode,
                "priority": item["优先级"],
                "rule_level": item["规则层级"],
                "trigger_phrases": _split_phrases(item["触发词 / 触发短语（命中任一即触发）"]),
                "match_type": item["匹配方式"],
                "applicable_products": item["适用产品"],
                "example": item["顾客原话示例"],
                "reason": item["判定理由"],
                "action": item["命中后动作"],
                "safety_boundary": item["安全边界（命中后禁止做什么）"],
                "source_ref": {
                    "sheet": "03_三情景语义库",
                    "row": int(item["_source_row"]),
                },
            }
        )

    keyword_rules = []
    for item in keyword_rows:
        rule_id = item["来源规则编号"]
        mode = item["目标模式"]
        if rule_id not in rule_ids:
            raise ValueError(f"04_关键词总表: 来源规则不存在：{rule_id}")
        semantic_mode = next(
            rule["target_mode"] for rule in semantic_rules if rule["rule_id"] == rule_id
        )
        if mode != semantic_mode:
            raise ValueError(f"04_关键词总表: {rule_id} 的目标模式与语义库不一致")
        keyword_rules.append(
            {
                "keyword": item["关键词 / 短语"],
                "target_mode": mode,
                "source_rule_id": rule_id,
                "priority": item["优先级"],
                "rule_level": item["规则层级"],
                "applicable_products": item["适用产品"],
                "match_type": item["匹配方式"],
                "source_ref": {
                    "sheet": "04_关键词总表",
                    "row": int(item["_source_row"]),
                },
            }
        )

    examples = [
        {
            "question_id": item["问题编号"],
            "group": item["问题分组"],
            "utterance": item["顾客典型问法（线上真实口语）"],
            "applicable_products": item["涉及产品"],
            "scene_major": item["官方场景 S"],
            "scene_minor": item["白名单 W"],
            "expected_mode": item["预期模式"],
            "response_guidance": item["应答要点 / 交接方向"],
            "evidence_requirement": item["依据"],
            "prohibited_action": item["绝对禁止"],
            "source_ref": {
                "sheet": "02_顾客问题清单",
                "row": int(item["_source_row"]),
            },
        }
        for item in question_rows
    ]
    conflict_rules = [
        {
            "id": item["序号"],
            "category": item["规则类别"],
            "rule": item["规则内容"],
            "example": item["示例 / 说明"],
        }
        for item in conflict_rows
    ]
    review_items = [
        {
            "id": item["序号"],
            "type": item["类型"],
            "item": item["事项"],
            "impact": item["影响范围"],
            "recommended_action": item["建议处理"],
            "owner": item["责任人"],
        }
        for item in review_rows
    ]
    prohibited_knowledge = [
        {
            "id": item["序号"],
            "claim": item["传言内容"],
            "source_type": item["出处类型"],
            "conflict": item["与本库核实结果的冲突"],
            "disposition": item["处置结论"],
        }
        for item in negative_rows
    ]
    auto_rules = [rule for rule in semantic_rules if rule["target_mode"] == "AUTO_REPLY"]
    auto_keywords = [rule for rule in keyword_rules if rule["target_mode"] == "AUTO_REPLY"]
    unexpected_auto_scenes = sorted(
        {scene for rule in auto_rules for scene in AUTO_SCENES if scene in rule["rule_level"]}
        ^ AUTO_SCENES
    )
    if unexpected_auto_scenes:
        raise ValueError(
            "AUTO_REPLY 语义库未完整覆盖 W01-W04：" + ", ".join(unexpected_auto_scenes)
        )

    return {
        "schema_version": "1.0",
        "dataset_name": "loreal_three_product_knowledge_and_routing",
        "source": {
            "workbook_version": version,
            "effective_date": source_date,
            "contains_customer_data": False,
        },
        "policy": {
            "mode_priority": ["HUMAN_REQUIRED", "AGENT_ASSIST", "AUTO_REPLY"],
            "auto_reply_scenes": sorted(AUTO_SCENES),
            "knowledge_gate": (
                "仅核验状态为已登记、AUTO_REPLY 权限以“是”开头、来源可追踪且"
                "非仅禁止项的知识进入有效证据。"
            ),
        },
        "products": products,
        "product_aliases": aliases,
        "knowledge_evidence": knowledge,
        "evidence_constraints": constraints,
        "excluded_knowledge": excluded,
        "semantic_rules": semantic_rules,
        "keyword_rules": keyword_rules,
        "question_examples": examples,
        "conflict_rules": conflict_rules,
        "review_items": review_items,
        "prohibited_knowledge": prohibited_knowledge,
        "audit": {
            "product_count": len(products),
            "accepted_knowledge_count": len(knowledge),
            "excluded_knowledge_count": len(excluded),
            "semantic_rule_count": len(semantic_rules),
            "keyword_rule_count": len(keyword_rules),
            "question_example_count": len(examples),
            "mode_rule_distribution": dict(
                sorted(Counter(item["target_mode"] for item in semantic_rules).items())
            ),
            "mode_keyword_distribution": dict(
                sorted(Counter(item["target_mode"] for item in keyword_rules).items())
            ),
            "auto_reply_rule_count": len(auto_rules),
            "auto_reply_keyword_count": len(auto_keywords),
        },
    }


def convert_file(source: Path, output: Path, *, compact: bool = False) -> dict[str, Any]:
    """读取 XLSX 并原子化写入 JSON。"""

    bundle = build_bundle(read_xlsx(source))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=None if compact else 2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return bundle


def parse_args(args: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="三产品知识与三情景语义库 XLSX 路径")
    parser.add_argument("output", type=Path, help="输出 JSON 路径")
    parser.add_argument("--compact", action="store_true", help="输出无缩进 JSON")
    return parser.parse_args(args)


def main() -> None:
    args = parse_args()
    bundle = convert_file(args.source, args.output, compact=args.compact)
    print(json.dumps({"output": str(args.output), **bundle["audit"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
