from __future__ import annotations

import pytest
from pydantic import ValidationError

from sq_bi_contracts.execution import ControlledQueryPlan, ResolvedExecutionRequest
from sq_bi_contracts.enums import ExecutionPath
from sq_bi_contracts.runtime_projection import RuntimeRequestContext


def test_formal_execution_requires_exact_selected_asset() -> None:
    with pytest.raises(ValidationError):
        ResolvedExecutionRequest(
            question="shipment count",
            context=RuntimeRequestContext(user_id="u1", data_source_id="ds1"),
            execution_path=ExecutionPath.FORMAL_METRIC,
        )


def test_controlled_plan_rejects_sql_identifiers_and_unbounded_limit() -> None:
    with pytest.raises(ValidationError):
        ControlledQueryPlan(entity="orders; drop table x", fields=["id"])
    with pytest.raises(ValidationError):
        ControlledQueryPlan(entity="orders", fields=["id"], limit=201)


def test_controlled_plan_accepts_closed_grammar() -> None:
    plan = ControlledQueryPlan.model_validate(
        {
            "entity": "orders",
            "fields": ["status"],
            "aggregates": [{"function": "count", "alias": "order_count"}],
            "filters": [{"field": "status", "operator": "eq", "value": "OPEN"}],
            "group_by": ["status"],
            "limit": 50,
        }
    )
    assert plan.limit == 50
