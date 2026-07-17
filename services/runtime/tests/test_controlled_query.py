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


def test_filter_key_synonym_column_is_normalized_to_field() -> None:
    plan = parse_controlled_plan(
        '{"entity":"ORDERS","fields":["ID"],'
        '"filters":[{"column":"STATUS","operator":"eq","value":"OPEN"}]}'
    )
    sql = compile_controlled_plan(plan, CATALOG)
    assert "STATUS = 'OPEN'" in sql


def test_relative_date_filter_value_compiles_to_date_expression() -> None:
    for value in (
        "CURRENT_DATE - INTERVAL 30 DAY",
        "CURRENT_DATE - INTERVAL '30 days'",
        "current_date - 30",
        "SYSDATE - 30 DAYS",
    ):
        plan = parse_controlled_plan(
            '{"entity":"ORDERS","fields":["ID"],'
            f'"filters":[{{"field":"STATUS","operator":"gte","value":"{value}"}}]}}'
        )
        sql = compile_controlled_plan(plan, CATALOG)
        assert "STATUS >= CURRENT_DATE - INTERVAL '30' DAY" in sql, (value, sql)


def test_plain_string_filter_values_stay_quoted_literals() -> None:
    plan = parse_controlled_plan(
        '{"entity":"ORDERS","fields":["ID"],'
        '"filters":[{"field":"STATUS","operator":"eq","value":"CURRENT_DATE_REPORT"}]}'
    )
    sql = compile_controlled_plan(plan, CATALOG)
    assert "STATUS = 'CURRENT_DATE_REPORT'" in sql


COLUMN_TYPES = {"ORDERS": {"ID": "integer", "STATUS": "text", "AMOUNT": "numeric", "IS_PAID": "boolean"}}
CATALOG_TYPED = {"ORDERS": {"ID", "STATUS", "AMOUNT", "IS_PAID"}}


def test_boolean_avg_and_sum_are_wrapped_when_types_known() -> None:
    plan = parse_controlled_plan(
        '{"entity":"ORDERS","aggregates":['
        '{"function":"avg","field":"IS_PAID","alias":"paid_rate"},'
        '{"function":"sum","field":"IS_PAID","alias":"paid_count"},'
        '{"function":"avg","field":"AMOUNT","alias":"avg_amount"}]}'
    )
    sql = compile_controlled_plan(plan, CATALOG_TYPED, column_types=COLUMN_TYPES)
    assert "AVG(CASE WHEN IS_PAID THEN 1 ELSE 0 END) AS paid_rate" in sql
    assert "SUM(CASE WHEN IS_PAID THEN 1 ELSE 0 END) AS paid_count" in sql
    assert "AVG(AMOUNT) AS avg_amount" in sql


def test_boolean_wrap_is_skipped_without_type_information() -> None:
    plan = parse_controlled_plan(
        '{"entity":"ORDERS","aggregates":[{"function":"avg","field":"IS_PAID"}]}'
    )
    sql = compile_controlled_plan(plan, CATALOG_TYPED, column_types=None)
    assert "AVG(IS_PAID)" in sql


def test_mysql_tinyint1_counts_as_boolean() -> None:
    types = {"ORDERS": {"IS_PAID": "tinyint(1)"}}
    plan = parse_controlled_plan(
        '{"entity":"ORDERS","aggregates":[{"function":"sum","field":"IS_PAID"}]}'
    )
    sql = compile_controlled_plan(plan, CATALOG_TYPED, column_types=types)
    assert "SUM(CASE WHEN IS_PAID THEN 1 ELSE 0 END)" in sql
