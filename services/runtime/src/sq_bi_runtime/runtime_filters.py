from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlglot import exp, parse_one

from sq_bi_contracts.execution import PlanFilter
from sq_bi_contracts.metrics import MetricDefinition


_PARAMETER_BINDING_PROMPT = """You are the SQ-BI runtime parameter binder.
Extract filters and dimensions from the current user request and recent conversation.
Return JSON only, never SQL:
{
  "views": [{
    "title": "short user-facing title",
    "filters": [{"field":"TABLE.COLUMN or COLUMN","operator":"eq|ne|gt|gte|lt|lte|in","value":"scalar or array"}],
    "dimensions": ["TABLE.COLUMN or COLUMN"],
    "ranking": {"direction":"asc|desc","limit":1},
    "dimension_order": "asc|desc|null",
    "presentation": "TABLE|BAR|LINE|AREA"
  }],
  "filters": [{"field":"TABLE.COLUMN or COLUMN","operator":"eq|ne|gt|gte|lt|lte|in","value":"scalar or array"}],
  "dimensions": ["TABLE.COLUMN or COLUMN"],
  "ranking": {"direction":"asc|desc","limit":1},
  "assumptions": ["short user-visible assumption"],
  "unresolved": ["only a genuinely ambiguous parameter that blocks a correct query"],
  "requires_clarification": false
}

Rules:
- Use only fields listed in Allowed fields.
- Produce one view for a simple request. When the user explicitly asks for multiple distinct views
  (for example a category comparison and a time trend), produce one view per requested analysis,
  at most three. Each view must remain the same metric and contain its own dimensions and filters.
- Extract every relevant constraint: time range, factory, region, project, carrier, status and other business dimensions.
- Put requested breakdown/grouping fields in dimensions. For highest, lowest, top-N or bottom-N,
  emit ranking with the appropriate direction and limit; otherwise use null.
- ranking always orders the metric value. Never use ranking to order a time trend. For a time trend,
  use dimension_order "asc", keep ranking null, and return the complete requested time window.
- Convert relative dates using Current time. Represent a date interval as gte start and lt end.
- Reuse explicit constraints from recent conversation unless the current message replaces them.
- Do not invent values. Optional dimensions may remain absent and do not require clarification.
- Treat shorthand such as "最近", "近期", or "最新" as a non-blocking request. Infer the most useful
  completed business period from the metric meaning and declared time field; when no stronger grain
  is evident, use the latest completed day and state that choice in assumptions.
- Ask for clarification only when two or more plausible bindings would materially change the result.
"""


@dataclass
class RuntimeBindings:
    filters: list[PlanFilter] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    metric_order: str | None = None
    result_limit: int | None = None
    assumptions: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    requires_clarification: bool = False
    views: list["RuntimeAnalysisView"] = field(default_factory=list)


@dataclass
class RuntimeAnalysisView:
    title: str = "分析结果"
    filters: list[PlanFilter] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    metric_order: str | None = None
    dimension_order: str | None = None
    result_limit: int | None = None
    presentation: str = "TABLE"


