from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from .assets import AssetRef
from .common import ContractModel


class PromotionLifecycle(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    DEPLOYED = "deployed"
    VALIDATED = "validated"
    ACTIVATED = "activated"


class PersonalWorkspace(ContractModel):
    workspace_id: str
    owner_user_id: str
    org_id: str = "default"
    name: str = "个人工作区"


class PersonalAssetScope(ContractModel):
    workspace_id: str
    data_source_id: str
    environment: str = "default"
    semantic_space_ids: list[str] = Field(default_factory=list)
    physical_tables: list[str] = Field(default_factory=list)
    physical_fields: list[str] = Field(default_factory=list)


class AssetDependencyGraph(ContractModel):
    asset_ref: AssetRef
    dependency_refs: list[AssetRef] = Field(default_factory=list)
    effective_scope: PersonalAssetScope

    @model_validator(mode="after")
    def _no_direct_self_cycle(self) -> "AssetDependencyGraph":
        if self.asset_ref in self.dependency_refs:
            raise ValueError("dependency graph contains a self cycle")
        return self


class PersonalAssetRecord(ContractModel):
    asset_ref: AssetRef
    name: str
    workspace_id: str
    owner_user_id: str
    scope: PersonalAssetScope
    dependency_refs: list[AssetRef] = Field(default_factory=list)
    # Set when this asset was derived from a runtime-eligible official/
    # enterprise template (personal-workspace-product-surface). The
    # template source is never mutated or listed in the workspace — this
    # only records provenance on the new private asset.
    template_asset_ref: AssetRef | None = None
    created_at: datetime | None = None


class PromotionConflict(ContractModel):
    code: str
    message: str
    asset_ref: AssetRef | None = None


class StandardFieldProposal(ContractModel):
    field_id: str
    business_name: str
    physical_table: str
    physical_column: str
    data_type: str = "text"
    evidence: str


class MappingCandidateProposal(ContractModel):
    standard_field_id: str
    physical_table: str
    physical_column: str
    confidence: float = Field(default=1.0, ge=0, le=1)
    evidence: str


class PromotionPreviewRequest(ContractModel):
    workspace_id: str
    target_pack_id: str
    asset_refs: list[AssetRef]
    requested_by: str


class PromotionPreview(ContractModel):
    eligible: bool
    workspace_id: str
    target_pack_id: str
    asset_refs: list[AssetRef]
    conflicts: list[PromotionConflict] = Field(default_factory=list)
    standard_fields: list[StandardFieldProposal] = Field(default_factory=list)
    mapping_candidates: list[MappingCandidateProposal] = Field(default_factory=list)


class ConfirmPromotionRequest(PromotionPreviewRequest):
    confirmed_standard_fields: list[StandardFieldProposal] = Field(default_factory=list)
    confirmed_mappings: list[MappingCandidateProposal] = Field(default_factory=list)


class PromotionRecord(ContractModel):
    promotion_id: str
    workspace_id: str
    target_pack_id: str
    source_refs: list[AssetRef]
    target_refs: list[AssetRef] = Field(default_factory=list)
    requested_by: str
    lifecycle: PromotionLifecycle = PromotionLifecycle.DRAFT
    next_action: str = "publish_pack"
    created_at: datetime
