from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .assets import AssetRef
from .common import ContractModel
from .enums import ExecutionFailureCode, ExecutionPath, ExecutionStage
from .runtime_projection import ResolvedRuntimeAsset, RuntimeRequestContext


class ExecutionProvenance(ContractModel):
    asset_ref: AssetRef | None = None
    deployment_id: str | None = None
    workspace_id: str | None = None
    data_source_id: str
    environment: str = "default"
    semantic_space_ids: list[str] = Field(default_factory=list)


class ExecutionStageTiming(ContractModel):
    stage: ExecutionStage
    duration_ms: int = Field(ge=0)


class ExecutionFailure(ContractModel):
    stage: ExecutionStage
    code: ExecutionFailureCode
    message: str
    retryable: bool = False


class PlanFilter(ContractModel):
    field: str
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in"]
    value: str | int | float | bool | list[str | int | float | bool]


class ResolvedExecutionRequest(ContractModel):
    question: str
    context: RuntimeRequestContext
    execution_path: ExecutionPath
    selected_asset: ResolvedRuntimeAsset | None = None
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    runtime_filters: list[PlanFilter] = Field(default_factory=list)
    group_by_fields: list[str] = Field(default_factory=list)
    metric_order: Literal["asc", "desc"] | None = None
    dimension_order: Literal["asc", "desc"] | None = None
    result_limit: int | None = Field(default=None, ge=1, le=200)

    @model_validator(mode="after")
    def _formal_requires_asset(self) -> "ResolvedExecutionRequest":
        if self.execution_path == ExecutionPath.FORMAL_METRIC and self.selected_asset is None:
            raise ValueError("formal_metric execution requires selected_asset")
        return self


class PlanAggregate(ContractModel):
    function: Literal["count", "count_distinct", "sum", "avg", "min", "max"]
    field: str | None = None
    alias: str | None = None


class PlanOrder(ContractModel):
    field: str
    direction: Literal["asc", "desc"] = "asc"


class PlanJoin(ContractModel):
    relationship_id: str


class ControlledQueryPlan(ContractModel):
    entity: str
    fields: list[str] = Field(default_factory=list)
    aggregates: list[PlanAggregate] = Field(default_factory=list)
    filters: list[PlanFilter] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    order_by: list[PlanOrder] = Field(default_factory=list)
    joins: list[PlanJoin] = Field(default_factory=list)
    limit: int = Field(default=200, ge=1, le=200)

    @field_validator("entity")
    @classmethod
    def _identifier_only(cls, value: str) -> str:
        if not value.replace("_", "").isalnum():
            raise ValueError("entity must be a catalog identifier, not SQL")
        return value

    @field_validator("fields", "group_by")
    @classmethod
    def _field_identifiers(cls, values: list[str]) -> list[str]:
        if any(not value.replace("_", "").isalnum() for value in values):
            raise ValueError("fields must be catalog identifiers, not SQL")
        return values

    @model_validator(mode="after")
    def _has_projection(self) -> "ControlledQueryPlan":
        if not self.fields and not self.aggregates:
            raise ValueError("plan requires fields or aggregates")
        return self
