from __future__ import annotations

import pytest

from sq_bi_runtime.controlled_query import (
    ControlledPlanError,
    compile_controlled_plan,
    parse_controlled_plan,
)


CATALOG = {"ORDERS": {"ID", "STATUS", "AMOUNT", "CUSTOMER_ID"}}


def test_raw_sql_payload_is_rejected() -> None:
    with pytest.raises(ControlledPlanError, match="raw SQL"):
        parse_controlled_plan('{"sql":"select * from orders","entity":"ORDERS","fields":["ID"]}')


def test_unknown_identifier_and_undeclared_join_are_rejected() -> None:
    plan = parse_controlled_plan('{"entity":"ORDERS","fields":["SECRET"]}')
    with pytest.raises(ControlledPlanError, match="unknown field"):
        compile_controlled_plan(plan, CATALOG)

    join_plan = parse_controlled_plan(
        '{"entity":"ORDERS","fields":["ID"],"joins":[{"relationship_id":"orders_customer"}]}'
    )
    with pytest.raises(ControlledPlanError, match="undeclared relationship"):
        compile_controlled_plan(join_plan, CATALOG)


def test_valid_plan_compiles_with_escaped_literal_and_bound_limit() -> None:
    plan = parse_controlled_plan(
        '{"entity":"ORDERS","fields":["STATUS"],'
        '"aggregates":[{"function":"sum","field":"AMOUNT","alias":"TOTAL"}],'
        '"filters":[{"field":"STATUS","operator":"eq","value":"O\u0027HARE"}],'
        '"group_by":["STATUS"],"limit":25}'
    )
    sql = compile_controlled_plan(plan, CATALOG)
    assert "STATUS = 'O''HARE'" in sql
    assert "SUM(AMOUNT) AS TOTAL" in sql
    assert sql.endswith("FETCH FIRST 25 ROWS ONLY")
