from __future__ import annotations

import json

from sq_bi_contracts.execution import PlanFilter
from sq_bi_contracts.metrics import MetricDefinition, MetricFormula

from sq_bi_runtime.runtime_filters import (
    apply_runtime_filters,
    apply_runtime_dimension_order,
    apply_runtime_group_by,
    apply_runtime_ranking,
    bind_runtime_parameters,
)


class _StubLLM:
    def chat(self, system: str, user: str) -> str:
        assert "never SQL" in system
        assert "TMS_ORDER.REGION_NAME" in user
        return json.dumps({
            "filters": [
                {"field": "REGION_NAME", "operator": "eq", "value": "华东"},
                {"field": "TMS_ORDER.CREATED_AT", "operator": "gte", "value": "2026-06-01"},
                {"field": "TMS_ORDER.CREATED_AT", "operator": "lt", "value": "2026-07-01"},
                {"field": "NOT_ALLOWED", "operator": "eq", "value": "x"},
            ],
            "dimensions": ["REGION_NAME"],
            "ranking": {"direction": "desc", "limit": 1},
            "assumptions": ["上个月按自然月计算"],
            "unresolved": [],
            "requires_clarification": False,
        }, ensure_ascii=False)


def _metric() -> MetricDefinition:
    return MetricDefinition(
        metric_code="order_count",
        name="订单量",
        definition="订单数量",
        visibility="official",
        formula=MetricFormula(
            expression="SELECT COUNT(ID) AS VALUE FROM TMS_ORDER",
            time_field="CREATED_AT",
        ),
        data_source_id="tms",
        owner="official",
    )


def test_model_bindings_are_restricted_to_catalog_fields() -> None:
    bindings = bind_runtime_parameters(
        _StubLLM(),
        question="上个月华东订单量",
        metric=_metric(),
        sql="SELECT COUNT(ID) AS VALUE FROM TMS_ORDER",
        schema_catalog={"TMS_ORDER": {"ID", "REGION_NAME", "CREATED_AT"}},
    )
    assert [item.field for item in bindings.filters] == [
        "TMS_ORDER.REGION_NAME",
        "TMS_ORDER.CREATED_AT",
        "TMS_ORDER.CREATED_AT",
    ]
    assert bindings.dimensions == ["TMS_ORDER.REGION_NAME"]
    assert bindings.metric_order == "desc"
    assert bindings.result_limit == 1


def test_runtime_filters_are_compiled_without_accepting_sql() -> None:
    sql = apply_runtime_filters(
        "SELECT COUNT(ID) AS VALUE FROM TMS_ORDER o",
        [
            PlanFilter(field="TMS_ORDER.REGION_NAME", operator="eq", value="华东"),
            PlanFilter(field="TMS_ORDER.CREATED_AT", operator="gte", value="2026-06-01"),
        ],
    )
    assert "o.REGION_NAME = '华东'" in sql
    assert "TO_DATE('2026-06-01', 'YYYY-MM-DD')" in sql


def test_runtime_dimensions_are_added_to_metric_grouping() -> None:
    sql = apply_runtime_group_by(
        "SELECT ROUND(AVG(TRANSPORT_COST), 2) AS VALUE FROM V_SHIPMENT_ANALYSIS",
        ["V_SHIPMENT_ANALYSIS.CARRIER_NAME"],
        dialect="postgres",
    )
    assert sql.startswith("SELECT V_SHIPMENT_ANALYSIS.CARRIER_NAME,")
    assert "AVG(TRANSPORT_COST)" in sql
    assert "GROUP BY V_SHIPMENT_ANALYSIS.CARRIER_NAME" in sql


def test_runtime_ranking_orders_metric_alias_and_limits_rows() -> None:
    sql = apply_runtime_ranking(
        "SELECT CARRIER_NAME, AVG(TRANSPORT_COST) AS VALUE FROM V_SHIPMENT_ANALYSIS GROUP BY CARRIER_NAME",
        "desc",
        1,
        dialect="postgres",
    )
    assert "ORDER BY VALUE DESC" in sql
    assert "LIMIT 1" in sql


def test_runtime_dimension_order_keeps_full_time_series() -> None:
    sql = apply_runtime_dimension_order(
        "SELECT SHIP_DATE, AVG(TRANSPORT_COST) AS VALUE FROM V_SHIPMENT_ANALYSIS GROUP BY SHIP_DATE",
        "asc",
        dialect="postgres",
    )
    assert "ORDER BY SHIP_DATE ASC" in sql
    assert "LIMIT" not in sql
