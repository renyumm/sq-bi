"""Unit tests for the whole-database catalog persistence (save_catalog,
list_catalog_tables, get_catalog_overview) added to SemanticProfileStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from sq_bi_contracts.semantic_profile import ScanPhase, TableRecommendation
from sq_bi_runtime.schema_scanner import ColumnMeta, TableMeta
from sq_bi_runtime.semantic_profile_store import SemanticProfileStore


@pytest.fixture
def store(tmp_path: Path) -> SemanticProfileStore:
    return SemanticProfileStore(tmp_path / "semantic_profile.db")


def _tables() -> list[TableMeta]:
    return [
        TableMeta(
            name="TMS_SHIPMENT",
            schema="TMS",
            comment="运单表",
            row_count_approx=12000,
            recommendation=TableRecommendation.recommended_include,
            columns=[
                ColumnMeta(name="SHIPMENT_ID", data_type="NUMBER", is_pk=True),
                ColumnMeta(name="CARRIER_NAME", data_type="VARCHAR2", comment="承运商名称"),
            ],
        ),
        TableMeta(
            name="TMP_STAGING_001",
            schema="TMS",
            excluded=True,
            excluded_reason="default_exclusion:TMP_.*",
            recommendation=TableRecommendation.not_relevant,
            columns=[ColumnMeta(name="COL_A", data_type="VARCHAR2")],
        ),
        TableMeta(
            name="TMS_LOOKUP_STATUS",
            schema="TMS",
            recommendation=TableRecommendation.possibly_relevant,
            columns=[ColumnMeta(name="STATUS_CODE", data_type="VARCHAR2")],
        ),
    ]


def test_save_and_list_catalog_tables(store: SemanticProfileStore) -> None:
    snap = store.create_snapshot("ds_tms")
    store.save_catalog(snap.snapshot_id, _tables())

    tables = store.list_catalog_tables("ds_tms")
    assert len(tables) == 3
    shipment = next(t for t in tables if t.table_name == "TMS_SHIPMENT")
    assert shipment.schema_name == "TMS"
    assert shipment.row_count_estimate == 12000
    assert len(shipment.columns) == 2
    assert {c.column_name for c in shipment.columns} == {"SHIPMENT_ID", "CARRIER_NAME"}
    assert next(c for c in shipment.columns if c.column_name == "SHIPMENT_ID").is_pk is True


def test_excluded_table_reason_persisted(store: SemanticProfileStore) -> None:
    snap = store.create_snapshot("ds_tms")
    store.save_catalog(snap.snapshot_id, _tables())

    tables = store.list_catalog_tables("ds_tms")
    staging = next(t for t in tables if t.table_name == "TMP_STAGING_001")
    assert staging.excluded is True
    assert staging.excluded_reason == "default_exclusion:TMP_.*"


def test_resave_replaces_prior_catalog_for_same_snapshot(store: SemanticProfileStore) -> None:
    snap = store.create_snapshot("ds_tms")
    store.save_catalog(snap.snapshot_id, _tables())
    store.save_catalog(snap.snapshot_id, _tables()[:1])

    tables = store.list_catalog_tables("ds_tms")
    assert len(tables) == 1
    assert tables[0].table_name == "TMS_SHIPMENT"


def test_no_snapshot_returns_empty_catalog(store: SemanticProfileStore) -> None:
    assert store.list_catalog_tables("ds_unknown") == []
    assert store.get_catalog_overview("ds_unknown") is None


def test_catalog_overview_counts_and_lists(store: SemanticProfileStore) -> None:
    snap = store.create_snapshot("ds_tms")
    store.save_catalog(snap.snapshot_id, _tables())
    store.update_snapshot(
        snap.snapshot_id,
        scan_phase=ScanPhase.done,
        scanned_schemas=["TMS"],
        table_count=3,
        included_table_count=2,
        excluded_table_count=1,
    )

    overview = store.get_catalog_overview("ds_tms")
    assert overview is not None
    assert overview.data_source_id == "ds_tms"
    assert overview.snapshot_id == snap.snapshot_id
    assert overview.schema_count == 1
    assert overview.table_count == 3
    assert overview.column_count == 4  # 2 + 1 + 1
    assert overview.excluded_table_count == 1
    assert overview.included_table_count == 2
    assert [t.table_name for t in overview.excluded_tables] == ["TMP_STAGING_001"]
    # Only recommended_include, non-excluded tables count as "suspected business tables"
    assert [t.table_name for t in overview.suspected_business_tables] == ["TMS_SHIPMENT"]


def test_overview_reflects_latest_snapshot_only(store: SemanticProfileStore) -> None:
    snap1 = store.create_snapshot("ds_tms")
    store.save_catalog(snap1.snapshot_id, _tables())
    snap2 = store.create_snapshot("ds_tms")
    store.save_catalog(snap2.snapshot_id, _tables()[:1])

    overview = store.get_catalog_overview("ds_tms")
    assert overview is not None
    assert overview.snapshot_id == snap2.snapshot_id
    assert overview.table_count == 1
