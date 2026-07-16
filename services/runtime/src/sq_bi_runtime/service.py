from __future__ import annotations

from dataclasses import dataclass
import re
from time import monotonic
from typing import Any, Callable, Protocol

from .db import OracleExecutor
from .guardrails import validate_sql
from .llm_client import OpenAICompatClient, parse_json_payload
from .prompts import ASKDATA_SYSTEM_PROMPT
from .schema_catalog import SchemaCatalog, schema_catalog_to_prompt
from .controlled_query import compile_controlled_plan, parse_controlled_plan


CONTROLLED_QUERY_PLAN_SYSTEM_PROMPT = """You are the SQ-BI controlled query planner.
Return exactly one JSON object and never return SQL. Allowed keys are:
entity, fields, aggregates, filters, group_by, order_by, joins, limit.
Use only identifiers present in the supplied schema catalog. Aggregates use
function=count|count_distinct|sum|avg|min|max and an optional field/alias.
Filters use operator=eq|ne|gt|gte|lt|lte|in. Joins reference only declared
relationship_id values. The limit must be between 1 and 200."""


class LLMProtocol(Protocol):
    def chat(self, system_prompt: str, user_prompt: str) -> str: ...

class DBProtocol(Protocol):
    def execute(self, sql: str, params: dict | None = None) -> list[dict]: ...
    def get_schema_catalog(self) -> dict[str, list[str]]: ...

