"""Contracts for the database semantic profile pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field

from .common import ContractModel


class EvidenceSource(str, Enum):
    """Signal source for a semantic inference."""
    comment = "comment"
    document = "document"
    name = "name"
    sample = "sample"
    user_note = "user_note"
    official_pack = "official_pack"
    ai_inference = "ai_inference"


class FieldOrigin(str, Enum):
    standard = "standard"
    enterprise = "enterprise"
    inferred = "inferred"


class TableRecommendation(str, Enum):
    recommended_include = "recommended_include"
    possibly_relevant = "possibly_relevant"
    not_relevant = "not_relevant"


class ScanPhase(str, Enum):
    pending = "pending"
    phase_one = "phase_one"
    phase_two = "phase_two"
    discovering = "discovering"
    done = "done"
    failed = "failed"


class FieldStatus(str, Enum):
    """Per-semantic-space field adoption status overlay."""
    confirmed = "confirmed"
    pending = "pending"
    excluded = "excluded"
    sensitive = "sensitive"
    invalid = "invalid"


class SemanticSpaceVersionState(str, Enum):
    draft = "draft"
    published = "published"


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

class EvidenceItem(ContractModel):
    source: EvidenceSource
    detail: str | None = None


# ---------------------------------------------------------------------------
# Profile nodes
# ---------------------------------------------------------------------------

class SemanticField(ContractModel):
    field_id: str
    entity_id: str
    physical_table: str
    physical_column: str
    business_name: str
    description: str | None = None
    data_type: str | None = None
    origin: FieldOrigin
    semantic_role: str | None = None
    default_aggregation: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    physical_reference: str | None = None
    is_candidate: bool = False
    status: FieldStatus | None = None


class SemanticEntity(ContractModel):
    entity_id: str
    space_id: str
    physical_table: str
    business_name: str
    description: str | None = None
    recommendation: TableRecommendation = TableRecommendation.recommended_include
    fields: list[SemanticField] = Field(default_factory=list)


class SemanticSpace(ContractModel):
    space_id: str
    snapshot_id: str
    name: str
    description: str | None = None
    entities: list[SemanticEntity] = Field(default_factory=list)
    accepted: bool = False
    # Standalone versioning overlay (semantic-space-management capability).
    # None on scan-time candidate clusters that have never been explicitly
    # managed; set once a user creates/refreshes/publishes the space.
    version: int | None = None
    version_state: SemanticSpaceVersionState | None = None
    created_at: str | None = None
    published_at: str | None = None


class SchemaSnapshot(ContractModel):
    snapshot_id: str
    data_source_id: str
    version: int
    scanned_schemas: list[str] = Field(default_factory=list)
    table_count: int = 0
    included_table_count: int = 0
    excluded_table_count: int = 0
    recommendation_counts: dict[str, int] = Field(default_factory=dict)
    scan_phase: ScanPhase = ScanPhase.pending
    created_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Whole-database catalog (ground truth, independent of LLM clustering)
# ---------------------------------------------------------------------------

class CatalogColumnRecord(ContractModel):
    """One scanned physical column — persisted regardless of whether the LLM
    discovery pass ever clustered it into a semantic space."""

    schema_name: str | None = None
    table_name: str
    column_name: str
    data_type: str | None = None
    comment: str | None = None
    nullable: bool = True
    is_pk: bool = False
    is_fk: bool = False
    has_index: bool = False


class CatalogTableRecord(ContractModel):
    """One scanned physical table with its full column list."""

    schema_name: str | None = None
    table_name: str
    table_type: str = "table"
    comment: str | None = None
    row_count_estimate: int | None = None
    classification: TableRecommendation = TableRecommendation.recommended_include
    excluded: bool = False
    excluded_reason: str | None = None
    columns: list[CatalogColumnRecord] = Field(default_factory=list)


class CatalogOverview(ContractModel):
    """Aggregate view over the latest persisted catalog for a data source."""

    data_source_id: str
    snapshot_id: str
    version: int
    schema_count: int = 0
    table_count: int = 0
    column_count: int = 0
    included_table_count: int = 0
    excluded_table_count: int = 0
    excluded_tables: list[CatalogTableRecord] = Field(default_factory=list)
    suspected_business_tables: list[CatalogTableRecord] = Field(default_factory=list)
    recommendation_counts: dict[str, int] = Field(default_factory=dict)
    scan_phase: ScanPhase = ScanPhase.pending
    created_at: str | None = None


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class DataSourceDocument(ContractModel):
    document_id: str
    data_source_id: str
    filename: str
    content_type: str
    byte_size: int
    upload_status: Literal["pending", "processing", "ready", "failed"] = "pending"
    uploaded_at: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# API request/response shapes
# ---------------------------------------------------------------------------

class ScanRequest(ContractModel):
    force_rescan: bool = False
    authorized_schemas: list[str] = Field(default_factory=list)
    include_rules: list[str] = Field(default_factory=list)
    exclude_rules: list[str] = Field(default_factory=list)


class ScanStatus(ContractModel):
    scan_id: str
    data_source_id: str
    snapshot_id: str | None = None
    phase: ScanPhase
    progress_message: str | None = None
    table_count: int = 0
    included_table_count: int = 0
    recommendation_counts: dict[str, int] = Field(default_factory=dict)
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


class ProfileView(ContractModel):
    data_source_id: str
    snapshot_id: str
    version: int
    spaces: list[SemanticSpace] = Field(default_factory=list)
    scan_phase: ScanPhase
    created_at: str | None = None


class SemanticFieldAdjustment(ContractModel):
    business_name: str | None = None
    description: str | None = None
    semantic_role: str | None = None
    default_aggregation: str | None = None
    synonyms: list[str] | None = None


class SemanticSpaceAdjustment(ContractModel):
    space_id: str
    accepted: bool
    name: str | None = None
    description: str | None = None
    field_statuses: dict[str, FieldStatus] = Field(default_factory=dict)
    field_updates: dict[str, SemanticFieldAdjustment] = Field(default_factory=dict)