def bind_runtime_parameters(
    llm_client: Any,
    *,
    question: str,
    metric: MetricDefinition,
    sql: str,
    schema_catalog: dict[str, set[str]] | None,
    conversation: list[dict[str, str]] | None = None,
    dialect: str = "oracle",
) -> RuntimeBindings:
    allowed = _allowed_fields(sql, schema_catalog or {}, dialect)
    if not allowed:
        return RuntimeBindings()
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    recent = (conversation or [])[-12:]
    prompt = (
        f"Current time: {now.isoformat()}\n"
        f"Metric: {metric.name} ({metric.metric_code})\n"
        f"Metric definition: {metric.definition}\n"
        f"Declared time field: {metric.formula.time_field or 'none'}\n"
        f"Allowed fields: {', '.join(sorted(allowed))}\n"
        f"Recent conversation: {json.dumps(recent, ensure_ascii=False)}\n"
        f"Current request: {question}"
    )
    raw = llm_client.chat(_PARAMETER_BINDING_PROMPT, prompt)
    payload = _json_object(raw)
    def parse_filters(items: Any) -> list[PlanFilter]:
        values: list[PlanFilter] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            field_name = _resolve_allowed_field(str(item.get("field") or ""), allowed)
            if field_name is None:
                continue
            try:
                values.append(PlanFilter(
                    field=field_name,
                    operator=str(item.get("operator") or "eq"),
                    value=item.get("value"),
                ))
            except Exception:
                continue
        return values

    def parse_dimensions(items: Any) -> list[str]:
        values: list[str] = []
        for value in items or []:
            field_name = _resolve_allowed_field(str(value or ""), allowed)
            if field_name is not None and field_name not in values:
                values.append(field_name)
        return values

    def parse_ranking(value: Any) -> tuple[str | None, int | None]:
        ranking = value if isinstance(value, dict) else {}
        direction = str(ranking.get("direction") or "").lower()
        if direction not in {"asc", "desc"}:
            return None, None
        try:
            limit = min(200, max(1, int(ranking.get("limit"))))
        except (TypeError, ValueError):
            limit = 1
        return direction, limit

    filters = parse_filters(payload.get("filters"))
    dimensions = parse_dimensions(payload.get("dimensions"))
    metric_order, result_limit = parse_ranking(payload.get("ranking"))
    views: list[RuntimeAnalysisView] = []
    for index, item in enumerate(payload.get("views") or []):
        if not isinstance(item, dict):
            continue
        if index >= 3:
            break
        view_order, view_limit = parse_ranking(item.get("ranking"))
        presentation = str(item.get("presentation") or "TABLE").upper()
        if presentation not in {"TABLE", "BAR", "LINE", "AREA"}:
            presentation = "TABLE"
        dimension_order = str(item.get("dimension_order") or "").lower()
        if dimension_order not in {"asc", "desc"}:
            dimension_order = None
        view_dimensions = parse_dimensions(item.get("dimensions"))
        declared_time_field = str(metric.formula.time_field or "").upper()
        is_time_trend = presentation in {"LINE", "AREA"} and any(
            value.rsplit(".", 1)[-1] == declared_time_field for value in view_dimensions
        )
        if is_time_trend:
            view_order = None
            view_limit = None
            dimension_order = dimension_order or "asc"
        views.append(RuntimeAnalysisView(
            title=str(item.get("title") or f"分析视图 {index + 1}")[:80],
            filters=parse_filters(item.get("filters")) or list(filters),
            dimensions=view_dimensions,
            metric_order=view_order,
            dimension_order=dimension_order,
            result_limit=view_limit,
            presentation=presentation,
        ))
    return RuntimeBindings(
        filters=filters,
        dimensions=dimensions,
        metric_order=metric_order,
        result_limit=result_limit,
        assumptions=[str(value) for value in payload.get("assumptions") or [] if str(value).strip()],
        unresolved=[str(value) for value in payload.get("unresolved") or [] if str(value).strip()],
        requires_clarification=bool(payload.get("requires_clarification")),
        views=views,
    )


def apply_runtime_filters(sql: str, filters: list[PlanFilter], *, dialect: str = "oracle") -> str:
    if not filters:
        return sql
    tree = parse_one(sql, read=dialect)
    select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    if select is None:
        return sql
    aliases = _table_aliases(select)
    condition: exp.Expression | None = None
    for item in filters:
        column = _column_expression(item.field, aliases)
        predicate = _predicate(column, item, dialect)
        condition = predicate if condition is None else exp.and_(condition, predicate)
    if condition is not None:
        select.where(condition, append=True, copy=False)
    return tree.sql(dialect=dialect)


def apply_runtime_group_by(sql: str, fields: list[str], *, dialect: str = "oracle") -> str:
    if not fields:
        return sql
    tree = parse_one(sql, read=dialect)
    select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    if select is None:
        return sql
    aliases = _table_aliases(select)
    dimensions = [_column_expression(field, aliases) for field in fields]
    # Place dimensions before metric values so the result is naturally readable.
    select.set("expressions", [*(item.copy() for item in dimensions), *select.expressions])
    select.group_by(*(item.copy() for item in dimensions), append=True, copy=False)
    return tree.sql(dialect=dialect)


