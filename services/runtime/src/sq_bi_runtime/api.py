from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import logging
import os
import re
import tempfile
from io import BytesIO
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlglot import exp, parse_one
from sqlglot.errors import ParseError
import yaml
from sq_bi_semantic.api import get_repository, router as semantic_router
from sq_bi_semantic.product_repository import ReportRecord, SQLiteProductRepository
from pydantic import BaseModel, ConfigDict, Field
from sq_bi_contracts.common import ApiError, ApiResponse
from sq_bi_contracts.datasource import DataSourceConnectionConfig, DataSourceConnector
from sq_bi_contracts.domain_pack import PackStandardField
from sq_bi_contracts.enums import ChartType, DatabaseType, ErrorCode
from sq_bi_contracts.metrics import MetricDraft, MetricDraftRequest
from sq_bi_contracts.harness import HarnessRequest
from sq_bi_contracts.query import (
    ChartSuggestion,
    Lineage,
    LineageDataSource,
    LineageInfo,
    LineageMetric,
    LineageSkill,
    QueryResult,
)
from sq_bi_contracts.field_mount import (
    CandidateMapping,
    ConfirmationRequest,
    CreateDeploymentRequest,
    DeploymentInstance,
    DeploymentListItem,
    FieldMapping,
    LogicalMetricDefinition,
    LogicalMetricFormula,
    MappingEvidence,
    MountTriggerRequest,
    PackWithDeployments,
    ScopeCandidateTable,
    SmokeTestMetric,
    SmokeTestResult,
    ValidationStatus,
)
from sq_bi_contracts.skills import SkillDefinition
from sq_bi_contracts.semantic_space import (
    CreateSemanticSpaceRequest,
    FieldImpactReference,
    GapLookupRequest,
    PublishImpactSummary,
    PublishSemanticSpaceRequest,
)
from sq_bi_contracts.enterprise_pack import (
    CreateEnterprisePackRequest as _CreateEnterprisePackRequest,
    EffectiveDomainPack as _EffectiveDomainPack,
    EffectiveDomainPackAsset as _EffectiveDomainPackAsset,
    EffectivePackAssetRef as _EffectivePackAssetRef,
    EffectivePackView as _EffectivePackView,
    EnterprisePack as _EnterprisePack,
    EnterprisePackDraft as _EnterprisePackDraft,
    ExtensionLayerState as _ExtensionLayerState,
    PackExtensionLayer as _PackExtensionLayer,
    PackDraftRequest as _PackDraftRequest,
    PublishPackRequest as _PublishPackRequest,
)

from .config import AppConfig, DBConfig, LLMConfig, load_config, resolve_storage_path
from .domain_pack_authoring import DomainPackAuthoringService
from .field_mapping_store import FieldMappingStore
from .mounting_pipeline import MountingPipeline
from .pack_loader import PackRegistry, _registry as _GLOBAL_PACK_REGISTRY, get_registry, load_manifest
from .pack_dist import extract_pack, install_extracted_pack, validate_pack
from .scope_recommendation import recommend_scope_for_pack
from .connectors import OracleConnector
from .controlled_query import ControlledPlanError
from .guardrails import SQLValidationError, validate_sql
from .llm_client import OpenAICompatClient, parse_json_payload
from .prompts import (
    CONVERSATION_INTERPRET_SYSTEM_PROMPT,
    METRIC_DRAFT_SYSTEM_PROMPT,
    REPORT_HTML_ARTIFACT_SYSTEM_PROMPT,
    REPORT_DRAFT_SYSTEM_PROMPT,
    SKILL_DRAFT_SYSTEM_PROMPT,
)
from .schema_catalog import load_semantic_schema_catalog, merge_schema_catalogs
from .semantic_assets import load_semantic_asset_bundle
from .service import build_service
from .settings import (
    DBSettingsUpdate,
    apply_local_db_settings,
    apply_local_llm_settings,
    as_response_payload,
    db_settings_view,
    update_db_settings,
)
from .auth import is_admin, resolve_user_context
from .auth_routes import register_auth_routes
from .system_routes import register_system_routes

from .skill_loader import load_demo_business_bundle, load_skill_bundle

logger = logging.getLogger("sq_bi_runtime.api")


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    execute_sql: bool = True


class QueryAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1)
    user_id: str = "anonymous"
    execute: bool = True
    data_source_id: str | None = None
    data_source_ids: list[str] = Field(default_factory=list)


class SkillDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = "anonymous"
    name: str = ""
    description: str = ""
    prompt: str
    adjustment: str | None = None


class SkillExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = "anonymous"
    question: str
    skill: SkillDefinition
    execute: bool = True
    # Fallback execution scope when the skill definition carries no
    # data-source bindings (e.g. pack skills resolved through a deployment).
    data_source_id: str | None = None


class AssetDraftTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = "anonymous"
    asset_type: str
    name: str
    description: str
    logical_sql: str | None = None
    data_source_id: str | None = None
    conversation_context: str = ""
    default_time_range: str = "本月"
    execute: bool = True


class ReportDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = "anonymous"
    output_type: str
    title: str
    background: str = ""
    prompt: str = ""
    template: str = ""
    template_requirements: str = ""
    bound_metric_codes: list[str] = Field(default_factory=list)
    bound_skill_ids: list[str] = Field(default_factory=list)


class ReportArtifactGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = "anonymous"
    output_type: str
    title: str | None = None
    content: str = ""
    question: str = ""
    bound_metric_codes: list[str] = Field(default_factory=list)
    bound_skill_ids: list[str] = Field(default_factory=list)


class ConversationInterpretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = "anonymous"
    current_text: str = Field(..., min_length=1)
    pending_invocation: dict[str, Any] = Field(default_factory=dict)


def _request_id() -> str:
    return "req_" + uuid4().hex


def _response(data: Any) -> dict[str, Any]:
    return ApiResponse(request_id=_request_id(), data=data).model_dump(mode="json")