def _normalized_field_token(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def _display_column_maps(display_columns: list[Any] | None) -> tuple[dict[str, str], dict[str, str]]:
    label_to_key: dict[str, str] = {}
    key_to_label: dict[str, str] = {}
    for item in display_columns or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        if not key:
            continue
        key_to_label[key.upper()] = label or key
        label_to_key[_normalized_field_token(key)] = key
        if label:
            label_to_key[_normalized_field_token(label)] = key
    return label_to_key, key_to_label


def _resolve_chart_field(value: Any, columns: list[str], display_columns: list[Any] | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    column_by_upper = {column.upper(): column for column in columns}
    raw = value.strip()
    if raw.upper() in column_by_upper:
        return column_by_upper[raw.upper()]
    label_to_key, _ = _display_column_maps(display_columns)
    resolved = label_to_key.get(_normalized_field_token(raw))
    if resolved and resolved.upper() in column_by_upper:
        return column_by_upper[resolved.upper()]
    return None


def _display_label_for_key(value: str | None, display_columns: list[Any] | None) -> str:
    if not value:
        return ""
    _, key_to_label = _display_column_maps(display_columns)
    return key_to_label.get(value.upper()) or value


def _build_chart_suggestion(
    columns: list[str],
    rows: list[Any],
    metrics: list[Any],
    dimensions: list[Any],
    explanation: str,
    raw_chart: dict[str, Any] | None = None,
    display_columns: list[Any] | None = None,
) -> dict[str, Any]:
    if raw_chart:
        chart = dict(raw_chart)
        chart.setdefault("chart_type", "table")
        chart.setdefault("title", str(metrics[0]) if metrics else "查询结果")
        chart.setdefault("description", explanation)
        for field in ("x_field", "y_field", "value_field"):
            resolved = _resolve_chart_field(chart.get(field), columns, display_columns)
            if resolved:
                chart[field] = resolved
            elif field in chart:
                chart.pop(field, None)
        chart_type = str(chart.get("chart_type") or "table").lower()
        if chart_type in {"bar", "line", "area"} and (not chart.get("x_field") or not chart.get("y_field")):
            fallback = _build_chart_suggestion(
                columns,
                rows,
                metrics,
                dimensions,
                explanation,
                raw_chart=None,
                display_columns=display_columns,
            )
            fallback["title"] = chart.get("title") or fallback.get("title")
            fallback["description"] = chart.get("description") or fallback.get("description")
            return fallback
        if chart.get("y_field") and not chart.get("series_field"):
            chart["series_field"] = _display_label_for_key(str(chart.get("y_field")), display_columns)
        return chart

    if not columns:
        return {
            "chart_type": "none",
            "title": "无结果",
            "description": explanation,
        }

    numeric_columns: list[str] = []
    for idx, column in enumerate(columns):
        if rows and isinstance(rows[0][idx], (int, float)):
            numeric_columns.append(column)

    if len(rows) == 1 and numeric_columns:
        value_field = numeric_columns[0]
        return {
            "chart_type": "kpi",
            "title": str(metrics[0]) if metrics else value_field,
            "value_field": value_field,
            "description": explanation,
        }

    if len(columns) >= 2 and numeric_columns:
        y_field = numeric_columns[0]
        x_candidates = [col for col in columns if col != y_field]
        x_field = x_candidates[0] if x_candidates else columns[0]
        title = f"{dimensions[0]} vs {metrics[0]}" if dimensions and metrics else "查询结果图表"
        series_label = str(metrics[0]) if metrics else _display_label_for_key(y_field, display_columns)
        return {
            "chart_type": "bar",
            "title": title,
            "x_field": x_field,
            "y_field": y_field,
            "series_field": series_label,
            "description": explanation,
        }

    return {
        "chart_type": "table",
        "title": "明细结果",
        "description": explanation,
    }


def _normalize_display_columns(columns: list[str], raw_display_columns: Any) -> list[Any]:
    if not columns:
        return []
    if not isinstance(raw_display_columns, list) or not raw_display_columns:
        return columns

    normalized: list[Any] = []
    keyed_labels: dict[str, str] = {}
    ordered_labels: list[str] = []
    for item in raw_display_columns:
        if isinstance(item, dict):
            key = str(item.get("key") or item.get("field") or item.get("name") or "")
            label = str(item.get("label") or item.get("title") or "")
            if key and label:
                keyed_labels[key.upper()] = label
            if label:
                ordered_labels.append(label)
        elif isinstance(item, str):
            ordered_labels.append(item)

    for idx, column in enumerate(columns):
        label = keyed_labels.get(column.upper())
        if not label and idx < len(ordered_labels):
            label = ordered_labels[idx]
        normalized.append({"key": column, "label": label} if label else column)
    return normalized


@dataclass
class AskDataService:
    skill_context: str
    llm_client: LLMProtocol
    db_executor: DBProtocol | None = None
    allowed_schemas: tuple[str, ...] = ()
    schema_catalog: SchemaCatalog | None = None
    asset_context_provider: Callable[[], str] | None = None
    max_repair_attempts: int = 2
    sql_dialect: str = "oracle"

    def _attach_data(self, result: dict[str, Any], execute_sql: bool) -> dict[str, Any]:
        if execute_sql and self.db_executor is not None:
            raw_result = self.db_executor.execute(result["sql"])
            if isinstance(raw_result, dict):
                raw_columns = [str(column) for column in raw_result.get("columns", [])]
                raw_values = list(raw_result.get("rows", []))
                rows = [
                    [row.get(column) for column in raw_columns]
                    if isinstance(row, dict)
                    else list(row)
                    for row in raw_values
                ]
            elif raw_result:
                raw_columns = [str(k) for k in raw_result[0]]
                rows = [[row.get(k) for k in raw_columns] for row in raw_result]
            else:
                raw_columns = []
                rows = []
            result["rows"] = rows
            result["columns"] = _normalize_display_columns(raw_columns, result.get("display_columns"))
            result["physical_columns"] = raw_columns
        else:
            result["rows"] = []
            result["columns"] = []
            result["physical_columns"] = []

        result["chart_suggestion"] = _build_chart_suggestion(
            result["physical_columns"],
            result["rows"],
            result.get("metrics", []),
            result.get("dimensions", []),
            result.get("explanation", "") or "",
            result.get("chart_suggestion") if isinstance(result.get("chart_suggestion"), dict) else None,
            result["columns"],
        )
        return result

    def _build_prompt(self, question: str, extra_context: str = "", repair_context: str = "") -> str:
        schema_context = schema_catalog_to_prompt(self.schema_catalog or {})
        asset_context = self.asset_context_provider() if self.asset_context_provider else ""
        return (
            "Below are classified Skills and assets used by ask-data execution:\n"
            "1. Database Schema Skills: physical tables, physical fields, joins, comments, and live catalog validation.\n"
            "2. TMS Business Skills: business flow, metric intent, status codes, and domain analysis rules.\n"
            "3. Metric Definition Skills: saved metric contracts with complete SELECT SQL.\n"
            "4. Skill Center Analysis Skills: saved analysis methods, parameters, steps, and output schema.\n"
            "5. Report Factory Skills: saved report analysis chains, templates, sections, and renderer contracts.\n"
            "6. Natural Language Compiler Skills: system skills that generate metric, analysis, and report assets.\n\n"
            f"{self.skill_context}\n\n"
            f"{asset_context}\n\n"
            f"{schema_context}\n\n"
            f"{extra_context}\n\n"
            f"{repair_context}\n\n"
            f"User question: {question}"
        )

    def _build_repair_context(self, failed_sql: str, error: Exception) -> str:
        try:
            tables = validate_sql(
                failed_sql,
                allowed_schemas=self.allowed_schemas,
                dialect=self.sql_dialect,
            ).tables
        except Exception:
            tables = []
        schema_context = schema_catalog_to_prompt(self.schema_catalog or {}, tables=tables)
        return (
            "# Previous SQL Failed Validation Or Execution\n\n"
            f"Failed SQL:\n{failed_sql}\n\n"
            f"Error:\n{error}\n\n"
            f"{schema_context}\n\n"
            "Regenerate the JSON response. Do not repeat the failed SQL. "
            "Use only columns listed above or in the database schema Skill. "
            "If the user requested a business concept that has no physical field, map it to an existing business field and explain the mapping."
        )

    def ask(self, question: str, execute_sql: bool = True, extra_context: str = "") -> dict[str, Any]:
        repair_context = ""
        last_error: Exception | None = None
        for attempt in range(self.max_repair_attempts + 1):
            user_prompt = self._build_prompt(question, extra_context, repair_context)
            raw = self.llm_client.chat(ASKDATA_SYSTEM_PROMPT, user_prompt)
            payload = parse_json_payload(raw)
            sql = str(payload.get("sql", "")).strip()
            if not sql:
                last_error = ValueError("LLM response did not include SQL.")
            else:
                try:
                    validation = validate_sql(
                        sql,
                        allowed_schemas=self.allowed_schemas,
                        schema_catalog=self.schema_catalog,
                        dialect=self.sql_dialect,
                    )
                    result = {
                        "intent": payload.get("intent"),
                        "metrics": payload.get("metrics", []),
                        "dimensions": payload.get("dimensions", []),
                        "time_range": payload.get("time_range"),
                        "sql": validation.sql,
                        "display_columns": payload.get("display_columns") or payload.get("columns"),
                        "chart_suggestion": payload.get("chart_suggestion"),
                        "explanation": payload.get("explanation"),
                        "tables": validation.tables,
                    }
                    return self._attach_data(result, execute_sql)
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    sql = sql or "<empty>"
            if attempt >= self.max_repair_attempts:
                break
            repair_context = self._build_repair_context(sql, last_error)
        if last_error:
            raise last_error
        raise ValueError("Ask-data execution failed.")

    def ask_controlled(
        self,
        question: str,
        execute_sql: bool = True,
        extra_context: str = "",
        relationships: dict[str, tuple[str, str, str, str]] | None = None,
    ) -> dict[str, Any]:
        """Plan exploration through a closed DTO; raw LLM SQL is never executed."""
        schema_context = schema_catalog_to_prompt(self.schema_catalog or {})
        planning_started = monotonic()
        raw = self.llm_client.chat(
            CONTROLLED_QUERY_PLAN_SYSTEM_PROMPT,
            f"{schema_context}\n\n{extra_context}\n\nUser question: {question}",
        )
        plan = parse_controlled_plan(raw)
        planning_ms = max(0, int((monotonic() - planning_started) * 1000))
        compile_started = monotonic()
        sql = compile_controlled_plan(plan, self.schema_catalog or {}, relationships=relationships)
        compile_ms = max(0, int((monotonic() - compile_started) * 1000))
        guard_started = monotonic()
        validation = validate_sql(
            sql,
            allowed_schemas=self.allowed_schemas,
            schema_catalog=self.schema_catalog,
            dialect=self.sql_dialect,
        )
        guard_ms = max(0, int((monotonic() - guard_started) * 1000))
        result = {
            "intent": "controlled_exploration",
            "metrics": [item.alias or item.function for item in plan.aggregates],
            "dimensions": list(plan.fields),
            "sql": validation.sql,
            "explanation": "已通过受控查询计划编译并执行。",
            "tables": validation.tables,
            "controlled_plan": plan.model_dump(mode="json"),
            "execution_timings": [
                {"stage": "plan_validation", "duration_ms": planning_ms},
                {"stage": "compilation", "duration_ms": compile_ms},
                {"stage": "guardrail", "duration_ms": guard_ms},
            ],
        }
        execution_started = monotonic()
        attached = self._attach_data(result, execute_sql)
        if execute_sql and self.db_executor is not None:
            attached["execution_timings"].append(
                {
                    "stage": "execution",
                    "duration_ms": max(
                        0,
                        int((monotonic() - execution_started) * 1000),
                    ),
                }
            )
        return attached


def build_service(
    skill_context: str,
    llm_client: OpenAICompatClient,
    db_executor: OracleExecutor | None,
    allowed_schemas: tuple[str, ...] = (),
    schema_catalog: SchemaCatalog | None = None,
    asset_context_provider: Callable[[], str] | None = None,
) -> AskDataService:
    return AskDataService(
        skill_context=skill_context,
        llm_client=llm_client,
        db_executor=db_executor,
        allowed_schemas=allowed_schemas,
        schema_catalog=schema_catalog,
        asset_context_provider=asset_context_provider,
    )
