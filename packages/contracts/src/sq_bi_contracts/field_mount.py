from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .common import ContractModel
from .enums import DataType

MappingSource = Literal["auto", "llm", "manual"]
MappingStatus = Literal["active", "pending", "stale"]
MountJobStatus = Literal["in_progress", "completed", "failed"]
ValidationStatus = Literal["unvalidated", "incomplete", "failed", "ready"]
ScopeTier = Literal["recommended", "ambiguous", "excluded"]
CandidateScope = Literal["bound_space", "scanned_catalog"]
BindingStatus = Literal["available", "unavailable"]

# Restricted DSL: only supported transform type in v1.
# Format: {"type": "enum_map", "mapping": {"SRC": "DST", ...}}
_DSL_TYPE_ALLOWLIST = frozenset({"enum_map"})
# Raw SQL detection heuristic – reject if the value looks like SQL.
_SQL_KEYWORDS = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|EXEC|EXECUTE|GRANT|REVOKE|MERGE|TRUNCATE)\b",
    re.IGNORECASE,
)


def _validate_transform_dsl(value: str | None) -> str | None:
    """Reject raw-SQL transforms; allow None or valid DSL JSON strings."""
    if value is None:
        return None
    if _SQL_KEYWORDS.search(value):
        raise ValueError(
            "FieldMapping.transform must be a restricted DSL expression, not raw SQL. "
            "For complex transformations create a customer-side read-only database view."
        )
    return value


class StandardFieldDefinition(ContractModel):
    """A standard field declared in a domain pack — independent of physical schema."""

    field_id: str
    business_name: str
    data_type: DataType
    description: str | None = None
    enum_values: list[str] = Field(default_factory=list)
    required: bool = False
    tags: list[str] = Field(default_factory=list)


class LogicalMetricFormula(ContractModel):
    """A metric defined as a logical expression referencing standard fields."""

    expression: str
    referenced_standard_fields: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    time_field: str | None = None


class LogicalMetricDefinition(ContractModel):
    """A metric expressed using standard fields and logical expressions."""

    metric_code: str
    name: str
    definition: str
    logical_formula: LogicalMetricFormula
    visibility: str = "official"
    data_source_id: str
    owner: str
    version: str = "1.0.0"
    lifecycle_status: str = "published"
    update_frequency: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    permission_tags: list[str] = Field(default_factory=list)


class MappingEvidence(ContractModel):
    """Multi-signal auditable evidence carried by each candidate mapping.

    All fields are optional — filled where the pipeline has the signal.
    """

    name_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    business_name_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    type_compatible: bool | None = None
    comment_evidence: str | None = None
    sample_values: list[str] = Field(default_factory=list)
    conflicting_candidates: list[str] = Field(default_factory=list)
    affected_metric_count: int | None = Field(default=None, ge=0)
    data_quality_flags: list[str] = Field(default_factory=list)


class CandidateMapping(ContractModel):
    """One candidate mapping proposed by the pipeline."""

    physical_table: str
    physical_column: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    evidence: MappingEvidence = Field(default_factory=MappingEvidence)


class PendingMapping(ContractModel):
    """A standard field with candidate mappings pending admin confirmation."""

    mapping_request_id: str = ""  # stable ID so the confirmation index stays valid
    standard_field_id: str
    business_name: str
    candidates: list[CandidateMapping] = Field(default_factory=list)
    outside_scope_candidates: list[CandidateMapping] = Field(default_factory=list)


class FieldMapping(ContractModel):
    """Mapping from a standard field to a physical column in one data source."""

    mapping_id: str
    pack_id: str
    standard_field_id: str
    data_source_id: str
    physical_table: str
    physical_column: str
    transform: str | None = None  # Must be restricted DSL, not raw SQL
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: MappingSource = "manual"
    status: MappingStatus = "active"
    version: str = "1"
    deployment_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None

    @field_validator("physical_table", "physical_column")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("physical_table and physical_column must be non-empty")
        return v

    @field_validator("transform", mode="before")
    @classmethod
    def _validate_transform(cls, v: object) -> object:
        if isinstance(v, str):
            _validate_transform_dsl(v)
        return v


# ── Deployment Instance ─────────────────────────────────────────────


class DeploymentInstance(ContractModel):
    """First-class entity binding a domain pack to a data source."""

    deployment_id: str
    pack_id: str
    pack_version: str
    data_source_id: str
    license_ref: str | None = None  # Placeholder; full license enforcement is out of scope v1
    validation_status: ValidationStatus = "unvalidated"
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    blocking_reasons: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Semantic-space binding (additive). Empty means the deployment is scoped
    # to the whole data source, preserving pre-existing behavior.
    semantic_space_ids: list[str] = Field(default_factory=list)
    # Additive (P3 task 2.1): part of the deployment's binding identity
    # alongside pack_version, data_source_id, and semantic_space_ids — see
    # openspec/changes/runtime-asset-projection/design.md decision 2.
    # Defaults to "default" so legacy deployments stay valid unchanged.
    environment: str = "default"
    # Activation is an independent dimension from validation_status: a
    # deployment can be "ready" (mapping/coverage/smoke-test all pass)
    # without yet being active — an admin must explicitly turn it on before
    # it is considered live/consumable. See
    # .design/asset_semantic_space_harness_operating_model.md §9/§11 (P0:
    # split publish/deploy/validate/activate into independent states).
    is_active: bool = False
    activated_at: datetime | None = None
    activated_by: str | None = None
    # Optional additive layer selected for this base-pack deployment.  The
    # deployment identity remains the base pack; this field selects its one
    # effective extension without turning it into a top-level pack.
    extension_layer_id: str | None = None


