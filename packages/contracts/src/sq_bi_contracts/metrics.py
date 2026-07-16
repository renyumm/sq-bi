from __future__ import annotations

from pydantic import Field

from .assets import AssetRef
from .asset_build import AssetBuildEvent, ExecutableAssetContract, ValidationEvidence
from .common import ContractModel
from .enums import MetricVisibility


class MetricFormula(ContractModel):
    """Physical SQL formula — kept for backward compatibility (task 1.5).

    During the migration period, metrics may still carry physical SQL
    expressions. New logical metrics use LogicalMetricFormula instead.
    """

    expression: str
    numerator: str | None = None
    denominator: str | None = None
    filters: list[str] = Field(default_factory=list)
    time_field: str | None = None


class LogicalMetricFormula(ContractModel):
    """A metric defined as a logical expression referencing standard fields.

    This replaces physical SQL in the new standard-field layer.
    """

    expression: str
    referenced_standard_fields: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    time_field: str | None = None


class MetricDefinition(ContractModel):
    """Metric definition — supports both physical SQL and logical expressions."""

    metric_code: str
    name: str
    definition: str
    visibility: MetricVisibility = MetricVisibility.OFFICIAL
    formula: MetricFormula
    data_source_id: str
    owner: str
    version: str = "1.0.0"
    lifecycle_status: str = "published"
    update_frequency: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    permission_tags: list[str] = Field(default_factory=list)
    # Logical expression (standard-field layer, optional for backward compat)
    logical_formula: LogicalMetricFormula | None = None
    asset_ref: AssetRef | None = None
    dependency_refs: list[AssetRef] = Field(default_factory=list)
    execution_contract: ExecutableAssetContract | None = None
    build_trace: list[AssetBuildEvent] = Field(default_factory=list)
    validation_evidence: list[ValidationEvidence] = Field(default_factory=list)


class MetricDraftRequest(ContractModel):
    name: str
    natural_language_definition: str
    user_id: str


class MetricDraft(ContractModel):
    name: str
    formula: MetricFormula
    mapped_fields: list[str] = Field(default_factory=list)
    explanation: str
    warnings: list[str] = Field(default_factory=list)
    execution_contract: ExecutableAssetContract | None = None
    build_trace: list[AssetBuildEvent] = Field(default_factory=list)
    validation_evidence: list[ValidationEvidence] = Field(default_factory=list)


class CreateUserMetricRequest(ContractModel):
    draft: MetricDraft
    confirmed_by_user: bool
    visibility: MetricVisibility = MetricVisibility.PRIVATE
    user_id: str = "anonymous"
    data_source_id: str = "oracle_tms"
