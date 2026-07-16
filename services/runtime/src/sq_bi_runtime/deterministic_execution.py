from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Protocol

from sq_bi_contracts.enums import (
    ExecutionFailureCode,
    ExecutionPath,
    ExecutionStage,
)
from sq_bi_contracts.execution import (
    ExecutionFailure,
    ExecutionProvenance,
    ExecutionStageTiming,
    ResolvedExecutionRequest,
)
from sq_bi_contracts.metrics import MetricDefinition

from .dsl_compiler import compile_for_dialect
from .field_mapping_store import FieldMappingStore
from .guardrails import SQLValidationError, ensure_row_limit, validate_sql
from .runtime_filters import (
    apply_runtime_dimension_order,
    apply_runtime_filters,
    apply_runtime_group_by,
    apply_runtime_ranking,
)


class ExecutionDB(Protocol):
    def execute(self, sql: str, max_rows: int = 200) -> dict[str, Any]: ...


@dataclass
class DeterministicExecutionResult:
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    provenance: ExecutionProvenance | None = None
    timings: list[ExecutionStageTiming] = field(default_factory=list)
    failure: ExecutionFailure | None = None


class DeterministicExecutionPipeline:
    def __init__(
        self,
        mapping_store: FieldMappingStore,
        db_executor: ExecutionDB | None,
        *,
        allowed_schemas: tuple[str, ...] = (),
        schema_catalog: dict[str, set[str]] | None = None,
        max_rows: int = 200,
        dialect: str = "oracle",
    ) -> None:
        self._mapping_store = mapping_store
        self._db = db_executor
        self._allowed_schemas = allowed_schemas
        self._schema_catalog = schema_catalog
        self._max_rows = max_rows
        self._dialect = dialect

    def execute(self, request: ResolvedExecutionRequest, *, execute_sql: bool = True) -> DeterministicExecutionResult:
        selected = request.selected_asset
        if request.execution_path != ExecutionPath.FORMAL_METRIC or selected is None:
            return self._failure(
                ExecutionStage.COMPILATION,
                ExecutionFailureCode.UNSUPPORTED_EXPRESSION,
                "deterministic formal pipeline requires a selected metric asset",
            )
        if not isinstance(selected.definition, MetricDefinition):
            return self._failure(
                ExecutionStage.COMPILATION,
                ExecutionFailureCode.UNSUPPORTED_EXPRESSION,
                "selected runtime asset is not a metric",
            )

        provenance = ExecutionProvenance(
            asset_ref=selected.asset_ref,
            deployment_id=selected.deployment_id,
            workspace_id=selected.workspace_id,
            data_source_id=selected.data_source_id,
            environment=selected.environment,
            semantic_space_ids=selected.semantic_space_ids,
        )
        timings: list[ExecutionStageTiming] = []

        started = monotonic()
        try:
            sql = self._compile(selected.definition, selected.deployment_id)
            sql = apply_runtime_filters(sql, request.runtime_filters, dialect=self._dialect)
            sql = apply_runtime_group_by(sql, request.group_by_fields, dialect=self._dialect)
            sql = apply_runtime_dimension_order(sql, request.dimension_order, dialect=self._dialect)
            sql = apply_runtime_ranking(
                sql,
                request.metric_order,
                request.result_limit,
                dialect=self._dialect,
            )
        except ValueError as exc:
            code = (
                ExecutionFailureCode.MISSING_MAPPING
                if "mapping" in str(exc).lower()
                else ExecutionFailureCode.UNSUPPORTED_EXPRESSION
            )
            return self._failure(ExecutionStage.COMPILATION, code, str(exc), provenance, timings, started)
        timings.append(self._timing(ExecutionStage.COMPILATION, started))

        started = monotonic()
        try:
            validation = validate_sql(
                sql,
                allowed_schemas=self._allowed_schemas,
                schema_catalog=self._schema_catalog,
                dialect=self._dialect,
            )
            guarded_sql = ensure_row_limit(validation.sql, max_rows=self._max_rows, dialect=self._dialect)
        except SQLValidationError as exc:
            return self._failure(
                ExecutionStage.GUARDRAIL,
                ExecutionFailureCode.QUERY_REJECTED,
                str(exc),
                provenance,
                timings,
                started,
            )
        timings.append(self._timing(ExecutionStage.GUARDRAIL, started))

        if not execute_sql or self._db is None:
            return DeterministicExecutionResult(
                sql=guarded_sql,
                provenance=provenance,
                timings=timings,
            )

        started = monotonic()
        try:
            payload = self._db.execute(guarded_sql, max_rows=self._max_rows)
        except TimeoutError as exc:
            return self._failure(
                ExecutionStage.EXECUTION,
                ExecutionFailureCode.EXECUTION_TIMEOUT,
                str(exc) or "query execution timed out",
                provenance,
                timings,
                started,
            )
        except Exception as exc:  # noqa: BLE001
            return self._failure(
                ExecutionStage.EXECUTION,
                ExecutionFailureCode.EXECUTION_FAILED,
                str(exc),
                provenance,
                timings,
                started,
            )
        timings.append(self._timing(ExecutionStage.EXECUTION, started))
        return DeterministicExecutionResult(
            sql=guarded_sql,
            columns=[str(value) for value in payload.get("columns", [])],
            rows=[list(row) for row in payload.get("rows", [])],
            provenance=provenance,
            timings=timings,
        )

    def compile_asset(self, metric: MetricDefinition, deployment_id: str | None) -> str:
        """Compile a metric before execution so runtime parameters can be grounded."""
        return self._compile(metric, deployment_id)

    def _compile(self, metric: MetricDefinition, deployment_id: str | None) -> str:
        if metric.logical_formula is not None:
            if not deployment_id:
                raise ValueError("logical metric has no deployment mapping scope")
            mappings = self._mapping_store.get_mappings_dict_by_deployment(deployment_id)
            referenced = set(metric.logical_formula.referenced_standard_fields)
            missing = sorted(referenced - set(mappings))
            if missing:
                raise ValueError(f"missing active mapping for standard fields: {', '.join(missing)}")
            return compile_for_dialect(metric.logical_formula.expression, mappings, {}, dialect=self._dialect)
        expression = metric.formula.expression.strip()
        if not expression:
            raise ValueError("metric has no executable formula")
        return expression

    @staticmethod
    def _timing(stage: ExecutionStage, started: float) -> ExecutionStageTiming:
        return ExecutionStageTiming(stage=stage, duration_ms=max(0, int((monotonic() - started) * 1000)))

    def _failure(
        self,
        stage: ExecutionStage,
        code: ExecutionFailureCode,
        message: str,
        provenance: ExecutionProvenance | None = None,
        timings: list[ExecutionStageTiming] | None = None,
        started: float | None = None,
    ) -> DeterministicExecutionResult:
        values = list(timings or [])
        if started is not None:
            values.append(self._timing(stage, started))
        return DeterministicExecutionResult(
            provenance=provenance,
            timings=values,
            failure=ExecutionFailure(stage=stage, code=code, message=message),
        )
