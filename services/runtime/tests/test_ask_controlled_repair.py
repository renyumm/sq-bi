from __future__ import annotations

import json

import pytest

from sq_bi_runtime.controlled_query import ControlledPlanError
from sq_bi_runtime.datasource_executors import ConnectorExecutor
from sq_bi_runtime.service import AskDataService

CATALOG = {"ORDERS": {"ID", "STATUS", "IS_PAID"}}

GOOD_PLAN = json.dumps({
    "entity": "ORDERS",
    "aggregates": [{"function": "count", "alias": "order_count"}],
})
BAD_PLAN = json.dumps({
    "entity": "ORDERS",
    "aggregates": [{"function": "count", "alias": "order_count"}],
    "filters": [{"field": "SECRET_FIELD", "operator": "eq", "value": "x"}],
})


class ScriptedLLM:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.prompts: list[str] = []

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        del system_prompt
        self.prompts.append(user_prompt)
        return self.outputs[min(len(self.prompts) - 1, len(self.outputs) - 1)]


class FakeExecutor:
    def __init__(self, fail_first: int = 0) -> None:
        self.calls = 0
        self.fail_first = fail_first

    def execute(self, sql: str, max_rows: int = 200):
        del sql, max_rows
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RuntimeError("function avg(boolean) does not exist")
        return {"columns": ["order_count"], "rows": [[42]]}


def _service(llm: ScriptedLLM, executor: FakeExecutor | None) -> AskDataService:
    return AskDataService(
        skill_context="",
        llm_client=llm,
        db_executor=executor,
        schema_catalog=CATALOG,
        sql_dialect="postgres",
    )


def test_repair_loop_recovers_from_invalid_plan() -> None:
    llm = ScriptedLLM([BAD_PLAN, GOOD_PLAN])
    result = _service(llm, FakeExecutor()).ask_controlled("有多少订单")

    assert result["rows"] == [[42]]
    assert result["repair_attempts"] == 1
    assert len(llm.prompts) == 2
    # 修复轮的提示必须携带失败计划与错误信息
    assert "Previous plan failed" in llm.prompts[1]
    assert "SECRET_FIELD" in llm.prompts[1]


def test_repair_loop_recovers_from_database_error() -> None:
    llm = ScriptedLLM([GOOD_PLAN, GOOD_PLAN])
    executor = FakeExecutor(fail_first=1)
    result = _service(llm, executor).ask_controlled("有多少订单")

    assert result["rows"] == [[42]]
    assert result["repair_attempts"] == 1
    assert "avg(boolean) does not exist" in llm.prompts[1]


def test_repair_loop_exhaustion_reraises_last_error() -> None:
    llm = ScriptedLLM([BAD_PLAN])
    with pytest.raises(ControlledPlanError, match="unknown filter field"):
        _service(llm, FakeExecutor()).ask_controlled("有多少订单")
    # 初次 + max_repair_attempts 次修复
    assert len(llm.prompts) == 3


def test_first_attempt_success_records_zero_repairs() -> None:
    llm = ScriptedLLM([GOOD_PLAN])
    result = _service(llm, FakeExecutor()).ask_controlled("有多少订单")
    assert result["repair_attempts"] == 0
    assert len(llm.prompts) == 1


class StubConnector:
    def describe_schema(self, schema=None):
        del schema
        return [
            {"table": "orders", "column": "id", "data_type": "Integer"},
            {"table": "orders", "column": "is_paid", "data_type": "BOOLEAN"},
        ]

    def get_schema_catalog(self):
        return {"orders": ["id", "is_paid"]}


def test_executor_typed_catalog_is_normalized_and_cached() -> None:
    executor = ConnectorExecutor(StubConnector())
    types = executor.get_schema_column_types()
    assert types == {"ORDERS": {"ID": "integer", "IS_PAID": "boolean"}}
    assert executor.get_schema_column_types() is types