def _match_explicit_asset_candidates(
    explicit_name: str,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match @/#// references by the longest active asset-name prefix.

    A conversational rewrite may produce ``@指标名最好`` without a separator;
    the suffix is an analysis condition and must not become part of the asset name.
    """
    normalized = explicit_name.strip().lower()
    prefix_matches: list[tuple[int, dict[str, Any]]] = []
    for candidate in candidates:
        aliases = [
            str(candidate.get(key) or "").strip().lower()
            for key in ("name", "code")
        ]
        matched_lengths = [
            len(alias)
            for alias in aliases
            if alias and (normalized.startswith(alias) or alias.startswith(normalized))
        ]
        if matched_lengths:
            prefix_matches.append((max(matched_lengths), candidate))
    if not prefix_matches:
        return []
    longest = max(length for length, _candidate in prefix_matches)
    return [
        {**candidate, "score": 100}
        for length, candidate in prefix_matches
        if length == longest
    ]


def _remove_inferred_asset_triggers(
    latest_turn: str,
    standalone_question: str,
    previous_reference: str = "",
) -> str:
    """Allow a forced route only when typed now or carried from the same prior asset."""
    if re.search(r"(?<!\S)[@/#](?=\S)", latest_turn):
        return standalone_question
    inferred = re.search(r"(?<!\S)(?P<trigger>[@/#])(?P<name>[^\s，,。！？!?]+)", standalone_question)
    previous = re.search(r"(?<!\S)(?P<trigger>[@/#])(?P<name>[^\s，,。！？!?]+)", previous_reference)
    if inferred and previous:
        same_trigger = inferred.group("trigger") == previous.group("trigger")
        same_asset = inferred.group("name").strip().lower() == previous.group("name").strip().lower()
        if same_trigger and same_asset:
            return standalone_question
    return re.sub(r"(?<!\S)[@/#](?=\S)", "", standalone_question).strip()


def _resolve_skill_parameter_slots(
    skill: SkillDefinition,
    question: str,
    llm: Any | None = None,
) -> list[dict[str, Any]]:
    """Let the model bind declared slots; code only validates the execution contract."""
    contract_slots = {
        slot.name: slot
        for slot in (skill.execution_contract.parameter_slots if skill.execution_contract else [])
    }
    parameter_specs = []
    for parameter in skill.parameters:
        contract_slot = contract_slots.get(parameter.name)
        parameter_specs.append({
            "name": parameter.name,
            "data_type": parameter.data_type,
            "required": parameter.required,
            "description": parameter.description,
            "allowed_values": parameter.allowed_values or (contract_slot.allowed_values if contract_slot else []),
            "default_value": contract_slot.default_value if contract_slot else None,
        })
    model_values: dict[str, Any] = {}
    if llm is not None and parameter_specs:
        try:
            raw = llm.chat(
                """Bind the user's request to the declared Skill parameter slots. Return JSON only:
{"slots":[{"name":"declared name","value":null,"status":"resolved|ambiguous|unresolved","candidates":[]}]}
Use conversation meaning, not keyword rules. Never invent a value. Respect allowed_values.
Optional omitted slots are resolved with null. A declared default may be used and must be labeled resolved.
Do not output SQL or undeclared slot names.""",
                json.dumps({
                    "skill": {"name": skill.name, "description": skill.description},
                    "parameters": parameter_specs,
                    "question": question,
                }, ensure_ascii=False, default=str),
            )
            parsed = parse_json_payload(raw)
            model_values = {
                str(item.get("name")): item
                for item in parsed.get("slots") or []
                if isinstance(item, dict) and item.get("name")
            }
        except Exception:
            model_values = {}
    resolved: list[dict[str, Any]] = []
    for parameter, spec in zip(skill.parameters, parameter_specs, strict=True):
        contract_slot = contract_slots.get(parameter.name)
        allowed_values = list(spec["allowed_values"] or [])
        model_slot = model_values.get(parameter.name, {})
        value = model_slot.get("value")
        status = str(model_slot.get("status") or "unresolved")
        if allowed_values and value not in allowed_values:
            value = None
            status = "unresolved"
        default_value = spec["default_value"]
        if value is None and default_value is not None and status != "ambiguous":
            value = default_value
            status = "resolved"
        if value is None and not parameter.required and status != "ambiguous":
            status = "resolved"
        resolved.append(
            {
                "name": parameter.name,
                "data_type": parameter.data_type,
                "required": parameter.required,
                "description": parameter.description,
                "value": value,
                "default_value": default_value,
                "allowed_values": allowed_values,
                "candidates": list(model_slot.get("candidates") or []),
                "status": status,
                "resolution_source": "ai_context_binding" if model_slot else "declared_contract",
            }
        )
    return resolved


def _error_response(
    status_code: int,
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload = ApiResponse[None](
        request_id=_request_id(),
        error=ApiError(code=code, message=message, details=details or {}),
    ).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=payload)


def _chart_suggestion_from_ask(payload: dict[str, Any]) -> ChartSuggestion:
    raw = payload.get("chart_suggestion") if isinstance(payload.get("chart_suggestion"), dict) else {}
    chart_type = str(raw.get("chart_type") or "table").lower()
    allowed = {item.value for item in ChartType}
    if chart_type not in allowed:
        chart_type = "table"
    return ChartSuggestion(
        chart_type=ChartType(chart_type),
        title=str(raw.get("title") or payload.get("intent") or "查询结果"),
        x_field=raw.get("x_field"),
        y_field=raw.get("y_field"),
        series_field=raw.get("series_field") or raw.get("series_name"),
        value_field=raw.get("value_field"),
        description=raw.get("description") or payload.get("explanation"),
    )


def _query_columns_from_ask(payload: dict[str, Any]) -> list[Any]:
    columns: list[Any] = []
    for item in payload.get("columns", []):
        if isinstance(item, dict):
            key = str(item.get("key") or "")
            if key:
                columns.append({"key": key, "label": str(item.get("label")) if item.get("label") else None})
        else:
            columns.append(str(item))
    return columns


def _query_result_from_ask(
    payload: dict[str, Any],
    user_id: str,
    *,
    answer_path: Any = None,
    assumptions: list[Any] | None = None,
    confidence_tier: Any = None,
    clarification: Any = None,
    is_exploratory: bool = False,
    gap_candidates: list[Any] | None = None,
    execution_path: Any = None,
    execution_provenance: Any = None,
    execution_timings: list[Any] | None = None,
    execution_failure: Any = None,
) -> QueryResult:
    query_id = "qry_" + uuid4().hex
    audit_id = "aud_" + uuid4().hex
    sql = str(payload.get("sql") or "")
    metrics = [str(item) for item in payload.get("metrics", [])]
    tables = [str(item) for item in payload.get("tables", [])]
    executed_at = datetime.now(UTC)
    # Use the execution's actual data source when the payload carries it;
    # the legacy labels only remain as fallback for unscoped payloads.
    payload_data_source = str(payload.get("data_source_id") or "")
    return QueryResult(
        query_id=query_id,
        audit_id=audit_id,
        columns=_query_columns_from_ask(payload),
        rows=[list(row) for row in payload.get("rows", [])],
        chart_suggestion=_chart_suggestion_from_ask(payload),
        lineage=Lineage(
            lineage_id="lin_" + uuid4().hex,
            source_system="SQ_BI_LLM_SKILL_RUNTIME",
            data_source_id=payload_data_source or "tms_oracle",
            metric_codes=metrics,
            formula_summary=f"llm_skill_sql:{sha256(sql.encode('utf-8')).hexdigest()[:16]}",
            physical_tables=tables,
            physical_fields=[str(item) for item in payload.get("physical_columns", [])],
            executed_at=executed_at,
        ),
        lineage_info=LineageInfo(
            metrics=[
                LineageMetric(
                    metric_id=metric,
                    metric_name=metric,
                    visibility="unknown",
                    formula_expression=str(payload.get("explanation") or ""),
                    version="1.0.0",
                )
                for metric in metrics
            ],
            skills=[
                LineageSkill(skill_id=str(skill_id), skill_name=str(skill_id))
                for skill_id in payload.get("skill_ids", [])
            ],
            data_sources=[
                LineageDataSource(data_source_id=payload_data_source, name=payload_data_source)
                if payload_data_source
                else LineageDataSource(data_source_id="oracle_tms", name="TMS Oracle 固定连接")
            ],
            executed_at=executed_at,
            data_watermark=executed_at.strftime("%Y-%m-%d %H:%M:%S"),
        ),
        summary=str(payload.get("narrative") or payload.get("explanation") or "已通过大模型 Skill 编排完成查询。"),
        answer_path=answer_path,
        assumptions=assumptions or [],
        confidence_tier=confidence_tier,
        clarification=clarification,
        is_exploratory=is_exploratory,
        gap_candidates=gap_candidates or [],
        execution_path=execution_path,
        execution_provenance=execution_provenance,
        execution_timings=execution_timings or [],
        execution_failure=execution_failure,
    )


def _metric_catalog_context(skill_context: str, asset_context: str = "", live_db_context: str = "") -> str:
    live_section = f"\n\n{live_db_context}" if live_db_context else ""
    return f"# TMS Business Skill Context\n\n{skill_context}\n\n# Classified Skill Assets\n\n{asset_context}{live_section}"


def _find_report(repo: SQLiteProductRepository, report_id: str) -> ReportRecord:
    for report in repo.list_reports():
        if report.report_id == report_id:
            return report
    raise KeyError(f"Report '{report_id}' not found.")


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            items.append(text)
    return items


def _normalize_asset_ref(value: Any) -> str:
    return "".join(str(value or "").strip().lower().split())


def _append_unique(items: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in items:
        items.append(text)


def _metric_reference_map(repo: SQLiteProductRepository) -> dict[str, str]:
    refs: dict[str, str] = {}
    for metric in repo.list_metrics():
        values = [metric.metric_code, metric.name, *metric.synonyms]
        for value in values:
            normalized = _normalize_asset_ref(value)
            if normalized:
                refs[normalized] = metric.metric_code
    return refs


def _resolve_metric_code(value: Any, metric_refs: dict[str, str]) -> str | None:
    normalized = _normalize_asset_ref(value)
    if not normalized:
        return None
    return metric_refs.get(normalized)


def _resolve_report_runtime_assets(
    repo: SQLiteProductRepository,
    report: ReportRecord,
    request: ReportArtifactGenerateRequest,
) -> tuple[list[str], list[str]]:
    metric_refs = _metric_reference_map(repo)
    skill_ids = {skill.skill_id for skill in repo.list_skills()}
    bound_metric_codes: list[str] = []
    bound_skill_ids: list[str] = []

    for metric_code in request.bound_metric_codes:
        if repo.get_metric_by_code(metric_code):
            _append_unique(bound_metric_codes, metric_code)
    for skill_id in request.bound_skill_ids:
        if skill_id in skill_ids:
            _append_unique(bound_skill_ids, skill_id)

    for step in report.analysis_chain:
        if not isinstance(step, dict):
            continue
        skill_id = str(step.get("skill_id") or "").strip()
        if skill_id in skill_ids:
            _append_unique(bound_skill_ids, skill_id)
        for item in _string_items(step.get("inputs")) + _string_items(step.get("metrics")):
            metric_code = _resolve_metric_code(item, metric_refs)
            if metric_code:
                _append_unique(bound_metric_codes, metric_code)

    skill_by_id = {skill.skill_id: skill for skill in repo.list_skills()}
    for skill_id in list(bound_skill_ids):
        skill = skill_by_id.get(skill_id)
        if not skill:
            continue
        output_schema = skill.output_schema or {}
        for item in _string_items(output_schema.get("metrics")):
            metric_code = _resolve_metric_code(item, metric_refs)
            if metric_code:
                _append_unique(bound_metric_codes, metric_code)
        nested_schema = output_schema.get("schema")
        if isinstance(nested_schema, dict):
            for item in _string_items(nested_schema.get("metrics")):
                metric_code = _resolve_metric_code(item, metric_refs)
                if metric_code:
                    _append_unique(bound_metric_codes, metric_code)

    return bound_metric_codes, bound_skill_ids


def _json_safe_cell(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _rows_as_dicts(columns: list[str], rows: list[Any], max_rows: int = 12) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows[:max_rows]:
        values = list(row) if isinstance(row, (list, tuple)) else [row]
        normalized_rows.append(
            {
                column: _json_safe_cell(values[index]) if index < len(values) else None
                for index, column in enumerate(columns)
            }
        )
    return normalized_rows


@dataclass(frozen=True)
class ReportRuntimeAsset:
    asset_type: str
    asset_id: str
    name: str
    description: str
    sql: str
    data_source_id: str = ""


@dataclass(frozen=True)
class ReportTimeWindow:
    label: str
    start: date
    end: date


@dataclass(frozen=True)
class _ScalarMetricMergeCandidate:
    asset: ReportRuntimeAsset
    alias: str
    projection: exp.Expression
    source_key: str
    from_expression: exp.Expression
    joins: tuple[exp.Expression, ...]
    where_condition: exp.Expression | None


def _is_select_sql(sql: str) -> bool:
    return sql.strip().lower().startswith("select")


def _report_sql_max_workers() -> int:
    try:
        configured = int(os.getenv("SQ_BI_REPORT_SQL_MAX_WORKERS", "4"))
    except ValueError:
        configured = 4
    return max(1, min(configured, 8))


def _safe_sql_alias(value: str) -> str:
    normalized = re.sub(r"\W+", "_", value.strip().lower()).strip("_")
    if not normalized:
        normalized = "metric_value"
    if normalized[0].isdigit():
        normalized = f"m_{normalized}"
    return normalized[:64]


def _first_day_of_month(value: date) -> date:
    return value.replace(day=1)


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _report_time_window(request: ReportArtifactGenerateRequest) -> ReportTimeWindow | None:
    text = f"{request.question} {request.content}".strip()
    today = datetime.now().date()
    current_month = _first_day_of_month(today)
    if any(token in text for token in ("上月", "上个月", "上一月")):
        start = _add_months(current_month, -1)
        return ReportTimeWindow(label="上月", start=start, end=current_month)
    if any(token in text for token in ("本月", "这个月", "当月")):
        return ReportTimeWindow(label="本月", start=current_month, end=_add_months(current_month, 1))
    if any(token in text for token in ("近7天", "最近7天")):
        return ReportTimeWindow(label="近7天", start=today - timedelta(days=7), end=today + timedelta(days=1))
    if any(token in text for token in ("近30天", "最近30天")):
        return ReportTimeWindow(label="近30天", start=today - timedelta(days=30), end=today + timedelta(days=1))
    return None


def _normalize_time_fields(value: Any) -> tuple[dict[str, str], list[str]]:
    table_fields: dict[str, str] = {}
    global_fields: list[str] = []
    if isinstance(value, dict):
        for table, field in value.items():
            table_name = str(table or "").strip().upper()
            field_name = str(field or "").strip().upper()
            if table_name and field_name:
                table_fields[table_name] = field_name
    elif isinstance(value, list):
        for item in value:
            table_items, global_items = _normalize_time_fields(item)
            table_fields.update(table_items)
            global_fields.extend(global_items)
    elif isinstance(value, str):
        field = value.strip()
        if "." in field:
            table, column = field.rsplit(".", 1)
            table_name = table.strip().upper()
            field_name = column.strip().upper()
            if table_name and field_name:
                table_fields[table_name] = field_name
        elif field:
            global_fields.append(field.upper())
    return table_fields, list(dict.fromkeys(global_fields))


def _select_table_refs(select: exp.Select) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    from_expression = select.args.get("from_")
    if from_expression is not None and isinstance(from_expression.this, exp.Table):
        table = from_expression.this
        refs.append((table.name.upper(), table.alias_or_name))
    for join in select.args.get("joins") or []:
        if isinstance(join.this, exp.Table):
            table = join.this
            refs.append((table.name.upper(), table.alias_or_name))
    return refs


def _time_field_for_table(
    table_name: str,
    table_fields: dict[str, str],
    global_fields: list[str],
    schema_catalog: dict[str, set[str]] | None,
) -> str | None:
    field = table_fields.get(table_name)
    if field:
        return field
    available_columns = (schema_catalog or {}).get(table_name, set())
    for candidate in global_fields:
        if not available_columns or candidate in available_columns:
            return candidate
    return None


def _apply_time_window_to_sql(
    sql: str,
    *,
    time_fields: Any,
    window: ReportTimeWindow | None,
    schema_catalog: dict[str, set[str]] | None,
) -> str:
    if window is None or not _is_select_sql(sql):
        return sql
    table_fields, global_fields = _normalize_time_fields(time_fields)
    if not table_fields and not global_fields:
        return sql
    try:
        tree = parse_one(sql, read="oracle")
    except ParseError:
        return sql
    if not isinstance(tree, exp.Select):
        return sql

    for select in tree.find_all(exp.Select):
        for table_name, alias in _select_table_refs(select):
            if table_name == "DUAL":
                continue
            field = _time_field_for_table(table_name, table_fields, global_fields, schema_catalog)
            if not field:
                continue
            where = select.args.get("where")
            where_sql = where.sql(dialect="oracle").upper() if where is not None else ""
            if field in where_sql:
                break
            column = f"{alias}.{field}" if alias else f"{table_name}.{field}"
            condition = parse_one(
                f"{column} >= DATE '{window.start.isoformat()}' AND {column} < DATE '{window.end.isoformat()}'",
                read="oracle",
            )
            select.where(condition, append=True, copy=False)
            break

    return tree.sql(dialect="oracle")


def _source_key(tree: exp.Select) -> str:
    parts = [tree.args["from_"].sql(dialect="oracle")]
    parts.extend(join.sql(dialect="oracle") for join in tree.args.get("joins") or [])
    return " ".join(parts).upper()


def _has_aggregate(expression: exp.Expression) -> bool:
    aggregate_types = (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)
    return any(isinstance(node, aggregate_types) for node in expression.walk())


def _scalar_metric_merge_candidate(asset: ReportRuntimeAsset) -> _ScalarMetricMergeCandidate | None:
    if asset.asset_type != "metric" or not _is_select_sql(asset.sql):
        return None
    try:
        tree = parse_one(asset.sql, read="oracle")
    except ParseError:
        return None
    if not isinstance(tree, exp.Select):
        return None
    if len(tree.expressions) != 1:
        return None
    if not tree.args.get("from_"):
        return None
    if any(tree.args.get(key) is not None for key in ("group", "having", "qualify", "order", "limit", "offset", "fetch")):
        return None
    projection = tree.expressions[0].copy()
    if isinstance(projection, exp.Star) or not _has_aggregate(projection):
        return None
    # Metric SQLs conventionally alias their scalar as "value"; merged
    # projections must each carry a unique, asset-derived alias or every
    # metric in the group reads the same output cell.
    inner = projection.this if isinstance(projection, exp.Alias) else projection
    alias = _safe_sql_alias(asset.asset_id)
    projection = exp.alias_(inner.copy(), alias)
    where = tree.args.get("where")
    return _ScalarMetricMergeCandidate(
        asset=asset,
        alias=alias,
        projection=projection,
        source_key=_source_key(tree),
        from_expression=tree.args["from_"].this.copy(),
        joins=tuple(join.copy() for join in tree.args.get("joins") or []),
        where_condition=where.this.copy() if where is not None else None,
    )


def _case_when(condition: exp.Expression, value: exp.Expression) -> exp.Case:
    return exp.Case(ifs=[exp.If(this=condition.copy(), true=value.copy())])


def _conditioned_projection(projection: exp.Expression, condition: exp.Expression | None) -> exp.Expression:
    if condition is None:
        return projection.copy()

    def apply_condition(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Count):
            updated = node.copy()
            argument = updated.args.get("this")
            if isinstance(argument, exp.Distinct):
                updated.set(
                    "this",
                    exp.Distinct(
                        expressions=[
                            _case_when(condition, expression)
                            for expression in argument.expressions
                        ]
                    ),
                )
            elif argument is None or isinstance(argument, exp.Star):
                updated.set("this", _case_when(condition, exp.Literal.number(1)))
            else:
                updated.set("this", _case_when(condition, argument))
            return updated
        if isinstance(node, (exp.Sum, exp.Avg, exp.Min, exp.Max)):
            updated = node.copy()
            argument = updated.args.get("this")
            if argument is not None:
                updated.set("this", _case_when(condition, argument))
            return updated
        return node

    return projection.copy().transform(apply_condition)


def _execute_report_sql_dataset(
    *,
    service: Any,
    asset_type: str,
    asset_id: str,
    name: str,
    description: str,
    sql: str,
    time_fields: Any = None,
    time_window: ReportTimeWindow | None = None,
    max_rows: int = 50,
) -> dict[str, Any]:
    dataset: dict[str, Any] = {
        "asset_type": asset_type,
        "asset_id": asset_id,
        "name": name,
        "description": description,
        "sql": sql,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "status": "skipped",
    }
    if service.db_executor is None:
        dataset["error"] = "数据库未配置，无法执行数据查询。"
        return dataset
    if not _is_select_sql(sql):
        dataset["error"] = "资产未提供可执行 SELECT SQL。"
        return dataset
    try:
        execution_sql = _apply_time_window_to_sql(
            sql,
            time_fields=time_fields,
            window=time_window,
            schema_catalog=service.schema_catalog,
        )
        validation = validate_sql(
            execution_sql,
            allowed_schemas=service.allowed_schemas,
            schema_catalog=service.schema_catalog,
            dialect=getattr(service, "sql_dialect", "oracle"),
        )
        data = service.db_executor.execute(validation.sql, max_rows=max_rows)
        columns = [str(column) for column in data.get("columns", [])]
        rows = list(data.get("rows", []))
        dataset.update(
            {
                "sql": validation.sql,
                "columns": columns,
                "rows": _rows_as_dicts(columns, rows),
                "row_count": len(rows),
                "status": "ok",
                "time_window": (
                    {
                        "label": time_window.label,
                        "start": time_window.start.isoformat(),
                        "end": time_window.end.isoformat(),
                    }
                    if time_window
                    else None
                ),
            }
        )
    except Exception as exc:  # noqa: BLE001
        dataset.update({"status": "error", "error": str(exc)})
    return dataset


def _error_report_dataset(asset: ReportRuntimeAsset, message: str) -> dict[str, Any]:
    return {
        "asset_type": asset.asset_type,
        "asset_id": asset.asset_id,
        "name": asset.name,
        "description": asset.description,
        "sql": asset.sql,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "status": "error",
        "error": message,
    }


def _execute_scalar_metric_merge_group(service: Any, candidates: list[_ScalarMetricMergeCandidate]) -> list[dict[str, Any]]:
    if not candidates:
        return []
    assets = [candidate.asset for candidate in candidates]
    if service.db_executor is None:
        return [_error_report_dataset(asset, "数据库未配置，无法执行数据查询。") for asset in assets]

    first = candidates[0]
    projections = [
        _conditioned_projection(candidate.projection, candidate.where_condition)
        for candidate in candidates
    ]
    merged_tree = exp.select(*projections).from_(first.from_expression.copy())
    for join in first.joins:
        merged_tree.append("joins", join.copy())
    merged_sql = merged_tree.sql(dialect="oracle")
    try:
        validation = validate_sql(
            merged_sql,
            allowed_schemas=service.allowed_schemas,
            schema_catalog=service.schema_catalog,
            dialect=getattr(service, "sql_dialect", "oracle"),
        )
        data = service.db_executor.execute(validation.sql, max_rows=1)
        columns = [str(column) for column in data.get("columns", [])]
        rows = list(data.get("rows", []))
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        return [_error_report_dataset(asset, message) for asset in assets]

    values = list(rows[0]) if rows else []
    values_by_column = {
        column.upper(): _json_safe_cell(values[index]) if index < len(values) else None
        for index, column in enumerate(columns)
    }
    datasets: list[dict[str, Any]] = []
    for candidate in candidates:
        alias = candidate.alias
        value = values_by_column.get(alias.upper())
        datasets.append(
            {
                "asset_type": candidate.asset.asset_type,
                "asset_id": candidate.asset.asset_id,
                "name": candidate.asset.name,
                "description": candidate.asset.description,
                "sql": candidate.asset.sql,
                "execution_sql": validation.sql,
                "execution_strategy": "merged_scalar_metric",
                "merged_asset_ids": [item.asset.asset_id for item in candidates],
                "columns": [alias],
                "rows": [{alias: value}] if rows else [],
                "row_count": 1 if rows else 0,
                "status": "ok" if rows else "skipped",
            }
        )
    return datasets


def _execute_report_runtime_assets(
    service: Any,
    assets: list[ReportRuntimeAsset],
    service_resolver: Any | None = None,
) -> list[dict[str, Any]]:
    resolve_service = service_resolver or (lambda _data_source_id: service)
    candidates: list[_ScalarMetricMergeCandidate] = []
    remaining_assets: list[ReportRuntimeAsset] = []
    for asset in assets:
        candidate = _scalar_metric_merge_candidate(asset)
        if candidate is None:
            remaining_assets.append(asset)
        else:
            candidates.append(candidate)

    candidates_by_source: dict[tuple[str, str], list[_ScalarMetricMergeCandidate]] = {}
    for candidate in candidates:
        candidates_by_source.setdefault(
            (candidate.asset.data_source_id, candidate.source_key), []
        ).append(candidate)

    tasks: list[Any] = []
    for group in candidates_by_source.values():
        if len(group) >= 2:
            tasks.append(lambda group=group: _execute_scalar_metric_merge_group(
                resolve_service(group[0].asset.data_source_id), group
            ))
        else:
            remaining_assets.append(group[0].asset)
    for asset in remaining_assets:
        tasks.append(
            lambda asset=asset: [
                _execute_report_sql_dataset(
                    service=resolve_service(asset.data_source_id),
                    asset_type=asset.asset_type,
                    asset_id=asset.asset_id,
                    name=asset.name,
                    description=asset.description,
                    sql=asset.sql,
                )
            ]
        )

    if not tasks:
        return []

    results_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    max_workers = min(_report_sql_max_workers(), len(tasks))
    if max_workers == 1:
        for task in tasks:
            for dataset in task():
                results_by_key[(dataset["asset_type"], dataset["asset_id"])] = dataset
    else:
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="report-sql") as executor:
            futures = [executor.submit(task) for task in tasks]
            for future in as_completed(futures):
                for dataset in future.result():
                    results_by_key[(dataset["asset_type"], dataset["asset_id"])] = dataset

    return [
        results_by_key[(asset.asset_type, asset.asset_id)]
        for asset in assets
        if (asset.asset_type, asset.asset_id) in results_by_key
    ]


def _skill_sql(skill: SkillDefinition) -> str:
    output_schema = skill.output_schema or {}
    sql = output_schema.get("sql")
    if isinstance(sql, str) and sql.strip():
        return sql
    nested_schema = output_schema.get("schema")
    if isinstance(nested_schema, dict):
        nested_sql = nested_schema.get("sql")
        if isinstance(nested_sql, str) and nested_sql.strip():
            return nested_sql
    return ""


def _skill_time_fields(skill: SkillDefinition) -> Any:
    output_schema = skill.output_schema or {}
    time_fields = output_schema.get("time_fields")
    if time_fields:
        return time_fields
    nested_schema = output_schema.get("schema")
    if isinstance(nested_schema, dict):
        return nested_schema.get("time_fields")
    return None


def _build_report_runtime_data(
    *,
    repo: SQLiteProductRepository,
    report: ReportRecord,
    request: ReportArtifactGenerateRequest,
    service: Any,
    service_resolver: Any | None = None,
) -> dict[str, Any]:
    metric_codes, skill_ids = _resolve_report_runtime_assets(repo, report, request)
    skill_by_id = {skill.skill_id: skill for skill in repo.list_skills()}
    assets: list[ReportRuntimeAsset] = []
    context_assets: list[dict[str, Any]] = []
    time_window = _report_time_window(request)

    def schema_catalog_for(data_source_id: str) -> Any:
        if service_resolver is None or not data_source_id:
            return service.schema_catalog
        return service_resolver(data_source_id).schema_catalog

    for metric_code in metric_codes[:16]:
        metric = repo.get_metric_by_code(metric_code)
        if not metric:
            continue
        if not _is_select_sql(metric.formula.expression):
            context_assets.append(
                {
                    "asset_type": "metric",
                    "asset_id": metric.metric_code,
                    "name": metric.name,
                    "reason": "no_executable_select_sql",
                }
            )
            continue
        assets.append(
            ReportRuntimeAsset(
                asset_type="metric",
                asset_id=metric.metric_code,
                name=metric.name,
                description=metric.definition,
                data_source_id=metric.data_source_id,
                sql=_apply_time_window_to_sql(
                    metric.formula.expression,
                    time_fields=metric.formula.time_field,
                    window=time_window,
                    schema_catalog=schema_catalog_for(metric.data_source_id),
                ),
            )
        )

    for skill_id in skill_ids[:8]:
        skill = skill_by_id.get(skill_id)
        if not skill:
            continue
        sql = _skill_sql(skill)
        if not _is_select_sql(sql):
            context_assets.append(
                {
                    "asset_type": "skill",
                    "asset_id": skill.skill_id,
                    "name": skill.name,
                    "reason": "no_executable_select_sql",
                }
            )
            continue
        skill_data_source_id = next(
            (binding.data_source_id for binding in skill.data_source_bindings if binding.role == "primary"),
            skill.data_source_bindings[0].data_source_id if skill.data_source_bindings else "",
        )
        assets.append(
            # A raw SQL-producing skill executes against its declared primary
            # source. Multi-source skills are orchestrated at the skill layer.
            ReportRuntimeAsset(
                asset_type="skill",
                asset_id=skill.skill_id,
                name=skill.name,
                description=skill.description,
                data_source_id=skill_data_source_id,
                sql=_apply_time_window_to_sql(
                    sql,
                    time_fields=_skill_time_fields(skill),
                    window=time_window,
                    schema_catalog=schema_catalog_for(skill_data_source_id),
                ),
            )
        )

    runtime_results = _execute_report_runtime_assets(
        service,
        assets,
        service_resolver=service_resolver,
    )
    metric_results = [item for item in runtime_results if item.get("asset_type") == "metric"]
    skill_results = [item for item in runtime_results if item.get("asset_type") == "skill"]

    warnings = [
        f"{item['asset_type']}:{item['asset_id']} 执行未完成：{item.get('error') or item['status']}"
        for item in [*metric_results, *skill_results]
        if item.get("status") != "ok"
    ]
    return {
        "bound_metric_codes": metric_codes,
        "bound_skill_ids": skill_ids,
        "metric_results": metric_results,
        "skill_results": skill_results,
        "context_assets": context_assets,
        "warnings": warnings,
        "time_window": (
            {
                "label": time_window.label,
                "start": time_window.start.isoformat(),
                "end": time_window.end.isoformat(),
            }
            if time_window
            else None
        ),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _targeted_report_asset_context(
    repo: SQLiteProductRepository,
    metric_codes: list[str],
    skill_ids: list[str],
) -> str:
    lines = ["# Targeted Runtime Assets"]
    if metric_codes:
        lines.append("\n## Metric Definition Skills")
    for metric_code in metric_codes:
        metric = repo.get_metric_by_code(metric_code)
        if not metric:
            continue
        lines.extend(
            [
                f"- metric_code: {metric.metric_code}",
                f"  name: {metric.name}",
                f"  definition: {metric.definition}",
                f"  time_field: {metric.formula.time_field or '未声明'}",
            ]
        )
    skill_by_id = {skill.skill_id: skill for skill in repo.list_skills()}
    if skill_ids:
        lines.append("\n## Skill Center Analysis Skills")
    for skill_id in skill_ids:
        skill = skill_by_id.get(skill_id)
        if not skill:
            continue
        output_schema = skill.output_schema or {}
        nested_schema = output_schema.get("schema")
        analysis_method = str(
            output_schema.get("analysisMethod")
            or (nested_schema.get("analysisMethod") if isinstance(nested_schema, dict) else "")
            or ""
        )
        lines.extend(
            [
                f"- skill_id: {skill.skill_id}",
                f"  name: {skill.name}",
                f"  description: {skill.description}",
                f"  analysisMethod: {analysis_method}",
            ]
        )
    return "\n".join(lines)


def _compact_report_skill_context(report: ReportRecord) -> dict[str, Any]:
    return {
        "report_id": report.report_id,
        "name": report.name,
        "description": report.description,
        "outputTypes": report.outputTypes,
        "template": report.template,
        "templateMode": report.templateMode,
        "flow": report.flow,
        "sections": report.sections[:10],
        "analysis_chain": [
            {
                "name": step.get("name") or step.get("step"),
                "type": step.get("type"),
                "skill_id": step.get("skill_id"),
                "inputs": step.get("inputs"),
                "output": step.get("output") or step.get("description"),
            }
            for step in report.analysis_chain[:8]
            if isinstance(step, dict)
        ],
    }


def _trim_context(context: str, max_chars: int = 4000) -> str:
    return context[:max_chars]


def _clean_html_artifact_response(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:html)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text).strip()
    lower = text.lower()
    html_start = lower.find("<!doctype html")
    if html_start < 0:
        html_start = lower.find("<html")
    return text[html_start:].strip() if html_start >= 0 else text


def _html_artifact_failure_details(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {
            "stage": "artifact_render",
            "renderer": "llm",
            "output_type": "html",
            "reason": "empty_response",
        }
    try:
        payload = parse_json_payload(text)
    except Exception:
        preview = re.sub(r"\s+", " ", text)[:240]
        return {
            "stage": "artifact_render",
            "renderer": "llm",
            "output_type": "html",
            "reason": "non_html_response",
            "response_preview": preview,
        }
    html = str(payload.get("html") or "").strip()
    if html and not html.lower().startswith(("<!doctype html", "<html")):
        return {
            "stage": "artifact_render",
            "renderer": "llm",
            "output_type": "html",
            "reason": "invalid_html_field",
            "response_keys": sorted(map(str, payload.keys()))[:20],
        }
    return {
        "stage": "artifact_render",
        "renderer": "llm",
        "output_type": "html",
        "reason": "json_without_html",
        "response_keys": sorted(map(str, payload.keys()))[:20],
    }


def _report_runtime_failure_details(runtime_data: dict[str, Any]) -> dict[str, Any] | None:
    all_items = [
        *(runtime_data.get("metric_results") or []),
        *(runtime_data.get("skill_results") or []),
    ]
    failed_items = [
        item
        for item in all_items
        if item.get("status") != "ok"
    ]
    if failed_items:
        return {
            "stage": "data_query",
            "reason": "asset_execution_failed",
            "failed_assets": [
                {
                    "asset_type": item.get("asset_type"),
                    "asset_id": item.get("asset_id"),
                    "name": item.get("name"),
                    "status": item.get("status"),
                    "error": item.get("error"),
                    "execution_strategy": item.get("execution_strategy"),
                }
                for item in failed_items
            ],
            "asset_counts": {
                "total": len(all_items),
                "failed": len(failed_items),
                "successful": len(all_items) - len(failed_items),
            },
        }

    successful_items = [
        item
        for item in all_items
        if item.get("status") == "ok" and int(item.get("row_count") or 0) > 0
    ]
    if not successful_items:
        return {
            "stage": "data_query",
            "reason": "no_successful_dataset",
            "asset_counts": {
                "total": len(all_items),
                "failed": len(failed_items),
                "successful": 0,
            },
        }
    return None


def _successful_report_evidence(runtime_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "bound_metric_codes": runtime_data.get("bound_metric_codes") or [],
        "bound_skill_ids": runtime_data.get("bound_skill_ids") or [],
        "time_window": runtime_data.get("time_window"),
        "metric_results": [
            {
                key: item.get(key)
                for key in ("asset_id", "name", "columns", "rows", "row_count")
            }
            for item in runtime_data.get("metric_results") or []
            if item.get("status") == "ok" and int(item.get("row_count") or 0) > 0
        ],
        "skill_results": [
            {
                key: item.get(key)
                for key in ("asset_id", "name", "columns", "rows", "row_count")
            }
            for item in runtime_data.get("skill_results") or []
            if item.get("status") == "ok" and int(item.get("row_count") or 0) > 0
        ],
        "generated_at": runtime_data.get("generated_at"),
    }


def _default_config(base_path: Path) -> AppConfig:
    return AppConfig(
        llm=LLMConfig(base_url="http://localhost", api_key="disabled", model="disabled"),
        db=DBConfig(
            user=os.getenv("TMS_DB_USER") or os.getenv("TMS_DB_USERNAME"),
            password=os.getenv("TMS_DB_PASSWORD"),
            dsn=os.getenv("TMS_DB_DSN"),
        ),
        skill_dir=(base_path.parent / "skills" / "tms-system-askdata").resolve(),
        storage_path=os.getenv("SQ_BI_STORAGE_PATH") or ".local",
    )


def _path_revision(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return (str(path), 0, 0)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _repository_asset_revision(repository: Any) -> str:
    if hasattr(repository, "asset_revision"):
        try:
            return str(repository.asset_revision())
        except Exception:
            return "asset_revision_error"
    return str(id(repository))


class _ConnectorDBBridge:
    """Adapt DataSourceConnector.execute() → dict-based {columns, rows} for AskDataService."""

    def __init__(self, connector: DataSourceConnector) -> None:
        self._connector = connector

    def execute(self, sql: str, max_rows: int = 200) -> dict[str, Any]:
        rows_as_dicts = self._connector.execute(sql)
        if not rows_as_dicts:
            return {"columns": [], "rows": []}
        columns = list(rows_as_dicts[0].keys())
        rows = [list(d.values()) for d in rows_as_dicts]
        return {"columns": columns, "rows": rows}

    def get_schema_catalog(self) -> dict[str, set[str]]:
        catalog = self._connector.get_schema_catalog()
        return {table: set(cols) for table, cols in catalog.items()}

    def describe_schema(self) -> str:
        info = self._connector.describe_schema()
        return "\n".join(f"{row.get('table', '')} {row.get('column', '')}" for row in info)

    def close(self) -> None:
        if hasattr(self._connector, "close"):
            self._connector.close()


from sq_bi_contracts.exploration import SaveExplorationAsMetricRequest as _SaveExplorationAsMetricRequest


def _install_domain_packs(domain_packs_dir: Path, registry: PackRegistry) -> None:
    """Scan domain_packs_dir for pack.yaml manifests and register each with
    the module-level PackRegistry. A malformed pack is skipped, not fatal."""
    if not domain_packs_dir.is_dir():
        return
    manifests = sorted({*domain_packs_dir.rglob("pack.yaml"), *domain_packs_dir.rglob("manifest.yaml")})
    for manifest_path in manifests:
        pack_dir = manifest_path.parent
        try:
            registry.install(load_manifest(pack_dir), pack_dir)
        except (ValueError, OSError):
            continue


def create_app(config_path: str | Path | None = None) -> FastAPI:
    repo_root = Path(__file__).resolve().parents[4]
    default_path = Path("config.yaml")
    if config_path is None and not default_path.exists():
        llm_base_url = os.getenv("LLM_BASE_URL") or os.getenv("TMS_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("TMS_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        if llm_base_url and llm_api_key:
            config = load_config(default_path)
        else:
            config = _default_config(default_path)
    else:
        config = load_config(config_path or default_path)
    storage_root = resolve_storage_path(config.storage_path, repo_root)
    storage_root.mkdir(parents=True, exist_ok=True)
    config.storage_path = str(storage_root)
    settings_path = storage_root / "runtime_settings.json"
    config.llm = apply_local_llm_settings(config.llm, settings_path)
    config.db = apply_local_db_settings(config.db, settings_path)
    configured_registry = get_registry()
    pack_registry = PackRegistry() if configured_registry is _GLOBAL_PACK_REGISTRY else configured_registry
    _install_domain_packs(repo_root / "domain-packs", pack_registry)
    imported_packs_root = storage_root / "imported-packs"
    _install_domain_packs(imported_packs_root, pack_registry)
    llm_client = OpenAICompatClient(config.llm)
    db_executor: _ConnectorDBBridge | None = None
    if config.db.is_configured:
        conn_config = DataSourceConnectionConfig(
            data_source_id="local",
            name="Local Oracle",
            engine=DatabaseType.ORACLE,
            host="",
            port=1521,
            database="",
            username=config.db.user or "",
            password=config.db.password or "",
            dsn=config.db.dsn,
        )
        db_executor = _ConnectorDBBridge(OracleConnector(conn_config))
    semantic_catalog_path = Path(__file__).resolve().parents[3] / "semantic" / "data" / "tms_semantic.yaml"
    try:
        skill_context = load_skill_bundle(config.skill_dir) + load_demo_business_bundle(repo_root)
    except FileNotFoundError:
        skill_context = ""

    asset_context_lock = Lock()
    asset_context_cache: dict[str, Any] = {"signature": None, "value": ""}

    def asset_context_provider() -> str:
        repository = get_repository()
        signature = (_path_revision(semantic_catalog_path), _repository_asset_revision(repository))
        with asset_context_lock:
            if asset_context_cache["signature"] == signature:
                return str(asset_context_cache["value"])
        value = load_semantic_asset_bundle(semantic_catalog_path, repository=repository)
        with asset_context_lock:
            asset_context_cache["signature"] = signature
            asset_context_cache["value"] = value
        return value

    semantic_schema_catalog = load_semantic_schema_catalog(semantic_catalog_path)
    live_schema_catalog = {}
    if db_executor is not None:
        try:
            live_schema_catalog = db_executor.get_schema_catalog()
        except Exception:
            live_schema_catalog = {}
    schema_catalog = merge_schema_catalogs(semantic_schema_catalog, live_schema_catalog)
    service = build_service(
        skill_context,
        llm_client,
        db_executor,
        allowed_schemas=(config.db.user,) if config.db.user else (),
        schema_catalog=schema_catalog,
        asset_context_provider=asset_context_provider,
    )
    app = FastAPI(title=config.app_title)
    app.include_router(semantic_router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def close_runtime_resources() -> None:
        llm_client.close()
        if service.db_executor is not None and hasattr(service.db_executor, "close"):
            service.db_executor.close()
        try:
            _data_source_executors.close()
        except NameError:
            pass

    if hasattr(app, "add_event_handler"):
        app.add_event_handler("shutdown", close_runtime_resources)
    elif hasattr(app.router, "add_event_handler"):
        app.router.add_event_handler("shutdown", close_runtime_resources)
    elif hasattr(app, "on_event"):
        app.on_event("shutdown")(close_runtime_resources)

    register_system_routes(
        app,
        llm_client=llm_client,
        settings_path=settings_path,
        response=_response,
        error_response=_error_response,
    )

    @app.get("/api/v1/settings/db", response_model=None)
    def get_db_settings(http_request: Request) -> Any:
        auth = _require_admin(http_request)
        if isinstance(auth, JSONResponse):
            return auth
        return _response(as_response_payload(db_settings_view(config.db, settings_path)))

    @app.patch("/api/v1/settings/db", response_model=None)
    def patch_db_settings(request: DBSettingsUpdate, http_request: Request) -> Any:
        auth = _require_admin(http_request)
        if isinstance(auth, JSONResponse):
            return auth
        old_executor = service.db_executor
        config.db = update_db_settings(config.db, request, settings_path)
        conn_config = DataSourceConnectionConfig(
            data_source_id="local",
            name="Local Oracle",
            engine=DatabaseType.ORACLE,
            host="",
            port=1521,
            database="",
            username=config.db.user or "",
            password=config.db.password or "",
            dsn=config.db.dsn,
        )
        next_executor = _ConnectorDBBridge(OracleConnector(conn_config))
        service.db_executor = next_executor
        if old_executor is not None and hasattr(old_executor, "close"):
            try:
                old_executor.close()
            except Exception:
                pass
        service.allowed_schemas = (config.db.user,) if config.db.user else ()
        next_live_schema_catalog = {}
        if next_executor is not None:
            try:
                next_live_schema_catalog = next_executor.get_schema_catalog()
            except Exception:
                next_live_schema_catalog = {}
        service.schema_catalog = merge_schema_catalogs(semantic_schema_catalog, next_live_schema_catalog)
        return _response(as_response_payload(db_settings_view(config.db, settings_path)))

    register_auth_routes(
        app,
        storage_path=config.storage_path,
        response=_response,
        error_response=_error_response,
    )
    @app.post("/api/ask")
    def ask(request: AskRequest) -> dict:
        try:
            return service.ask_controlled(request.question, execute_sql=request.execute_sql)
        except ControlledPlanError as exc:
            return _error_response(
                400,
                ErrorCode.QUERY_REJECTED,
                str(exc),
                {"stage": "plan_validation", "failure_code": "invalid_plan"},
            )
        except SQLValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/v1/query/ask", response_model=None)
    def ask_query(request: QueryAskRequest) -> Any:
        from sq_bi_contracts.exploration import AnswerPath
        try:
            semantic_ctx = ""
            answer_path = None
            assumptions: list = []
            confidence_tier = None
            clarification = None
            is_exploratory = False
            gap_candidates: list = []

            requested_source_ids = list(dict.fromkeys(
                ([request.data_source_id] if request.data_source_id else [])
                + request.data_source_ids
            ))
            candidate_source_ids = requested_source_ids

            from .query_router import QueryRouter
            from .runtime_asset_providers import (
                ResolverBackedMetricCandidates as _ResolverBackedMetricCandidates,
            )
            from sq_bi_contracts.runtime_projection import (
                RuntimeRequestContext as _AskRuntimeRequestContext,
            )

            routed_assets: list[tuple[str, Any, Any]] = []
            for candidate_source_id in candidate_source_ids:
                candidate_context = _AskRuntimeRequestContext(
                    user_id=request.user_id,
                    data_source_id=candidate_source_id,
                    workspace_id=request.user_id,
                )
                candidate_route = QueryRouter(
                    _ResolverBackedMetricCandidates(_runtime_asset_resolver, candidate_context)
                ).route(request.question, data_source_id=candidate_source_id)
                if candidate_route.selected_asset is not None:
                    routed_assets.append((candidate_source_id, candidate_context, candidate_route))

            # One question may explicitly reference formal metrics from several
            # databases. Execute them independently, then merge only the
            # result evidence — never generate a cross-database SQL JOIN.
            unique_routes: dict[tuple[str, str], tuple[str, Any, Any]] = {}
            for source_id, context, route in routed_assets:
                asset_id = route.selected_asset.asset_ref.asset.asset_id
                unique_routes[(source_id, asset_id)] = (source_id, context, route)
            routed_assets = list(unique_routes.values())

            if len(routed_assets) > 1:
                from sq_bi_contracts.enums import ExecutionPath as _ExecutionPath
                from sq_bi_contracts.execution import ResolvedExecutionRequest as _ResolvedExecutionRequest
                from .deterministic_execution import DeterministicExecutionPipeline as _DeterministicExecutionPipeline

                records_by_id = {
                    str(item.get("data_source_id")): item for item in _load_datasources()
                }

                def execute_routed_asset(entry: tuple[str, Any, Any]) -> dict[str, Any]:
                    source_id, context, route = entry
                    record = records_by_id.get(source_id, {})
                    dialect = {
                        "postgresql": "postgres",
                        "postgres": "postgres",
                        "mysql": "mysql",
                        "clickhouse": "clickhouse",
                    }.get(str(record.get("database_type") or "oracle").lower(), "oracle")
                    if record:
                        try:
                            executor = _data_source_executors.get(source_id)
                            source_catalog = executor.get_schema_catalog()
                        except Exception as exc:  # noqa: BLE001
                            return {
                                "data_source_id": source_id,
                                "metric_code": route.matched_metric.metric_code if route.matched_metric else "",
                                "metric_name": route.matched_metric.name if route.matched_metric else "",
                                "columns": [],
                                "rows": [],
                                "sql": "",
                                "failure": f"数据源连接失败：{exc}",
                            }
                    else:
                        executor = service.db_executor
                        source_catalog = service.schema_catalog
                    execution = _DeterministicExecutionPipeline(
                        _mapping_store,
                        executor,
                        allowed_schemas=(str(record.get("username")),) if record.get("username") else (),
                        schema_catalog=source_catalog,
                        dialect=dialect,
                    ).execute(
                        _ResolvedExecutionRequest(
                            question=request.question,
                            context=context,
                            execution_path=_ExecutionPath.FORMAL_METRIC,
                            selected_asset=route.selected_asset,
                        ),
                        execute_sql=request.execute,
                    )
                    return {
                        "data_source_id": source_id,
                        "metric_code": route.matched_metric.metric_code if route.matched_metric else "",
                        "metric_name": route.matched_metric.name if route.matched_metric else "",
                        "columns": execution.columns,
                        "rows": execution.rows,
                        "sql": execution.sql or "",
                        "failure": execution.failure.message if execution.failure else "",
                    }

                max_workers = min(8, len(routed_assets))
                with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="cross-ds-query") as executor:
                    cross_source_results = list(executor.map(execute_routed_asset, routed_assets))
                successful = [item for item in cross_source_results if not item["failure"]]
                shared_columns = successful[0]["columns"] if successful else []
                same_shape = bool(shared_columns) and all(
                    item["columns"] == shared_columns for item in successful
                )
                if same_shape:
                    result_columns = ["数据源", "指标", *shared_columns, "状态"]
                    result_rows = []
                    for item in cross_source_results:
                        if item["failure"]:
                            result_rows.append([
                                item["data_source_id"], item["metric_name"],
                                *([None] * len(shared_columns)), item["failure"],
                            ])
                        else:
                            result_rows.extend([
                                [item["data_source_id"], item["metric_name"], *row, "成功"]
                                for row in item["rows"]
                            ])
                else:
                    result_columns = ["数据源", "指标", "结果", "状态"]
                    result_rows = [
                        [
                            item["data_source_id"],
                            item["metric_name"],
                            json.dumps(
                                {"columns": item["columns"], "rows": item["rows"]},
                                ensure_ascii=False,
                                default=str,
                            ) if not item["failure"] else None,
                            item["failure"] or "成功",
                        ]
                        for item in cross_source_results
                    ]
                payload = {
                    "metrics": [item["metric_code"] for item in cross_source_results],
                    "dimensions": ["data_source_id", "metric_name"],
                    "sql": "",
                    "columns": result_columns,
                    "physical_columns": result_columns,
                    "rows": result_rows,
                    "tables": [],
                    "explanation": "已按数据源分别执行确定性指标，并在结果层受控汇集；未生成跨库 SQL JOIN。",
                }
                return _response(_query_result_from_ask(
                    payload,
                    request.user_id,
                    answer_path=AnswerPath.official,
                    execution_path=_ExecutionPath.FORMAL_METRIC,
                ))

            effective_data_source_id = request.data_source_id
            if effective_data_source_id is None and routed_assets:
                effective_data_source_id = routed_assets[0][0]
            if effective_data_source_id is None and candidate_source_ids:
                # Exploration remains single-source: select the first scoped
                # semantic candidate instead of constructing unsafe cross-DB SQL.
                effective_data_source_id = candidate_source_ids[0]

            if effective_data_source_id:
                from .semantic_retriever import SemanticRetriever
                semantic_ctx = SemanticRetriever(_profile_store_path).get_context_for_question(
                    request.question, effective_data_source_id
                )

                candidate_context = _AskRuntimeRequestContext(
                    user_id=request.user_id,
                    data_source_id=effective_data_source_id,
                    workspace_id=request.user_id,
                )
                route = QueryRouter(
                    _ResolverBackedMetricCandidates(_runtime_asset_resolver, candidate_context)
                ).route(request.question, data_source_id=effective_data_source_id)
                answer_path = route.answer_path

                if route.selected_asset is not None:
                    from sq_bi_contracts.enums import ExecutionPath as _ExecutionPath
                    from sq_bi_contracts.execution import (
                        ResolvedExecutionRequest as _ResolvedExecutionRequest,
                    )
                    from .deterministic_execution import (
                        DeterministicExecutionPipeline as _DeterministicExecutionPipeline,
                    )

                    execution_request = _ResolvedExecutionRequest(
                        question=request.question,
                        context=candidate_context,
                        execution_path=_ExecutionPath.FORMAL_METRIC,
                        selected_asset=route.selected_asset,
                    )
                    source_record = next(
                        (item for item in _load_datasources() if item.get("data_source_id") == effective_data_source_id),
                        {},
                    )
                    if source_record:
                        scoped_executor = _data_source_executors.get(effective_data_source_id)
                        scoped_catalog = scoped_executor.get_schema_catalog()
                    else:
                        scoped_executor = service.db_executor
                        scoped_catalog = service.schema_catalog
                    execution = _DeterministicExecutionPipeline(
                        _mapping_store,
                        scoped_executor,
                        allowed_schemas=(str(source_record.get("username")),) if source_record.get("username") else service.allowed_schemas,
                        schema_catalog=scoped_catalog,
                        dialect={
                            "postgresql": "postgres",
                            "postgres": "postgres",
                            "mysql": "mysql",
                            "clickhouse": "clickhouse",
                        }.get(str(source_record.get("database_type") or "oracle").lower(), "oracle"),
                    ).execute(execution_request, execute_sql=request.execute)
                    metric = route.matched_metric
                    payload = {
                        "metrics": [metric.metric_code] if metric else [],
                        "dimensions": [],
                        "sql": execution.sql or "",
                        "columns": execution.columns,
                        "physical_columns": execution.columns,
                        "rows": execution.rows,
                        "tables": [],
                        "explanation": (
                            execution.failure.message
                            if execution.failure
                            else "已通过确定性指标管线执行。"
                        ),
                    }
                    return _response(_query_result_from_ask(
                        payload,
                        request.user_id,
                        answer_path=answer_path,
                        execution_path=_ExecutionPath.FORMAL_METRIC,
                        execution_provenance=execution.provenance,
                        execution_timings=execution.timings,
                        execution_failure=execution.failure,
                    ))

                if route.answer_path == AnswerPath.ai_exploration:
                    from .exploration_planner import ExplorationPlanner
                    plan = ExplorationPlanner(
                        llm_client=llm_client,
                        profile_store_path=_profile_store_path,
                    ).plan(request.question, effective_data_source_id, semantic_context=semantic_ctx)

                    assumptions = [plan.assumption]
                    confidence_tier = plan.confidence_tier
                    clarification = plan.clarification
                    is_exploratory = True

                    gap_candidates = _profile_store.lookup_gap_candidates(
                        effective_data_source_id, request.question
                    )

                    if not plan.executable:
                        # Return the clarification / single-table fallback without executing SQL
                        _now = datetime.now(UTC)
                        result = QueryResult(
                            query_id="qry_" + uuid4().hex,
                            audit_id="aud_" + uuid4().hex,
                            columns=[],
                            rows=[],
                            chart_suggestion=ChartSuggestion(chart_type=ChartType.TABLE, title="AI 探索"),
                            lineage=Lineage(
                                lineage_id="lin_" + uuid4().hex,
                                source_system="SQ_BI_AI_EXPLORATION",
                                data_source_id=effective_data_source_id or "",
                                metric_codes=[],
                                formula_summary="exploration:clarification",
                                physical_tables=[],
                                physical_fields=[],
                                executed_at=_now,
                            ),
                            summary="需要进一步澄清才能继续分析。",
                            answer_path=answer_path,
                            assumptions=assumptions,
                            confidence_tier=confidence_tier,
                            clarification=clarification,
                            is_exploratory=True,
                            gap_candidates=gap_candidates,
                        )
                        return _response(result)

                    # Executable: feed interpretation as extra_context into ask pipeline
                    semantic_ctx = (semantic_ctx + "\n\n" + plan.follow_up_context).strip()

            query_service = service
            if effective_data_source_id:
                from dataclasses import replace

                source_record = next(
                    (item for item in _load_datasources() if item.get("data_source_id") == effective_data_source_id),
                    {},
                )
                if source_record:
                    scoped_executor = _data_source_executors.get(effective_data_source_id)
                    query_service = replace(
                        service,
                        db_executor=scoped_executor,
                        allowed_schemas=(str(source_record.get("username")),) if source_record.get("username") else (),
                        schema_catalog=scoped_executor.get_schema_catalog(),
                        sql_dialect={
                            "postgresql": "postgres",
                            "postgres": "postgres",
                            "mysql": "mysql",
                            "clickhouse": "clickhouse",
                        }.get(str(source_record.get("database_type") or "oracle").lower(), "oracle"),
                    )
            payload = query_service.ask_controlled(
                request.question,
                execute_sql=request.execute,
                extra_context=semantic_ctx,
            )
            from sq_bi_contracts.enums import ExecutionPath as _ExecutionPath
            return _response(_query_result_from_ask(
                payload,
                request.user_id,
                answer_path=answer_path,
                assumptions=assumptions,
                confidence_tier=confidence_tier,
                clarification=clarification,
                is_exploratory=is_exploratory,
                gap_candidates=gap_candidates,
                execution_path=_ExecutionPath.CONTROLLED_EXPLORATION,
                execution_timings=payload.get("execution_timings") or [],
            ))
        except ControlledPlanError as exc:
            return _error_response(
                400,
                ErrorCode.QUERY_REJECTED,
                str(exc),
                {"stage": "plan_validation", "failure_code": "invalid_plan"},
            )
        except SQLValidationError as exc:
            return _error_response(400, ErrorCode.QUERY_REJECTED, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.post("/api/v1/query/exploration/save-metric", response_model=None)
    def save_exploration_as_metric(body: _SaveExplorationAsMetricRequest) -> Any:
        from sq_bi_contracts.metrics import MetricDefinition, MetricFormula, MetricVisibility
        import re as _re
        try:
            name_slug = _re.sub(r"[^\w一-龥-]", "_", body.business_name).strip("_").lower()
            if not name_slug:
                name_slug = "metric"
            user_slug = _re.sub(r"[^\w-]", "_", body.user_id).strip("_").lower() or "anonymous"
            metric_code = f"exp_{user_slug}::{name_slug}"

            vis = MetricVisibility.PRIVATE

            sql_expr = body.sql or f"SELECT NULL AS placeholder -- exploration: {body.business_name}"
            metric_def = MetricDefinition(
                metric_code=metric_code,
                name=body.business_name,
                definition=body.definition,
                visibility=vis,
                formula=MetricFormula(expression=sql_expr),
                data_source_id=body.data_source_id or "oracle_tms",
                owner=body.user_id,
                synonyms=list(body.synonyms or []),
            )
            persisted = get_repository().create_user_metric(metric_def)
            from sq_bi_contracts.personal_assets import PersonalAssetScope as _PersonalAssetScope
            from .personal_asset_store import new_personal_record as _new_personal_record

            provenance = dict(body.execution_provenance or {})
            lineage = dict(body.lineage or {})
            workspace_id = _personal_store.workspace_id_for(body.user_id)
            scope = _PersonalAssetScope(
                workspace_id=workspace_id,
                data_source_id=str(provenance.get("data_source_id") or body.data_source_id or "oracle_tms"),
                environment=str(provenance.get("environment") or body.environment or "default"),
                semantic_space_ids=list(provenance.get("semantic_space_ids") or body.semantic_space_ids or []),
                physical_tables=list(lineage.get("physical_tables") or []),
                physical_fields=list(lineage.get("physical_fields") or []),
            )
            if persisted.asset_ref is None:
                from sq_bi_contracts.assets import AssetKey as _AssetKey, AssetRef as _AssetRef
                from sq_bi_contracts.enums import AssetSourceType as _AssetSourceType, AssetType as _AssetType
                persisted = persisted.model_copy(update={
                    "asset_ref": _AssetRef(
                        asset=_AssetKey(
                            source_type=_AssetSourceType.PERSONAL_WORKSPACE,
                            source_id=workspace_id,
                            asset_type=_AssetType.METRIC,
                            local_code=persisted.metric_code,
                        ),
                        version=persisted.version,
                    )
                })
            assert persisted.asset_ref is not None
            personal_record = _personal_store.save_asset(
                _new_personal_record(
                    asset_ref=persisted.asset_ref,
                    name=persisted.name,
                    owner_user_id=body.user_id,
                    scope=scope,
                )
            )
            return _response({
                "metric": persisted.model_dump(mode="json"),
                "personal_asset": personal_record.model_dump(mode="json"),
                "promotion_required": bool(body.target_pack_id),
                "next_action": "preview_promotion" if body.target_pack_id else None,
            })
        except ValueError as exc:
            return _error_response(409, ErrorCode.CONFLICT, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.post("/api/v1/ai/metrics/draft", response_model=None)
    def draft_metric_with_llm(request: MetricDraftRequest) -> Any:
        try:
            live_db_context = ""
            if service.db_executor is not None and hasattr(service.db_executor, "describe_schema"):
                try:
                    live_db_context = service.db_executor.describe_schema()
                except Exception:
                    live_db_context = ""
            user_prompt = (
                f"{_metric_catalog_context(skill_context, asset_context_provider(), live_db_context)}\n\n"
                f"User metric name: {request.name}\n"
                f"User metric definition: {request.natural_language_definition}\n"
                f"User id: {request.user_id}"
            )
            raw = llm_client.chat(METRIC_DRAFT_SYSTEM_PROMPT, user_prompt)
            payload = parse_json_payload(raw)
            payload["name"] = payload.get("name") or request.name
            return _response(MetricDraft(**payload))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.post("/api/v1/ai/skills/draft", response_model=None)
    def draft_skill_with_llm(request: SkillDraftRequest) -> Any:
        try:
            user_prompt = (
                f"{_metric_catalog_context(skill_context, asset_context_provider())}\n\n"
                f"Skill name: {request.name}\n"
                f"Description: {request.description}\n"
                f"User prompt: {request.prompt}\n"
                f"Adjustment: {request.adjustment or ''}\n"
                f"User id: {request.user_id}"
            )
            return _response(parse_json_payload(llm_client.chat(SKILL_DRAFT_SYSTEM_PROMPT, user_prompt)))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.post("/api/v1/ai/skills/execute", response_model=None)
    def execute_skill_with_llm(request: SkillExecuteRequest) -> Any:
        try:
            parameter_slots = _resolve_skill_parameter_slots(request.skill, request.question, llm_client)
            blocking_slots = [
                slot for slot in parameter_slots
                if slot["required"] and slot["status"] in {"unresolved", "ambiguous"}
            ]
            if blocking_slots:
                labels = [str(slot.get("description") or slot["name"]) for slot in blocking_slots]
                return _response(
                    {
                        "clarification_required": True,
                        "message": f"执行前还需要确认：{'、'.join(labels)}。",
                        "skill_id": request.skill.skill_id,
                        "parameter_slots": parameter_slots,
                        "build_event": {
                            "event_id": f"evt_{uuid4().hex[:12]}",
                            "event_type": "slot_resolution",
                            "title": "等待参数确认",
                            "summary": "必填参数未解析或存在歧义，已阻止执行。",
                            "created_at": datetime.now(UTC).isoformat(),
                            "payload": {"blocking_slots": [slot["name"] for slot in blocking_slots]},
                        },
                    }
                )
            extra_context = (
                "# Saved Product Skill To Execute\n\n"
                f"{json.dumps(request.skill.model_dump(mode='json'), ensure_ascii=False, indent=2)}\n\n"
                f"# Resolved Parameter Slots\n{json.dumps(parameter_slots, ensure_ascii=False, indent=2)}\n\n"
                "Use this saved Skill as the primary execution contract. "
                "Respect its parameters, steps, schema, bound metrics, and output_schema."
            )
            binding_ids = [binding.data_source_id for binding in request.skill.data_source_bindings]
            if request.skill.execution_contract is not None:
                binding_ids.extend(
                    binding.data_source_id
                    for binding in request.skill.execution_contract.data_source_bindings
                )
            binding_ids = list(dict.fromkeys(value for value in binding_ids if value))
            if not binding_ids and request.data_source_id:
                binding_ids = [request.data_source_id]

            if len(binding_ids) <= 1:
                scoped_service = (
                    _scoped_service_for_data_source(binding_ids[0]) if binding_ids else service
                )
                payload = scoped_service.ask_controlled(
                    request.question,
                    execute_sql=request.execute,
                    extra_context=extra_context,
                )
                if binding_ids:
                    payload.setdefault("data_source_id", binding_ids[0])
            else:
                def execute_skill_source(data_source_id: str) -> tuple[str, dict[str, Any]]:
                    scoped = _scoped_service_for_data_source(data_source_id)
                    result = scoped.ask_controlled(
                        request.question,
                        execute_sql=request.execute,
                        extra_context=(
                            f"{extra_context}\n\nOnly execute the steps bound to data source "
                            f"'{data_source_id}'. Do not join another database in SQL."
                        ),
                    )
                    return data_source_id, result

                with ThreadPoolExecutor(
                    max_workers=min(8, len(binding_ids)),
                    thread_name_prefix="cross-ds-skill",
                ) as executor:
                    source_payloads = list(executor.map(execute_skill_source, binding_ids))
                shared_columns = source_payloads[0][1].get("columns", [])
                same_shape = bool(shared_columns) and all(
                    item.get("columns", []) == shared_columns for _, item in source_payloads
                )
                if same_shape:
                    columns = ["数据源", *shared_columns]
                    rows = [
                        [data_source_id, *row]
                        for data_source_id, item in source_payloads
                        for row in item.get("rows", [])
                    ]
                else:
                    columns = ["数据源", "分析结果"]
                    rows = [
                        [
                            data_source_id,
                            json.dumps(
                                {"columns": item.get("columns", []), "rows": item.get("rows", [])},
                                ensure_ascii=False,
                                default=str,
                            ),
                        ]
                        for data_source_id, item in source_payloads
                    ]
                payload = {
                    "intent": "cross_datasource_skill",
                    "metrics": list(dict.fromkeys(
                        metric
                        for _, item in source_payloads
                        for metric in item.get("metrics", [])
                    )),
                    "dimensions": ["data_source_id"],
                    "sql": "",
                    "columns": columns,
                    "physical_columns": columns,
                    "rows": rows,
                    "tables": [],
                    "explanation": "技能已按数据源分别执行，并在结果层受控汇集。",
                    "execution_timings": [
                        timing
                        for _, item in source_payloads
                        for timing in item.get("execution_timings", [])
                    ],
                }
            payload["skill_ids"] = [request.skill.skill_id]
            payload["parameter_slots"] = parameter_slots
            from sq_bi_contracts.enums import ExecutionPath as _ExecutionPath
            from sq_bi_contracts.exploration import AnswerPath as _AnswerPath
            if request.skill.visibility.value == "official":
                answer_path = _AnswerPath.official
            elif request.skill.visibility.value == "shared":
                answer_path = _AnswerPath.enterprise
            else:
                answer_path = _AnswerPath.personal
            return _response(_query_result_from_ask(
                payload,
                request.user_id,
                answer_path=answer_path,
                execution_path=_ExecutionPath.CONTROLLED_EXPLORATION,
                execution_timings=payload.get("execution_timings") or [],
            ))
        except ControlledPlanError as exc:
            return _error_response(
                400,
                ErrorCode.QUERY_REJECTED,
                str(exc),
                {"stage": "plan_validation", "failure_code": "invalid_plan"},
            )
        except SQLValidationError as exc:
            return _error_response(400, ErrorCode.QUERY_REJECTED, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.post("/api/v1/ai/assets/test", response_model=None)
    def test_asset_draft(request: AssetDraftTestRequest) -> Any:
        """Test the current draft through the closed controlled-plan pipeline."""
        try:
            # Guardrails and execution must run against the draft's bound data
            # source, not the legacy default service.
            scoped_service = _scoped_service_for_data_source(request.data_source_id or "")
            candidate_context = {
                "asset_type": request.asset_type,
                "name": request.name,
                "description": request.description,
                "logical_sql_evidence": request.logical_sql or "",
                "data_source_id": request.data_source_id,
                "default_time_range": request.default_time_range,
                "conversation_context": request.conversation_context,
            }
            if request.asset_type == "metric" and request.logical_sql:
                validation = validate_sql(
                    request.logical_sql,
                    allowed_schemas=scoped_service.allowed_schemas,
                    schema_catalog=scoped_service.schema_catalog,
                )
                raw_data = scoped_service.db_executor.execute(validation.sql, max_rows=200) if request.execute and scoped_service.db_executor else {"columns": [], "rows": []}
                payload = {
                    "intent": request.name,
                    "metrics": [request.name],
                    "dimensions": [],
                    "sql": validation.sql,
                    "columns": list(raw_data.get("columns", [])),
                    "rows": list(raw_data.get("rows", [])),
                    "physical_columns": list(raw_data.get("columns", [])),
                    "tables": validation.tables,
                    "explanation": "已严格执行当前指标 SQL 草案，未重新选择字段或数据表。",
                    "execution_timings": [{"stage": "guardrail", "duration_ms": 0}],
                }
                time_default_applied = bool(re.search(
                    r"\b(?:sysdate|current_date|current_timestamp|add_months|trunc)\b|\bbetween\b|\binterval\b",
                    request.logical_sql,
                    flags=re.IGNORECASE,
                ))
            else:
                question = (
                    f"验证当前{request.asset_type}草案「{request.name}」并直接返回查询结果。"
                    f"未明确时间范围时采用{request.default_time_range}。{request.description}"
                )
                payload = scoped_service.ask_controlled(
                    question,
                    execute_sql=request.execute,
                    extra_context=(
                        "# Asset Draft Under Controlled Test\n"
                        f"{json.dumps(candidate_context, ensure_ascii=False, indent=2)}\n\n"
                        "Build a closed controlled query plan from the schema, compile it deterministically, "
                        "apply guardrails, and return the result without asking for clarification when the "
                        "declared default time range is sufficient."
                    ),
                )
            if request.asset_type == "metric" and request.logical_sql:
                payload["explanation"] = (
                    f"已按默认{request.default_time_range}验证当前 SQL 草案，通过只读防护和真实数据源执行。"
                    if time_default_applied
                    else f"当前 SQL 草案未检测到时间筛选，本次展示全量结果；默认{request.default_time_range}尚未写入草案，请继续对话修订后复测。"
                )
            else:
                payload["explanation"] = (
                    f"已使用{request.default_time_range}作为未指定时间范围的默认值，"
                    "并通过受控计划编译、SQL 防护和真实数据源执行。"
                )
            from sq_bi_contracts.enums import ExecutionPath as _ExecutionPath
            from sq_bi_contracts.exploration import AnswerPath as _AnswerPath
            return _response(_query_result_from_ask(
                payload,
                request.user_id,
                answer_path=_AnswerPath.personal,
                is_exploratory=False,
                execution_path=_ExecutionPath.CONTROLLED_EXPLORATION,
                execution_timings=payload.get("execution_timings") or [],
            ))
        except ControlledPlanError as exc:
            return _error_response(400, ErrorCode.QUERY_REJECTED, str(exc), {"stage": "plan_validation"})
        except SQLValidationError as exc:
            return _error_response(400, ErrorCode.QUERY_REJECTED, str(exc), {"stage": "guardrail"})
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.post("/api/v1/ai/reports/draft", response_model=None)
    def draft_report_with_llm(request: ReportDraftRequest) -> Any:
        try:
            user_prompt = (
                f"{_metric_catalog_context(skill_context, asset_context_provider())}\n\n"
                f"Output type: {request.output_type}\n"
                f"Report title: {request.title}\n"
                f"Template shell: {request.template}\n"
                f"Template requirements: {request.template_requirements}\n"
                f"Background: {request.background}\n"
                f"User prompt: {request.prompt}\n"
                f"Bound metrics: {request.bound_metric_codes}\n"
                f"Bound skills: {request.bound_skill_ids}\n"
                f"User id: {request.user_id}"
            )
            return _response(parse_json_payload(llm_client.chat(REPORT_DRAFT_SYSTEM_PROMPT, user_prompt)))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.post("/api/v1/ai/reports/{report_id}/generate", response_model=None)
    def generate_report_artifact_with_llm(report_id: str, request: ReportArtifactGenerateRequest) -> Any:
        repo = get_repository()
        if not isinstance(repo, SQLiteProductRepository):
            return _error_response(400, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
        try:
            report = _find_report(repo, report_id)
        except KeyError as exc:
            return _error_response(404, ErrorCode.NOT_FOUND, str(exc))

        artifact_title = request.title or report.name
        artifact_content = ""
        output_type = request.output_type.lower()
        if output_type != "html":
            return _error_response(400, ErrorCode.VALIDATION_ERROR, "Only html report artifacts are supported.")
        runtime_data = _build_report_runtime_data(
            repo=repo,
            report=report,
            request=request,
            service=service,
            service_resolver=_scoped_service_for_data_source,
        )
        runtime_failure = _report_runtime_failure_details(runtime_data)
        if runtime_failure:
            return _error_response(
                500,
                ErrorCode.INTERNAL_ERROR,
                "REPORT_ARTIFACT_DATA_QUERY_FAILED",
                runtime_failure,
            )

        prompt_payload = {
            "user_id": request.user_id,
            "question": request.question,
            "output_type": request.output_type,
            "requested_title": request.title,
            "content": request.content,
            "bound_metric_codes": runtime_data["bound_metric_codes"],
            "bound_skill_ids": runtime_data["bound_skill_ids"],
            "runtime_data": _successful_report_evidence(runtime_data),
            "context_assets": runtime_data.get("context_assets") or [],
            "saved_report_skill": _compact_report_skill_context(report),
            "targeted_skill_assets": _targeted_report_asset_context(
                repo,
                runtime_data["bound_metric_codes"],
                runtime_data["bound_skill_ids"],
            ),
            "domain_context": _trim_context(skill_context),
        }
        user_prompt = json.dumps(prompt_payload, ensure_ascii=False, separators=(",", ":"))
        try:
            raw_model_response = llm_client.chat(
                REPORT_HTML_ARTIFACT_SYSTEM_PROMPT,
                user_prompt,
                response_format={},
            )
        except Exception as exc:  # noqa: BLE001
            return _error_response(
                500,
                ErrorCode.INTERNAL_ERROR,
                "REPORT_ARTIFACT_RENDER_FAILED",
                {
                    "stage": "artifact_render",
                    "renderer": "llm",
                    "output_type": "html",
                    "reason": "model_call_failed",
                    "error": str(exc),
                },
            )
        raw_html = _clean_html_artifact_response(raw_model_response)
        if raw_html.lower().startswith(("<!doctype html", "<html")):
            artifact_content = raw_html
        else:
            try:
                html_payload = parse_json_payload(raw_model_response)
                html_content = str(html_payload.get("html") or "").strip()
            except Exception:
                html_content = ""
                html_payload = {}
            if html_content.lower().startswith(("<!doctype html", "<html")):
                artifact_content = html_content
                artifact_title = str(html_payload.get("title") or artifact_title).strip() or artifact_title
            else:
                return _error_response(
                    500,
                    ErrorCode.INTERNAL_ERROR,
                    "REPORT_ARTIFACT_RENDER_FAILED",
                    _html_artifact_failure_details(raw_model_response),
                )

        try:
            generated = repo.generate_report_file(
                report_id,
                user_id=request.user_id,
                output_type=request.output_type,
                title=artifact_title,
                content=artifact_content,
                bound_metric_codes=runtime_data["bound_metric_codes"],
                bound_skill_ids=runtime_data["bound_skill_ids"],
            )
            return _response(generated)
        except KeyError as exc:
            return _error_response(404, ErrorCode.NOT_FOUND, str(exc))
        except ValueError as exc:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))

    # ── Admin: mounting & deployment ────────────────────────────────────

    _mapping_store_path = Path(config.storage_path) / "field_mappings.sqlite3"
    _mapping_store = FieldMappingStore(_mapping_store_path)
    _mounting_pipeline = MountingPipeline(store=_mapping_store, llm_client=llm_client)

    def _require_admin(request: Request) -> Any:
        session_id = request.headers.get("X-Session-Id")
        user_ctx = resolve_user_context(session_id=session_id)
        if user_ctx is None:
            return _error_response(401, ErrorCode.UNAUTHORIZED, "Authentication required.")
        if not is_admin(user_ctx):
            return _error_response(403, ErrorCode.FORBIDDEN, "Admin role required.")
        return user_ctx

    # ── Catalog: data sources ────────────────────────────────────────────

    _ds_store_path = Path(config.storage_path) / "datasources.json"

    def _load_datasources() -> list[dict]:
        from .connection_secrets import decrypt_password

        if _ds_store_path.exists():
            try:
                records = json.loads(_ds_store_path.read_text(encoding="utf-8"))
            except Exception:
                records = []
        elif config.db and config.db.is_configured:
            records = [{
                "data_source_id": "default",
                "name": "默认数据源",
                "database_type": "oracle",
                "host": config.db.dsn or "",
                "port": 1521,
                "database": "",
                "username": config.db.user or "",
                "password": "",
                "is_read_only": True,
                "description": None,
                "tags": [],
            }]
        else:
            records = []
        for rec in records:
            if rec.get("password"):
                rec["password"] = decrypt_password(rec["password"], config.storage_path)
        return records

    def _save_datasources(ds_list: list[dict]) -> None:
        from .connection_secrets import encrypt_password

        to_write = []
        for rec in ds_list:
            rec_copy = dict(rec)
            if rec_copy.get("password"):
                rec_copy["password"] = encrypt_password(rec_copy["password"], config.storage_path)
            to_write.append(rec_copy)
        _ds_store_path.write_text(json.dumps(to_write, ensure_ascii=False, indent=2), encoding="utf-8")

    from .datasource_executors import DataSourceExecutorRegistry

    _data_source_executors = DataSourceExecutorRegistry(_load_datasources)

    def _scoped_service_for_data_source(data_source_id: str) -> Any:
        if not data_source_id:
            return service
        from dataclasses import replace

        record = next(
            (item for item in _load_datasources() if item.get("data_source_id") == data_source_id),
            None,
        )
        if record is None:
            return service
        scoped_executor = _data_source_executors.get(data_source_id)
        dialect = {
            "postgresql": "postgres",
            "postgres": "postgres",
            "mysql": "mysql",
            "clickhouse": "clickhouse",
        }.get(str(record.get("database_type") or "oracle").lower(), "oracle")
        return replace(
            service,
            db_executor=scoped_executor,
            allowed_schemas=(str(record.get("username")),) if record.get("username") else (),
            schema_catalog=scoped_executor.get_schema_catalog(),
            sql_dialect=dialect,
        )

    def _mask_ds(ds: dict) -> dict:
        masked = {k: v for k, v in ds.items() if k != "password"}
        raw_user = ds.get("username") or ""
        if len(raw_user) > 2:
            masked["user_mask"] = raw_user[0] + "*" * (len(raw_user) - 2) + raw_user[-1]
        elif raw_user:
            masked["user_mask"] = raw_user[0] + "***"
        else:
            masked["user_mask"] = None
        return masked

    # Connection is technical-connection-only (checklist: 数据库连接页面只回答
    # "怎么连上数据库，以及这个连接下大概有哪些元数据"). Business description,
    # semantic scope, and scan include/exclude rules live on the semantic
    # space, not here.
    _DS_TECHNICAL_FIELDS = (
        "name", "database_type", "host", "port", "database",
        "service_name", "sid", "dsn", "username",
        "is_read_only", "description", "tags",
        "connect_timeout_seconds", "metadata_scan_enabled",
        "pool_min", "pool_max", "pool_wait_timeout_ms",
    )
    # Changing any of these invalidates the last connection test and requires
    # a fresh metadata scan (checklist: "连接参数变更后，需要重新测试连接并刷新
    # 元数据概览").
    _DS_CONNECTION_CRITICAL_FIELDS = (
        "host", "port", "database", "service_name", "sid", "dsn", "username", "password",
    )

    @app.get("/api/v1/catalog/data-sources", response_model=None)
    def list_datasources(request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        return _response([_mask_ds(ds) for ds in _load_datasources()])

    @app.get("/api/v1/admin/data-sources", response_model=None)
    def admin_list_datasources(request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        return _response([_mask_ds(ds) for ds in _load_datasources()])

    @app.get("/api/v1/admin/data-sources/{ds_id}", response_model=None)
    def admin_get_datasource(ds_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        ds_record = next((d for d in _load_datasources() if d["data_source_id"] == ds_id), None)
        if not ds_record:
            return _error_response(404, ErrorCode.NOT_FOUND, f"Data source '{ds_id}' not found.")
        return _response(_mask_ds(ds_record))

    @app.post("/api/v1/admin/data-sources", response_model=None)
    async def admin_create_datasource(request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        body = await request.json()
        ds_id = str(body.get("data_source_id") or "").strip()
        if not ds_id:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, "data_source_id is required.")
        existing = _load_datasources()
        if any(d["data_source_id"] == ds_id for d in existing):
            return _error_response(409, ErrorCode.VALIDATION_ERROR, f"Data source '{ds_id}' already exists.")
        new_ds = {
            "data_source_id": ds_id,
            "name": str(body.get("name") or ds_id),
            "database_type": str(body.get("database_type") or "oracle"),
            "host": str(body.get("host") or ""),
            "port": int(body.get("port") or 1521),
            "database": str(body.get("database") or ""),
            "service_name": body.get("service_name") or None,
            "sid": body.get("sid") or None,
            "dsn": body.get("dsn") or None,
            "username": str(body.get("username") or ""),
            "password": str(body.get("password") or ""),
            "is_read_only": bool(body.get("is_read_only", True)),
            "description": body.get("description") or None,
            "tags": list(body.get("tags") or []),
            "connect_timeout_seconds": body.get("connect_timeout_seconds") or None,
            "metadata_scan_enabled": bool(body.get("metadata_scan_enabled", True)),
            "pool_min": max(0, int(body.get("pool_min") or 1)),
            "pool_max": max(1, int(body.get("pool_max") or 4)),
            "pool_wait_timeout_ms": max(100, int(body.get("pool_wait_timeout_ms") or 15000)),
        }
        existing.append(new_ds)
        _save_datasources(existing)

        response_extra: dict[str, Any] = {}
        if new_ds["metadata_scan_enabled"]:
            # Auto-trigger a metadata scan immediately after save (checklist §二 step 6).
            scan_status = _profile_store.create_scan_job(ds_id)
            snapshot = _profile_store.create_snapshot(ds_id)
            _discovery_executor.submit(
                _run_scan_background,
                ds_id, new_ds, scan_status.scan_id, snapshot.snapshot_id, {},
            )
            response_extra = {"scan_id": scan_status.scan_id, "snapshot_id": snapshot.snapshot_id}

        return _response({**_mask_ds(new_ds), **response_extra})

    @app.put("/api/v1/admin/data-sources/{ds_id}", response_model=None)
    async def admin_update_datasource(ds_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        body = await request.json()
        existing = _load_datasources()
        idx = next((i for i, d in enumerate(existing) if d["data_source_id"] == ds_id), None)
        if idx is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"Data source '{ds_id}' not found.")
        before = existing[idx]
        updated = {**before}
        for field in _DS_TECHNICAL_FIELDS:
            if field in body:
                updated[field] = body[field]
        password_changed = bool(body.get("password")) and body["password"] != before.get("password")
        if body.get("password"):
            updated["password"] = str(body["password"])
        existing[idx] = updated
        _save_datasources(existing)

        connection_changed = password_changed or any(
            field != "password" and body.get(field) is not None and updated.get(field) != before.get(field)
            for field in _DS_CONNECTION_CRITICAL_FIELDS
        )
        if connection_changed:
            _data_source_executors.invalidate(ds_id)

        response_extra: dict[str, Any] = {"connection_changed": connection_changed}
        if connection_changed and updated.get("metadata_scan_enabled", True):
            scan_status = _profile_store.create_scan_job(ds_id)
            snapshot = _profile_store.create_snapshot(ds_id)
            _discovery_executor.submit(
                _run_scan_background,
                ds_id, updated, scan_status.scan_id, snapshot.snapshot_id, {},
            )
            response_extra.update({"scan_id": scan_status.scan_id, "snapshot_id": snapshot.snapshot_id})

        return _response({**_mask_ds(updated), **response_extra})

    @app.delete("/api/v1/admin/data-sources/{ds_id}", response_model=None)
    def admin_delete_datasource(ds_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        existing = _load_datasources()
        if not any(d["data_source_id"] == ds_id for d in existing):
            return _error_response(404, ErrorCode.NOT_FOUND, f"Data source '{ds_id}' not found.")
        try:
            in_use = [dep.deployment_id for dep in _mapping_store.list_deployments() if dep.data_source_id == ds_id]
        except Exception:
            in_use = []
        if in_use:
            return _error_response(
                409, ErrorCode.VALIDATION_ERROR,
                f"数据源 '{ds_id}' 正在被以下部署使用：{', '.join(in_use[:3])}，请先移除相关部署。",
            )
        _save_datasources([d for d in existing if d["data_source_id"] != ds_id])
        _data_source_executors.invalidate(ds_id)
        return _response({"deleted": ds_id})

    @app.post("/api/v1/admin/data-sources/test", response_model=None)
    async def admin_test_datasource_connection(request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        body = await request.json()
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as _FutureTimeoutError

        from .connectors.factory import build_connector

        _empty_caps = {
            "can_read_schemas": False, "can_read_tables": False,
            "can_read_columns": False, "can_read_keys": False,
        }
        ds_id = str(body.get("data_source_id") or "").strip()
        if ds_id:
            saved = next((d for d in _load_datasources() if d["data_source_id"] == ds_id), None)
            if saved:
                merged = dict(saved)
                for key, value in body.items():
                    if key == "password" and not value:
                        continue
                    if key == "username" and isinstance(value, str) and "*" in value:
                        continue
                    if value is not None and value != "":
                        merged[key] = value
                body = merged

        def _attempt() -> dict[str, bool]:
            connector = build_connector(body)
            try:
                # A successful catalog fetch proves schema/table/column
                # enumeration together — the connector protocol doesn't
                # expose them as separate calls.
                connector.get_schema_catalog()
                caps = {"can_read_schemas": True, "can_read_tables": True, "can_read_columns": True}
                # Key/index readability is checked separately and is
                # best-effort: a failure here degrades only this one
                # capability, not overall connection success.
                try:
                    connector.describe_schema()
                    caps["can_read_keys"] = True
                except Exception:  # noqa: BLE001
                    caps["can_read_keys"] = False
                return caps
            finally:
                close = getattr(connector, "close", None)
                if callable(close):
                    close()

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                capabilities = pool.submit(_attempt).result(timeout=8)
            return _response({
                "success": True, "message": "数据库连接测试成功。", "capabilities": capabilities,
            })
        except _FutureTimeoutError:
            return _response({
                "success": False, "message": "连接超时（8 秒），请检查地址、端口或网络可达性。",
                "capabilities": _empty_caps,
            })
        except ImportError as exc:
            return _response({"success": False, "message": str(exc), "capabilities": _empty_caps})
        except Exception as exc:  # noqa: BLE001
            return _response({
                "success": False, "message": f"连接失败：{exc}", "capabilities": _empty_caps,
            })

    # ── Semantic Discovery endpoints ─────────────────────────────────────────

    _profile_store_path = Path(config.storage_path) / "semantic_profile.sqlite3"
    _document_storage_dir = Path(config.storage_path) / "ds_documents"

    from .semantic_profile_store import SemanticProfileStore
    from .document_store import DocumentStore as _DocumentStore
    from .schema_scanner import SchemaScanner
    from .schema_profiler import SchemaProfiler
    from .semantic_discovery import SemanticDiscovery
    from sq_bi_contracts.semantic_profile import (
        ScanRequest as SemanticScanRequest,
        SemanticSpaceAdjustment,
    )

    _profile_store = SemanticProfileStore(_profile_store_path)
    _doc_store = _DocumentStore(_document_storage_dir)
    _discovery_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sem_scan")

    def _run_scan_background(
        ds_id: str,
        ds_record: dict,
        scan_id: str,
        snapshot_id: str,
        scan_req: dict,
    ) -> None:
        """Execute a full scan pipeline in a background thread."""
        from .semantic_profile_store import SemanticProfileStore as _SPS
        from .schema_scanner import SchemaScanner as _SS
        from .schema_profiler import SchemaProfiler as _SP, select_profile_targets
        from .semantic_discovery import SemanticDiscovery as _SD
        from sq_bi_contracts.semantic_profile import ScanPhase

        store = _SPS(_profile_store_path)
        try:
            store.update_scan_job(scan_id, ScanPhase.phase_one, snapshot_id=snapshot_id,
                                  progress_message="正在扫描表结构元数据…")
            store.update_snapshot(snapshot_id, scan_phase=ScanPhase.phase_one)

            # Build connector from ds_record
            from .connectors.factory import build_connector
            connector = build_connector(ds_record)

            authorized_schemas = scan_req.get("authorized_schemas") or ds_record.get("authorized_schemas") or []
            include_rules = scan_req.get("include_rules") or ds_record.get("include_rules") or []
            exclude_rules = scan_req.get("exclude_rules") or ds_record.get("exclude_rules") or []
            business_desc = ds_record.get("business_description")

            scanner = _SS(
                connector, ds_id,
                authorized_schemas=authorized_schemas,
                include_rules=include_rules,
                exclude_rules=exclude_rules,
            )
            metadata = scanner.scan()
            store.save_catalog(snapshot_id, metadata.tables)

            store.update_snapshot(
                snapshot_id,
                scan_phase=ScanPhase.phase_two,
                scanned_schemas=metadata.scanned_schemas,
                table_count=len(metadata.tables),
                included_table_count=len(metadata.included),
                excluded_table_count=len(metadata.excluded),
            )
            store.update_scan_job(scan_id, ScanPhase.phase_two, snapshot_id=snapshot_id,
                                  progress_message="正在分析推荐表样本…",
                                  table_count=len(metadata.tables),
                                  included_table_count=len(metadata.included))

            # Phase 2: profile recommended tables
            profiler = _SP(connector)
            profiles = {}
            chunks = scanner.chunk_metadata_for_llm(metadata)
            for tbl in select_profile_targets(metadata.included):
                try:
                    profiles[tbl.name] = profiler.profile_table(tbl)
                except Exception:
                    pass

            store.update_scan_job(scan_id, ScanPhase.discovering, snapshot_id=snapshot_id,
                                  progress_message="AI 正在推断语义空间…")

            discovery = _SD(llm_client)
            spaces, rec_counts = discovery.discover(
                snapshot_id, chunks, profiles, business_description=business_desc
            )
            store.save_spaces(snapshot_id, spaces)
            store.update_snapshot(
                snapshot_id,
                scan_phase=ScanPhase.done,
                recommendation_counts=rec_counts,
                included_table_count=len(metadata.included),
                excluded_table_count=len(metadata.excluded),
                table_count=len(metadata.tables),
                scanned_schemas=metadata.scanned_schemas,
            )
            store.update_scan_job(
                scan_id, ScanPhase.done, snapshot_id=snapshot_id,
                table_count=len(metadata.tables),
                included_table_count=len(metadata.included),
                recommendation_counts=rec_counts,
            )
        except Exception as exc:
            from sq_bi_contracts.semantic_profile import ScanPhase as _SP2
            store.update_scan_job(scan_id, _SP2.failed, error=str(exc))
            store.update_snapshot(snapshot_id, scan_phase=_SP2.failed, error=str(exc))

    @app.post("/api/v1/datasources/{ds_id}/scan", response_model=None)
    async def start_scan(ds_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        ds_list = _load_datasources()
        ds_record = next((d for d in ds_list if d["data_source_id"] == ds_id), None)
        if not ds_record:
            return _error_response(404, ErrorCode.NOT_FOUND, f"数据源 '{ds_id}' 不存在。")
        try:
            scan_req = await request.json()
        except Exception:
            scan_req = {}
        scan_status = _profile_store.create_scan_job(ds_id)
        snapshot = _profile_store.create_snapshot(ds_id)
        _discovery_executor.submit(
            _run_scan_background,
            ds_id, ds_record, scan_status.scan_id, snapshot.snapshot_id, scan_req,
        )
        updated = _profile_store.update_scan_job(
            scan_status.scan_id,
            __import__("sq_bi_contracts.semantic_profile", fromlist=["ScanPhase"]).ScanPhase.pending,
            snapshot_id=snapshot.snapshot_id,
        )
        return _response((updated or scan_status).model_dump(mode="json"))

    @app.get("/api/v1/datasources/{ds_id}/scan/{scan_id}", response_model=None)
    def get_scan_status_endpoint(ds_id: str, scan_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        status = _profile_store.get_scan_status(scan_id)
        if not status or status.data_source_id != ds_id:
            return _error_response(404, ErrorCode.NOT_FOUND, "Scan not found.")
        return _response(status.model_dump(mode="json"))

    @app.get("/api/v1/datasources/{ds_id}/profile", response_model=None)
    def get_profile(ds_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        profile = _profile_store.load_profile(ds_id)
        if not profile:
            return _error_response(404, ErrorCode.NOT_FOUND, f"数据源 '{ds_id}' 尚无语义档案，请先触发扫描。")
        return _response(profile.model_dump(mode="json"))

    @app.get("/api/v1/datasources/{ds_id}/catalog/overview", response_model=None)
    def get_catalog_overview(ds_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        overview = _profile_store.get_catalog_overview(ds_id)
        if overview is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"数据源 '{ds_id}' 尚无元数据快照，请先触发扫描。")
        return _response(overview.model_dump(mode="json"))

    @app.get("/api/v1/datasources/{ds_id}/catalog/latest", response_model=None)
    def get_catalog_latest(ds_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        tables = _profile_store.list_catalog_tables(ds_id)
        return _response([t.model_dump(mode="json") for t in tables])

    @app.put("/api/v1/datasources/{ds_id}/semantic-spaces", response_model=None)
    async def update_semantic_spaces(ds_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        profile = _profile_store.load_profile(ds_id)
        if not profile:
            return _error_response(404, ErrorCode.NOT_FOUND, f"数据源 '{ds_id}' 尚无语义档案。")
        try:
            body = await request.json()
            raw_adjustments = body.get("adjustments", [])
            adjustments = [SemanticSpaceAdjustment(**a) for a in raw_adjustments]
        except Exception as exc:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))
        _profile_store.apply_space_adjustments(profile.snapshot_id, adjustments)
        refreshed = _profile_store.load_profile(ds_id)
        return _response((refreshed or profile).model_dump(mode="json"))

    # ── Semantic space management (semantic-space-simplification) ────────────

    @app.get("/api/v1/datasources/{ds_id}/semantic-spaces", response_model=None)
    def list_semantic_spaces(ds_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        spaces = _profile_store.list_managed_spaces(ds_id)
        return _response([s.model_dump(mode="json") for s in spaces])

    @app.post("/api/v1/datasources/{ds_id}/semantic-spaces", response_model=None)
    def create_semantic_space(ds_id: str, body: CreateSemanticSpaceRequest, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            space = _profile_store.create_space(
                ds_id, body.name, body.description, body.initial_tables
            )
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))
        return _response(space.model_dump(mode="json"))

    # Registered before the {space_id} route below — "recommendations" would
    # otherwise be swallowed as a space_id path param (Starlette matches
    # routes in registration order, not static-before-dynamic).
    @app.get("/api/v1/datasources/{ds_id}/semantic-spaces/recommendations", response_model=None)
    def list_recommended_semantic_spaces(ds_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        spaces = _profile_store.list_recommended_spaces(ds_id)
        return _response([s.model_dump(mode="json") for s in spaces])

    @app.get("/api/v1/datasources/{ds_id}/semantic-spaces/{space_id}", response_model=None)
    def get_semantic_space(ds_id: str, space_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        space = _profile_store.get_space(space_id)
        if space is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"语义空间 '{space_id}' 不存在。")
        return _response(space.model_dump(mode="json"))

    @app.delete("/api/v1/datasources/{ds_id}/semantic-spaces/{space_id}", response_model=None)
    def delete_semantic_space(ds_id: str, space_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        deleted = _profile_store.delete_space(space_id)
        if not deleted:
            return _error_response(404, ErrorCode.NOT_FOUND, f"语义空间 '{space_id}' 不存在。")
        return _response({"deleted": True, "space_id": space_id})

    @app.post("/api/v1/datasources/{ds_id}/semantic-spaces/{space_id}/refresh", response_model=None)
    def refresh_semantic_space(ds_id: str, space_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            diff = _profile_store.refresh_space(space_id)
        except KeyError:
            return _error_response(404, ErrorCode.NOT_FOUND, f"语义空间 '{space_id}' 不存在。")
        return _response(diff.model_dump(mode="json"))

    def _publish_impact_analysis(ds_id: str, space_id: str, published_version: int | None) -> PublishImpactSummary:
        """Diff this publish's field snapshot against the prior published
        version: fields that were confirmed before and no longer are (removed,
        or demoted to pending/excluded/invalid) are 'lost'. Report which
        enterprise packs and deployments referenced them (openspec 2.4)."""
        from sq_bi_contracts.semantic_profile import FieldStatus

        empty = PublishImpactSummary(space_id=space_id, version=published_version or 0)
        if published_version is None:
            return empty
        prior_versions = [v for v in _profile_store.list_space_versions(space_id) if v < published_version]
        if not prior_versions:
            return empty
        prior = _profile_store.get_space_version(space_id, max(prior_versions))
        current = _profile_store.get_space_version(space_id, published_version)
        if prior is None or current is None:
            return empty

        def _confirmed_by_key(space: Any) -> dict[tuple[str, str], Any]:
            return {
                (f.physical_table, f.physical_column): f
                for e in space.entities for f in e.fields
                if f.status == FieldStatus.confirmed
            }

        prior_confirmed = _confirmed_by_key(prior)
        current_confirmed = _confirmed_by_key(current)
        lost_keys = set(prior_confirmed) - set(current_confirmed)
        if not lost_keys:
            return empty
        lost_fields = {k: prior_confirmed[k] for k in lost_keys}

        # Enterprise pack definitions are portable and no longer own physical
        # table/column bindings (those live only on PackDeployment), so lost
        # physical fields can only be attributed to deployments, not definitions.
        references: list[FieldImpactReference] = []
        for dep in _mapping_store.list_deployments():
            if dep.data_source_id != ds_id or space_id not in (dep.semantic_space_ids or []):
                continue
            for key, f in lost_fields.items():
                references.append(FieldImpactReference(
                    field_id=f.field_id,
                    physical_table=key[0],
                    physical_column=key[1],
                    kind="deployment",
                    ref_id=dep.deployment_id,
                    name=f"{dep.pack_id} × {dep.data_source_id}",
                ))

        return PublishImpactSummary(
            space_id=space_id,
            version=published_version,
            lost_field_ids=[f.field_id for f in lost_fields.values()],
            references=references,
        )

    @app.post("/api/v1/datasources/{ds_id}/semantic-spaces/{space_id}/publish", response_model=None)
    def publish_semantic_space(
        ds_id: str, space_id: str, body: PublishSemanticSpaceRequest, request: Request
    ) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            published = _profile_store.publish_space(
                space_id, body.confirmed_suggestions, published_by=body.published_by
            )
        except KeyError:
            return _error_response(404, ErrorCode.NOT_FOUND, f"语义空间 '{space_id}' 不存在。")
        impact = _publish_impact_analysis(ds_id, space_id, published.version)
        return _response({
            **published.model_dump(mode="json"),
            "impact": impact.model_dump(mode="json"),
        })

    @app.post("/api/v1/query/gap-lookup", response_model=None)
    def gap_lookup(body: GapLookupRequest, request: Request) -> Any:
        session_id = request.headers.get("X-Session-Id")
        if resolve_user_context(session_id=session_id) is None:
            return _error_response(401, ErrorCode.UNAUTHORIZED, "Authentication required.")
        candidates = _profile_store.lookup_gap_candidates(body.connection_id, body.query)
        return _response([c.model_dump(mode="json") for c in candidates])

    @app.post("/api/v1/datasources/{ds_id}/documents", response_model=None)
    async def upload_document(ds_id: str, request: Request) -> Any:
        from fastapi import UploadFile
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        ds_list = _load_datasources()
        if not any(d["data_source_id"] == ds_id for d in ds_list):
            return _error_response(404, ErrorCode.NOT_FOUND, f"数据源 '{ds_id}' 不存在。")
        try:
            form = await request.form()
            file: UploadFile = form["file"]  # type: ignore[assignment]
            content = await file.read()
            doc = _profile_store.create_document(
                ds_id, file.filename or "unknown", file.content_type or "application/octet-stream", len(content)
            )
            _doc_store.save_file(doc.document_id, file.filename or "unknown", content)
            result = _doc_store.extract_hints(doc.document_id, file.filename or "unknown", content)
            _profile_store.update_document_status(
                doc.document_id,
                "ready" if result.success else "failed",
                error=result.error,
            )
            final_doc = _profile_store.list_documents(ds_id)
            doc_record = next((d for d in final_doc if d.document_id == doc.document_id), doc)
        except Exception as exc:
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))
        return _response(doc_record.model_dump(mode="json"))

    @app.get("/api/v1/datasources/{ds_id}/documents", response_model=None)
    def list_documents(ds_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        docs = _profile_store.list_documents(ds_id)
        return _response([d.model_dump(mode="json") for d in docs])

    @app.delete("/api/v1/datasources/{ds_id}/documents/{document_id}", response_model=None)
    def delete_document(ds_id: str, document_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        doc = _profile_store.get_document(document_id)
        if doc is None or doc.data_source_id != ds_id:
            return _error_response(404, ErrorCode.NOT_FOUND, f"文档 '{document_id}' 不存在。")
        _profile_store.delete_document(document_id)
        _doc_store.delete_file(document_id, doc.filename)
        return _response({"deleted": True, "document_id": document_id})

    def _compute_deployment_readiness(deployment: DeploymentInstance) -> tuple[float, ValidationStatus, list[str]]:
        """Coverage/validation_status/blocking_reasons for one deployment —
        space-scoped (task 5.4) when bound, legacy pack-manifest path otherwise.
        Both paths measure the same thing: whether the pack's required
        standard fields are actually mapped, not how curated a space is
        (.design/asset_semantic_space_harness_operating_model.md §9).
        Shared by admin_list_packs and admin_get_deployment_status so both
        views agree."""
        registry = pack_registry
        pack_manifest = next(
            (p for p in registry.list_packs() if p.pack_id == deployment.pack_id), None
        )
        required_fields = [
            sf.field_id for sf in (pack_manifest.standard_fields if pack_manifest else [])
            if sf.required
        ]
        if pack_manifest is None:
            enterprise_pack = _ep_store.get(deployment.pack_id)
            if enterprise_pack is not None:
                required_fields.extend(field.field_id for field in enterprise_pack.draft.fields)
        if deployment.extension_layer_id:
            layer = _ep_store.get_extension(deployment.extension_layer_id)
            if layer is None or layer.state != _ExtensionLayerState.active:
                return 0.0, "incomplete", ["选用的扩建层不可用或已停用。"]
            # Additions are the only incremental mapping work.  Extension
            # fields are intentionally required once the layer is deployed;
            # optionality can be introduced with a future field metadata flag.
            required_fields.extend(field.field_id for field in layer.draft.fields)
        if deployment.semantic_space_ids:
            spaces = [
                s for sid in deployment.semantic_space_ids
                if (s := _profile_store.get_space(sid)) is not None
            ]
            unavailable_ids = [
                sid for sid in deployment.semantic_space_ids
                if _profile_store.get_space(sid) is None
            ]
            if unavailable_ids:
                return (
                    0.0,
                    "incomplete",
                    [f"绑定语义空间已删除：{', '.join(unavailable_ids)}"],
                )
            return _mapping_store.compute_coverage_from_spaces(
                deployment.deployment_id, required_fields, spaces
            )
        return _mapping_store.compute_coverage(deployment.deployment_id, required_fields)

    def _active_extension_base(
        enterprise_pack: Any,
        data_source_id: str,
        semantic_space_ids: list[str],
    ) -> tuple[DeploymentInstance | None, str | None]:
        """Resolve the exact active official deployment required by a delta."""
        if enterprise_pack is None or not enterprise_pack.base_pack_id:
            return None, None
        expected_spaces = set(semantic_space_ids)
        candidates = [
            deployment
            for deployment in _mapping_store.list_deployments(enterprise_pack.base_pack_id)
            if deployment.pack_version == enterprise_pack.base_pack_version
            and deployment.data_source_id == data_source_id
            and deployment.is_active
            and set(deployment.semantic_space_ids) == expected_spaces
        ]
        if candidates:
            return candidates[0], None
        return None, (
            f"扩展包依赖官方领域包 {enterprise_pack.base_pack_id} "
            f"v{enterprise_pack.base_pack_version} 在当前数据源和语义空间中已启用的部署。"
        )

    def _get_pack_entry(pack_id: str) -> tuple[Any, Path] | None:
        return next(
            (
                (manifest, pack_dir)
                for manifest, pack_dir in pack_registry.list_enabled_pack_entries()
                if manifest.pack_id == pack_id
            ),
            None,
        )

    def _load_pack_content(pack_id: str) -> tuple[Any, Path, dict[str, Any]]:
        entry = _get_pack_entry(pack_id)
        if entry is None:
            raise KeyError(f"Pack '{pack_id}' not found.")
        manifest, pack_dir = entry
        semantic_asset = next(
            (asset for asset in manifest.assets if asset.asset_type == "semantic"),
            None,
        )
        raw: dict[str, Any] = {}
        if semantic_asset is not None:
            loaded = yaml.safe_load((pack_dir / semantic_asset.path).read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
        return manifest, pack_dir, raw

    def _preview_pack_archive(filename: str, content: bytes) -> tuple[dict[str, Any], Path, Any, Any]:
        if len(content) > 20 * 1024 * 1024:
            raise ValueError("领域包文件不能超过 20 MB。")
        if not content:
            raise ValueError("领域包文件为空。")
        temp_dir = tempfile.TemporaryDirectory(prefix="sqbi-pack-import-")
        try:
            pack_root = extract_pack(BytesIO(content), Path(temp_dir.name))
            issues = validate_pack(pack_root)
            if issues:
                raise ValueError("；".join(issues))
            manifest = load_manifest(pack_root)
            semantic_asset = next(
                (asset for asset in manifest.assets if asset.asset_type == "semantic"),
                None,
            )
            raw: dict[str, Any] = {}
            if semantic_asset is not None:
                loaded = yaml.safe_load((pack_root / semantic_asset.path).read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    raw = loaded
            existing = _get_pack_entry(manifest.pack_id)
            conflict = None
            if existing is not None:
                conflict = (
                    f"领域包 ID“{manifest.pack_id}”已存在（当前版本 {existing[0].version}）。"
                    "当前版本暂不允许覆盖安装。"
                )
            preview = {
                "filename": filename,
                "pack_id": manifest.pack_id,
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description or "",
                "author": manifest.author or "",
                "tags": manifest.tags,
                "standard_field_count": len(manifest.standard_fields),
                "metric_count": len(raw.get("metrics") or []),
                "skill_count": len(raw.get("skills") or []),
                "report_count": len(raw.get("reports") or []),
                "can_import": conflict is None,
                "conflict": conflict,
                "warnings": ["导入后不会自动关联数据源、字段映射或激活状态。"],
            }
            return preview, pack_root, manifest, temp_dir
        except Exception:
            temp_dir.cleanup()
            raise

    def _pack_logical_metrics(
        pack_id: str, data_source_id: str
    ) -> list[LogicalMetricDefinition]:
        manifest, _pack_dir, raw = _load_pack_content(pack_id)
        result: list[LogicalMetricDefinition] = []
        for metric in raw.get("metrics") or []:
            logical = metric.get("logical_formula")
            if not isinstance(logical, dict) or not logical.get("expression"):
                continue
            result.append(LogicalMetricDefinition(
                metric_code=str(metric.get("metric_code")),
                name=str(metric.get("name") or metric.get("metric_code")),
                definition=str(metric.get("definition") or ""),
                logical_formula=LogicalMetricFormula(
                    expression=str(logical["expression"]),
                    referenced_standard_fields=list(
                        logical.get("referenced_standard_fields") or []
                    ),
                    filters=list(logical.get("filters") or []),
                    time_field=(
                        str(logical["time_field"])
                        if logical.get("time_field") is not None
                        else None
                    ),
                ),
                data_source_id=data_source_id,
                owner=str(metric.get("owner") or manifest.author or "system"),
                version=manifest.version,
                synonyms=list(metric.get("synonyms") or []),
            ))
        return result

    def _seed_verified_pack_mappings(
        deployment: DeploymentInstance,
        pack_dir: Path,
        manifest: Any,
        allowed_tables: set[str] | None,
        catalog_columns: set[tuple[str, str]],
    ) -> int:
        mapping_asset = next(
            (asset for asset in manifest.assets if asset.asset_type == "field_mappings"),
            None,
        )
        if mapping_asset is None:
            return 0
        loaded = yaml.safe_load((pack_dir / mapping_asset.path).read_text(encoding="utf-8")) or {}
        existing = _mapping_store.get_mappings_dict_by_deployment(deployment.deployment_id)
        allowed_upper = {table.upper() for table in allowed_tables} if allowed_tables else None
        count = 0
        for item in loaded.get("mappings") or []:
            field_id = str(item.get("standard_field_id") or "")
            table = str(item.get("physical_table") or "").upper()
            column = str(item.get("physical_column") or "").upper()
            if not field_id or field_id in existing:
                continue
            if (table, column) not in catalog_columns:
                continue
            if allowed_upper is not None and table not in allowed_upper:
                continue
            _mapping_store.upsert(FieldMapping(
                mapping_id=f"map_{uuid4().hex[:12]}",
                pack_id=deployment.pack_id,
                standard_field_id=field_id,
                data_source_id=deployment.data_source_id,
                physical_table=table,
                physical_column=column,
                confidence=float(item.get("confidence", 1.0)),
                source="auto",
                status="active",
                deployment_id=deployment.deployment_id,
                created_by="official_pack",
                confirmed_by="official_pack",
                confirmed_at=datetime.now(UTC),
            ))
            count += 1
        return count

    def _verified_pack_candidates(
        pack_dir: Path,
        manifest: Any,
        catalog_columns: set[tuple[str, str]],
    ) -> dict[str, CandidateMapping]:
        mapping_asset = next(
            (asset for asset in manifest.assets if asset.asset_type == "field_mappings"),
            None,
        )
        if mapping_asset is None:
            return {}
        loaded = yaml.safe_load((pack_dir / mapping_asset.path).read_text(encoding="utf-8")) or {}
        result: dict[str, CandidateMapping] = {}
        for item in loaded.get("mappings") or []:
            field_id = str(item.get("standard_field_id") or "")
            table = str(item.get("physical_table") or "").upper()
            column = str(item.get("physical_column") or "").upper()
            if not field_id or (table, column) not in catalog_columns:
                continue
            result[field_id] = CandidateMapping(
                physical_table=table,
                physical_column=column,
                confidence=float(item.get("confidence", 1.0)),
                reason=str(item.get("notes") or "领域包内置并验证过的默认映射。"),
                evidence=MappingEvidence(
                    name_similarity=1.0,
                    business_name_similarity=1.0,
                ),
            )
        return result

    @app.get("/api/v1/admin/packs/{pack_id}/content", response_model=None)
    def admin_get_pack_content(pack_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            manifest, _pack_dir, raw = _load_pack_content(pack_id)
            return _response({
                "pack_id": manifest.pack_id,
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "standard_fields": [field.model_dump(mode="json") for field in manifest.standard_fields],
                "fields": list(raw.get("fields") or []),
                "metrics": list(raw.get("metrics") or []),
                "skills": list(raw.get("skills") or []),
                "reports": list(raw.get("reports") or []),
            })
        except KeyError as exc:
            return _error_response(404, ErrorCode.NOT_FOUND, str(exc))

    @app.post("/api/v1/admin/packs/import/preview", response_model=None)
    async def admin_preview_pack_import(request: Request) -> Any:
        from fastapi import UploadFile

        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            form = await request.form()
            file: UploadFile = form["file"]  # type: ignore[assignment]
            content = await file.read()
            preview, _pack_root, _manifest, temp_dir = _preview_pack_archive(
                file.filename or "domain-pack.sqbipack", content
            )
            temp_dir.cleanup()
            return _response(preview)
        except ValueError as exc:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.post("/api/v1/admin/packs/import", response_model=None)
    async def admin_import_pack(request: Request) -> Any:
        from fastapi import UploadFile

        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        temp_dir: Any | None = None
        try:
            form = await request.form()
            file: UploadFile = form["file"]  # type: ignore[assignment]
            content = await file.read()
            preview, pack_root, _manifest, temp_dir = _preview_pack_archive(
                file.filename or "domain-pack.sqbipack", content
            )
            if not preview["can_import"]:
                return _error_response(409, ErrorCode.CONFLICT, str(preview["conflict"]))
            installed_root = install_extracted_pack(pack_root, imported_packs_root)
            imported_manifest = load_manifest(installed_root)
            result = pack_registry.install(imported_manifest, installed_root)
            if not result.success:
                return _error_response(
                    400,
                    ErrorCode.VALIDATION_ERROR,
                    "；".join(result.errors) or "领域包安装失败。",
                )
            return _response({**preview, "installed": True})
        except FileExistsError as exc:
            return _error_response(409, ErrorCode.CONFLICT, str(exc))
        except ValueError as exc:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()

    @app.get("/api/v1/admin/packs", response_model=None)
    def admin_list_packs(request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        registry = pack_registry
        packs = registry.list_packs()
        deployments_by_pack = {}
        for dep in _mapping_store.list_deployments():
            deployments_by_pack.setdefault(dep.pack_id, []).append(dep)
        result = []
        for p in packs:
            try:
                _manifest, _pack_dir, pack_raw = _load_pack_content(p.pack_id)
            except KeyError:
                pack_raw = {}
            deployment_items = []
            for d in deployments_by_pack.get(p.pack_id, []):
                coverage, status, _blocking = _compute_deployment_readiness(d)
                resolved_spaces = [
                    space for sid in d.semantic_space_ids
                    if (space := _profile_store.get_space(sid)) is not None
                ]
                unavailable_ids = [
                    sid for sid in d.semantic_space_ids
                    if _profile_store.get_space(sid) is None
                ]
                deployment_items.append(DeploymentListItem(
                    deployment_id=d.deployment_id,
                    data_source_id=d.data_source_id,
                    validation_status=status,
                    coverage=coverage,
                    semantic_space_ids=d.semantic_space_ids,
                    semantic_space_names=[space.name for space in resolved_spaces],
                    unavailable_semantic_space_ids=unavailable_ids,
                    binding_status="unavailable" if unavailable_ids else "available",
                    is_active=d.is_active,
                ))
            result.append(PackWithDeployments(
                pack_id=p.pack_id,
                pack_version=p.version,
                name=p.name,
                description=p.description or "",
                author=p.author or "",
                tags=p.tags,
                distribution_source=(
                    "imported"
                    if _get_pack_entry(p.pack_id)
                    and imported_packs_root in _get_pack_entry(p.pack_id)[1].parents
                    else "built_in"
                ),
                standard_field_count=len(p.standard_fields),
                metric_count=len(pack_raw.get("metrics") or []),
                skill_count=len(pack_raw.get("skills") or []),
                report_count=len(pack_raw.get("reports") or []),
                deployments=deployment_items,
            ))
        return _response([r.model_dump(mode="json") for r in result])

    def _resolve_or_create_implicit_space(
        data_source_id: str,
        standard_fields: list[PackStandardField] | None = None,
        override_tables: list[str] | None = None,
        pack_name: str | None = None,
    ) -> tuple[list[str], str | None]:
        """Resolve semantic_space_ids for a deployment request that didn't
        specify any (P1: pack-first mounting shouldn't require a manual
        semantic-space-creation step first — see
        .design/asset_semantic_space_harness_operating_model.md §2.3).

        - An explicit ``override_tables`` selection always creates a dedicated
          pack-specific space, so unrelated existing spaces are never reused.
        - Exactly one existing managed space: reuse it only when there is no
          explicit pack-aware table selection.
        - Zero existing spaces: auto-create one, scoped to a pack-aware
          candidate recommendation rather than the whole connection (P1
          remainder: smart candidate-scope recommendation). ``override_tables``
          lets an admin who reviewed GET .../deployments/recommend-scope
          supply their own confirmed table list instead.
        - More than one existing space: refuse to guess — a mixed-domain
          connection needs an explicit choice, which is exactly the
          ambiguity semantic spaces exist to prevent.

        Returns (semantic_space_ids, auto_created_space_id_or_None).
        Raises ValueError if the caller must disambiguate explicitly.
        """
        existing = _profile_store.list_managed_spaces(data_source_id)
        # An explicit table override comes from the pack-aware preview. It is
        # a request for a dedicated pack scope, even when unrelated managed
        # spaces already exist on the same connection.
        if override_tables is None:
            if len(existing) == 1:
                return [existing[0].space_id], None
            if len(existing) > 1:
                raise ValueError(
                    f"数据源 '{data_source_id}' 存在 {len(existing)} 个语义空间，"
                    "请显式指定 semantic_space_ids。"
                )

        catalog_tables = _profile_store.list_catalog_tables(data_source_id)

        if override_tables is not None:
            valid_names = {t.table_name for t in catalog_tables}
            initial_tables = [t for t in override_tables if t in valid_names]
        else:
            candidates = recommend_scope_for_pack(standard_fields or [], catalog_tables)
            initial_tables = [c.table_name for c in candidates if c.tier == "recommended"]
            if not initial_tables:
                # Safety net: never silently create an empty space just
                # because the pack's fields don't match anything strongly
                # and every table landed in "ambiguous".
                from sq_bi_contracts.semantic_profile import TableRecommendation

                initial_tables = [
                    t.table_name for t in catalog_tables
                    if not t.excluded and t.classification != TableRecommendation.not_relevant
                ]

        space = _profile_store.create_space(
            data_source_id,
            name=f"{pack_name or data_source_id} · 自动适配",
            description=(
                f"系统挂载“{pack_name}”时自动创建的领域范围，覆盖该扩展包推荐相关的表。"
                if pack_name
                else "系统挂载扩展包时自动创建的领域范围，覆盖该扩展包推荐相关的表。"
            ),
            initial_tables=initial_tables,
        )
        return [space.space_id], space.space_id

    @app.get("/api/v1/admin/deployments/recommend-scope", response_model=None)
    def admin_recommend_scope(pack_id: str, data_source_id: str, request: Request) -> Any:
        """Preview the pack-aware candidate scope for a data source that has
        no semantic spaces yet, before an implicit default space is created
        (P1 remainder: smart candidate-scope recommendation)."""
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        registry = pack_registry
        pack_manifest = next((p for p in registry.list_packs() if p.pack_id == pack_id), None)
        if pack_manifest is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"Pack '{pack_id}' not found.")
        catalog_tables = _profile_store.list_catalog_tables(data_source_id)
        candidates = recommend_scope_for_pack(pack_manifest.standard_fields, catalog_tables)
        entry = _get_pack_entry(pack_id)
        verified_tables: set[str] = set()
        if entry is not None:
            manifest, pack_dir = entry
            mapping_asset = next(
                (asset for asset in manifest.assets if asset.asset_type == "field_mappings"),
                None,
            )
            if mapping_asset is not None:
                raw_mappings = yaml.safe_load(
                    (pack_dir / mapping_asset.path).read_text(encoding="utf-8")
                ) or {}
                verified_tables = {
                    str(item.get("physical_table") or "").upper()
                    for item in raw_mappings.get("mappings") or []
                    if item.get("physical_table")
                }
        available_verified = verified_tables & {
            table.table_name.upper() for table in catalog_tables
        }
        if available_verified:
            candidates = [
                ScopeCandidateTable(
                    table_name=table.table_name,
                    tier=(
                        "recommended"
                        if table.table_name.upper() in available_verified
                        else "excluded"
                    ),
                    matched_field_ids=(
                        [
                            field.field_id
                            for field in pack_manifest.standard_fields
                            if any(
                                str(item.get("standard_field_id")) == field.field_id
                                and str(item.get("physical_table") or "").upper()
                                == table.table_name.upper()
                                for item in raw_mappings.get("mappings") or []
                            )
                        ]
                        if table.table_name.upper() in available_verified
                        else []
                    ),
                    reason=(
                        "领域包内置并校验过的默认字段映射表。"
                        if table.table_name.upper() in available_verified
                        else "未被当前领域包的校验映射引用。"
                    ),
                )
                for table in catalog_tables
            ]
        return _response([c.model_dump(mode="json") for c in candidates])

    @app.post("/api/v1/admin/deployments", response_model=None)
    def admin_create_deployment(body: CreateDeploymentRequest, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        registry = pack_registry
        try:
            pack_entry = _get_pack_entry(body.pack_id)
            enterprise_pack = _ep_store.get(body.pack_id) if pack_entry is None else None
            if pack_entry is None and enterprise_pack is None:
                return _error_response(404, ErrorCode.NOT_FOUND, f"Pack '{body.pack_id}' not found.")
            pack_manifest = pack_entry[0] if pack_entry else None
            pack_dir = pack_entry[1] if pack_entry else None
            pack_version = pack_manifest.version if pack_manifest else enterprise_pack.version
            selected_extension: _PackExtensionLayer | None = None
            if body.extension_layer_id:
                selected_extension = _ep_store.get_extension(body.extension_layer_id)
                if selected_extension is None or selected_extension.base_pack_id != body.pack_id:
                    return _error_response(400, ErrorCode.VALIDATION_ERROR, "扩建层不属于当前领域包。")
                if selected_extension.state != _ExtensionLayerState.active:
                    return _error_response(409, ErrorCode.CONFLICT, "扩建层尚未发布启用，不能适配语义空间。")
                pack_version = f"{pack_version}+{selected_extension.version}"
            semantic_space_ids = list(body.semantic_space_ids)
            auto_created_space_id: str | None = None
            if not semantic_space_ids:
                try:
                    implicit_fields = pack_manifest.standard_fields if pack_manifest else [
                        PackStandardField(
                            field_id=field.field_id,
                            business_name=field.business_name,
                            data_type=field.data_type,
                            description=field.description,
                            required=True,
                        )
                        for field in enterprise_pack.draft.fields
                    ]
                    semantic_space_ids, auto_created_space_id = _resolve_or_create_implicit_space(
                        body.data_source_id,
                        standard_fields=implicit_fields,
                        override_tables=body.implicit_space_tables,
                        pack_name=pack_manifest.name if pack_manifest else enterprise_pack.name,
                    )
                except ValueError as exc:
                    return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))
            base_deployment, base_blocking = _active_extension_base(
                enterprise_pack, body.data_source_id, semantic_space_ids
            )
            if base_blocking:
                return _error_response(
                    409, ErrorCode.CONFLICT, base_blocking,
                    {"base_pack_id": enterprise_pack.base_pack_id,
                     "base_pack_version": enterprise_pack.base_pack_version},
                )
            deployment = _mapping_store.get_or_create_deployment(
                pack_id=body.pack_id,
                pack_version=pack_version,
                data_source_id=body.data_source_id,
                semantic_space_ids=semantic_space_ids,
                extension_layer_id=body.extension_layer_id,
            )
            if selected_extension is not None:
                base_candidates = [
                    item for item in _mapping_store.list_deployments(body.pack_id)
                    if item.extension_layer_id is None
                    and item.data_source_id == body.data_source_id
                    and item.is_active
                    and set(item.semantic_space_ids) == set(semantic_space_ids)
                ]
                if base_candidates:
                    base_deployment = base_candidates[0]
                else:
                    return _error_response(
                        409,
                        ErrorCode.CONFLICT,
                        "扩建层需要当前数据源和语义空间中已激活的基础领域包部署。",
                    )
            reused_base_mappings = (
                _mapping_store.reuse_deployment_mappings(
                    base_deployment.deployment_id,
                    deployment.deployment_id,
                    deployment.pack_id,
                )
                if base_deployment is not None
                else 0
            )
            std_fields_dict = {
                sf.field_id: sf
                for sf in (pack_manifest.standard_fields if pack_manifest else [])
            }
            if enterprise_pack is not None:
                std_fields_dict.update({
                    field.field_id: PackStandardField(
                        field_id=field.field_id,
                        business_name=field.business_name,
                        data_type=field.data_type,
                        description=field.description,
                        required=True,
                    )
                    for field in enterprise_pack.draft.fields
                })
            if selected_extension is not None:
                std_fields_dict.update({
                    field.field_id: PackStandardField(
                        field_id=field.field_id,
                        business_name=field.business_name,
                        data_type=field.data_type,
                        description=field.description,
                        required=True,
                    )
                    for field in selected_extension.draft.fields
                })
            # When the deployment is bound to specific semantic spaces, scope
            # matching to their adopted tables rather than the whole connection.
            allowed_tables: set[str] | None = None
            if deployment.semantic_space_ids:
                allowed_tables = set()
                for sid in deployment.semantic_space_ids:
                    space = _profile_store.get_space(sid)
                    if space:
                        allowed_tables.update(e.physical_table for e in space.entities)
            catalog_tables = _profile_store.list_catalog_tables(body.data_source_id)
            catalog_columns = {
                (table.table_name.upper(), column.column_name.upper())
                for table in catalog_tables
                for column in table.columns
            }
            selected_catalog = {
                table.table_name: {column.column_name for column in table.columns}
                for table in catalog_tables
                if not table.excluded
            }
            seeded_count = (
                _seed_verified_pack_mappings(
                    deployment,
                    pack_dir,
                    pack_manifest,
                    allowed_tables,
                    catalog_columns,
                )
                if pack_manifest is not None and pack_dir is not None
                else 0
            )
            trigger_resp = _mounting_pipeline.trigger(
                MountTriggerRequest(
                    pack_id=body.pack_id,
                    data_source_id=body.data_source_id,
                    deployment_id=deployment.deployment_id,
                ),
                standard_fields=std_fields_dict,
                live_catalog={},
                semantic_catalog=selected_catalog,
                logical_metrics=(
                    _pack_logical_metrics(body.pack_id, body.data_source_id)
                    if pack_manifest is not None
                    else []
                ),
                allowed_tables=allowed_tables,
                preferred_candidates=(
                    _verified_pack_candidates(pack_dir, pack_manifest, catalog_columns)
                    if pack_manifest is not None and pack_dir is not None
                    else {}
                ),
            )
            _mapping_store.replace_pending_requests(
                deployment.deployment_id, trigger_resp.pending
            )
            deployment = _mapping_store.get_deployment(deployment.deployment_id) or deployment
            return _response({
                "deployment": deployment.model_dump(mode="json"),
                "auto_mapped_count": seeded_count + len(trigger_resp.auto_mapped) + reused_base_mappings,
                "reused_base_mapping_count": reused_base_mappings,
                "pending": [p.model_dump(mode="json") for p in trigger_resp.pending],
                "errors": trigger_resp.errors,
                "auto_created_semantic_space_id": auto_created_space_id,
            })
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.get("/api/v1/admin/deployments/{deployment_id}/pending", response_model=None)
    def admin_get_pending(deployment_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        deployment = _mapping_store.get_deployment(deployment_id)
        if deployment is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"Deployment '{deployment_id}' not found.")
        pending_mappings = _mapping_store.list_pending_requests(deployment_id)
        return _response([m.model_dump(mode="json") for m in pending_mappings])

    @app.post(
        "/api/v1/admin/deployments/{deployment_id}/mappings/{standard_field_id}/remap",
        response_model=None,
    )
    def admin_prepare_remap(
        deployment_id: str, standard_field_id: str, request: Request
    ) -> Any:
        """Build a fresh, editable candidate set for an existing mapping.

        Preparing a change is read-only for the deployed mapping. The current
        mapping is only replaced after the administrator confirms a candidate.
        """
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        deployment = _mapping_store.get_deployment(deployment_id)
        if deployment is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"Deployment '{deployment_id}' not found.")
        pack_entry = _get_pack_entry(deployment.pack_id)
        if pack_entry is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"Pack '{deployment.pack_id}' not found.")
        pack_manifest, _pack_dir = pack_entry
        standard_field = next(
            (field for field in pack_manifest.standard_fields if field.field_id == standard_field_id),
            None,
        )
        if standard_field is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"Standard field '{standard_field_id}' not found.")
        if standard_field_id not in _mapping_store.get_mappings_dict_by_deployment(deployment_id):
            return _error_response(409, ErrorCode.CONFLICT, "Only confirmed mappings can be modified.")

        allowed_tables: set[str] | None = None
        if deployment.semantic_space_ids:
            allowed_tables = {
                entity.physical_table
                for sid in deployment.semantic_space_ids
                if (space := _profile_store.get_space(sid)) is not None
                for entity in space.entities
            }
        catalog_tables = _profile_store.list_catalog_tables(deployment.data_source_id)
        selected_catalog = {
            table.table_name: {column.column_name for column in table.columns}
            for table in catalog_tables
            if not table.excluded
        }
        trigger = _mounting_pipeline.trigger(
            MountTriggerRequest(
                pack_id=deployment.pack_id,
                data_source_id=deployment.data_source_id,
                deployment_id=deployment_id,
            ),
            standard_fields={standard_field_id: standard_field},
            live_catalog={},
            semantic_catalog=selected_catalog,
            logical_metrics=_pack_logical_metrics(deployment.pack_id, deployment.data_source_id),
            allowed_tables=allowed_tables,
            force_pending_fields={standard_field_id},
        )
        pending = next(
            (item for item in trigger.pending if item.standard_field_id == standard_field_id),
            None,
        )
        if pending is None:
            return _error_response(
                422,
                ErrorCode.VALIDATION_ERROR,
                "未能为该字段生成可修改的候选，请检查语义空间范围后重试。",
            )
        _mapping_store.upsert_pending_request(deployment_id, pending)
        return _response(pending.model_dump(mode="json"))

    @app.post("/api/v1/admin/deployments/{deployment_id}/confirm", response_model=None)
    def admin_confirm_mapping(deployment_id: str, body: ConfirmationRequest, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        deployment = _mapping_store.get_deployment(deployment_id)
        if deployment is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"Deployment '{deployment_id}' not found.")
        try:
            pending_item = _mapping_store.get_pending_request(
                deployment_id, body.mapping_request_id
            )
            if pending_item is None:
                return _error_response(404, ErrorCode.NOT_FOUND, f"Pending mapping '{body.mapping_request_id}' not found.")
            existing_mapping = _mapping_store.get_mappings_dict_by_deployment(deployment_id).get(
                body.standard_field_id
            )
            body_with_dep = body.model_copy(update={"deployment_id": deployment_id})
            if body.physical_table and body.physical_column:
                allowed_pairs = {
                    (field.physical_table.upper(), field.physical_column.upper())
                    for sid in deployment.semantic_space_ids
                    if (space := _profile_store.get_space(sid)) is not None
                    for entity in space.entities
                    for field in entity.fields
                }
                requested_pair = (
                    body.physical_table.upper(), body.physical_column.upper()
                )
                if allowed_pairs and requested_pair not in allowed_pairs:
                    return _error_response(
                        400,
                        ErrorCode.VALIDATION_ERROR,
                        "手动选择的物理字段不在当前绑定语义空间内。",
                    )
                mapping = _mounting_pipeline.confirm_mapping(
                    pack_id=deployment.pack_id,
                    data_source_id=deployment.data_source_id,
                    standard_field_id=body.standard_field_id,
                    physical_table=body.physical_table,
                    physical_column=body.physical_column,
                    deployment_id=deployment_id,
                    confirmed_by=body.confirmed_by,
                )
            else:
                if body.candidate_scope == "scanned_catalog":
                    if len(deployment.semantic_space_ids) != 1:
                        return _error_response(
                            400,
                            ErrorCode.VALIDATION_ERROR,
                            "扩展候选需要部署只绑定一个语义空间。",
                        )
                    candidate_index = body.chosen_candidate_index or 0
                    if candidate_index >= len(pending_item.outside_scope_candidates):
                        return _error_response(
                            400,
                            ErrorCode.VALIDATION_ERROR,
                            "所选扫描候选不存在或已过期。",
                        )
                    outside_candidate = pending_item.outside_scope_candidates[candidate_index]
                    _profile_store.add_catalog_table_to_space(
                        deployment.semantic_space_ids[0], outside_candidate.physical_table
                    )
                mapping = _mounting_pipeline.confirm(body_with_dep, pending_item)
            if existing_mapping is not None:
                _mapping_store.mark_smoke_result(deployment_id, passed=False)
                _mapping_store.deactivate_deployment(deployment_id)
            _mapping_store.delete_pending_request(deployment_id, body.mapping_request_id)
            return _response(mapping.model_dump(mode="json"))
        except (ValueError, IndexError) as exc:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.post("/api/v1/admin/deployments/{deployment_id}/smoke-test", response_model=None)
    def admin_run_smoke_test(deployment_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        deployment = _mapping_store.get_deployment(deployment_id)
        if deployment is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"Deployment '{deployment_id}' not found.")
        try:
            pack_entry = _get_pack_entry(deployment.pack_id)
            test_metrics: list[LogicalMetricDefinition] = []
            enterprise_metrics: list[Any] = []
            if pack_entry is not None:
                pack_manifest, _pack_dir = pack_entry
                std_fields = {sf.field_id: sf for sf in pack_manifest.standard_fields}
                if deployment.extension_layer_id:
                    layer = _ep_store.get_extension(deployment.extension_layer_id)
                    if layer is None or layer.state != _ExtensionLayerState.active:
                        return _error_response(409, ErrorCode.CONFLICT, "选用的扩建层不可用或已停用。")
                    std_fields.update({
                        field.field_id: PackStandardField(
                            field_id=field.field_id,
                            business_name=field.business_name,
                            data_type=field.data_type,
                            description=field.description,
                            required=True,
                        )
                        for field in layer.draft.fields
                    })
                active_mappings = _mapping_store.get_mappings_dict_by_deployment(deployment_id)
                test_metrics = [
                    metric
                    for metric in _pack_logical_metrics(deployment.pack_id, deployment.data_source_id)
                    if metric.logical_formula.referenced_standard_fields
                    and all(
                        field_id in active_mappings
                        for field_id in metric.logical_formula.referenced_standard_fields
                    )
                    and len({
                        active_mappings[field_id].physical_table
                        for field_id in metric.logical_formula.referenced_standard_fields
                    }) == 1
                ]
            else:
                # Enterprise pack (blank or official-extension): definitions
                # own no physical mappings, so only its own logical standard
                # fields participate — the pinned base's fields are covered
                # by the base's own deployment. Enterprise metrics currently
                # carry a free-form MetricFormula rather than a compiled
                # LogicalMetricFormula, so there is nothing DSL-compilable to
                # smoke test yet; this still turns the previous 404 into a
                # coherent (trivially empty) result instead of failing hard.
                enterprise_pack = _ep_store.get(deployment.pack_id)
                if enterprise_pack is None:
                    return _error_response(404, ErrorCode.NOT_FOUND, f"Pack '{deployment.pack_id}' not found.")
                std_fields = {
                    f.field_id: PackStandardField(
                        field_id=f.field_id,
                        business_name=f.business_name,
                        data_type=f.data_type,
                        description=f.description,
                    )
                    for f in enterprise_pack.draft.fields
                }
                enterprise_metrics = list(enterprise_pack.draft.metrics)
            if enterprise_metrics:
                ds_record = next(
                    (item for item in _load_datasources() if item["data_source_id"] == deployment.data_source_id),
                    None,
                )
                if ds_record is None:
                    return _error_response(404, ErrorCode.NOT_FOUND, f"Data source '{deployment.data_source_id}' not found.")
                from .connectors.factory import build_connector
                connector = build_connector(ds_record)
                metric_results: list[SmokeTestMetric] = []
                try:
                    schema_catalog = connector.get_schema_catalog()
                    dialect = {
                        "postgresql": "postgres", "postgres": "postgres",
                        "mysql": "mysql", "clickhouse": "clickhouse",
                    }.get(str(ds_record.get("database_type") or "oracle").lower(), "oracle")
                    for metric in enterprise_metrics:
                        item = SmokeTestMetric(metric_code=metric.metric_code, name=metric.name)
                        started = datetime.now(UTC)
                        try:
                            validation = validate_sql(
                                metric.formula.expression,
                                schema_catalog=schema_catalog,
                                dialect=dialect,
                            )
                            item.compiled = True
                            rows = connector.execute(validation.sql)
                            item.executed = True
                            item.row_count = len(rows or [])
                        except Exception as exc:  # noqa: BLE001
                            item.error = str(exc)
                        item.elapsed_ms = max(0, int((datetime.now(UTC) - started).total_seconds() * 1000))
                        metric_results.append(item)
                finally:
                    if hasattr(connector, "close"):
                        connector.close()
                result = SmokeTestResult(
                    pack_id=deployment.pack_id,
                    data_source_id=deployment.data_source_id,
                    deployment_id=deployment_id,
                    metrics=metric_results,
                    all_passed=bool(metric_results) and all(item.compiled and item.executed and not item.error for item in metric_results),
                    tested_at=datetime.now(UTC),
                )
                _mapping_store.mark_smoke_result(
                    deployment_id,
                    passed=result.all_passed,
                    result=result.model_dump(mode="json"),
                )
                return _response(result.model_dump(mode="json"))
            if not test_metrics:
                result = _mounting_pipeline.run_smoke_test(
                    pack_id=deployment.pack_id,
                    data_source_id=deployment.data_source_id,
                    standard_fields=std_fields,
                    test_metrics=[],
                    deployment_id=deployment_id,
                )
                _mapping_store.mark_smoke_result(
                    deployment_id,
                    passed=False,
                    result=result.model_dump(mode="json"),
                )
                return _response(result.model_dump(mode="json"))
            ds_record = next(
                (
                    item for item in _load_datasources()
                    if item["data_source_id"] == deployment.data_source_id
                ),
                None,
            )
            if ds_record is None:
                return _error_response(
                    404,
                    ErrorCode.NOT_FOUND,
                    f"Data source '{deployment.data_source_id}' not found.",
                )
            from .connectors.factory import build_connector
            connector = build_connector(ds_record)
            try:
                result = _mounting_pipeline.run_smoke_test(
                    pack_id=deployment.pack_id,
                    data_source_id=deployment.data_source_id,
                    standard_fields=std_fields,
                    test_metrics=test_metrics,
                    executor=connector,
                    deployment_id=deployment_id,
                )
            finally:
                if hasattr(connector, "close"):
                    connector.close()
            _mapping_store.mark_smoke_result(
                deployment_id,
                passed=result.all_passed,
                result=result.model_dump(mode="json"),
            )
            return _response(result.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.get("/api/v1/admin/deployments/{deployment_id}/status", response_model=None)
    def admin_get_deployment_status(deployment_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        deployment = _mapping_store.get_deployment(deployment_id)
        if deployment is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"Deployment '{deployment_id}' not found.")
        coverage, status, blocking = _compute_deployment_readiness(deployment)
        pack_entry = _get_pack_entry(deployment.pack_id)
        standard_fields = list(pack_entry[0].standard_fields) if pack_entry else []
        if pack_entry is None:
            enterprise_pack = _ep_store.get(deployment.pack_id)
            if enterprise_pack is not None:
                standard_fields.extend(
                    PackStandardField(
                        field_id=field.field_id,
                        business_name=field.business_name,
                        data_type=field.data_type,
                        description=field.description,
                        required=True,
                    )
                    for field in enterprise_pack.draft.fields
                )
        if deployment.extension_layer_id:
            layer = _ep_store.get_extension(deployment.extension_layer_id)
            if layer is not None:
                standard_fields.extend(
                    PackStandardField(
                        field_id=field.field_id,
                        business_name=field.business_name,
                        data_type=field.data_type,
                        description=field.description,
                        required=True,
                    )
                    for field in layer.draft.fields
                )
        mappings = list(
            _mapping_store.get_mappings_dict_by_deployment(deployment_id).values()
        )
        pending = _mapping_store.list_pending_requests(deployment_id)
        resolved_spaces = [
            space for sid in deployment.semantic_space_ids
            if (space := _profile_store.get_space(sid)) is not None
        ]
        unavailable_ids = [
            sid for sid in deployment.semantic_space_ids
            if _profile_store.get_space(sid) is None
        ]
        return _response({
            "deployment_id": deployment_id,
            "pack_id": deployment.pack_id,
            "data_source_id": deployment.data_source_id,
            "pack_version": deployment.pack_version,
            "validation_status": status,
            "is_ready": status == "ready",
            "coverage": coverage,
            "blocking_reasons": blocking,
            "total_standard_fields": len(standard_fields),
            "mapped_fields": len(mappings),
            "pending_fields": len(pending),
            "smoke_test": _mapping_store.get_smoke_result(deployment_id),
            "standard_fields": [field.model_dump(mode="json") for field in standard_fields],
            "mappings": [mapping.model_dump(mode="json") for mapping in mappings],
            "is_active": deployment.is_active,
            "activated_at": deployment.activated_at.isoformat() if deployment.activated_at else None,
            "activated_by": deployment.activated_by,
            "semantic_space_ids": deployment.semantic_space_ids,
            "semantic_space_names": [space.name for space in resolved_spaces],
            "unavailable_semantic_space_ids": unavailable_ids,
            "binding_status": "unavailable" if unavailable_ids else "available",
            "environment": deployment.environment,
            "extension_layer_id": deployment.extension_layer_id,
        })

    @app.post("/api/v1/admin/deployments/{deployment_id}/activate", response_model=None)
    def admin_activate_deployment(deployment_id: str, request: Request) -> Any:
        """Explicitly turn a deployment on. Independent from validation_status
        (P0: split validate/activate — see
        .design/asset_semantic_space_harness_operating_model.md §9/§11).
        Only allowed once validation_status == 'ready': all required fields
        mapped to confirmed in-space targets and the last smoke test passed."""
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        deployment = _mapping_store.get_deployment(deployment_id)
        if deployment is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"Deployment '{deployment_id}' not found.")
        enterprise_pack = _ep_store.get(deployment.pack_id)
        _base, base_blocking = _active_extension_base(
            enterprise_pack, deployment.data_source_id, deployment.semantic_space_ids
        )
        if base_blocking:
            return _error_response(409, ErrorCode.CONFLICT, base_blocking)
        _coverage, status, blocking = _compute_deployment_readiness(deployment)
        if status != "ready":
            return _error_response(
                400, ErrorCode.VALIDATION_ERROR,
                "Deployment is not ready for activation: " + "; ".join(blocking or ["validation incomplete"]),
            )
        updated = _mapping_store.activate_deployment(deployment_id, auth.user_id)
        if updated is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"Deployment '{deployment_id}' not found.")
        if enterprise_pack is not None:
            # Repository-backed surfaces (report generation, metric listings)
            # must see the pack's assets once it is live on a data source.
            try:
                from .pack_projection import project_pack_assets

                projection_repo = get_repository()
                if isinstance(projection_repo, SQLiteProductRepository):
                    project_pack_assets(projection_repo, enterprise_pack, updated.data_source_id)
            except Exception:  # noqa: BLE001 — activation must not fail on projection
                logger.warning(
                    "pack_projection.activate_failed",
                    extra={"pack_id": updated.pack_id, "deployment_id": deployment_id},
                    exc_info=True,
                )
        return _response(updated.model_dump(mode="json"))

    @app.post("/api/v1/admin/deployments/{deployment_id}/deactivate", response_model=None)
    def admin_deactivate_deployment(deployment_id: str, request: Request) -> Any:
        """Explicitly turn a deployment off. Always allowed regardless of
        validation_status — an admin may need to pull a pack offline even if
        its validation state has since degraded."""
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        updated = _mapping_store.deactivate_deployment(deployment_id)
        if updated is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"Deployment '{deployment_id}' not found.")
        if _ep_store.get(updated.pack_id) is not None:
            # Withdraw projected assets once the pack has no live deployment left.
            try:
                still_active = any(
                    item.is_active for item in _mapping_store.list_deployments(updated.pack_id)
                )
                if not still_active:
                    from .pack_projection import remove_pack_assets

                    projection_repo = get_repository()
                    if isinstance(projection_repo, SQLiteProductRepository):
                        remove_pack_assets(projection_repo, updated.pack_id)
            except Exception:  # noqa: BLE001 — deactivation must not fail on cleanup
                logger.warning(
                    "pack_projection.deactivate_cleanup_failed",
                    extra={"pack_id": updated.pack_id, "deployment_id": deployment_id},
                    exc_info=True,
                )
        return _response(updated.model_dump(mode="json"))

    @app.post("/api/v1/ai/conversation/interpret", response_model=None)
    def interpret_conversation_with_llm(request: ConversationInterpretRequest) -> Any:
        try:
            user_prompt = json.dumps(
                {
                    "user_id": request.user_id,
                    "current_text": request.current_text,
                    "pending_invocation": request.pending_invocation,
                },
                ensure_ascii=False,
                indent=2,
            )
            payload = parse_json_payload(llm_client.chat(CONVERSATION_INTERPRET_SYSTEM_PROMPT, user_prompt))
            return _response(
                {
                    "is_continuation": bool(payload.get("is_continuation")),
                    "confidence": float(payload.get("confidence") or 0),
                    "effective_text": str(payload.get("effective_text") or request.current_text),
                    "reason": str(payload.get("reason") or ""),
                }
            )
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    # ── Phase 4: Enterprise Domain Pack endpoints ────────────────────────────
    from .enterprise_pack_store import EnterprisePackStore as _EnterprisePackStore
    from .enterprise_pack_builder import EnterprisePackBuilder as _EnterprisePackBuilder
    from .pack_drafter import PackDrafter as _PackDrafter

    _ep_store_path = Path(config.storage_path) / "enterprise_packs.sqlite3"
    _ep_store = _EnterprisePackStore(_ep_store_path)
    _ep_builder = _EnterprisePackBuilder(_ep_store)

    def _domain_pack_base(
        base_pack_id: str, base_kind: str,
    ) -> tuple[str, _EnterprisePackDraft, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Resolve immutable base data without copying it into an extension.

        The returned tuple is (version, portable draft, raw metrics, raw
        skills, raw reports).  Official data is read from its manifest every
        time, while a standalone enterprise base uses its own draft.
        """
        if base_kind == "official":
            manifest, _pack_dir, raw = _load_pack_content(base_pack_id)
            draft = _EnterprisePackDraft(
                fields=[
                    {
                        "field_id": field.field_id,
                        "business_name": field.business_name,
                        "data_type": field.data_type,
                        "description": field.description,
                    }
                    for field in manifest.standard_fields
                ]
            )
            return (
                manifest.version, draft, list(raw.get("metrics") or []),
                list(raw.get("skills") or []), list(raw.get("reports") or []),
            )
        if base_kind == "enterprise":
            base = _ep_store.get(base_pack_id)
            if base is None or base.base_pack_id is not None:
                raise KeyError(f"Standalone enterprise base pack '{base_pack_id}' not found.")
            return (
                base.version, base.draft,
                [item.model_dump(mode="json") for item in base.draft.metrics],
                [item.model_dump(mode="json") for item in base.draft.skills],
                [item.model_dump(mode="json") for item in base.draft.reports],
            )
        raise ValueError("base_kind must be 'official' or 'enterprise'.")

    def _effective_domain_pack(
        base_pack_id: str, base_kind: str, *, include_inactive: bool = False,
    ) -> _EffectiveDomainPack:
        version, base_draft, raw_metrics, raw_skills, raw_reports = _domain_pack_base(
            base_pack_id, base_kind
        )
        layer = _ep_store.get_extension_for_base(base_pack_id)
        if layer is not None and (
            layer.base_kind != base_kind or layer.base_pack_version != version
        ):
            # A pinned layer is not silently rebound when its base changes.
            raise ValueError("Extension layer is pinned to a different base version.")
        apply_layer = bool(
            layer and (layer.state == _ExtensionLayerState.active or include_inactive)
        )
        delta = layer.draft if apply_layer and layer is not None else _EnterprisePackDraft()

        def _asset(asset_id: str, name: str, asset_type: str, source: str, definition: dict[str, Any]) -> _EffectiveDomainPackAsset:
            return _EffectiveDomainPackAsset(
                asset_id=asset_id, name=name, asset_type=asset_type, source=source,
                definition=definition,
            )

        base_fields = [
            _asset(item.field_id, item.business_name, "field", "base", item.model_dump(mode="json"))
            for item in base_draft.fields
        ]
        base_metrics = [
            _asset(str(item.get("metric_code")), str(item.get("name") or item.get("metric_code")), "metric", "base", item)
            for item in raw_metrics
        ]
        base_skills = [
            _asset(str(item.get("skill_id")), str(item.get("name") or item.get("skill_id")), "skill", "base", item)
            for item in raw_skills
        ]
        base_reports = [
            _asset(str(item.get("report_skill_id") or item.get("report_id")), str(item.get("name") or item.get("report_skill_id") or item.get("report_id")), "report", "base", item)
            for item in raw_reports
        ]
        return _EffectiveDomainPack(
            base_pack_id=base_pack_id, base_pack_version=version, base_kind=base_kind,
            extension_layer=layer,
            fields=base_fields + [
                _asset(item.field_id, item.business_name, "field", "extension", item.model_dump(mode="json"))
                for item in delta.fields
            ],
            metrics=base_metrics + [
                _asset(item.metric_code, item.name, "metric", "extension", item.model_dump(mode="json"))
                for item in delta.metrics
            ],
            skills=base_skills + [
                _asset(item.skill_id, item.name, "skill", "extension", item.model_dump(mode="json"))
                for item in delta.skills
            ],
            reports=base_reports + [
                _asset(item.report_id, item.name, "report", "extension", item.model_dump(mode="json"))
                for item in delta.reports
            ],
        )

    def _validate_extension_draft(layer: _PackExtensionLayer, draft: _EnterprisePackDraft) -> None:
        """Validate additive identities and same-layer/base dependencies."""
        base = _effective_domain_pack(layer.base_pack_id, layer.base_kind)
        base_ids = {
            "field": {item.asset_id for item in base.fields if item.source == "base"},
            "metric": {item.asset_id for item in base.metrics if item.source == "base"},
            "skill": {item.asset_id for item in base.skills if item.source == "base"},
            "report": {item.asset_id for item in base.reports if item.source == "base"},
        }
        delta_ids = {
            "field": {item.field_id for item in draft.fields},
            "metric": {item.metric_code for item in draft.metrics},
            "skill": {item.skill_id for item in draft.skills},
            "report": {item.report_id for item in draft.reports},
        }
        for asset_type, identifiers in delta_ids.items():
            conflict = identifiers & base_ids[asset_type]
            if conflict:
                raise ValueError(
                    f"Extension cannot override base {asset_type}: {', '.join(sorted(conflict))}"
                )
        field_ids = base_ids["field"] | delta_ids["field"]
        metric_ids = base_ids["metric"] | delta_ids["metric"]
        skill_ids = base_ids["skill"] | delta_ids["skill"]
        for skill in draft.skills:
            missing_metrics = set(skill_step_metric for step in skill.steps for skill_step_metric in step.metric_codes) - metric_ids
            missing_fields = set(field for step in skill.steps for field in step.dimension_field_ids) - field_ids
            if missing_metrics or missing_fields:
                raise ValueError(
                    f"Extension skill '{skill.skill_id}' has unresolved dependencies: "
                    + ", ".join(sorted(missing_metrics | missing_fields))
                )
        for report in draft.reports:
            missing = (set(report.metric_codes) - metric_ids) | (set(report.skill_ids) - skill_ids)
            if missing:
                raise ValueError(
                    f"Extension report '{report.report_id}' has unresolved dependencies: {', '.join(sorted(missing))}"
                )

    @app.get("/api/v1/admin/domain-packs/{base_pack_id}/extension-layer", response_model=None)
    def get_domain_pack_extension(base_pack_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        layer = _ep_store.get_extension_for_base(base_pack_id)
        if layer is None:
            return _response(None)
        return _response(layer.model_dump(mode="json"))

    @app.post("/api/v1/admin/domain-packs/{base_pack_id}/extension-layer", response_model=None)
    def create_or_open_domain_pack_extension(base_pack_id: str, body: dict, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            base_kind = str(body.get("base_kind") or "")
            version, _draft, _metrics, _skills, _reports = _domain_pack_base(base_pack_id, base_kind)
            layer = _ep_store.get_or_create_extension(
                base_pack_id=base_pack_id, base_pack_version=version,
                base_kind=base_kind, created_by=str(body.get("created_by") or auth.user_id),
            )
            return _response(layer.model_dump(mode="json"))
        except (KeyError, ValueError) as exc:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))

    @app.get("/api/v1/admin/domain-packs/{base_pack_id}/effective-content", response_model=None)
    def get_domain_pack_effective_content(base_pack_id: str, request: Request, base_kind: str | None = None) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            resolved_kind = base_kind or (
                "official" if _get_pack_entry(base_pack_id) is not None else "enterprise"
            )
            return _response(_effective_domain_pack(base_pack_id, resolved_kind).model_dump(mode="json"))
        except (KeyError, ValueError) as exc:
            return _error_response(404, ErrorCode.NOT_FOUND, str(exc))

    @app.put("/api/v1/admin/extension-layers/{extension_id}", response_model=None)
    def update_domain_pack_extension(extension_id: str, body: dict, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            layer = _ep_store.get_extension(extension_id)
            if layer is None:
                return _error_response(404, ErrorCode.NOT_FOUND, "Extension layer not found.")
            draft = _EnterprisePackDraft.model_validate(body.get("draft") or {})
            _validate_extension_draft(layer, draft)
            updated = _ep_store.update_extension_draft(extension_id, draft, updated_by=auth.user_id)
            return _response(updated.model_dump(mode="json"))
        except (KeyError, ValueError) as exc:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))

    @app.post("/api/v1/admin/extension-layers/{extension_id}/{action}", response_model=None)
    def transition_domain_pack_extension(extension_id: str, action: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            if action == "publish":
                result = _ep_store.publish_extension(extension_id, actor=auth.user_id)
            elif action == "deactivate":
                result = _ep_store.set_extension_state(extension_id, _ExtensionLayerState.inactive, actor=auth.user_id)
            elif action == "archive":
                result = _ep_store.set_extension_state(extension_id, _ExtensionLayerState.archived, actor=auth.user_id)
            elif action == "restore":
                result = _ep_store.set_extension_state(extension_id, _ExtensionLayerState.inactive, actor=auth.user_id)
            else:
                return _error_response(404, ErrorCode.NOT_FOUND, "Unknown extension action.")
            return _response(result.model_dump(mode="json"))
        except (KeyError, ValueError) as exc:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))

    @app.delete("/api/v1/admin/extension-layers/{extension_id}", response_model=None)
    def delete_domain_pack_extension(extension_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        active = [
            deployment.deployment_id for deployment in _mapping_store.list_deployments()
            if deployment.extension_layer_id == extension_id and deployment.is_active
        ]
        try:
            if not _ep_store.delete_extension(extension_id, active_deployment_ids=active):
                return _error_response(404, ErrorCode.NOT_FOUND, "Extension layer not found.")
            return _response({"deleted": True, "extension_id": extension_id})
        except ValueError as exc:
            return _error_response(409, ErrorCode.CONFLICT, str(exc))

    @app.get("/api/v1/admin/enterprise-packs", response_model=None)
    def list_enterprise_packs(request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            packs = _ep_store.list_base_packs()
            return _response([
                {
                    **pack.model_dump(mode="json"),
                    "deployments": [
                        DeploymentListItem(
                            deployment_id=deployment.deployment_id,
                            data_source_id=deployment.data_source_id,
                            validation_status=_compute_deployment_readiness(deployment)[1],
                            coverage=_compute_deployment_readiness(deployment)[0],
                            semantic_space_ids=deployment.semantic_space_ids,
                            semantic_space_names=[
                                space.name for space_id in deployment.semantic_space_ids
                                if (space := _profile_store.get_space(space_id)) is not None
                            ],
                            unavailable_semantic_space_ids=[
                                space_id for space_id in deployment.semantic_space_ids
                                if _profile_store.get_space(space_id) is None
                            ],
                            binding_status=(
                                "unavailable"
                                if any(_profile_store.get_space(space_id) is None for space_id in deployment.semantic_space_ids)
                                else "available"
                            ),
                            is_active=deployment.is_active,
                        ).model_dump(mode="json")
                        for deployment in _mapping_store.list_deployments(pack.pack_id)
                    ],
                    "extension_layer": (
                        layer.model_dump(mode="json")
                        if (layer := _ep_store.get_extension_for_base(pack.pack_id)) is not None
                        else None
                    ),
                }
                for pack in packs
            ])
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.get("/api/v1/admin/enterprise-packs/{pack_id}", response_model=None)
    def get_enterprise_pack(pack_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        pack = _ep_store.get(pack_id)
        if pack is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"Enterprise pack not found: {pack_id}")
        return _response(pack.model_dump(mode="json"))

    def _build_effective_pack_view(pack: _EnterprisePack) -> _EffectivePackView:
        """Read-only official base (pinned manifest) + editable enterprise
        delta, with per-asset provenance. Never mutates or copies the
        official source — the base lists are recomputed on every call from
        the live official registry (official-pack-extension-layer)."""
        base_fields: list[_EffectivePackAssetRef] = []
        base_metrics: list[_EffectivePackAssetRef] = []
        base_skills: list[_EffectivePackAssetRef] = []
        base_reports: list[_EffectivePackAssetRef] = []
        if pack.base_pack_id:
            try:
                manifest, _pack_dir, raw = _load_pack_content(pack.base_pack_id)
            except KeyError:
                manifest, raw = None, {}
            if manifest is not None:
                base_fields = [
                    _EffectivePackAssetRef(asset_id=sf.field_id, name=sf.business_name, source="official")
                    for sf in manifest.standard_fields
                ]
                base_metrics = [
                    _EffectivePackAssetRef(
                        asset_id=str(m.get("metric_code")),
                        name=str(m.get("name") or m.get("metric_code")),
                        source="official",
                    )
                    for m in raw.get("metrics") or []
                ]
                base_skills = [
                    _EffectivePackAssetRef(
                        asset_id=str(s.get("skill_id")),
                        name=str(s.get("name") or s.get("skill_id")),
                        source="official",
                    )
                    for s in raw.get("skills") or []
                ]
                base_reports = [
                    _EffectivePackAssetRef(
                        asset_id=str(r.get("report_skill_id") or r.get("report_id")),
                        name=str(r.get("name") or r.get("report_skill_id") or r.get("report_id")),
                        source="official",
                    )
                    for r in raw.get("reports") or []
                ]
        return _EffectivePackView(
            pack_id=pack.pack_id,
            base_pack_id=pack.base_pack_id,
            base_pack_version=pack.base_pack_version,
            base_standard_fields=base_fields,
            enterprise_standard_fields=[
                _EffectivePackAssetRef(asset_id=f.field_id, name=f.business_name, source="enterprise")
                for f in pack.draft.fields
            ],
            base_metrics=base_metrics,
            enterprise_metrics=[
                _EffectivePackAssetRef(asset_id=m.metric_code, name=m.name, source="enterprise")
                for m in pack.draft.metrics
            ],
            base_skills=base_skills,
            enterprise_skills=[
                _EffectivePackAssetRef(asset_id=s.skill_id, name=s.name, source="enterprise")
                for s in pack.draft.skills
            ],
            base_reports=base_reports,
            enterprise_reports=[
                _EffectivePackAssetRef(asset_id=r.report_id, name=r.name, source="enterprise")
                for r in pack.draft.reports
            ],
        )

    @app.get("/api/v1/admin/enterprise-packs/{pack_id}/effective", response_model=None)
    def get_enterprise_pack_effective(pack_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        pack = _ep_store.get(pack_id)
        if pack is None:
            return _error_response(404, ErrorCode.NOT_FOUND, f"Enterprise pack not found: {pack_id}")
        return _response(_build_effective_pack_view(pack).model_dump(mode="json"))

    @app.post("/api/v1/admin/enterprise-packs", response_model=None)
    def create_enterprise_pack(body: _CreateEnterprisePackRequest, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            official_manifest = None
            if body.mode.value == "extend_official":
                if not body.base_pack_id:
                    return _error_response(400, ErrorCode.VALIDATION_ERROR, "base_pack_id is required for extend_official.")
                registry = pack_registry
                if registry:
                    found = [m for m in registry.list_packs() if m.pack_id == body.base_pack_id]
                    official_manifest = found[0] if found else None
                if official_manifest is None:
                    return _error_response(400, ErrorCode.VALIDATION_ERROR, "Official base pack was not found.")
                if body.base_pack_version and body.base_pack_version != official_manifest.version:
                    return _error_response(400, ErrorCode.VALIDATION_ERROR, "The requested official base version is not available.")
            pack = _ep_builder.build(body, official_manifest=official_manifest)
            return _response(pack.model_dump(mode="json"))
        except ValueError as exc:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.put("/api/v1/admin/enterprise-packs/{pack_id}", response_model=None)
    def update_enterprise_pack(pack_id: str, body: dict, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            from sq_bi_contracts.enterprise_pack import EnterprisePackDraft as _Draft
            if "draft" in body:
                draft = _Draft.model_validate(body["draft"])
                pack = _ep_store.update_draft(pack_id, draft)
            else:
                pack = _ep_store.update_meta(
                    pack_id,
                    name=body.get("name"),
                    description=body.get("description"),
                    business_context=body.get("business_context"),
                )
            return _response(pack.model_dump(mode="json"))
        except (KeyError, ValueError) as exc:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.delete("/api/v1/admin/enterprise-packs/{pack_id}", response_model=None)
    def delete_enterprise_pack(pack_id: str, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            deployments = _mapping_store.list_deployments(pack_id)
            if deployments:
                return _error_response(
                    409,
                    ErrorCode.CONFLICT,
                    "该领域包仍存在语义空间适配实例，请先移除相关适配。",
                )
            if _ep_store.get_extension_for_base(pack_id) is not None:
                return _error_response(
                    409,
                    ErrorCode.CONFLICT,
                    "该领域包仍有扩建层，请先删除扩建层。",
                )
            _ep_store.delete(pack_id)
            return _response({"pack_id": pack_id, "deleted": True})
        except KeyError as exc:
            return _error_response(404, ErrorCode.NOT_FOUND, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.post("/api/v1/admin/enterprise-packs/draft", response_model=None)
    def draft_enterprise_pack(body: _PackDraftRequest, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            document_texts: list[str] = []
            if body.document_ids:
                try:
                    from .document_store import DocumentStore as _DS
                    doc_store = _DS(Path(config.storage_path) / "ds_documents")
                    for doc_id in body.document_ids:
                        text = doc_store.get_text(body.data_source_id, doc_id)
                        if text:
                            document_texts.append(text)
                except Exception:
                    pass

            drafter = _PackDrafter(
                llm_client=llm_client,
                profile_store_path=_profile_store_path,
            )
            result = drafter.draft(body.data_source_id, document_texts=document_texts)

            if body.pack_id:
                try:
                    _ep_store.update_draft(body.pack_id, result.draft)
                except Exception:
                    pass

            return _response(result.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.post("/api/v1/admin/domain-pack-authoring/suggest", response_model=None)
    def suggest_domain_pack_authoring(body: dict[str, Any], request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            scope = str(body.get("scope") or "all")
            if scope not in {"all", "fields", "metrics", "skills", "reports", "self_check"}:
                return _error_response(400, ErrorCode.VALIDATION_ERROR, "Unsupported authoring scope.")
            draft = _EnterprisePackDraft.model_validate(body.get("draft") or {})
            result = DomainPackAuthoringService(llm_client).suggest(
                scope=scope,
                name=str(body.get("name") or "").strip(),
                description=str(body.get("description") or "").strip(),
                business_context=str(body.get("business_context") or "").strip(),
                draft=draft,
                instruction=str(body.get("instruction") or "").strip(),
            )
            return _response(result)
        except ValueError as exc:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.post("/api/v1/admin/enterprise-packs/{pack_id}/publish", response_model=None)
    def publish_enterprise_pack(pack_id: str, body: _PublishPackRequest, request: Request) -> Any:
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            pack = _ep_store.publish(
                pack_id,
                version=body.version or None,
                published_by=body.published_by,
            )
            return _response(pack.model_dump(mode="json"))
        except (KeyError, ValueError) as exc:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    @app.post("/api/v1/admin/enterprise-packs/{pack_id}/fork", response_model=None)
    def fork_enterprise_pack(pack_id: str, request: Request) -> Any:
        """Fork a published pack to create a new editable draft version."""
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        try:
            pack = _ep_store.fork_for_edit(pack_id)
            return _response(pack.model_dump(mode="json"))
        except (KeyError, ValueError) as exc:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    # ── P3: Runtime asset projection (admin diagnostics) ─────────────────
    # Wires the existing AssetCatalog providers and RuntimeAssetResolver
    # (openspec/changes/runtime-asset-projection) into the running app so
    # admins can see, per request context, exactly which deployments'
    # assets are runtime-visible right now and why the rest are not.
    from .asset_catalog import AssetCatalog as _AssetCatalog
    from .asset_catalog import EnterprisePackAssetProvider as _EnterprisePackAssetProvider
    from .asset_catalog import ExtensionLayerAssetProvider as _ExtensionLayerAssetProvider
    from .asset_catalog import LegacyPersonalAssetProvider as _LegacyPersonalAssetProvider
    from .asset_catalog import OfficialPackAssetProvider as _OfficialPackAssetProvider
    from .runtime_asset_providers import FieldMappingDeploymentProvider as _FieldMappingDeploymentProvider
    from .runtime_asset_providers import StoredPersonalBindingProvider as _StoredPersonalBindingProvider
    from .runtime_asset_resolver import RuntimeAssetResolver as _RuntimeAssetResolver
    from .personal_asset_store import PersonalAssetStore as _PersonalAssetStore
    from sq_bi_contracts.runtime_projection import RuntimeRequestContext as _RuntimeRequestContext

    _runtime_catalog_providers: list[Any] = [
        _OfficialPackAssetProvider(pack_registry),
        _EnterprisePackAssetProvider(_ep_store),
        _ExtensionLayerAssetProvider(_ep_store),
    ]
    _runtime_catalog_repo = get_repository()
    if isinstance(_runtime_catalog_repo, SQLiteProductRepository):
        _runtime_catalog_providers.append(_LegacyPersonalAssetProvider(_runtime_catalog_repo))
    _runtime_asset_catalog = _AssetCatalog(_runtime_catalog_providers)
    _personal_store = _PersonalAssetStore(Path(config.storage_path) / "personal_assets.sqlite3")
    if isinstance(_runtime_catalog_repo, SQLiteProductRepository):
        _personal_store.backfill_from_repository(_runtime_catalog_repo)
    _runtime_deployment_provider = _FieldMappingDeploymentProvider(
        _mapping_store, pack_registry, _ep_store, _compute_deployment_readiness,
    )
    _runtime_asset_resolver = _RuntimeAssetResolver(
        _runtime_asset_catalog, _runtime_deployment_provider, _StoredPersonalBindingProvider(_personal_store),
    )

    @app.get("/api/v1/personal-assets/templates", response_model=None)
    def list_personal_asset_templates(data_source_id: str, request: Request, environment: str = "default") -> Any:
        """Runtime-eligible official/enterprise assets offered as
        source-versioned creation templates (personal-workspace-product-surface).
        Purely a read projection through the existing resolver — it never
        writes a personal asset, so nothing here is listed as one."""
        from sq_bi_contracts.enums import AssetSourceType as _TemplateSourceType

        session_id = request.headers.get("X-Session-Id")
        user_ctx = resolve_user_context(session_id=session_id)
        if user_ctx is None:
            return _error_response(401, ErrorCode.UNAUTHORIZED, "Authentication required.")
        context = _RuntimeRequestContext(
            user_id=user_ctx.user_id,
            data_source_id=data_source_id,
            environment=environment,
        )
        projection = _runtime_asset_resolver.resolve(context)
        templates = [
            {
                "asset_ref": asset.asset_ref.model_dump(mode="json"),
                "name": getattr(asset.definition, "name", asset.asset_ref.asset.local_code),
                "description": getattr(asset.definition, "description", None),
                "asset_type": str(asset.asset_ref.asset.asset_type.value),
                "source_type": str(asset.asset_ref.asset.source_type.value),
                "source_id": asset.asset_ref.asset.source_id,
                "version": asset.asset_ref.version,
            }
            for asset in projection.resolved
            if asset.asset_ref.asset.source_type
            in (_TemplateSourceType.OFFICIAL_PACK, _TemplateSourceType.ENTERPRISE_PACK)
        ]
        return _response(templates)

    from .promotion_service import PersonalAssetPromotionService as _PersonalAssetPromotionService
    from sq_bi_contracts.personal_assets import (
        ConfirmPromotionRequest as _ConfirmPromotionRequest,
        PromotionPreviewRequest as _PromotionPreviewRequest,
    )

    _promotion_service = (
        _PersonalAssetPromotionService(_personal_store, _ep_store, _runtime_catalog_repo)
        if isinstance(_runtime_catalog_repo, SQLiteProductRepository)
        else None
    )

    def _require_promoter(request: Request) -> Any:
        session_id = request.headers.get("X-Session-Id")
        user_ctx = resolve_user_context(session_id=session_id)
        if user_ctx is None:
            return _error_response(401, ErrorCode.UNAUTHORIZED, "Authentication required.")
        roles = {str(role).lower() for role in user_ctx.role_ids}
        if not is_admin(user_ctx) and not roles.intersection({"analyst", "role_analyst"}):
            return _error_response(403, ErrorCode.FORBIDDEN, "Analyst or admin role required.")
        return user_ctx

    @app.get("/api/v1/personal-assets", response_model=None)
    def list_personal_assets(workspace_id: str, request: Request) -> Any:
        session_id = request.headers.get("X-Session-Id")
        auth = resolve_user_context(session_id=session_id)
        if auth is None:
            return _error_response(401, ErrorCode.UNAUTHORIZED, "Authentication required.")
        if workspace_id != _personal_store.workspace_id_for(auth.user_id) and not is_admin(auth):
            return _error_response(403, ErrorCode.FORBIDDEN, "Workspace access denied.")
        return _response([
            item.model_dump(mode="json") for item in _personal_store.list_assets(workspace_id)
        ])

    @app.post("/api/v1/personal-assets/provenance", response_model=None)
    def save_personal_asset_provenance(body: dict[str, Any], request: Request) -> Any:
        """Save private-asset provenance without changing its template source."""
        from sq_bi_contracts.assets import AssetKey as _AssetKey, AssetRef as _AssetRef
        from sq_bi_contracts.enums import AssetSourceType as _AssetSourceType, AssetType as _AssetType
        from sq_bi_contracts.personal_assets import PersonalAssetScope as _PersonalAssetScope
        from .personal_asset_store import new_personal_record as _new_personal_record

        auth = resolve_user_context(session_id=request.headers.get("X-Session-Id"))
        if auth is None:
            return _error_response(401, ErrorCode.UNAUTHORIZED, "Authentication required.")
        try:
            asset_type = _AssetType(str(body["asset_type"]))
            local_code = str(body["local_code"]).strip()
            name = str(body["name"]).strip()
            if not local_code or not name:
                return _error_response(400, ErrorCode.VALIDATION_ERROR, "Asset code and name are required.")
            template_ref = (
                _AssetRef.model_validate(body["template_asset_ref"])
                if body.get("template_asset_ref")
                else None
            )
            dependency_refs = [
                _AssetRef.model_validate(item) for item in body.get("dependency_refs", [])
            ]
            dependency_refs = list({item.asset.asset_id: item for item in dependency_refs}.values())
            workspace_id = _personal_store.workspace_id_for(auth.user_id)
            asset_ref = _AssetRef(asset=_AssetKey(
                source_type=_AssetSourceType.PERSONAL_WORKSPACE,
                source_id=workspace_id,
                asset_type=asset_type,
                local_code=local_code,
            ), version="1.0.0")
            record = _personal_store.save_asset(_new_personal_record(
                asset_ref=asset_ref,
                name=name,
                owner_user_id=auth.user_id,
                scope=_PersonalAssetScope(
                    workspace_id=workspace_id,
                    data_source_id=str(body.get("data_source_id") or "unbound"),
                ),
                dependency_refs=dependency_refs,
                template_asset_ref=template_ref,
            ))
            return _response(record.model_dump(mode="json"))
        except (KeyError, ValueError) as exc:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))

    @app.post("/api/v1/personal-assets/promotions/preview", response_model=None)
    def preview_personal_asset_promotion(
        body: dict, request: Request
    ) -> Any:
        body = _PromotionPreviewRequest.model_validate(body)
        auth = _require_promoter(request)
        if isinstance(auth, JSONResponse):
            return auth
        if _promotion_service is None:
            return _error_response(500, ErrorCode.INTERNAL_ERROR, "Product repository unavailable.")
        if body.requested_by != auth.user_id and not is_admin(auth):
            return _error_response(403, ErrorCode.FORBIDDEN, "Cannot promote another user's assets.")
        return _response(_promotion_service.preview(body).model_dump(mode="json"))

    @app.post("/api/v1/personal-assets/promotions/confirm", response_model=None)
    def confirm_personal_asset_promotion(
        body: dict, request: Request
    ) -> Any:
        body = _ConfirmPromotionRequest.model_validate(body)
        auth = _require_promoter(request)
        if isinstance(auth, JSONResponse):
            return auth
        if _promotion_service is None:
            return _error_response(500, ErrorCode.INTERNAL_ERROR, "Product repository unavailable.")
        if body.requested_by != auth.user_id and not is_admin(auth):
            return _error_response(403, ErrorCode.FORBIDDEN, "Cannot promote another user's assets.")
        try:
            return _response(_promotion_service.confirm(body).model_dump(mode="json"))
        except ValueError as exc:
            return _error_response(409, ErrorCode.CONFLICT, str(exc))

    @app.get("/api/v1/personal-assets/promotions/{promotion_id}", response_model=None)
    def get_personal_asset_promotion(promotion_id: str, request: Request) -> Any:
        auth = _require_promoter(request)
        if isinstance(auth, JSONResponse):
            return auth
        record = _personal_store.get_promotion(promotion_id)
        if record is None:
            return _error_response(404, ErrorCode.NOT_FOUND, "Promotion not found.")
        from sq_bi_contracts.personal_assets import PromotionLifecycle as _PromotionLifecycle

        lifecycle = _PromotionLifecycle.DRAFT
        next_action = "publish_pack"
        pack = _ep_store.get(record.target_pack_id)
        if pack is not None and pack.version_state.value == "published":
            lifecycle = _PromotionLifecycle.PUBLISHED
            next_action = "create_deployment"
            deployments = [
                dep for dep in _mapping_store.list_deployments()
                if dep.pack_id == record.target_pack_id and dep.pack_version == pack.version
            ]
            if deployments:
                lifecycle = _PromotionLifecycle.DEPLOYED
                next_action = "validate_deployment"
            if any(_compute_deployment_readiness(dep)[1] == "ready" for dep in deployments):
                lifecycle = _PromotionLifecycle.VALIDATED
                next_action = "activate_deployment"
            if any(
                dep.is_active and _compute_deployment_readiness(dep)[1] == "ready"
                for dep in deployments
            ):
                lifecycle = _PromotionLifecycle.ACTIVATED
                next_action = "share_formal_asset"
        return _response(
            record.model_copy(update={"lifecycle": lifecycle, "next_action": next_action}).model_dump(mode="json")
        )

    @app.get("/api/v1/admin/deployments/runtime-projection", response_model=None)
    def admin_runtime_asset_projection(
        data_source_id: str,
        request: Request,
        environment: str = "default",
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> Any:
        """Report the resolver-eligible runtime assets for one request
        context, with machine-readable exclusion reasons per deployment.
        Catalog presence and publication never imply runtime visibility on
        their own (see openspec/changes/runtime-asset-projection/specs/
        asset-visibility-tiers/spec.md)."""
        auth = _require_admin(request)
        if isinstance(auth, JSONResponse):
            return auth
        context = _RuntimeRequestContext(
            user_id=user_id or auth.user_id,
            data_source_id=data_source_id,
            environment=environment,
            workspace_id=workspace_id,
        )
        projection = _runtime_asset_resolver.resolve(context)

        by_deployment: dict[str, dict[str, Any]] = {}
        for asset in projection.resolved:
            if asset.deployment_id is None:
                continue
            entry = by_deployment.setdefault(asset.deployment_id, {
                "deployment_id": asset.deployment_id,
                "source_type": str(asset.asset_ref.asset.source_type),
                "source_id": asset.asset_ref.asset.source_id,
                "effective_asset_count": 0,
                "excluded": False,
                "exclusion_reason": None,
            })
            entry["effective_asset_count"] += 1
        for excluded in projection.excluded:
            if excluded.deployment_id is None:
                continue
            entry = by_deployment.setdefault(excluded.deployment_id, {
                "deployment_id": excluded.deployment_id,
                "source_type": str(excluded.source_type),
                "source_id": excluded.source_id,
                "effective_asset_count": 0,
                "excluded": True,
                "exclusion_reason": str(excluded.reason),
            })
            entry["excluded"] = True
            entry["exclusion_reason"] = str(excluded.reason)

        return _response({
            "context": context.model_dump(mode="json"),
            "effective_asset_count": len(projection.resolved),
            "deployments": sorted(by_deployment.values(), key=lambda d: str(d["deployment_id"])),
            "resolved": [a.model_dump(mode="json") for a in projection.resolved],
            "excluded": [e.model_dump(mode="json") for e in projection.excluded],
        })

    # ── P6: bounded Harness planning loop ──────────────────────────────
    from sq_bi_contracts.harness import (
        HarnessObservation as _HarnessObservation,
        HarnessRequest as _HarnessRequest,
        HarnessToolName as _HarnessToolName,
    )
    from .harness import (
        ConfirmationStore as _HarnessConfirmationStore,
        ControlledToolRegistry as _ControlledToolRegistry,
        DeterministicHarnessPlanner as _DeterministicHarnessPlanner,
        HarnessService as _HarnessService,
        JsonHarnessPlanner as _JsonHarnessPlanner,
        PolicyHarnessPlanner as _PolicyHarnessPlanner,
    )

    _harness_tools = _ControlledToolRegistry()
    _harness_llm_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="harness-llm")

    def _harness_chat(system_prompt: str, user_prompt: str, *, timeout_seconds: float = 8.0) -> str:
        """Keep external model latency inside the product's controlled budget."""
        from concurrent.futures import TimeoutError as _HarnessLLMTimeout

        future = _harness_llm_pool.submit(
            llm_client.chat,
            system_prompt,
            user_prompt,
            timeout_seconds=max(1.0, timeout_seconds - 1.0),
        )
        try:
            return future.result(timeout=timeout_seconds)
        except _HarnessLLMTimeout as exc:
            future.cancel()
            raise TimeoutError("Harness model step timed out.") from exc

    class _BoundedHarnessLLM:
        def chat(self, system_prompt: str, user_prompt: str) -> str:
            return _harness_chat(system_prompt, user_prompt, timeout_seconds=38.0)

    _bounded_harness_llm = _BoundedHarnessLLM()

    def _harness_assets(body: _HarnessRequest) -> list[Any]:
        cached = getattr(body, "_resolved_harness_assets", None)
        if isinstance(cached, list):
            return cached
        source_ids = body.data_source_ids or [body.context.data_source_id]
        assets: dict[tuple[str, str], Any] = {}
        for source_id in source_ids:
            context = body.context.model_copy(update={"data_source_id": source_id})
            for asset in _runtime_asset_resolver.resolve(context).resolved:
                assets[(source_id, asset.asset_ref.asset.asset_id)] = asset
        resolved = list(assets.values())
        object.__setattr__(body, "_resolved_harness_assets", resolved)
        return resolved

    def _asset_id(asset: Any) -> str:
        return f"{asset.data_source_id}::{asset.asset_ref.model_dump_json()}"

    def _harness_chart(columns: list[Any], rows: list[Any], question: str) -> dict[str, Any]:
        normalized = [str(value) for value in columns]
        fallback = {"chart_type": "TABLE", "title": "分析结果", "x_field": None, "y_field": None}
        if not normalized:
            return fallback
        if len(normalized) < 2 or len(rows) < 2:
            return fallback
        try:
            raw = _harness_chat(
                """Choose the clearest presentation for this BI result. Return JSON only:
{"chart_type":"TABLE|BAR|LINE|AREA|PIE|KPI","title":"short title","x_field":"existing column or null","y_field":"existing column or null"}
Use the user's requested form when present; otherwise infer from meaning and data shape.
Only use supplied column names. Never change or invent data.""",
                json.dumps({
                    "question": question,
                    "columns": normalized,
                    "sample_rows": rows[:8],
                }, ensure_ascii=False, default=str),
            )
            choice = parse_json_payload(raw)
            chart_type = str(choice.get("chart_type") or "TABLE").upper()
            if chart_type not in {"TABLE", "BAR", "LINE", "AREA", "PIE", "KPI"}:
                chart_type = "TABLE"
            x_field = choice.get("x_field") if choice.get("x_field") in normalized else None
            y_field = choice.get("y_field") if choice.get("y_field") in normalized else None
            if chart_type != "TABLE" and (not x_field or not y_field):
                chart_type = "TABLE"
            return {
                "chart_type": chart_type,
                "title": str(choice.get("title") or "分析结果")[:80],
                "x_field": x_field,
                "y_field": y_field,
            }
        except Exception:
            return fallback

    def _resolve_scope_tool(body: _HarnessRequest, arguments: dict[str, Any]) -> Any:
        del arguments
        return _HarnessObservation(ok=True, summary="已解析当前数据与语义范围。", data={
            "data_source_ids": body.data_source_ids or [body.context.data_source_id],
            "environment": body.context.environment,
            "eligible_asset_count": len(_harness_assets(body)),
        })

    def _search_assets_tool(body: _HarnessRequest, arguments: dict[str, Any]) -> Any:
        query_text = str(arguments.get("query") or body.question).strip()
        query = query_text.lower()
        explicit_match = re.search(r"(?P<trigger>[@/#])(?P<name>[^\s，,。！？!?]+)", query_text)
        explicit_trigger = explicit_match.group("trigger") if explicit_match else None
        explicit_name = explicit_match.group("name").strip().lower() if explicit_match else ""
        expected_type = {"@": "metric", "/": "skill", "#": "report"}.get(explicit_trigger or "")
        candidates = []
        for asset in _harness_assets(body):
            definition = asset.definition
            name = str(getattr(definition, "name", ""))
            code = str(getattr(definition, "metric_code", getattr(definition, "skill_id", "")))
            asset_type = asset.asset_ref.asset.asset_type.value
            if expected_type and asset_type != expected_type:
                continue
            candidates.append({
                "asset_id": _asset_id(asset),
                "name": name or code,
                "code": code,
                "asset_type": asset_type,
                "source_type": asset.asset_ref.asset.source_type.value,
                "deployment_id": asset.deployment_id,
                "data_source_id": asset.data_source_id,
                "description": str(getattr(definition, "definition", getattr(definition, "description", ""))),
            })
        assets: list[dict[str, Any]] = []
        if explicit_match:
            assets = _match_explicit_asset_candidates(explicit_name, candidates)
        elif candidates:
            try:
                ranked = parse_json_payload(_harness_chat(
                    """Select active BI assets relevant to the request. Return JSON only:
{"matches":[{"index":0,"score":0.0,"reason":"short reason"}]}
Use semantic meaning and recent conversation. Return only genuinely useful assets, best first,
at most 5. An empty list means formal assets are insufficient. Never invent an index.""",
                    json.dumps({
                        "request": body.question,
                        "planner_search_hint": query_text,
                        "conversation": [item.model_dump(mode="json") for item in body.conversation[-12:]],
                        "assets": [
                            {
                                "index": index,
                                "type": item["asset_type"],
                                "name": item["name"],
                                "description": item["description"],
                                "data_source_id": item["data_source_id"],
                            }
                            for index, item in enumerate(candidates)
                        ],
                    }, ensure_ascii=False, default=str),
                ))
                for match in ranked.get("matches") or []:
                    index = int(match.get("index", -1))
                    if 0 <= index < len(candidates):
                        assets.append({
                            **candidates[index],
                            "score": max(0, min(100, int(float(match.get("score", 0)) * 100))),
                            "match_reason": str(match.get("reason") or ""),
                        })
            except Exception:
                assets = [
                    {**candidate, "score": 50}
                    for candidate in candidates
                    if query and (
                        str(candidate["name"]).lower() in query
                        or query in str(candidate["name"]).lower()
                    )
                ]
        unavailable = bool(explicit_match and not assets)
        unavailable_message = (
            f"“{explicit_match.group(0)}”尚未挂载并激活，当前不能调用。请联系管理员完成适配、冒烟测试并启用。"
            if unavailable else ""
        )
        return _HarnessObservation(ok=True, summary=unavailable_message or f"找到 {len(assets)} 个当前可执行资产。", data={
            "assets": assets,
            "explicit_reference": bool(explicit_match),
            "explicit_trigger": explicit_trigger,
            "unavailable": unavailable,
            "unavailable_message": unavailable_message,
        })

    def _find_asset(body: _HarnessRequest, asset_id: str) -> Any | None:
        return next((asset for asset in _harness_assets(body) if _asset_id(asset) == asset_id), None)

    def _inspect_asset_tool(body: _HarnessRequest, arguments: dict[str, Any]) -> Any:
        asset = _find_asset(body, str(arguments.get("asset_id") or ""))
        if asset is None:
            return _HarnessObservation(ok=False, summary="资产不在当前可执行范围。", failure_code="permission_denied")
        definition = asset.definition.model_dump(mode="json")
        safe = {key: value for key, value in definition.items() if "sql" not in key.lower() and "expression" not in key.lower()}
        return _HarnessObservation(ok=True, summary="已检查资产口径、版本和绑定。", data={
            "asset": safe,
            "asset_id": _asset_id(asset),
            "deployment_id": asset.deployment_id,
            "semantic_space_ids": asset.semantic_space_ids,
        })

    def _execute_asset_tool(body: _HarnessRequest, arguments: dict[str, Any]) -> Any:
        asset = _find_asset(body, str(arguments.get("asset_id") or ""))
        if asset is None:
            return _HarnessObservation(ok=False, summary="资产不在当前可执行范围。", failure_code="permission_denied")
        from sq_bi_contracts.enums import ExecutionPath as _HarnessExecutionPath
        from sq_bi_contracts.execution import ResolvedExecutionRequest as _HarnessExecutionRequest
        from sq_bi_contracts.skills import SkillDefinition as _HarnessSkillDefinition
        from .deterministic_execution import DeterministicExecutionPipeline as _HarnessExecutionPipeline
        if isinstance(asset.definition, _HarnessSkillDefinition):
            skill_response = execute_skill_with_llm(SkillExecuteRequest(
                user_id=body.context.user_id,
                question=str(arguments.get("question") or body.question),
                skill=asset.definition,
                execute=body.execute,
                data_source_id=asset.data_source_id,
            ))
            if hasattr(skill_response, "body"):
                envelope = json.loads(bytes(skill_response.body).decode("utf-8"))
            else:
                envelope = skill_response
            payload = envelope.get("data") or {}
            error = envelope.get("error")
            if error:
                return _HarnessObservation(
                    ok=False,
                    summary=str(error.get("message")) if isinstance(error, dict) else "技能执行失败。",
                    failure_code="tool_failed",
                    data=payload,
                )
            if payload.get("clarification_required"):
                return _HarnessObservation(
                    ok=False,
                    summary=str(payload.get("message") or "技能参数需要补充。"),
                    failure_code="tool_failed",
                    data=payload,
                )
            return _HarnessObservation(
                ok=True,
                summary=str(payload.get("summary") or "分析技能执行完成。"),
                data=payload,
            )
        source_record = next(
            (item for item in _load_datasources() if item.get("data_source_id") == asset.data_source_id),
            {},
        )
        if source_record:
            scoped_executor = _data_source_executors.get(asset.data_source_id)
            scoped_catalog = scoped_executor.get_schema_catalog()
        else:
            scoped_executor = service.db_executor
            scoped_catalog = service.schema_catalog
        scoped_dialect = {
            "postgresql": "postgres",
            "postgres": "postgres",
            "mysql": "mysql",
            "clickhouse": "clickhouse",
        }.get(str(source_record.get("database_type") or "oracle").lower(), "oracle")
        pipeline = _HarnessExecutionPipeline(
            _mapping_store,
            scoped_executor,
            allowed_schemas=(str(source_record.get("username")),) if source_record.get("username") else service.allowed_schemas,
            schema_catalog=scoped_catalog,
            dialect=scoped_dialect,
        )
        from sq_bi_contracts.metrics import MetricDefinition as _HarnessMetricDefinition
        from .runtime_filters import (
            RuntimeAnalysisView as _RuntimeAnalysisView,
            bind_runtime_parameters as _bind_runtime_parameters,
        )

        if not isinstance(asset.definition, _HarnessMetricDefinition):
            return _HarnessObservation(
                ok=False,
                summary="该技能需要由技能执行器展开依赖链，不能按单指标方式执行。",
                failure_code="tool_failed",
                data={"asset_id": _asset_id(asset)},
            )
        compiled_sql = pipeline.compile_asset(asset.definition, asset.deployment_id)
        bindings = _bind_runtime_parameters(
            _bounded_harness_llm,
            question=str(arguments.get("question") or body.question),
            metric=asset.definition,
            sql=compiled_sql,
            schema_catalog=scoped_catalog,
            conversation=[item.model_dump(mode="json") for item in body.conversation],
            dialect=scoped_dialect,
        )
        if bindings.requires_clarification and bindings.unresolved:
            return _HarnessObservation(
                ok=False,
                summary="；".join(bindings.unresolved),
                failure_code="tool_failed",
                data={"clarification_required": True, "unresolved": bindings.unresolved},
            )
        view_specs = bindings.views or [_RuntimeAnalysisView(
            title="分析结果",
            filters=bindings.filters,
            dimensions=bindings.dimensions,
            metric_order=bindings.metric_order,
            result_limit=bindings.result_limit,
        )]
        view_results: list[dict[str, Any]] = []
        physical_tables: list[str] = []
        physical_fields: list[str] = []
        execution_provenance: dict[str, Any] = {}
        all_timings: list[dict[str, Any]] = []
        execution_failure = None
        for view in view_specs:
            execution = pipeline.execute(_HarnessExecutionRequest(
                question=str(arguments.get("question") or body.question),
                context=body.context,
                execution_path=_HarnessExecutionPath.FORMAL_METRIC,
                selected_asset=asset,
                runtime_filters=view.filters,
                group_by_fields=view.dimensions,
                metric_order=view.metric_order,
                dimension_order=view.dimension_order,
                result_limit=view.result_limit,
            ), execute_sql=body.execute)
            if execution.failure is not None:
                execution_failure = execution.failure
                break
            if execution.provenance:
                execution_provenance = execution.provenance.model_dump(mode="json")
            all_timings.extend(item.model_dump(mode="json") for item in execution.timings)
            if execution.sql:
                try:
                    physical_tables.extend(
                        table.name for table in parse_one(execution.sql, read=scoped_dialect).find_all(exp.Table)
                    )
                except Exception:
                    pass
            physical_fields.extend(item.field for item in view.filters)
            physical_fields.extend(view.dimensions)
            chart_type = view.presentation
            if chart_type != "TABLE" and (len(execution.columns) < 2 or len(execution.rows) < 2):
                chart_type = "TABLE"
            view_results.append({
                "title": view.title,
                "columns": execution.columns,
                "rows": execution.rows,
                "parameter_bindings": [item.model_dump(mode="json") for item in view.filters],
                "group_by_fields": view.dimensions,
                "ranking": {
                    "direction": view.metric_order,
                    "limit": view.result_limit,
                } if view.metric_order else None,
                "chart_suggestion": {
                    "chart_type": chart_type,
                    "title": view.title,
                    "x_field": execution.columns[0] if len(execution.columns) >= 2 else None,
                    "y_field": execution.columns[-1] if len(execution.columns) >= 2 else None,
                },
            })
        primary = view_results[0] if len(view_results) == 1 else {}
        lineage = {
            "lineage_id": f"lin_{uuid4().hex}",
            "source_system": "SQ_BI_FORMAL_ASSET",
            "data_source_id": asset.data_source_id,
            "metric_codes": [asset.definition.metric_code],
            "metric_versions": {asset.definition.metric_code: asset.definition.version},
            "physical_tables": list(dict.fromkeys(physical_tables)),
            "physical_fields": list(dict.fromkeys(physical_fields)),
            "executed_at": datetime.now(UTC).isoformat(),
        }
        return _HarnessObservation(
            ok=execution_failure is None,
            summary=execution_failure.message if execution_failure else "确定性资产执行完成。",
            data={
                "columns": primary.get("columns", []),
                "rows": primary.get("rows", []),
                "views": view_results if len(view_results) > 1 else [],
                "provenance": execution_provenance,
                "timings": all_timings,
                "parameter_bindings": primary.get("parameter_bindings", []),
                "group_by_fields": primary.get("group_by_fields", []),
                "ranking": primary.get("ranking"),
                "assumptions": bindings.assumptions,
                "unresolved": bindings.unresolved,
                "chart_suggestion": primary.get("chart_suggestion", {"chart_type": "TABLE", "title": "分析结果"}),
                "lineage": lineage,
            },
            failure_code="tool_failed" if execution_failure else None,
        )

    def _gap_tool(body: _HarnessRequest, arguments: dict[str, Any]) -> Any:
        query = str(arguments.get("query") or body.question)
        gaps = _profile_store.lookup_gap_candidates(body.context.data_source_id, query)
        return _HarnessObservation(ok=True, summary=f"识别到 {len(gaps)} 个语义缺口候选。", data={
            "gaps": [item.model_dump(mode="json") for item in gaps],
            "scope_expanded": False,
        })

    def _execute_report_tool(body: _HarnessRequest, arguments: dict[str, Any]) -> Any:
        asset = _find_asset(body, str(arguments.get("asset_id") or ""))
        if asset is None:
            return _HarnessObservation(ok=False, summary="报表不在当前可执行范围。", failure_code="permission_denied")
        # Runtime report assets use the ReportDefinition contract, whose id
        # field is report_skill_id; repo records use report_id.
        report_id = str(
            getattr(asset.definition, "report_skill_id", "")
            or getattr(asset.definition, "report_id", "")
        )
        response = generate_report_artifact_with_llm(report_id, ReportArtifactGenerateRequest(
            user_id=body.context.user_id,
            output_type="html",
            title=str(getattr(asset.definition, "name", report_id)),
            question=str(arguments.get("question") or body.question),
        ))
        if hasattr(response, "body"):
            envelope = json.loads(bytes(response.body).decode("utf-8"))
        else:
            envelope = response
        payload = envelope.get("data") or {}
        error = envelope.get("error")
        return _HarnessObservation(
            ok=error is None,
            summary=(str(error.get("message")) if isinstance(error, dict) else "报表生成失败。") if error else "正式报表已生成。",
            data=payload,
            failure_code="tool_failed" if error else None,
        )

    def _explore_tool(body: _HarnessRequest, arguments: dict[str, Any]) -> Any:
        question = str(arguments.get("question") or body.question)
        source_id = str(arguments.get("data_source_id") or body.context.data_source_id)
        from .semantic_retriever import SemanticRetriever as _HarnessSemanticRetriever
        semantic_context = _HarnessSemanticRetriever(_profile_store_path).get_context_for_question(
            question,
            source_id,
        )
        conversation_context = "\n".join(
            f"{turn.role}: {turn.text}" for turn in body.conversation[-12:]
        )
        scoped_service = _scoped_service_for_data_source(source_id)
        payload = scoped_service.ask_controlled(
            question,
            execute_sql=body.execute,
            extra_context=(
                f"# Retrieved semantic space\n{semantic_context}\n\n"
                f"# Recent conversation\n{conversation_context}"
            ),
        )
        payload.pop("sql", None)
        payload["exploration_tiers"] = ["semantic_space", "database_catalog"]
        payload["data_source_id"] = source_id
        payload["chart_suggestion"] = _harness_chart(
            list(payload.get("columns") or []),
            list(payload.get("rows") or []),
            question,
        )
        payload["lineage"] = {
            "lineage_id": f"lin_{uuid4().hex}",
            "source_system": "SQ_BI_CONTROLLED_EXPLORATION",
            "data_source_id": source_id,
            "metric_codes": list(payload.get("metrics") or []),
            "metric_versions": {},
            "physical_tables": list(payload.get("tables") or []),
            "physical_fields": list(payload.get("physical_columns") or payload.get("columns") or []),
            "executed_at": datetime.now(UTC).isoformat(),
        }
        return _HarnessObservation(ok=True, summary="已基于语义空间与数据库目录完成受控探索。", data=payload)

    def _save_tool(body: _HarnessRequest, arguments: dict[str, Any]) -> Any:
        # Confirmation is consumed by HarnessService before this boundary.
        # Persist a personal draft record; enterprise promotion remains P5.
        import re as _harness_re
        from sq_bi_contracts.assets import AssetKey as _HarnessAssetKey, AssetRef as _HarnessAssetRef
        from sq_bi_contracts.enums import AssetSourceType as _HarnessSourceType, AssetType as _HarnessAssetType
        from sq_bi_contracts.personal_assets import PersonalAssetScope as _HarnessPersonalScope
        from .personal_asset_store import new_personal_record as _harness_personal_record

        workspace_id = body.context.workspace_id or _personal_store.workspace_id_for(body.context.user_id)
        label = str(arguments.get("question") or body.question).strip() or "Harness 探索"
        slug = _harness_re.sub(r"[^\w一-龥-]", "_", label).strip("_").lower() or "exploration"
        local_code = f"harness_{slug[:48]}_{_HarnessConfirmationStore.digest(arguments)[:10]}"
        asset_ref = _HarnessAssetRef(
            asset=_HarnessAssetKey(
                source_type=_HarnessSourceType.PERSONAL_WORKSPACE,
                source_id=workspace_id,
                asset_type=_HarnessAssetType.METRIC,
                local_code=local_code,
            ),
            version="0.1.0",
        )
        scope = _HarnessPersonalScope(
            workspace_id=workspace_id,
            data_source_id=body.context.data_source_id,
            environment=body.context.environment,
        )
        record = _personal_store.save_asset(_harness_personal_record(
            asset_ref=asset_ref,
            name=label,
            owner_user_id=body.context.user_id,
            scope=scope,
        ))
        return _HarnessObservation(ok=True, summary="已确认个人资产保存请求。", data={
            "personal_asset_id": record.asset_ref.asset.asset_id,
            "asset_ref": record.asset_ref.model_dump(mode="json"),
            "owner_user_id": body.context.user_id,
            "workspace_id": workspace_id,
            "lifecycle": record.lifecycle.value,
        })

    _harness_tools.register(_HarnessToolName.RESOLVE_SCOPE, _resolve_scope_tool)
    _harness_tools.register(_HarnessToolName.SEARCH_ASSETS, _search_assets_tool)
    _harness_tools.register(_HarnessToolName.INSPECT_ASSET, _inspect_asset_tool)
    _harness_tools.register(_HarnessToolName.EXECUTE_METRIC, _execute_asset_tool)
    _harness_tools.register(_HarnessToolName.EXECUTE_SKILL, _execute_asset_tool)
    _harness_tools.register(_HarnessToolName.EXECUTE_REPORT, _execute_report_tool)
    _harness_tools.register(_HarnessToolName.LOOKUP_SEMANTIC_GAP, _gap_tool)
    _harness_tools.register(_HarnessToolName.EXPLORE_FIELDS, _explore_tool)
    _harness_tools.register(_HarnessToolName.SAVE_PERSONAL_ASSET, _save_tool)
    def _generate_harness_command(body: _HarnessRequest, observations: list[Any]) -> str:
        system_prompt = """You are the SQ-BI AI-native Harness planner. Choose exactly one next action.
Return one JSON object matching one of these shapes:
{"type":"call_tool","call":{"tool":"tool_name","arguments":{},"cost_units":1}}
{"type":"finish","message":"user-facing answer","result":{}}
{"type":"clarify","message":"one focused question","result":{}}

Available tools: resolve_scope, search_assets, inspect_asset, execute_metric,
execute_skill, execute_report, lookup_semantic_gap, explore_fields, save_personal_asset.

Planning policy:
- First understand the current request together with recent conversation.
- Prefer matching active formal assets. If none match, inspect semantic gaps and then explore
  semantic-space evidence and database catalog through controlled tools.
- An explicit @metric, /skill, or #report is a forced call. Never replace it with exploration.
- Select the data source and tool sequence from evidence; do not assume a fixed sequence.
- Ask only when ambiguity materially changes the result and evidence cannot resolve it.
- Use returned rows, lineage and parameter bindings as evidence. Never fabricate results.
- Tool arguments must never contain SQL, expressions, passwords, tokens, or credentials.
- Do not repeat an identical tool call. Finish once sufficient evidence exists.
"""
        user_prompt = json.dumps({
            "question": body.question,
            "session_id": body.session_id,
            "candidate_data_source_ids": body.data_source_ids or [body.context.data_source_id],
            "conversation": [item.model_dump(mode="json") for item in body.conversation[-12:]],
            "observations": [item.model_dump(mode="json") for item in observations],
        }, ensure_ascii=False, default=str)
        return _harness_chat(system_prompt, user_prompt)

    _harness_planner = _PolicyHarnessPlanner(
        _JsonHarnessPlanner(_generate_harness_command),
        fallback=_DeterministicHarnessPlanner(),
    )
    _harness_service = _HarnessService(_harness_planner, _harness_tools)

    @app.get("/api/v1/query/callable-assets", response_model=None)
    def list_callable_assets(user_id: str, data_source_id: str | None = None) -> Any:
        from sq_bi_contracts.runtime_projection import RuntimeRequestContext as _CallableRuntimeContext

        source_ids = [data_source_id] if data_source_id else [
            str(item.get("data_source_id"))
            for item in _load_datasources()
            if item.get("data_source_id")
        ]
        values: dict[str, dict[str, Any]] = {}

        def _definition_value(definition: Any, *keys: str) -> str:
            for key in keys:
                if isinstance(definition, dict):
                    value = definition.get(key)
                else:
                    value = getattr(definition, key, None)
                if value is not None and str(value).strip():
                    return str(value).strip()
            return ""

        for source_id in source_ids:
            context = _CallableRuntimeContext(
                user_id=user_id,
                data_source_id=source_id,
                workspace_id=user_id,
            )
            for asset in _runtime_asset_resolver.resolve(context).resolved:
                definition = asset.definition
                name = _definition_value(definition, "name")
                code = _definition_value(definition, "metric_code", "skill_id", "report_id")
                if not code:
                    code = asset.asset_ref.asset.local_code
                key = asset.asset_ref.asset.asset_id
                values[key] = {
                    "asset_id": key,
                    "asset_type": asset.asset_ref.asset.asset_type.value,
                    "name": name or code,
                    "code": code,
                    "data_source_id": source_id,
                    "asset_ref": asset.asset_ref.model_dump(mode="json"),
                }
        return _response(list(values.values()))

    @app.post("/api/v1/query/harness", response_model=None)
    def run_harness(body: HarnessRequest) -> Any:
        try:
            planning_body = body
            if body.conversation and not body.continuation:
                previous_reference = ""
                previous_user_request = ""
                for turn in reversed(body.conversation):
                    if turn.role != "user":
                        continue
                    match = re.search(r"(?<!\S)[@/#][^\s，,。！？!?]+", turn.text)
                    if match:
                        previous_reference = match.group(0)
                        previous_user_request = turn.text
                        break
                if previous_reference and previous_user_request and not re.search(
                    r"(?<!\S)[@/#](?=\S)",
                    body.question,
                ):
                    # Conversation-native drill-down: keep the last explicitly selected
                    # asset and let the binder apply the new dimensions/filters/views.
                    # This removes a redundant model round trip and prevents name-based
                    # switching to a merely similar asset.
                    planning_body = body.model_copy(update={
                        "question": f"{previous_user_request}；{body.question}",
                    })
                    return _response(_harness_service.run(planning_body).model_dump(mode="json"))
                try:
                    resolved = parse_json_payload(_harness_chat(
                        """Rewrite the latest user turn as one self-contained BI request using recent conversation
and the active asset catalog supplied by the product.
Return JSON only: {"standalone_question":"..."}.
Carry forward still-relevant filters and intent, then apply only the user's latest change.
If the follow-up changes time/filter or asks to break down/rank the previous metric by a dimension,
preserve the previously selected metric and add that dimension to the request. Do not switch to a
similarly named Skill merely because it mentions the requested dimension. Switch assets only when
the user explicitly invokes another asset or asks for a genuinely different analysis workflow.
Never invent an asset outside the supplied catalog.
Always put whitespace between the complete asset name and following analysis conditions,
for example "@准时到货率 按供应商比较最好和最差" rather than "@准时到货率最好".
Do not answer the question, add assumptions, SQL, or explanations. If already self-contained, return it unchanged.""",
                        json.dumps({
                            "latest_turn": body.question,
                            "conversation": [item.model_dump(mode="json") for item in body.conversation[-12:]],
                            "active_assets": [
                                {
                                    "trigger": {"metric": "@", "skill": "/", "report": "#"}.get(
                                        asset.asset_ref.asset.asset_type.value, ""
                                    ),
                                    "name": str(getattr(asset.definition, "name", "")),
                                    "type": asset.asset_ref.asset.asset_type.value,
                                    "description": str(getattr(
                                        asset.definition,
                                        "definition",
                                        getattr(asset.definition, "description", ""),
                                    )),
                                }
                                for asset in _harness_assets(body)
                            ],
                        }, ensure_ascii=False, default=str),
                        timeout_seconds=5.0,
                    ))
                    standalone = str(resolved.get("standalone_question") or "").strip()
                    if standalone:
                        planning_body = body.model_copy(update={
                            "question": _remove_inferred_asset_triggers(
                                body.question,
                                standalone,
                                previous_reference,
                            )
                        })
                        cached_assets = getattr(body, "_resolved_harness_assets", None)
                        if isinstance(cached_assets, list):
                            object.__setattr__(planning_body, "_resolved_harness_assets", cached_assets)
                except Exception:
                    # Model rewrite is an optimization, not a prerequisite. Preserve
                    # the user's last explicit asset and let the parameter binder apply
                    # the new turn over the existing conversation context.
                    if previous_reference and previous_user_request:
                        planning_body = body.model_copy(update={
                            "question": f"{previous_user_request}；{body.question}",
                        })
                        cached_assets = getattr(body, "_resolved_harness_assets", None)
                        if isinstance(cached_assets, list):
                            object.__setattr__(planning_body, "_resolved_harness_assets", cached_assets)
            return _response(_harness_service.run(planning_body).model_dump(mode="json"))
        except ValueError as exc:
            return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))

    return app


app = create_app()
