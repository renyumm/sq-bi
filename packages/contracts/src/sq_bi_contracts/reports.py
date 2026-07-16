from __future__ import annotations

from pydantic import Field

from .assets import AssetRef
from .asset_build import AssetBuildEvent, DataSourceBinding, ExecutableAssetContract, ValidationEvidence
from .common import ContractModel
from .enums import ChartType, SkillVisibility


class ReportWidget(ContractModel):
    widget_id: str
    title: str
    metric_codes: list[str]
    dimensions: list[str] = Field(default_factory=list)
    chart_type: ChartType
    config: dict[str, object] = Field(default_factory=dict)


class ReportDefinition(ContractModel):
    report_skill_id: str
    namespace: str
    name: str
    owner_user_id: str
    visibility: SkillVisibility = SkillVisibility.PRIVATE
    description: str | None = None
    time_grain: str | None = None
    widgets: list[ReportWidget] = Field(default_factory=list)
    permission_tags: list[str] = Field(default_factory=list)
    asset_ref: AssetRef | None = None
    dependency_refs: list[AssetRef] = Field(default_factory=list)
    data_source_bindings: list[DataSourceBinding] = Field(default_factory=list)
    execution_contract: ExecutableAssetContract | None = None
    build_trace: list[AssetBuildEvent] = Field(default_factory=list)
    validation_evidence: list[ValidationEvidence] = Field(default_factory=list)


class ExecuteReportRequest(ContractModel):
    user_id: str
    report_skill_id: str
    parameters: dict[str, object] = Field(default_factory=dict)
