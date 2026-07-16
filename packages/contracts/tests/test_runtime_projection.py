"""Serialization tests for the P3 runtime asset projection contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sq_bi_contracts.assets import AssetKey, AssetRef
from sq_bi_contracts.enums import AssetSourceType, AssetType, RuntimeVisibilityReason
from sq_bi_contracts.metrics import MetricDefinition, MetricFormula
from sq_bi_contracts.reports import ReportDefinition
from sq_bi_contracts.runtime_projection import (
    ExcludedRuntimeBinding,
    PersonalWorkspaceBinding,
    ResolvedRuntimeAsset,
    RuntimeAssetProjection,
    RuntimeDeploymentBinding,
    RuntimeRequestContext,
)
from sq_bi_contracts.skills import SkillDefinition


def _metric_ref(source_type: AssetSourceType, source_id: str, code: str, version: str) -> AssetRef:
    return AssetRef(
        asset=AssetKey(
            source_type=source_type,
            source_id=source_id,
            asset_type=AssetType.METRIC,
            local_code=code,
        ),
        version=version,
    )


def test_runtime_visibility_reason_values() -> None:
    assert RuntimeVisibilityReason.ACTIVE_DEPLOYMENT.value == "active_deployment"
    assert RuntimeVisibilityReason.PERSONAL_WORKSPACE_BINDING.value == "personal_workspace_binding"
    assert RuntimeVisibilityReason.DEPLOYMENT_INACTIVE.value == "deployment_inactive"
    assert RuntimeVisibilityReason.DEPLOYMENT_UNVALIDATED.value == "deployment_unvalidated"
    assert RuntimeVisibilityReason.VERSION_NOT_DEPLOYED.value == "version_not_deployed"
    assert RuntimeVisibilityReason.FOREIGN_WORKSPACE.value == "foreign_workspace"
    assert RuntimeVisibilityReason.NO_WORKSPACE_BINDING.value == "no_workspace_binding"


def test_runtime_request_context_serialization() -> None:
    context = RuntimeRequestContext(
        user_id="u1",
        data_source_id="ds_tms",
        environment="production",
        workspace_id="workspace-a",
    )
    dumped = context.model_dump(mode="json")
    assert dumped == {
        "user_id": "u1",
        "data_source_id": "ds_tms",
        "environment": "production",
        "workspace_id": "workspace-a",
    }
    assert RuntimeRequestContext.model_validate(dumped) == context


def test_runtime_deployment_binding_defaults_and_round_trip() -> None:
    binding = RuntimeDeploymentBinding(
        deployment_id="dep_1",
        source_type=AssetSourceType.ENTERPRISE_PACK,
        source_id="finance",
        exact_version="1.0.0",
        data_source_id="ds_tms",
    )
    assert binding.environment == "default"
    assert binding.semantic_space_ids == []
    assert binding.is_ready is False
    assert binding.is_active is False
    dumped = binding.model_dump(mode="json")
    assert RuntimeDeploymentBinding.model_validate(dumped) == binding


def test_personal_workspace_binding_round_trip() -> None:
    binding = PersonalWorkspaceBinding(
        workspace_id="workspace-a",
        data_source_id="ds_tms",
        environment="staging",
    )
    dumped = binding.model_dump(mode="json")
    assert PersonalWorkspaceBinding.model_validate(dumped) == binding


@pytest.mark.parametrize(
    "definition",
    [
        MetricDefinition(
            metric_code="total_revenue",
            name="Total revenue",
            definition="Published revenue",
            formula=MetricFormula(expression="select 1 from dual"),
            data_source_id="ds_tms",
            owner="finance-admin",
        ),
        SkillDefinition(
            skill_id="revenue_review",
            namespace="finance",
            name="Revenue review",
            skill_type="report",
            visibility="shared",
            description="Reviews revenue",
        ),
        ReportDefinition(
            report_skill_id="revenue_report",
            namespace="finance",
            name="Revenue report",
            owner_user_id="finance-admin",
        ),
    ],
)
def test_resolved_runtime_asset_definition_union_round_trips(definition) -> None:
    resolved = ResolvedRuntimeAsset(
        asset_ref=_metric_ref(AssetSourceType.ENTERPRISE_PACK, "finance", "total_revenue", "1.0.0"),
        definition=definition,
        data_source_id="ds_tms",
        deployment_id="dep_1",
        semantic_space_ids=["sps_1"],
    )
    dumped = resolved.model_dump(mode="json")
    restored = ResolvedRuntimeAsset.model_validate(dumped)
    assert type(restored.definition) is type(definition)
    assert restored == resolved
    assert restored.visibility_reason == RuntimeVisibilityReason.ACTIVE_DEPLOYMENT


def test_excluded_runtime_binding_serialization() -> None:
    excluded = ExcludedRuntimeBinding(
        source_type=AssetSourceType.ENTERPRISE_PACK,
        source_id="finance",
        deployment_id="dep_1",
        reason=RuntimeVisibilityReason.DEPLOYMENT_INACTIVE,
        detail="deployment not activated",
    )
    dumped = excluded.model_dump(mode="json")
    assert dumped["reason"] == "deployment_inactive"
    assert ExcludedRuntimeBinding.model_validate(dumped) == excluded


def test_runtime_asset_projection_bundles_resolved_and_excluded() -> None:
    resolved_asset = ResolvedRuntimeAsset(
        asset_ref=_metric_ref(AssetSourceType.OFFICIAL_PACK, "tms", "otd_rate", "1.0.0"),
        definition=MetricDefinition(
            metric_code="otd_rate",
            name="OTD",
            definition="On-time delivery rate",
            formula=MetricFormula(expression="select 1 from dual"),
            data_source_id="ds_tms",
            owner="ops",
        ),
        data_source_id="ds_tms",
        deployment_id="dep_tms",
    )
    excluded_binding = ExcludedRuntimeBinding(
        source_type=AssetSourceType.ENTERPRISE_PACK,
        source_id="finance",
        reason=RuntimeVisibilityReason.VERSION_NOT_DEPLOYED,
    )
    projection = RuntimeAssetProjection(resolved=[resolved_asset], excluded=[excluded_binding])
    dumped = projection.model_dump(mode="json")
    assert len(dumped["resolved"]) == 1
    assert len(dumped["excluded"]) == 1
    assert RuntimeAssetProjection.model_validate(dumped) == projection


def test_runtime_projection_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RuntimeRequestContext(user_id="u1", data_source_id="ds_tms", unexpected=True)
    with pytest.raises(ValidationError):
        RuntimeDeploymentBinding(
            deployment_id="dep_1",
            source_type=AssetSourceType.OFFICIAL_PACK,
            source_id="tms",
            exact_version="1.0.0",
            data_source_id="ds_tms",
            unexpected=True,
        )
