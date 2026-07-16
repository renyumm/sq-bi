from pathlib import Path

from sq_bi_runtime.semantic_assets import load_semantic_asset_bundle
from sq_bi_semantic.product_repository import SQLiteProductRepository


def test_classified_skill_asset_bundle_includes_product_asset_categories(tmp_path: Path) -> None:
    catalog_path = Path(__file__).resolve().parents[3] / "services" / "semantic" / "data" / "tms_semantic.yaml"
    repository = SQLiteProductRepository(
        data_file=catalog_path,
        store_path=tmp_path / "sqbi.sqlite3",
        file_root=tmp_path / "files",
    )

    bundle = load_semantic_asset_bundle(catalog_path, repository=repository)

    assert "# Database Schema Skill Assets" in bundle
    assert "# Metric Definition Skill Assets" in bundle
    assert "# Skill Center Analysis Skill Assets" in bundle
    assert "# Report Factory Skill Assets" in bundle
    assert "# Natural Language To Skill Compiler Assets" in bundle
    assert "RFQ 询比价分析" in bundle
    assert "TMS 经营管理汇报包" in bundle
    assert "指标定义自然语言转 Skill" in bundle
    assert "技能中心自然语言转 Skill" in bundle
    assert "报表工坊自然语言转 Skill" in bundle
