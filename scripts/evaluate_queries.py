#!/usr/bin/env python3
"""Run reproducible conversational Harness evaluations against a live SQ-BI API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


class ApiClient:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        login = self.post("/api/v1/auth/login", {"username": username, "password": password})
        self.session_id = str(login["session_id"])

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        headers = {"Content-Type": "application/json"}
        if hasattr(self, "session_id"):
            headers["X-Session-Id"] = self.session_id
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=150) as response:
                envelope = json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
        if envelope.get("error"):
            raise RuntimeError(json.dumps(envelope["error"], ensure_ascii=False))
        return envelope.get("data")


def _flatten(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _checks(result: dict[str, Any], expected: dict[str, Any], elapsed_ms: int) -> list[Check]:
    flattened = _flatten(result)
    checks = [
        Check(
            "status",
            result.get("status") == expected.get("status", "completed"),
            str(result.get("status")),
        )
    ]
    if expected.get("asset_contains"):
        needle = str(expected["asset_contains"])
        checks.append(Check("asset", needle in flattened, needle))
    if expected.get("field_contains"):
        needle = str(expected["field_contains"])
        checks.append(Check("field", needle.lower() in flattened.lower(), needle))
    if expected.get("answer_contains"):
        needle = str(expected["answer_contains"])
        checks.append(Check("answer", needle in str(result.get("answer") or ""), needle))
    if expected.get("lineage"):
        has_lineage = "lineage" in flattened.lower() or "血缘" in flattened
        checks.append(Check("lineage", has_lineage, "lineage evidence present"))
    maximum = int(expected.get("max_elapsed_ms") or 0)
    if maximum:
        checks.append(Check("latency", elapsed_ms <= maximum, f"{elapsed_ms}ms <= {maximum}ms"))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("--base-url", default=os.getenv("SQBI_EVAL_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--username", default=os.getenv("SQBI_EVAL_USERNAME", "admin"))
    parser.add_argument("--password", default=os.getenv("SQBI_EVAL_PASSWORD", "admin123"))
    parser.add_argument("--data-source-id", default=os.getenv("SQBI_EVAL_DATA_SOURCE_ID"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    defaults = suite.get("defaults", {})
    data_source_id = args.data_source_id or defaults.get("data_source_id")
    if not data_source_id:
        parser.error("data source id is required in suite defaults, CLI, or SQBI_EVAL_DATA_SOURCE_ID")

    client = ApiClient(args.base_url, args.username, args.password)
    records: list[dict[str, Any]] = []
    total_checks = passed_checks = 0

    for case in suite.get("cases", []):
        conversation: list[dict[str, str]] = []
        for turn_index, turn in enumerate(case.get("turns", []), start=1):
            started = time.perf_counter()
            error: str | None = None
            try:
                result = client.post(
                    "/api/v1/query/harness",
                    {
                        "question": turn["question"],
                        "context": {
                            "user_id": args.username,
                            "data_source_id": data_source_id,
                            "environment": "default",
                            "workspace_id": args.username,
                        },
                        "execute": True,
                        "conversation": conversation[-12:],
                        "data_source_ids": [data_source_id],
                        "budget": {
                            "max_steps": 8,
                            "max_elapsed_ms": int(defaults.get("max_elapsed_ms", 45000)),
                            "per_tool_timeout_ms": 60000,
                            "max_cost_units": 20,
                        },
                    },
                )
            except Exception as exc:  # noqa: BLE001 - evaluator records transport failures
                result = {"status": "transport_error"}
                error = str(exc)
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            expected = {**defaults, **turn.get("expect", {})}
            checks = _checks(result, expected, elapsed_ms)
            total_checks += len(checks)
            passed_checks += sum(check.passed for check in checks)
            records.append(
                {
                    "case": case["id"],
                    "turn": turn_index,
                    "question": turn["question"],
                    "elapsed_ms": elapsed_ms,
                    "checks": [check.__dict__ for check in checks],
                    "error": error,
                    "result": result,
                }
            )
            marker = "PASS" if all(check.passed for check in checks) else "FAIL"
            print(f"[{marker}] {case['id']}#{turn_index} ({elapsed_ms}ms)")
            for check in checks:
                print(f"  {'✓' if check.passed else '✗'} {check.name}: {check.detail}")
            conversation.extend(
                [
                    {"role": "user", "text": turn["question"]},
                    {"role": "assistant", "text": str(result.get("answer") or result.get("clarification") or "")},
                ]
            )

    score = round((passed_checks / total_checks * 100), 2) if total_checks else 0.0
    report = {
        "suite": suite.get("name", args.suite.name),
        "base_url": args.base_url,
        "data_source_id": data_source_id,
        "score_percent": score,
        "passed_checks": passed_checks,
        "total_checks": total_checks,
        "records": records,
    }
    print(f"\nScore: {score}% ({passed_checks}/{total_checks})")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report: {args.output}")
    return 0 if passed_checks == total_checks else 1


if __name__ == "__main__":
    sys.exit(main())

