from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import ContractModel
from .enums import ChartType
from .exploration import AnswerPath, ConfidenceTier, ClarificationRequest, QueryAssumption
from .semantic_space import SemanticGapCandidate
from .execution import ExecutionFailure, ExecutionProvenance, ExecutionStageTiming
from .enums import ExecutionPath


class ChartSuggestion(ContractModel):
    chart_type: ChartType
    title: str
    x_field: str | None = None
    y_field: str | None = None
    series_field: str | None = None
    value_field: str | None = None
    description: str | None = None


class QueryColumn(ContractModel):
    key: str
    label: str | None = None


class Lineage(ContractModel):
    lineage_id: str
    source_system: str
    data_source_id: str
    metric_codes: list[str] = Field(default_factory=list)
    metric_versions: dict[str, str] = Field(default_factory=dict)
    formula_summary: str | None = None
    physical_tables: list[str] = Field(default_factory=list)
    physical_fields: list[str] = Field(default_factory=list)
    executed_at: datetime | None = None


class LineageMetric(ContractModel):
    metric_id: str
    metric_name: str
    visibility: str = "unknown"
    formula_expression: str | None = None
    version: str = "1.0.0"


class LineageSkill(ContractModel):
    skill_id: str
    skill_name: str


class LineageDataSource(ContractModel):
    data_source_id: str
    name: str


class LineageInfo(ContractModel):
    metrics: list[LineageMetric] = Field(default_factory=list)
    skills: list[LineageSkill] = Field(default_factory=list)
    data_sources: list[LineageDataSource] = Field(default_factory=list)
    executed_at: datetime | None = None
    data_watermark: str | None = None


class AuditRecord(ContractModel):
    audit_id: str
    user_id: str
    query_id: str | None = None
    permission_decision: str
    sql_fingerprint: str | None = None
    duration_ms: int | None = None
    status: str
    created_at: datetime


class QueryResult(ContractModel):
    query_id: str
    audit_id: str
    columns: list[str | QueryColumn]
    rows: list[list[object]]
    chart_suggestion: ChartSuggestion
    lineage: Lineage
    lineage_info: LineageInfo | None = None
    summary: str | None = None
    # Phase 3 exploration fields — additive, all optional for backward compat
    answer_path: AnswerPath | None = None
    assumptions: list[QueryAssumption] = Field(default_factory=list)
    confidence_tier: ConfidenceTier | None = None
    clarification: ClarificationRequest | None = None
    is_exploratory: bool = False
    # Semantic-space simplification: fields scanned but not adopted into any
    # semantic space bound to this question, surfaced instead of guessed.
    gap_candidates: list[SemanticGapCandidate] = Field(default_factory=list)
    execution_path: ExecutionPath | None = None
    execution_provenance: ExecutionProvenance | None = None
    execution_timings: list[ExecutionStageTiming] = Field(default_factory=list)
    execution_failure: ExecutionFailure | None = None
