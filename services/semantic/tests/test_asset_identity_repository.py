from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sq_bi_contracts.assets import AssetKey, AssetRef
from sq_bi_contracts.enums import AssetSourceType, AssetType
from sq_bi_contracts.metrics import MetricDefinition, MetricFormula
from sq_bi_semantic.product_repository import SQLiteProductRepository


DATA_FILE = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"


def _metric(code: str, owner: str, version: str = "1.0.0") -> MetricDefinition:
    return MetricDefinition(
        metric_code=code,
        name=f"Metric {owner} {version}",
        definition="A personal metric.",
        formula=MetricFormula(expression="select 1 as value from dual"),
        data_source_id="oracle_tms",
        owner=owner,
        version=version,
        visibility="private",
    )


def test_same_local_code_can_coexist_across_sources_and_legacy_lookup_is_ambiguous(
    tmp_path: Path,
) -> None:
    repository = SQLiteProductRepository(
        data_file=DATA_FILE,
        store_path=tmp_path / "product.sqlite3",
        file_root=tmp_path / "files",
    )
    personal = repository.create_user_metric(_metric("apply_count", "workspace-a"))
    matches = [item for item in repository.list_metrics() if item.metric_code == "apply_count"]

    assert len(matches) == 2
    assert {item.asset_ref.asset.source_type for item in matches if item.asset_ref} == {
        AssetSourceType.OFFICIAL_PACK,
        AssetSourceType.PERSONAL_WORKSPACE,
    }
    assert personal.asset_ref is not None
    assert personal.asset_ref.asset.source_type == AssetSourceType.PERSONAL_WORKSPACE
    assert repository.get_metric_by_ref(personal.asset_ref) == personal
    with pytest.raises(ValueError, match="AMBIGUOUS_ASSET_REF"):
        repository.get_metric_by_code("apply_count")


def test_exact_version_lookup_never_falls_back_to_latest(tmp_path: Path) -> None:
    repository = SQLiteProductRepository(
        data_file=DATA_FILE,
        store_path=tmp_path / "product.sqlite3",
        file_root=tmp_path / "files",
    )
    version_one = repository.create_user_metric(_metric("personal_total", "workspace-a"))
    assert version_one.asset_ref is not None
    version_two = repository.create_user_metric(
        version_one.model_copy(
            update={"name": "Metric v2", "definition": "Second version", "version": "2.0.0"}
        )
    )
    missing = AssetRef(asset=version_one.asset_ref.asset, version="9.0.0")

    assert repository.get_metric_by_ref(version_one.asset_ref).definition == "A personal metric."
    assert repository.get_metric_by_ref(version_two.asset_ref).definition == "Second version"
    assert repository.get_metric_by_ref(missing) is None


