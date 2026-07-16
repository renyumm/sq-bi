"""Unit tests for the semantic-space-management additions to SemanticProfileStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from sq_bi_contracts.semantic_profile import (
    EvidenceItem,
    EvidenceSource,
    FieldOrigin,
    FieldStatus,
    ScanPhase,
    SemanticEntity,
    SemanticField,
    SemanticFieldAdjustment,
    SemanticSpace,
    SemanticSpaceAdjustment,
    SemanticSpaceVersionState,
)
from sq_bi_runtime.schema_scanner import ColumnMeta, TableMeta
from sq_bi_runtime.semantic_profile_store import SemanticProfileStore


@pytest.fixture
def store(tmp_path: Path) -> SemanticProfileStore:
    return SemanticProfileStore(tmp_path / "semantic_profile.db")


def _seed_candidate_pool(store: SemanticProfileStore, data_source_id: str) -> str:
    """Seed a scan-candidate space (version_state=NULL) with one field, as
    the existing schema-scan pipeline would via save_spaces()."""
    snap = store.create_snapshot(data_source_id)
    field = SemanticField(
        field_id="fld_coupon",
        entity_id="ent_orders",
        physical_table="orders",
        physical_column="coupon_discount",
        business_name="优惠券抵扣金额",
        origin=FieldOrigin.inferred,
        confidence=0.92,
        synonyms=["优惠券", "折扣金额"],
        evidence=[EvidenceItem(source=EvidenceSource.name, detail="column name hint")],
    )
    entity = SemanticEntity(
        entity_id="ent_orders",
        space_id="sp_candidate",
        physical_table="orders",
        business_name="订单",
        fields=[field],
    )
    candidate_space = SemanticSpace(
        space_id="sp_candidate", snapshot_id=snap.snapshot_id, name="候选空间", entities=[entity]
    )
    store.save_spaces(snap.snapshot_id, [candidate_space])
    store.update_snapshot(snap.snapshot_id, scan_phase=ScanPhase.done)
    return snap.snapshot_id


# ── create/list/get ─────────────────────────────────────────────────────


def test_create_space_is_draft_v1_and_independent_of_others(store: SemanticProfileStore) -> None:
    space_a = store.create_space("ds_tms", "TMS 运输执行", description="运输相关")
    space_b = store.create_space("ds_tms", "运费结算")

    assert space_a.version == 1
    assert space_a.version_state == SemanticSpaceVersionState.draft
    assert space_a.space_id != space_b.space_id

    managed = store.list_managed_spaces("ds_tms")
    ids = {s.space_id for s in managed}
    assert {space_a.space_id, space_b.space_id} <= ids


def test_create_space_with_initial_tables_seeds_entities(store: SemanticProfileStore) -> None:
    _seed_candidate_pool(store, "ds_tms")

    space = store.create_space("ds_tms", "TMS", initial_tables=["orders", "shipments"])
    tables = {e.physical_table for e in space.entities}
    assert tables == {"orders", "shipments"}
    orders = next(e for e in space.entities if e.physical_table == "orders")
    shipments = next(e for e in space.entities if e.physical_table == "shipments")
    assert [f.physical_column for f in orders.fields] == ["coupon_discount"]
    assert orders.fields[0].status == "confirmed"
    assert shipments.fields == []


def test_create_space_with_initial_tables_falls_back_to_catalog(store: SemanticProfileStore) -> None:
    snap = store.create_snapshot("ds_tms")
    store.save_catalog(
        snap.snapshot_id,
        [
            TableMeta(
                name="ORDERS",
                schema="TMS",
                columns=[
                    ColumnMeta(name="ORDER_ID", data_type="VARCHAR2", comment="订单号"),
                    ColumnMeta(name="AMOUNT", data_type="NUMBER", comment="订单金额"),
                ],
            )
        ],
    )

    space = store.create_space("ds_tms", "订单空间", initial_tables=["orders"])

    entity = space.entities[0]
    assert entity.physical_table == "TMS.ORDERS"
    assert [f.physical_column for f in entity.fields] == ["ORDER_ID", "AMOUNT"]
    assert entity.fields[1].semantic_role == "measure"


def test_create_space_merges_missing_catalog_columns_into_partial_recommendation(
    store: SemanticProfileStore,
) -> None:
    snap_id = _seed_candidate_pool(store, "ds_tms")
    store.save_catalog(
        snap_id,
        [
            TableMeta(
                name="orders",
                columns=[
                    ColumnMeta(name="coupon_discount", data_type="NUMBER"),
                    ColumnMeta(name="order_id", data_type="VARCHAR2"),
                ],
            )
        ],
    )

    space = store.create_space("ds_tms", "订单空间", initial_tables=["orders"])

    columns = {field.physical_column for field in space.entities[0].fields}
    assert columns == {"coupon_discount", "order_id"}


def test_add_catalog_table_to_space_expands_only_from_scanned_catalog(
    store: SemanticProfileStore,
) -> None:
    snap = store.create_snapshot("ds_tms")
    store.save_catalog(
        snap.snapshot_id,
        [
            TableMeta(
                name="HR_PROJECT_BASE",
                columns=[ColumnMeta(name="PROJECT_NAME", data_type="VARCHAR2")],
            )
        ],
    )
    space = store.create_space("ds_tms", "运输空间")

    expanded = store.add_catalog_table_to_space(space.space_id, "HR_PROJECT_BASE")

    assert [entity.physical_table for entity in expanded.entities] == ["HR_PROJECT_BASE"]
    assert expanded.entities[0].fields[0].physical_column == "PROJECT_NAME"
    assert expanded.entities[0].fields[0].status == "confirmed"
    with pytest.raises(KeyError):
        store.add_catalog_table_to_space(space.space_id, "NOT_SCANNED")


def test_apply_space_adjustment_updates_managed_field_status(store: SemanticProfileStore) -> None:
    _seed_candidate_pool(store, "ds_tms")
    space = store.create_space("ds_tms", "TMS", initial_tables=["orders"])
    field_id = space.entities[0].fields[0].field_id

    store.apply_space_adjustments(
        space.snapshot_id,
        [
            SemanticSpaceAdjustment(
                space_id=space.space_id,
                accepted=space.accepted,
                field_statuses={field_id: FieldStatus.excluded},
            )
        ],
    )

    updated = store.get_space(space.space_id)
    assert updated is not None
    assert updated.entities[0].fields[0].status == FieldStatus.excluded


def test_apply_space_adjustment_updates_managed_field_semantics(
    store: SemanticProfileStore,
) -> None:
    _seed_candidate_pool(store, "ds_tms")
    space = store.create_space("ds_tms", "TMS", initial_tables=["orders"])
    field_id = space.entities[0].fields[0].field_id

    store.apply_space_adjustments(
        space.snapshot_id,
        [
            SemanticSpaceAdjustment(
                space_id=space.space_id,
                accepted=space.accepted,
                field_updates={
                    field_id: SemanticFieldAdjustment(
                        business_name="优惠金额",
                        description="订单优惠券抵扣金额",
                        semantic_role="measure",
                        default_aggregation="sum",
                        synonyms=["优惠券", "抵扣"],
                    )
                },
            )
        ],
    )

    updated = store.get_space(space.space_id)
    assert updated is not None
    field = updated.entities[0].fields[0]
    assert field.business_name == "优惠金额"
    assert field.description == "订单优惠券抵扣金额"
    assert field.semantic_role == "measure"
    assert field.default_aggregation == "sum"
    assert field.synonyms == ["优惠券", "抵扣"]


def test_delete_space_removes_managed_space_and_versions(store: SemanticProfileStore) -> None:
    _seed_candidate_pool(store, "ds_tms")
    space = store.create_space("ds_tms", "TMS", initial_tables=["orders"])
    store.publish_space(space.space_id)

    assert store.delete_space(space.space_id) is True
    assert store.get_space(space.space_id) is None
    assert store.list_space_versions(space.space_id) == []
    assert store.delete_space(space.space_id) is False


def test_scan_candidate_spaces_are_not_listed_as_managed(store: SemanticProfileStore) -> None:
    _seed_candidate_pool(store, "ds_tms")
    assert store.list_managed_spaces("ds_tms") == []


def test_implicit_default_space_created_when_no_snapshot_exists(store: SemanticProfileStore) -> None:
    space = store.create_space("ds_fresh", "Default")
    assert store.get_latest_snapshot("ds_fresh") is not None
    assert space.snapshot_id == store.get_latest_snapshot("ds_fresh").snapshot_id


# ── refresh / diff ───────────────────────────────────────────────────────


def test_refresh_reports_new_field_from_candidate_pool(store: SemanticProfileStore) -> None:
    _seed_candidate_pool(store, "ds_tms")
    space = store.create_space("ds_tms", "TMS")

    diff = store.refresh_space(space.space_id)

    assert diff.space_id == space.space_id
    assert [f.field_id for f in diff.new_fields] == ["fld_coupon"]
    assert diff.removed_fields == []
    assert diff.changed_fields == []


def test_refresh_does_not_mutate_the_space(store: SemanticProfileStore) -> None:
    _seed_candidate_pool(store, "ds_tms")
    space = store.create_space("ds_tms", "TMS")
    store.refresh_space(space.space_id)

    unchanged = store.get_space(space.space_id)
    assert unchanged is not None
    assert unchanged.entities == []
    assert unchanged.version == 1
    assert unchanged.version_state == SemanticSpaceVersionState.draft


def test_field_already_adopted_elsewhere_excluded_from_new_fields(store: SemanticProfileStore) -> None:
    _seed_candidate_pool(store, "ds_tms")
    space_a = store.create_space("ds_tms", "Space A")
    store.publish_space(space_a.space_id, confirmed_field_ids=["fld_coupon"])

    space_b = store.create_space("ds_tms", "Space B")
    diff = store.refresh_space(space_b.space_id)
    assert diff.new_fields == []


# ── publish ──────────────────────────────────────────────────────────────


def test_publish_adopts_confirmed_field_and_bumps_version_on_republish(
    store: SemanticProfileStore,
) -> None:
    _seed_candidate_pool(store, "ds_tms")
    space = store.create_space("ds_tms", "TMS")

    published = store.publish_space(space.space_id, confirmed_field_ids=["fld_coupon"])
    assert published.version == 1  # first publish keeps the draft's v1
    assert published.version_state == SemanticSpaceVersionState.published
    assert published.published_at is not None
    entity = next(e for e in published.entities if e.physical_table == "orders")
    assert entity.fields[0].field_id == "fld_coupon"
    assert entity.fields[0].status == "confirmed"

    republished = store.publish_space(space.space_id)
    assert republished.version == 2  # subsequent publish bumps the version


def test_publish_ignores_unknown_field_id(store: SemanticProfileStore) -> None:
    _seed_candidate_pool(store, "ds_tms")
    space = store.create_space("ds_tms", "TMS")
    published = store.publish_space(space.space_id, confirmed_field_ids=["fld_does_not_exist"])
    assert published.entities == []


def test_publish_retains_version_history(store: SemanticProfileStore) -> None:
    _seed_candidate_pool(store, "ds_tms")
    space = store.create_space("ds_tms", "TMS")
    store.publish_space(space.space_id, confirmed_field_ids=["fld_coupon"])
    store.publish_space(space.space_id)

    versions = store.list_space_versions(space.space_id)
    assert versions == [1, 2]
    v1 = store.get_space_version(space.space_id, 1)
    assert v1 is not None
    assert v1.entities[0].fields[0].field_id == "fld_coupon"


# ── unadopted-field ledger / gap lookup ───────────────────────────────────


def test_unadopted_field_leaves_ledger_once_published(store: SemanticProfileStore) -> None:
    _seed_candidate_pool(store, "ds_tms")
    space = store.create_space("ds_tms", "TMS")

    before = store.list_unadopted_fields("ds_tms")
    assert [f.field_id for f in before] == ["fld_coupon"]

    store.publish_space(space.space_id, confirmed_field_ids=["fld_coupon"])

    after = store.list_unadopted_fields("ds_tms")
    assert after == []


def test_gap_lookup_matches_business_name_and_synonym(store: SemanticProfileStore) -> None:
    _seed_candidate_pool(store, "ds_tms")

    hits = store.lookup_gap_candidates("ds_tms", "优惠券折扣是多少")
    assert len(hits) == 1
    assert hits[0].field_id == "fld_coupon"
    assert hits[0].physical_table == "orders"
    assert hits[0].connection_id == "ds_tms"

    no_hits = store.lookup_gap_candidates("ds_tms", "承运商准时率")
    assert no_hits == []


def test_gap_lookup_empty_when_nothing_unadopted(store: SemanticProfileStore) -> None:
    _seed_candidate_pool(store, "ds_tms")
    space = store.create_space("ds_tms", "TMS")
    store.publish_space(space.space_id, confirmed_field_ids=["fld_coupon"])

    assert store.lookup_gap_candidates("ds_tms", "优惠券") == []


# ── Recommended (scan-candidate) spaces ─────────────────────────────────


def test_recommended_spaces_returns_scan_candidates(store: SemanticProfileStore) -> None:
    _seed_candidate_pool(store, "ds_tms")

    recommended = store.list_recommended_spaces("ds_tms")
    assert len(recommended) == 1
    assert recommended[0].name == "候选空间"
    assert recommended[0].version_state is None
    assert recommended[0].entities[0].physical_table == "orders"


def test_recommended_spaces_excludes_managed_spaces(store: SemanticProfileStore) -> None:
    _seed_candidate_pool(store, "ds_tms")
    store.create_space("ds_tms", "手动创建的空间")

    recommended = store.list_recommended_spaces("ds_tms")
    assert [s.name for s in recommended] == ["候选空间"]


def test_recommended_spaces_empty_when_no_snapshot(store: SemanticProfileStore) -> None:
    assert store.list_recommended_spaces("ds_unknown") == []


def test_recommended_spaces_scoped_to_latest_snapshot(store: SemanticProfileStore) -> None:
    _seed_candidate_pool(store, "ds_tms")
    # A second scan produces a new snapshot; the old candidate cluster
    # belongs to the stale snapshot and should no longer be "recommended".
    new_snap = store.create_snapshot("ds_tms")
    store.update_snapshot(new_snap.snapshot_id, scan_phase=ScanPhase.done)

    assert store.list_recommended_spaces("ds_tms") == []
