from __future__ import annotations

import sqlite3
from pathlib import Path

from sq_bi_contracts.assets import AssetQuery, AssetRef
from sq_bi_contracts.enterprise_pack import (
    CreateEnterprisePackRequest,
    EnterprisePackDraft,
    PackEnterpriseMetric,
    PackReport,
    PackSkill,
    PackSkillStep,
)
from sq_bi_contracts.enums import AssetSourceType, AssetType
from sq_bi_contracts.metrics import MetricDefinition, MetricFormula
from sq_bi_semantic.product_repository import SQLiteProductRepository
from sq_bi_runtime.asset_catalog import (
    AssetCatalog,
    EnterprisePackAssetProvider,
    LegacyPersonalAssetProvider,
    OfficialPackAssetProvider,
)
from sq_bi_runtime.enterprise_pack_store import EnterprisePackStore
from sq_bi_runtime.pack_loader import PackRegistry, load_manifest


ROOT = Path(__file__).parents[3]
DATA_FILE = ROOT / "services" / "semantic" / "data" / "tms_semantic.yaml"


def _personal_metric(code: str, owner: str) -> MetricDefinition:
    return MetricDefinition(
        metric_code=code,
        name=f"Personal {owner}",
        definition="Personal definition",
        formula=MetricFormula(expression="select 1 as value from dual"),
        data_source_id="oracle_tms",
        owner=owner,
        visibility="private",
    )


def test_catalog_reads_three_sources_without_projecting_enterprise_publish(
    tmp_path: Path,
) -> None:
    registry = PackRegistry()
    pack_dir = ROOT / "domain-packs" / "tms"
    registry.install(load_manifest(pack_dir), pack_dir)
    product_store = tmp_path / "product.sqlite3"
    repository = SQLiteProductRepository(
        data_file=DATA_FILE,
        store_path=product_store,
        file_root=tmp_path / "files",
    )
    personal_a = repository.create_user_metric(_personal_metric("workspace_metric", "workspace-a"))
    repository.create_user_metric(_personal_metric("workspace_metric", "workspace-b"))

    enterprise_store = EnterprisePackStore(tmp_path / "enterprise.sqlite3")
    pack = enterprise_store.create(
        CreateEnterprisePackRequest(
            name="Finance pack",
            created_by="finance-admin",
        )
    )
    draft = EnterprisePackDraft(
        metrics=[
            PackEnterpriseMetric(
                metric_code="total_revenue",
                name="Total revenue",
                definition="Published revenue definition",
                formula=MetricFormula(expression="select 1 as total_revenue from dual"),
            )
        ],
        skills=[
            PackSkill(
                skill_id="revenue_review",
                name="Revenue review",
                steps=[
                    PackSkillStep(
                        step_id="step-1",
                        description="Read revenue",
                        metric_codes=["total_revenue"],
                    )
                ],
            )
        ],
        reports=[
            PackReport(
                report_id="revenue_report",
                name="Revenue report",
                metric_codes=["total_revenue"],
                skill_ids=["revenue_review"],
            )
        ],
    )
    enterprise_store.update_draft(pack.pack_id, draft)
    enterprise_provider = EnterprisePackAssetProvider(enterprise_store)
    assert enterprise_provider.list_assets() == []
    with sqlite3.connect(product_store) as conn:
        before_publish = conn.execute("select count(*) from product_metrics").fetchone()[0]

    published = enterprise_store.publish(pack.pack_id, version="1.0.0")
    catalog = AssetCatalog(
        [
            OfficialPackAssetProvider(registry),
            enterprise_provider,
            LegacyPersonalAssetProvider(repository),
        ]
    )
    enterprise_assets = catalog.list_assets(
        AssetQuery(
            source_types=[AssetSourceType.ENTERPRISE_PACK],
            source_ids=[published.pack_id],
        )
    )
    personal_assets = catalog.list_assets(
        AssetQuery(
            source_types=[AssetSourceType.PERSONAL_WORKSPACE],
            source_ids=["workspace-a"],
        )
    )
    official_assets = catalog.list_assets(
        AssetQuery(
            source_types=[AssetSourceType.OFFICIAL_PACK],
            source_ids=["tms"],
            asset_types=[AssetType.METRIC],
        )
    )

    assert {item.asset_ref.asset.local_code for item in enterprise_assets} == {
        "total_revenue",
        "revenue_review",
        "revenue_report",
    }
    assert [item.asset_ref for item in personal_assets] == [personal_a.asset_ref]
    assert len(official_assets) >= 20
    with sqlite3.connect(product_store) as conn:
        assert conn.execute("select count(*) from product_metrics").fetchone()[0] == before_publish

    metric_descriptor = next(
        item
        for item in enterprise_assets
        if item.asset_ref.asset.asset_type == AssetType.METRIC
    )
    skill_descriptor = next(
        item
        for item in enterprise_assets
        if item.asset_ref.asset.asset_type == AssetType.SKILL
    )
    metric = catalog.get_asset(metric_descriptor.asset_ref)
    skill = catalog.get_asset(skill_descriptor.asset_ref)
    missing = AssetRef(asset=metric_descriptor.asset_ref.asset, version="9.0.0")

    assert metric is not None and metric.name == "Total revenue"
    assert skill is not None and skill.dependency_refs == [metric_descriptor.asset_ref]
    assert catalog.get_asset(missing) is None


def test_personal_provider_requires_explicit_workspace_scope(tmp_path: Path) -> None:
    repository = SQLiteProductRepository(
        data_file=DATA_FILE,
        store_path=tmp_path / "product.sqlite3",
        file_root=tmp_path / "files",
    )
    repository.create_user_metric(_personal_metric("metric-a", "workspace-a"))
    repository.create_user_metric(_personal_metric("metric-b", "workspace-b"))
    provider = LegacyPersonalAssetProvider(repository)

    assert provider.list_assets() == []
    assert provider.list_assets(AssetQuery(source_types=[AssetSourceType.PERSONAL_WORKSPACE])) == []
    scoped = provider.list_assets(AssetQuery(source_ids=["workspace-a"]))
    assert {item.asset_ref.asset.source_id for item in scoped} == {"workspace-a"}