def test_asset_identity_migrates_all_legacy_product_tables_without_data_loss(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "legacy.sqlite3"
    metric_payload = _metric("legacy_metric", "legacy-owner").model_dump(mode="json")
    historical_metric_payload = _metric(
        "legacy_metric", "legacy-owner", version="0.9.0"
    ).model_copy(update={"definition": "Historical definition"}).model_dump(mode="json")
    skill_payload = {
        "skill_id": "legacy_skill",
        "namespace": "legacy",
        "name": "Legacy skill",
        "skill_type": "metric",
        "visibility": "private",
        "owner_user_id": "legacy-owner",
        "description": "Legacy skill",
        "parameters": [],
        "output_schema": {"version": "1.2.0"},
        "permission_tags": [],
        "synonyms": [],
    }
    report_payload = {
        "report_id": "legacy_report",
        "name": "Legacy report",
        "description": "Legacy report",
        "visibility": "private",
        "owner": "legacy-owner",
        "outputTypes": ["html"],
        "channels": [],
        "flow": "Legacy flow",
        "version": "3.0.0",
    }
    with sqlite3.connect(store_path) as conn:
        conn.executescript(
            """
            create table meta (key text primary key, value text not null);
            create table product_metrics (
              metric_code text primary key, visibility text not null,
              owner_user_id text not null, payload text not null,
              created_at text not null, updated_at text not null
            );
            create table product_skills (
              skill_id text primary key, visibility text not null,
              owner_user_id text not null, skill_type text not null,
              payload text not null, created_at text not null, updated_at text not null
            );
            create table product_reports (
              report_id text primary key, visibility text not null,
              owner_user_id text not null, payload text not null,
              created_at text not null, updated_at text not null
            );
            create table entity_versions (
              version_id text primary key, entity_type text not null,
              entity_id text not null, version text not null, payload text not null,
              created_by text not null, created_at text not null
            );
            """
        )
        for key in (
            "product_seed_v1",
            "product_seed_v2_ai_native_reports",
            "product_seed_v3_rich_assets",
            "product_seed_v4_metric_sql_contracts",
            "product_seed_v5_html_report_publish",
            "product_seed_v6_asset_visibility_mix",
            "product_seed_v9_skill_contracts",
            "product_seed_v10_html_only_reports",
        ):
            conn.execute("insert into meta values (?, 'done')", (key,))
        conn.execute(
            "insert into product_metrics values (?, ?, ?, ?, 'created', 'updated')",
            ("legacy_metric", "private", "legacy-owner", json.dumps(metric_payload)),
        )
        conn.execute(
            "insert into product_skills values (?, ?, ?, ?, ?, 'created', 'updated')",
            ("legacy_skill", "private", "legacy-owner", "metric", json.dumps(skill_payload)),
        )
        conn.execute(
            "insert into product_reports values (?, ?, ?, ?, 'created', 'updated')",
            ("legacy_report", "private", "legacy-owner", json.dumps(report_payload)),
        )
        conn.execute(
            "insert into entity_versions values (?, ?, ?, ?, ?, ?, ?)",
            (
                "ver_legacy",
                "metric",
                "legacy_metric",
                "0.9.0",
                json.dumps(historical_metric_payload),
                "legacy-owner",
                "historical",
            ),
        )

    repository = SQLiteProductRepository(
        data_file=DATA_FILE,
        store_path=store_path,
        file_root=tmp_path / "files",
    )

    assert [item.metric_code for item in repository.list_metrics()] == ["legacy_metric"]
    assert [item.skill_id for item in repository.list_skills()] == ["legacy_skill"]
    assert [item.report_id for item in repository.list_reports()] == ["legacy_report"]
    current_metric = repository.list_metrics()[0]
    assert current_metric.asset_ref is not None
    historical_ref = AssetRef(asset=current_metric.asset_ref.asset, version="0.9.0")
    historical_metric = repository.get_metric_by_ref(historical_ref)
    assert historical_metric is not None
    assert historical_metric.definition == "Historical definition"
    with sqlite3.connect(store_path) as conn:
        for table in ("product_metrics", "product_skills", "product_reports"):
            columns = conn.execute(f"pragma table_info({table})").fetchall()
            assert next(row for row in columns if row[1] == "asset_id")[5] == 1
            assert conn.execute(f"select count(*) from {table}").fetchone()[0] == 1


def test_same_source_local_code_constraint_rejects_forged_duplicate(tmp_path: Path) -> None:
    store_path = tmp_path / "product.sqlite3"
    repository = SQLiteProductRepository(
        data_file=DATA_FILE,
        store_path=store_path,
        file_root=tmp_path / "files",
    )
    created = repository.create_user_metric(_metric("duplicate", "workspace-a"))
    assert created.asset_ref is not None
    with sqlite3.connect(store_path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            insert into product_metrics(
              asset_id, source_type, source_id, asset_type, local_code, version,
              metric_code, visibility, owner_user_id, payload, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "asset:v1:personal_workspace:workspace-a:metric:forged",
                "personal_workspace",
                "workspace-a",
                "metric",
                "duplicate",
                "1.0.0",
                "duplicate",
                "private",
                "workspace-a",
                created.model_dump_json(),
                "created",
                "updated",
            ),
        )


def test_personal_create_rejects_spoofed_official_identity(tmp_path: Path) -> None:
    repository = SQLiteProductRepository(
        data_file=DATA_FILE,
        store_path=tmp_path / "product.sqlite3",
        file_root=tmp_path / "files",
    )
    spoofed = _metric("spoofed", "workspace-a").model_copy(
        update={
            "asset_ref": AssetRef(
                asset=AssetKey(
                    source_type=AssetSourceType.OFFICIAL_PACK,
                    source_id="tms",
                    asset_type=AssetType.METRIC,
                    local_code="spoofed",
                ),
                version="1.0.0",
            )
        }
    )

    with pytest.raises(ValueError, match="must belong to the creating workspace"):
        repository.create_user_metric(spoofed)
