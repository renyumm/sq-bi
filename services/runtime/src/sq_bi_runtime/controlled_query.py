from __future__ import annotations

import json
import re
from typing import Any

from sq_bi_contracts.execution import ControlledQueryPlan


class ControlledPlanError(ValueError):
    pass


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Models regularly emit "column" where the contract says "field"; accept the
# synonym instead of failing an otherwise valid plan.
_FIELD_KEY_ALIASES = ("column", "field_id", "column_name")


def _normalize_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("filters", "aggregates", "order_by"):
        items = payload.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and "field" not in item:
                for alias in _FIELD_KEY_ALIASES:
                    if alias in item:
                        item["field"] = item.pop(alias)
                        break
    return payload


def parse_controlled_plan(raw: str) -> ControlledQueryPlan:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ControlledPlanError("LLM output is not a valid controlled query plan") from exc
    if not isinstance(payload, dict):
        raise ControlledPlanError("controlled query plan must be a JSON object")
    if any(str(key).lower() in {"sql", "query", "expression"} for key in payload):
        raise ControlledPlanError("raw SQL fields are forbidden in controlled query plans")
    try:
        return ControlledQueryPlan.model_validate(_normalize_plan_payload(payload))
    except Exception as exc:  # noqa: BLE001
        raise ControlledPlanError(str(exc)) from exc


def compile_controlled_plan(
    plan: ControlledQueryPlan,
    schema_catalog: dict[str, set[str]],
    *,
    relationships: dict[str, tuple[str, str, str, str]] | None = None,
) -> str:
    table = _resolve_identifier(plan.entity, schema_catalog.keys(), "entity")
    columns = schema_catalog[table]

    select_parts = [_resolve_identifier(field, columns, "field") for field in plan.fields]
    for aggregate in plan.aggregates:
        if aggregate.function == "count" and aggregate.field is None:
            expression = "COUNT(*)"
        else:
            if aggregate.field is None:
                raise ControlledPlanError(f"{aggregate.function} requires a field")
            column = _resolve_identifier(aggregate.field, columns, "aggregate field")
            function = "COUNT" if aggregate.function == "count_distinct" else aggregate.function.upper()
            expression = (
                f"COUNT(DISTINCT {column})"
                if aggregate.function == "count_distinct"
                else f"{function}({column})"
            )
        if aggregate.alias:
            if not _IDENTIFIER.fullmatch(aggregate.alias):
                raise ControlledPlanError("aggregate alias must be an identifier")
            expression += f" AS {aggregate.alias}"
        select_parts.append(expression)

    from_sql = table
    known_columns = set(columns)
    for join in plan.joins:
        relation = (relationships or {}).get(join.relationship_id)
        if relation is None:
            raise ControlledPlanError(f"undeclared relationship: {join.relationship_id}")
        left_table, left_column, right_table, right_column = relation
        if left_table != table:
            raise ControlledPlanError(f"relationship {join.relationship_id} is outside the root entity")
        _resolve_identifier(right_table, schema_catalog.keys(), "join table")
        _resolve_identifier(left_column, schema_catalog[left_table], "join field")
        _resolve_identifier(right_column, schema_catalog[right_table], "join field")
        from_sql += f" JOIN {right_table} ON {left_table}.{left_column} = {right_table}.{right_column}"
        known_columns.update(schema_catalog[right_table])

    where_parts: list[str] = []
    for index, item in enumerate(plan.filters):
        column = _resolve_identifier(item.field, known_columns, "filter field")
        op = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "in": "IN"}[item.operator]
        if item.operator == "in":
            if not isinstance(item.value, list) or not item.value:
                raise ControlledPlanError("in filter requires a non-empty list")
            value_sql = "(" + ", ".join(_literal(value) for value in item.value) + ")"
        else:
            if isinstance(item.value, list):
                raise ControlledPlanError(f"{item.operator} filter requires a scalar")
            relative_date = (
                _relative_date_sql(item.value) if isinstance(item.value, str) else None
            )
            value_sql = relative_date if relative_date is not None else _literal(item.value)
        where_parts.append(f"{column} {op} {value_sql}")

    group_by = [_resolve_identifier(field, known_columns, "group field") for field in plan.group_by]
    order_by = [
        f"{_resolve_identifier(item.field, known_columns | {a.alias for a in plan.aggregates if a.alias}, 'order field')} {item.direction.upper()}"
        for item in plan.order_by
    ]
    sql = f"SELECT {', '.join(select_parts)} FROM {from_sql}"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    if group_by:
        sql += " GROUP BY " + ", ".join(group_by)
    if order_by:
        sql += " ORDER BY " + ", ".join(order_by)
    return f"{sql} FETCH FIRST {plan.limit} ROWS ONLY"


def _resolve_identifier(value: str, allowed: Any, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ControlledPlanError(f"{label} must be a catalog identifier")
    by_upper = {str(item).upper(): str(item) for item in allowed}
    resolved = by_upper.get(value.upper())
    if resolved is None:
        raise ControlledPlanError(f"unknown {label}: {value}")
    return resolved


# Plans may only carry literal filter values, but models keep expressing
# relative time windows as pseudo-SQL strings ("CURRENT_DATE - INTERVAL 30
# DAY"), which would otherwise be quoted into a nonsense literal. Recognise a
# tightly whitelisted shape and re-render it from validated parts — the output
# is built exclusively from the fixed base keyword, a checked integer, and a
# normalised unit, never from the raw input.
_RELATIVE_DATE = re.compile(
    r"(?i)^(CURRENT_DATE|CURRENT_TIMESTAMP|SYSDATE|NOW|TODAY)"
    r"(?:\s*([+-])\s*(?:INTERVAL\s+)?(\d{1,4})\s*(DAYS?|MONTHS?|YEARS?)?)?$"
)


def _relative_date_sql(value: str) -> str | None:
    candidate = re.sub(r"\s+", " ", re.sub(r"['\"()]", " ", value)).strip()
    match = _RELATIVE_DATE.fullmatch(candidate)
    if match is None:
        return None
    base_raw, sign, amount, unit = match.groups()
    base = (
        "CURRENT_TIMESTAMP"
        if base_raw.upper() in {"CURRENT_TIMESTAMP", "NOW"}
        else "CURRENT_DATE"
    )
    if sign is None:
        return base
    unit_normalized = (unit or "DAY").upper().rstrip("S")
    return f"{base} {sign} INTERVAL '{int(amount)}' {unit_normalized}"


def _literal(value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + value.replace("'", "''") + "'"
