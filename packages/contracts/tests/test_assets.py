from __future__ import annotations

import pytest
from pydantic import ValidationError

from sq_bi_contracts.assets import AssetDescriptor, AssetKey, AssetQuery, AssetRef
from sq_bi_contracts.enums import AssetSourceType, AssetType
from sq_bi_contracts.metrics import MetricDefinition, MetricFormula
from sq_bi_contracts.reports import ReportDefinition
from sq_bi_contracts.skills import SkillDefinition


def test_asset_key_generates_stable_version_independent_id() -> None:
    key = AssetKey(
        source_type=AssetSourceType.PERSONAL_WORKSPACE,
        source_id="user:42",
        asset_type=AssetType.METRIC,
        local_code="user_42::total_revenue",
    )
    first = AssetRef(asset=key, version="1.0.0")
    second = AssetRef(asset=key, version="2.0.0")

    assert key.asset_id == "asset:v1:personal_workspace:user%3A42:metric:user_42%3A%3Atotal_revenue"
    assert first.asset.asset_id == second.asset.asset_id
    assert AssetRef.model_validate(first.model_dump()) == first


def test_asset_key_rejects_forged_asset_id() -> None:
    with pytest.raises(ValidationError, match="asset_id does not match"):
        AssetKey(
            source_type="official_pack",
            source_id="tms",
            asset_type="metric",
            local_code="total_revenue",
            asset_id="asset:v1:official_pack:tms:metric:other",
        )


def test_asset_descriptor_and_query_forbid_unknown_fields() -> None:
    ref = AssetRef(
        asset=AssetKey(
            source_type="official_pack",
            source_id="tms",
            asset_type="metric",
            local_code="total_revenue",
        ),
        version="1.0.0",
    )
    descriptor = AssetDescriptor(asset_ref=ref, name="Total revenue")
    query = AssetQuery(asset_types=[AssetType.METRIC], local_code="total_revenue")

    assert descriptor.asset_ref.asset.asset_id == "asset:v1:official_pack:tms:metric:total_revenue"
    assert query.model_dump(mode="json")["asset_types"] == ["metric"]
    with pytest.raises(ValidationError):
        AssetQuery(unknown=True)


def test_asset_refs_are_backward_compatible_on_asset_definitions() -> None:
    metric = MetricDefinition(
        metric_code="m1",
        name="Metric",
        definition="Definition",
        formula=MetricFormula(expression="select 1 as value from dual"),
        data_source_id="ds",
        owner="owner",
    )
    skill = SkillDefinition(
        skill_id="s1",
        namespace="personal",
        name="Skill",
        skill_type="metric",
        visibility="private",
        description="Description",
    )
    report = ReportDefinition(
        report_skill_id="r1",
        namespace="personal",
        name="Report",
        owner_user_id="owner",
    )

    assert metric.asset_ref is None
    assert skill.asset_ref is None and skill.dependency_refs == []
    assert report.asset_ref is None and report.dependency_refs == []
