from __future__ import annotations

from pydantic import Field

from .assets import AssetRef
from .asset_build import AssetBuildEvent, DataSourceBinding, ExecutableAssetContract, ValidationEvidence
from .common import ContractModel
from .enums import SkillType, SkillVisibility


class SkillParameter(ContractModel):
    name: str
    data_type: str
    required: bool = True
    description: str | None = None
    allowed_values: list[str] = Field(default_factory=list)


class SkillDefinition(ContractModel):
    skill_id: str
    namespace: str
    name: str
    skill_type: SkillType
    visibility: SkillVisibility
    owner_user_id: str | None = None
    owner_org_id: str | None = None
    description: str
    parameters: list[SkillParameter] = Field(default_factory=list)
    output_schema: dict[str, object] = Field(default_factory=dict)
    permission_tags: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    asset_ref: AssetRef | None = None
    dependency_refs: list[AssetRef] = Field(default_factory=list)
    data_source_bindings: list[DataSourceBinding] = Field(default_factory=list)
    execution_contract: ExecutableAssetContract | None = None
    build_trace: list[AssetBuildEvent] = Field(default_factory=list)
    validation_evidence: list[ValidationEvidence] = Field(default_factory=list)


class SkillResolveRequest(ContractModel):
    user_id: str
    text: str
    trigger: str


class SkillResolveResult(ContractModel):
    matched_skill: SkillDefinition | None = None
    candidates: list[SkillDefinition] = Field(default_factory=list)
