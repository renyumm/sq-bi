"""P3 runtime asset projection contracts.

Additive DTOs shared by `RuntimeAssetResolver` and its future admin API /
frontend consumers. These are read-time projection shapes, independent of
the persisted `DeploymentInstance` (`field_mount.py`) that P3 task 2 will
extend — see openspec/changes/runtime-asset-projection/design.md.
"""

from __future__ import annotations

from typing import TypeAlias

from pydantic import Field

from .assets import AssetRef
from .common import ContractModel
from .enums import AssetSourceType, RuntimeVisibilityReason
from .metrics import MetricDefinition
from .reports import ReportDefinition
from .skills import SkillDefinition

RuntimeAssetDefinition: TypeAlias = MetricDefinition | SkillDefinition | ReportDefinition


class RuntimeRequestContext(ContractModel):
    """Request-scoped context `RuntimeAssetResolver` projects candidates for."""

    user_id: str
    data_source_id: str
    environment: str = "default"
    workspace_id: str | None = None


class RuntimeDeploymentBinding(ContractModel):
    """One effective official/enterprise pack deployment binding, as seen by
    `RuntimeDeploymentProvider`. Scoping to the request's data source and
    environment is the provider's responsibility."""

    deployment_id: str
    source_type: AssetSourceType
    source_id: str
    exact_version: str
    data_source_id: str
    environment: str = "default"
    semantic_space_ids: list[str] = Field(default_factory=list)
    is_ready: bool = False
    is_active: bool = False


class PersonalWorkspaceBinding(ContractModel):
    """Effective binding making one personal workspace's assets runtime-visible."""

    workspace_id: str
    data_source_id: str
    environment: str = "default"


class ResolvedRuntimeAsset(ContractModel):
    """One runtime-visible asset with its exact identity, definition, and provenance."""

    asset_ref: AssetRef
    definition: RuntimeAssetDefinition
    data_source_id: str
    environment: str = "default"
    semantic_space_ids: list[str] = Field(default_factory=list)
    deployment_id: str | None = None
    workspace_id: str | None = None
    visibility_reason: RuntimeVisibilityReason = RuntimeVisibilityReason.ACTIVE_DEPLOYMENT


class ExcludedRuntimeBinding(ContractModel):
    """A deployment or personal-workspace binding that produced no runtime candidates."""

    source_type: AssetSourceType
    source_id: str
    reason: RuntimeVisibilityReason
    deployment_id: str | None = None
    detail: str | None = None


class RuntimeAssetProjection(ContractModel):
    """Full resolver output for one request context: what is visible, and why not the rest."""

    resolved: list[ResolvedRuntimeAsset] = Field(default_factory=list)
    excluded: list[ExcludedRuntimeBinding] = Field(default_factory=list)