class CreateDeploymentRequest(ContractModel):
    """Request to create or reuse a deployment instance and trigger mounting."""

    pack_id: str
    data_source_id: str
    confirmed_by: str | None = None
    semantic_space_ids: list[str] = Field(default_factory=list)
    # Admin-confirmed table list for the implicit default space (P1
    # remainder: smart candidate-scope recommendation). Only consulted when
    # semantic_space_ids is empty. Providing it explicitly requests a
    # dedicated pack-specific space even when other managed spaces exist.
    # None keeps the backward-compatible implicit resolution behavior.
    implicit_space_tables: list[str] | None = None
    extension_layer_id: str | None = None


class ScopeCandidateTable(ContractModel):
    """One scanned table's pack-aware relevance verdict, used to preview the
    implicit default semantic space before it is created."""

    table_name: str
    tier: ScopeTier
    matched_field_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class CreateDeploymentResponse(ContractModel):
    """Response from creating a deployment and triggering the mounting pipeline."""

    deployment: DeploymentInstance
    auto_mapped_count: int = 0
    pending: list[PendingMapping] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    # Set when the request omitted semantic_space_ids and no unambiguous
    # existing space was found, so the backend created an implicit default
    # space covering the whole connection (P1: pack-first mounting).
    auto_created_semantic_space_id: str | None = None


class DeploymentListItem(ContractModel):
    """Summary of a deployment instance as seen in the pack listing."""

    deployment_id: str
    data_source_id: str
    validation_status: ValidationStatus
    coverage: float = Field(ge=0.0, le=1.0)
    semantic_space_ids: list[str] = Field(default_factory=list)
    semantic_space_names: list[str] = Field(default_factory=list)
    unavailable_semantic_space_ids: list[str] = Field(default_factory=list)
    binding_status: BindingStatus = "available"
    is_active: bool = False


class PackWithDeployments(ContractModel):
    """Enabled pack entry with its deployment instance summaries."""

    pack_id: str
    pack_version: str
    name: str
    description: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    distribution_source: Literal["built_in", "imported"] = "built_in"
    standard_field_count: int = 0
    metric_count: int = 0
    skill_count: int = 0
    report_count: int = 0
    deployments: list[DeploymentListItem] = Field(default_factory=list)


# ── Mounting workflow DTOs ──────────────────────────────────────────


class MountTriggerRequest(ContractModel):
    """Request to trigger auto-mounting for a pack on a data source."""

    pack_id: str
    data_source_id: str
    deployment_id: str | None = None


class MountTriggerResponse(ContractModel):
    """Response from triggering auto-mounting."""

    auto_mapped: list[FieldMapping] = Field(default_factory=list)
    pending: list[PendingMapping] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    status: MountJobStatus = "completed"


class ConfirmationRequest(ContractModel):
    """Admin confirmation of one pending mapping."""

    pack_id: str
    data_source_id: str
    standard_field_id: str
    mapping_request_id: str  # matches PendingMapping.mapping_request_id
    chosen_candidate_index: int | None = Field(default=None, ge=0)
    candidate_scope: CandidateScope = "bound_space"
    confirmed_by: str | None = None
    deployment_id: str | None = None
    physical_table: str | None = None
    physical_column: str | None = None

    @field_validator("chosen_candidate_index")
    @classmethod
    def _index_reasonable(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v > 1000:
            raise ValueError("chosen_candidate_index is implausibly large")
        return v

    @model_validator(mode="after")
    def _candidate_or_manual_target(self) -> "ConfirmationRequest":
        has_index = self.chosen_candidate_index is not None
        has_manual = bool(self.physical_table and self.physical_column)
        if has_index == has_manual:
            raise ValueError(
                "Provide either chosen_candidate_index or physical_table/physical_column."
            )
        return self


class SmokeTestMetric(ContractModel):
    """One metric with its smoke test result."""

    metric_code: str
    name: str
    compiled: bool = False
    executed: bool = False
    elapsed_ms: int | None = None
    row_count: int | None = None
    error: str | None = None


class SmokeTestResult(ContractModel):
    """Result of running smoke tests for a pack on a data source."""

    pack_id: str
    data_source_id: str
    deployment_id: str | None = None
    metrics: list[SmokeTestMetric] = Field(default_factory=list)
    all_passed: bool = False
    tested_at: datetime | None = None


class MountStatus(ContractModel):
    """Overall mount status for a pack on a data source."""

    pack_id: str
    data_source_id: str
    deployment_id: str | None = None
    total_standard_fields: int = 0
    mapped_fields: int = 0
    pending_fields: int = 0
    is_ready: bool = False
    validation_status: ValidationStatus = "unvalidated"
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    blocking_reasons: list[str] = Field(default_factory=list)
    smoke_test: SmokeTestResult | None = None
    semantic_space_ids: list[str] = Field(default_factory=list)
    semantic_space_names: list[str] = Field(default_factory=list)
    unavailable_semantic_space_ids: list[str] = Field(default_factory=list)
    binding_status: BindingStatus = "available"
    is_active: bool = False