def apply_runtime_ranking(
    sql: str,
    direction: str | None,
    limit: int | None,
    *,
    dialect: str = "oracle",
) -> str:
    if direction not in {"asc", "desc"}:
        return sql
    tree = parse_one(sql, read=dialect)
    select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    if select is None or not select.expressions:
        return sql
    metric_expression = select.expressions[-1]
    metric_alias = metric_expression.alias_or_name
    order_value = exp.column(metric_alias) if metric_alias else metric_expression.copy()
    select.order_by(exp.Ordered(this=order_value, desc=direction == "desc"), copy=False)
    if limit is not None:
        select.limit(limit, copy=False)
    return tree.sql(dialect=dialect)


def apply_runtime_dimension_order(
    sql: str,
    direction: str | None,
    *,
    dialect: str = "oracle",
) -> str:
    if direction not in {"asc", "desc"}:
        return sql
    tree = parse_one(sql, read=dialect)
    select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    if select is None or not select.expressions:
        return sql
    dimension = select.expressions[0]
    order_value = exp.column(dimension.alias_or_name) if dimension.alias_or_name else dimension.copy()
    select.order_by(exp.Ordered(this=order_value, desc=direction == "desc"), copy=False)
    return tree.sql(dialect=dialect)


def _allowed_fields(sql: str, schema_catalog: dict[str, set[str]], dialect: str) -> set[str]:
    try:
        tree = parse_one(sql, read=dialect)
    except Exception:
        return set()
    result: set[str] = set()
    for table in tree.find_all(exp.Table):
        table_name = table.name.upper()
        columns = schema_catalog.get(table_name) or schema_catalog.get(table.name) or set()
        for column in columns:
            result.add(f"{table_name}.{str(column).upper()}")
    return result


def _resolve_allowed_field(value: str, allowed: set[str]) -> str | None:
    normalized = value.strip().upper()
    if normalized in allowed:
        return normalized
    matches = [item for item in allowed if item.rsplit(".", 1)[-1] == normalized]
    return matches[0] if len(matches) == 1 else None


def _table_aliases(select: exp.Select) -> dict[str, str]:
    return {table.name.upper(): table.alias_or_name for table in select.find_all(exp.Table)}


def _column_expression(field_name: str, aliases: dict[str, str]) -> exp.Column:
    table_name, column_name = field_name.rsplit(".", 1)
    return exp.column(column_name, table=aliases.get(table_name.upper(), table_name))


def _literal(value: Any, dialect: str) -> exp.Expression:
    if isinstance(value, bool):
        return exp.Boolean(this=value)
    if isinstance(value, (int, float)):
        return exp.Literal.number(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
        if dialect == "clickhouse":
            return exp.Anonymous(this="toDate", expressions=[exp.Literal.string(str(value))])
        return exp.StrToDate(
            this=exp.Literal.string(str(value)),
            format=exp.Literal.string("%Y-%m-%d"),
        )
    return exp.Literal.string(str(value))


def _predicate(column: exp.Column, item: PlanFilter, dialect: str) -> exp.Expression:
    if item.operator == "in":
        values = item.value if isinstance(item.value, list) else [item.value]
        return exp.In(this=column, expressions=[_literal(value, dialect) for value in values])
    if isinstance(item.value, list):
        raise ValueError(f"{item.operator} requires a scalar value")
    right = _literal(item.value, dialect)
    operators = {
        "eq": exp.EQ,
        "ne": exp.NEQ,
        "gt": exp.GT,
        "gte": exp.GTE,
        "lt": exp.LT,
        "lte": exp.LTE,
    }
    return operators[item.operator](this=column, expression=right)


def _json_object(raw: str) -> dict[str, Any]:
    value = raw.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[-1].rsplit("```", 1)[0]
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("parameter binding must be a JSON object")
    if any("sql" in str(key).lower() for key in parsed):
        raise ValueError("parameter binding cannot contain SQL")
    return parsed
