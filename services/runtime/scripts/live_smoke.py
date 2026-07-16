from __future__ import annotations

import json
from dataclasses import dataclass

from sq_bi_runtime.config import load_config
from sq_bi_runtime.db import OracleExecutor
from sq_bi_runtime.llm_client import OpenAICompatClient
from sq_bi_runtime.service import build_service
from sq_bi_runtime.skill_loader import load_skill_bundle


@dataclass
class SmokeCase:
    question: str
    expect_rows: bool = True


CASES = [
    SmokeCase("本月发货申请了多少单？"),
    SmokeCase("本月制单了多少单？"),
    SmokeCase("当前有多少单在运输途中？"),
    SmokeCase("本月已签收多少单？"),
    SmokeCase("本月哪些承运商承运量最高？"),
    SmokeCase("本月准时到货率是多少？"),
    SmokeCase("本月哪些项目发货量最高？"),
    SmokeCase("本月不同运输方式的申请量分布如何？"),
    SmokeCase("本月询价单有多少？"),
    SmokeCase("本月哪些供应商报价次数最多？"),
]


def main() -> None:
    cfg = load_config("config.yaml")
    if not cfg.db.is_configured:
        raise SystemExit("TMS_DB_USER / TMS_DB_PASSWORD / TMS_DB_DSN must be configured for live smoke tests.")

    service = build_service(
        skill_context=load_skill_bundle(cfg.skill_dir),
        llm_client=OpenAICompatClient(cfg.llm),
        db_executor=OracleExecutor(cfg.db),
    )

    results: list[dict[str, object]] = []
    failures = 0
    for case in CASES:
        try:
            result = service.ask(case.question, execute_sql=True)
            row_count = len(result["rows"])
            ok = bool(result["sql"]) and (row_count > 0 if case.expect_rows else True)
            if not ok:
                failures += 1
            results.append(
                {
                    "question": case.question,
                    "ok": ok,
                    "intent": result["intent"],
                    "row_count": row_count,
                    "columns": result["columns"],
                    "sql": result["sql"],
                }
            )
        except Exception as exc:  # noqa: BLE001
            failures += 1
            results.append(
                {
                    "question": case.question,
                    "ok": False,
                    "error": str(exc),
                }
            )

    print(json.dumps({"failures": failures, "results": results}, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
