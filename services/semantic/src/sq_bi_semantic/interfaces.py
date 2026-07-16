from __future__ import annotations

from typing import Protocol, runtime_checkable
from sq_bi_contracts.catalog import DataSource, SemanticTable, SemanticField
from sq_bi_contracts.metrics import MetricDefinition
from sq_bi_contracts.skills import SkillDefinition, SkillResolveRequest, SkillResolveResult
from sq_bi_contracts.enums import MetricVisibility, SkillVisibility


@runtime_checkable
class CatalogRepository(Protocol):
    def get_data_source(self, data_source_id: str) -> DataSource | None:
        """Fetch a specific DataSource by ID."""
        ...

    def list_data_sources(self) -> list[DataSource]:
        """List all authorized DataSources."""
        ...

    def get_table(self, table_id: str) -> SemanticTable | None:
        """Fetch a specific SemanticTable by ID."""
        ...

    def list_tables(self, data_source_id: str | None = None) -> list[SemanticTable]:
        """List all authorized SemanticTables, optionally filtered by DataSource ID."""
        ...

    def get_field(self, field_id: str) -> SemanticField | None:
        """Fetch a specific SemanticField by ID."""
        ...

    def list_fields(self, table_id: str | None = None) -> list[SemanticField]:
        """List all authorized SemanticFields, optionally filtered by SemanticTable ID."""
        ...


@runtime_checkable
class MetricRepository(Protocol):
    def list_metrics(self, visibility: MetricVisibility | None = None) -> list[MetricDefinition]:
        """List all metrics, optionally filtered by visibility."""
        ...

    def get_metric_by_code(self, metric_code: str) -> MetricDefinition | None:
        """Fetch a MetricDefinition by metric_code."""
        ...

    def create_user_metric(self, metric: MetricDefinition) -> MetricDefinition:
        """Persist a confirmed user-defined metric."""
        ...

@runtime_checkable
class SkillRepository(Protocol):
    def list_skills(self, visibility: SkillVisibility | None = None) -> list[SkillDefinition]:
        """List all registered skills, optionally filtered by visibility."""
        ...

    def resolve_skill(self, request: SkillResolveRequest) -> SkillResolveResult:
        """Resolve trigger text to a matched skill or candidate list."""
        ...
