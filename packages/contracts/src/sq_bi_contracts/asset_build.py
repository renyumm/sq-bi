from __future__ import annotations

from typing import Literal

from pydantic import Field

from .assets import AssetRef
from .common import ContractModel


AssetKind = Literal["metric", "skill", "report"]
BuildEventType = Literal[
    "user_intent",
    "plan",
    "slot_resolution",
    "dependency_resolution",
    "draft",
    "validation",
    "test",
    "revision",
    "confirmation",
    "artifact",
]
SlotStatus = Literal["unresolved", "ambiguous", "resolved", "defaulted", "confirmed"]
EvidenceStatus = Literal["pending", "passed", "failed"]


class ParameterSlotCandidate(ContractModel):
    value: object
    label: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: str | None = None


class ParameterSlot(ContractModel):
    name: str
    data_type: str
    required: bool = True
    description: str | None = None
    value: object | None = None
    default_value: object | None = None
    allowed_values: list[str] = Field(default_factory=list)
    candidates: list[ParameterSlotCandidate] = Field(default_factory=list)
    status: SlotStatus = "unresolved"
    resolution_source: str | None = None


class ValidationEvidence(ContractModel):
    check: str
    status: EvidenceStatus = "pending"
    message: str | None = None
    details: dict[str, object] = Field(default_factory=dict)


class DataSourceBinding(ContractModel):
    data_source_id: str
    name: str
    role: Literal["primary", "inherited", "step_input"] = "primary"
    reason: str | None = None


class AssetBuildEvent(ContractModel):
    event_id: str
    event_type: BuildEventType
    title: str
    summary: str | None = None
    created_at: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class ExecutableAssetContract(ContractModel):
    asset_kind: AssetKind
    parameter_slots: list[ParameterSlot] = Field(default_factory=list)
    dependency_refs: list[AssetRef] = Field(default_factory=list)
    data_source_bindings: list[DataSourceBinding] = Field(default_factory=list)
    steps: list[dict[str, object]] = Field(default_factory=list)
    logical_sql: str | None = None
    summary_rule: str | None = None
    output_contract: dict[str, object] = Field(default_factory=dict)
