"""运行转换后的 Eval JSON，并输出 deterministic baseline 报告。"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from loreal_ai_service_intelligence.evaluation import (
    load_eval_dataset,
    run_eval_dataset,
    write_eval_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="转换后的 Eval JSON")
    parser.add_argument("output", type=Path, help="Eval 报告输出路径")
    parser.add_argument(
        "--reference-date",
        type=date.fromisoformat,
        required=True,
        help="补足只有时分秒的消息时间，格式 YYYY-MM-DD；不参与业务判断",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_eval_dataset(
        load_eval_dataset(args.dataset),
        reference_date=args.reference_date,
    )
    write_eval_report(report, args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "case_count": report["case_count"],
                "metrics": report["metrics"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
