from __future__ import annotations

from pathlib import Path

from sq_bi_contracts.enterprise_pack import (
    EnterprisePack,
    EnterprisePackDraft,
    PackEnterpriseMetric,
    PackReport,
)
from sq_bi_contracts.enums import AssetSourceType
from sq_bi_contracts.metrics import MetricFormula
from sq_bi_semantic.product_repository import SQLiteProductRepository
from sq_bi_runtime.pack_projection import (
    build_pack_metric_definitions,
    build_pack_report_records,
    project_pack_assets,
    remove_pack_assets,
)

DATA_FILE = Path(__file__).parent.parent.parent / "semantic" / "data" / "tms_semantic.yaml"


def _pack() -> EnterprisePack:
    return EnterprisePack(
        pack_id="ep_projection_test",
        name="投影测试包",
        version="1.2.0",
        draft=EnterprisePackDraft(
            metrics=[
                PackEnterpriseMetric(
                    metric_code="proj_shipment_count",
                    name="投影运单量",
                    definition="投影测试指标",
                    formula=MetricFormula(
                        expression="SELECT COUNT(*) AS value FROM v_shipment_analysis",
                        time_field="ship_date",
                    ),
                ),
            ],
            reports=[
                PackReport(
                    report_id="proj_monthly_report",
                    name="投影月报",
                    description="投影测试报表",
                    metric_codes=["proj_shipment_count"],
                ),
            ],
        ),
    )


def test_builders_stamp_enterprise_pack_identity_and_data_source() -> None:
    pack = _pack()
    metrics = build_pack_metric_definitions(pack, "postgres_demo")
    assert len(metrics) == 1
    metric = metrics[0]
    assert metric.data_source_id == "postgres_demo"
    assert metric.asset_ref is not None
    assert metric.asset_ref.asset.source_type == AssetSourceType.ENTERPRISE_PACK
    assert metric.asset_ref.asset.source_id == "ep_projection_test"
    assert metric.asset_ref.version == "1.2.0"

    reports = build_pack_report_records(pack)
    assert len(reports) == 1
    report = reports[0]
    assert report.asset_ref is not None
    assert report.asset_ref.asset.source_type == AssetSourceType.ENTERPRISE_PACK
    assert report.analysis_chain[0]["metrics"] == ["proj_shipment_count"]


def test_projection_round_trip_upserts_then_removes(tmp_path: Path) -> None:
    repo = SQLiteProductRepository(
        data_file=DATA_FILE,
        store_path=tmp_path / "product.sqlite3",
        file_root=tmp_path / "files",
    )
    pack = _pack()

    project_pack_assets(repo, pack, "postgres_demo")
    # Idempotent re-projection must not raise or duplicate.
    project_pack_assets(repo, pack, "postgres_demo")

    metric = repo.get_metric_by_code("proj_shipment_count")
    assert metric is not None and metric.data_source_id == "postgres_demo"
    projected_metrics = [
        item
        for item in repo.list_metrics()
        if item.asset_ref and item.asset_ref.asset.source_id == "ep_projection_test"
    ]
    assert len(projected_metrics) == 1
    assert any(item.report_id == "proj_monthly_report" for item in repo.list_reports())

    remove_pack_assets(repo, pack.pack_id)
    assert not any(
        item.asset_ref and item.asset_ref.asset.source_id == "ep_projection_test"
        for item in repo.list_metrics()
    )
    assert not any(item.report_id == "proj_monthly_report" for item in repo.list_reports())
