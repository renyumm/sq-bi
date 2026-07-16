from __future__ import annotations

from pathlib import Path
from sq_bi_contracts.field_mount import FieldMapping
from sq_bi_runtime.field_mapping_store import FieldMappingStore


def test_upsert_and_get(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "test_mappings.sqlite3")
    mapping = FieldMapping(
        mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY",
        physical_column="DELIVER_NO", confidence=1.0, source="manual", status="active",
    )
    store.upsert(mapping)
    retrieved = store.get("tms", "ds_tms", "deliver_no")
    assert retrieved is not None
    assert retrieved.physical_column == "DELIVER_NO"


def test_get_mappings_dict(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "test_dict.sqlite3")
    store.upsert(FieldMapping(
        mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY",
        physical_column="DELIVER_NO", source="manual", status="active",
    ))
    d = store.get_mappings_dict("tms", "ds_tms")
    assert "deliver_no" in d
    assert d["deliver_no"].physical_column == "DELIVER_NO"


def test_list_for_data_source(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "test_list.sqlite3")
    store.upsert(FieldMapping(
        mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY",
        physical_column="DELIVER_NO", source="manual", status="active",
    ))
    store.upsert(FieldMapping(
        mapping_id="m2", pack_id="tms", standard_field_id="carrier_name",
        data_source_id="ds_other", physical_table="T_CARRIER",
        physical_column="NAME", source="manual", status="active",
    ))
    items = store.list_for_data_source("tms", "ds_tms")
    assert len(items) == 1


def test_multi_datasource_isolation(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "test_iso.sqlite3")
    store.upsert(FieldMapping(
        mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="ds_a", physical_table="T_A", physical_column="DELIVER_NO",
        source="manual", status="active",
    ))
    store.upsert(FieldMapping(
        mapping_id="m2", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="ds_b", physical_table="T_B", physical_column="DELIVER_NO",
        source="manual", status="active",
    ))
    assert store.count_mapped("tms", "ds_a") == 1
    assert store.count_mapped("tms", "ds_b") == 1


def test_delete(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "test_del.sqlite3")
    store.upsert(FieldMapping(
        mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY",
        physical_column="DELIVER_NO", source="manual", status="active",
    ))
    assert store.delete("tms", "ds_tms", "deliver_no") is True
    assert store.get("tms", "ds_tms", "deliver_no") is None


# ── Edge / boundary cases ─────────────────────────────────────────────

def test_get_nonexistent_returns_none(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "empty.sqlite3")
    assert store.get("tms", "ds_tms", "nonexistent") is None


def test_delete_nonexistent_returns_false(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "empty2.sqlite3")
    assert store.delete("tms", "ds_tms", "no_such_field") is False


def test_get_mappings_dict_excludes_pending(tmp_path: Path) -> None:
    """get_mappings_dict must only return active mappings."""
    store = FieldMappingStore(tmp_path / "test_pending.sqlite3")
    store.upsert(FieldMapping(
        mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY",
        physical_column="DELIVER_NO", source="auto", status="active",
    ))
    store.upsert(FieldMapping(
        mapping_id="m2", pack_id="tms", standard_field_id="carrier_name",
        data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY",
        physical_column="CARRIER_NAME", source="llm", status="pending",
    ))
    d = store.get_mappings_dict("tms", "ds_tms")
    assert "deliver_no" in d
    assert "carrier_name" not in d


def test_count_mapped_excludes_pending(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "test_count.sqlite3")
    store.upsert(FieldMapping(
        mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="ds_tms", physical_table="T", physical_column="COL_A",
        source="auto", status="active",
    ))
    store.upsert(FieldMapping(
        mapping_id="m2", pack_id="tms", standard_field_id="carrier_name",
        data_source_id="ds_tms", physical_table="T", physical_column="COL_B",
        source="llm", status="pending",
    ))
    assert store.count_mapped("tms", "ds_tms") == 1


def test_upsert_preserves_created_at(tmp_path: Path) -> None:
    """Re-upserting must not change created_at."""
    from datetime import datetime, timezone
    store = FieldMappingStore(tmp_path / "test_created.sqlite3")
    original_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    mapping = FieldMapping(
        mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="ds_tms", physical_table="T", physical_column="COL",
        source="manual", status="active", created_at=original_time,
    )
    store.upsert(mapping)
    # Upsert again — created_at must stay
    store.upsert(mapping)
    retrieved = store.get("tms", "ds_tms", "deliver_no")
    assert retrieved is not None
    assert retrieved.created_at is not None
    assert retrieved.created_at.year == 2025


def test_confidence_clamped_on_write(tmp_path: Path) -> None:
    """Pydantic must reject confidence > 1.0 before it reaches the store."""
    import pytest
    with pytest.raises(Exception):
        FieldMapping(
            mapping_id="m1", pack_id="tms", standard_field_id="f",
            data_source_id="ds", physical_table="T", physical_column="C",
            confidence=1.5, status="active",
        )


def test_invalid_datetime_in_db_returns_none(tmp_path: Path) -> None:
    """Corrupted datetime values in DB must not crash _row_to_mapping."""
    import sqlite3
    db = tmp_path / "corrupt.sqlite3"
    store = FieldMappingStore(db)
    store.upsert(FieldMapping(
        mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="ds_tms", physical_table="T", physical_column="C",
        source="manual", status="active",
    ))
    # Corrupt the created_at field directly
    with sqlite3.connect(str(db)) as conn:
        conn.execute("UPDATE field_mappings SET created_at='not-a-date' WHERE mapping_id='m1'")
        conn.commit()
    retrieved = store.get("tms", "ds_tms", "deliver_no")
    assert retrieved is not None
    assert retrieved.created_at is None  # graceful degradation


def test_concurrent_writes_do_not_corrupt(tmp_path: Path) -> None:
    """Two threads writing different fields must both be persisted."""
    import threading
    store = FieldMappingStore(tmp_path / "test_concurrent.sqlite3")
    errors: list[Exception] = []

    def write(field_id: str, col: str) -> None:
        try:
            store.upsert(FieldMapping(
                mapping_id=f"m_{field_id}", pack_id="tms",
                standard_field_id=field_id, data_source_id="ds_tms",
                physical_table="T", physical_column=col,
                source="auto", status="active",
            ))
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=write, args=(f"field_{i}", f"COL_{i}"))
        for i in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert store.count_mapped("tms", "ds_tms") == 10


# ── Deployment instance tests ─────────────────────────────────────────

def test_get_or_create_deployment_idempotent(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "deploy.sqlite3")
    d1 = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    d2 = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    assert d1.deployment_id == d2.deployment_id


def test_get_or_create_deployment_persists_semantic_space_ids(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "deploy_spaces.sqlite3")
    created = store.get_or_create_deployment(
        "tms", "1.0.0", "ds_tms", semantic_space_ids=["sps_1", "sps_2"]
    )
    assert created.semantic_space_ids == ["sps_1", "sps_2"]

    fetched = store.get_deployment(created.deployment_id)
    assert fetched is not None
    assert fetched.semantic_space_ids == ["sps_1", "sps_2"]


def test_legacy_deployment_has_empty_semantic_space_ids(tmp_path: Path) -> None:
    """Deployments created without semantic_space_ids stay backward-compatible."""
    store = FieldMappingStore(tmp_path / "deploy_legacy.sqlite3")
    dep = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    assert dep.semantic_space_ids == []


def test_get_or_create_deployment_unique_per_pack_and_data_source(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "deploy_unique.sqlite3")
    d_tms = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    d_wms = store.get_or_create_deployment("wms", "1.0.0", "ds_tms")
    assert d_tms.deployment_id != d_wms.deployment_id


# ── Binding-aware deployment identity tests (P3 runtime-asset-projection task 2) ──
#
# Deployment identity is (pack_id, pack_version, data_source_id, environment,
# normalized semantic_space_ids) — see
# openspec/changes/runtime-asset-projection/specs/pack-deployment-instance/spec.md

def test_get_or_create_deployment_idempotent_with_reordered_spaces(tmp_path: Path) -> None:
    """Repeated equivalent deployment: the same semantic-space set supplied
    in a different order resolves the existing deployment, not a duplicate."""
    store = FieldMappingStore(tmp_path / "deploy_reorder.sqlite3")
    d1 = store.get_or_create_deployment(
        "tms", "1.0.0", "ds_tms", semantic_space_ids=["sps_1", "sps_2"]
    )
    d2 = store.get_or_create_deployment(
        "tms", "1.0.0", "ds_tms", semantic_space_ids=["sps_2", "sps_1"]
    )
    assert d1.deployment_id == d2.deployment_id
    assert len(store.list_deployments(pack_id="tms")) == 1


def test_get_or_create_deployment_distinct_for_different_spaces(tmp_path: Path) -> None:
    """Same pack version deployed to a different semantic-space set creates
    a distinct deployment with independent identity."""
    store = FieldMappingStore(tmp_path / "deploy_diff_spaces.sqlite3")
    d1 = store.get_or_create_deployment("tms", "1.0.0", "ds_tms", semantic_space_ids=["sps_1"])
    d2 = store.get_or_create_deployment("tms", "1.0.0", "ds_tms", semantic_space_ids=["sps_2"])
    assert d1.deployment_id != d2.deployment_id
    assert len(store.list_deployments(pack_id="tms")) == 2


def test_get_or_create_deployment_distinct_for_different_environments(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "deploy_diff_env.sqlite3")
    d_default = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    d_staging = store.get_or_create_deployment("tms", "1.0.0", "ds_tms", environment="staging")
    assert d_default.deployment_id != d_staging.deployment_id
    assert d_default.environment == "default"
    assert d_staging.environment == "staging"


def test_get_or_create_deployment_idempotent_same_environment(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "deploy_same_env.sqlite3")
    d1 = store.get_or_create_deployment("tms", "1.0.0", "ds_tms", environment="staging")
    d2 = store.get_or_create_deployment("tms", "1.0.0", "ds_tms", environment="staging")
    assert d1.deployment_id == d2.deployment_id


def test_get_or_create_deployment_distinct_for_different_pack_version(tmp_path: Path) -> None:
    """Exact pack version is part of deployment identity: a deployment stays
    pinned to its prior version rather than being reused by a request for a
    newer one (spec: Exact Deployment Version Lifecycle)."""
    store = FieldMappingStore(tmp_path / "deploy_diff_version.sqlite3")
    d_v1 = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    d_v2 = store.get_or_create_deployment("tms", "2.0.0", "ds_tms")
    assert d_v1.deployment_id != d_v2.deployment_id
    assert d_v1.pack_version == "1.0.0"
    assert d_v2.pack_version == "2.0.0"


def test_activation_is_independent_per_binding(tmp_path: Path) -> None:
    """Activating one deployment must not affect a sibling deployment of the
    same pack/data source bound to a different semantic space."""
    store = FieldMappingStore(tmp_path / "deploy_indep_activation.sqlite3")
    d1 = store.get_or_create_deployment("tms", "1.0.0", "ds_tms", semantic_space_ids=["sps_1"])
    d2 = store.get_or_create_deployment("tms", "1.0.0", "ds_tms", semantic_space_ids=["sps_2"])
    store.activate_deployment(d1.deployment_id, activated_by="admin")
    refreshed_1 = store.get_deployment(d1.deployment_id)
    refreshed_2 = store.get_deployment(d2.deployment_id)
    assert refreshed_1 is not None and refreshed_1.is_active is True
    assert refreshed_2 is not None and refreshed_2.is_active is False


def test_activation_survives_store_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "deployment_restart.sqlite3"
    store = FieldMappingStore(db_path)
    deployment = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    store.activate_deployment(deployment.deployment_id, activated_by="admin")

    reopened = FieldMappingStore(db_path)
    restored = reopened.get_deployment(deployment.deployment_id)
    assert restored is not None
    assert restored.is_active is True
    assert restored.activated_by == "admin"
    assert restored.activated_at is not None


def test_environment_defaults_to_default(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "deploy_env_default.sqlite3")
    dep = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    assert dep.environment == "default"


def test_legacy_deployment_row_migrates_with_default_environment(tmp_path: Path) -> None:
    """A deployment row created under the pre-P3 schema (no `environment` or
    `semantic_space_key` columns, unique only on pack_id+data_source_id)
    survives the additive migration: it keeps its identity and prior state,
    defaults to environment='default', is reusable under the new
    binding-aware key, and no longer blocks independent deployments to a
    different semantic space."""
    import sqlite3

    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE deployments (
                deployment_id TEXT PRIMARY KEY,
                pack_id TEXT NOT NULL,
                pack_version TEXT NOT NULL DEFAULT '1.0.0',
                data_source_id TEXT NOT NULL,
                license_ref TEXT,
                last_smoke_passed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                semantic_space_ids TEXT NOT NULL DEFAULT '[]',
                is_active INTEGER NOT NULL DEFAULT 0,
                activated_at TEXT,
                activated_by TEXT,
                UNIQUE (pack_id, data_source_id)
            )
        """)
        conn.execute(
            """
            INSERT INTO deployments
                (deployment_id, pack_id, pack_version, data_source_id,
                 created_at, updated_at, semantic_space_ids, is_active)
            VALUES ('dep_legacy1', 'tms', '1.0.0', 'ds_tms',
                    '2025-01-01T00:00:00+00:00', '2025-01-01T00:00:00+00:00',
                    '["sps_1"]', 1)
            """
        )
        conn.commit()

    store = FieldMappingStore(db_path)

    preserved = store.get_deployment("dep_legacy1")
    assert preserved is not None
    assert preserved.pack_id == "tms"
    assert preserved.data_source_id == "ds_tms"
    assert preserved.semantic_space_ids == ["sps_1"]
    assert preserved.environment == "default"
    assert preserved.is_active is True

    # Repeating the same effective binding resolves the legacy row.
    reused = store.get_or_create_deployment(
        "tms", "1.0.0", "ds_tms", semantic_space_ids=["sps_1"]
    )
    assert reused.deployment_id == "dep_legacy1"

    # A different space now creates an independent deployment — the old
    # (pack_id, data_source_id)-only UNIQUE constraint no longer blocks it.
    other = store.get_or_create_deployment(
        "tms", "1.0.0", "ds_tms", semantic_space_ids=["sps_2"]
    )
    assert other.deployment_id != "dep_legacy1"
    assert len(store.list_deployments(pack_id="tms")) == 2


def test_list_deployments_returns_all(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "deploy_list.sqlite3")
    store.get_or_create_deployment("tms", "1.0.0", "ds_a")
    store.get_or_create_deployment("wms", "1.0.0", "ds_b")
    all_deps = store.list_deployments()
    assert len(all_deps) == 2


def test_list_deployments_filtered_by_pack(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "deploy_filter.sqlite3")
    store.get_or_create_deployment("tms", "1.0.0", "ds_a")
    store.get_or_create_deployment("wms", "1.0.0", "ds_b")
    tms_deps = store.list_deployments(pack_id="tms")
    assert len(tms_deps) == 1
    assert tms_deps[0].pack_id == "tms"


def test_get_deployment_returns_none_for_unknown(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "deploy_miss.sqlite3")
    assert store.get_deployment("no-such-id") is None


def test_mark_smoke_result_affects_status(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "deploy_smoke.sqlite3")
    dep = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    # Add a mapping so status can advance beyond 'unvalidated'
    store.upsert(FieldMapping(
        mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="ds_tms", physical_table="T", physical_column="C",
        source="auto", status="active", deployment_id=dep.deployment_id,
    ))
    assert dep.validation_status != "ready"
    store.mark_smoke_result(dep.deployment_id, passed=True)
    refreshed = store.get_deployment(dep.deployment_id)
    assert refreshed is not None
    assert refreshed.validation_status == "ready"


# ── compute_coverage tests ─────────────────────────────────────────────

def test_compute_coverage_full(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "cov_full.sqlite3")
    dep = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    store.mark_smoke_result(dep.deployment_id, passed=True)
    for field_id, col in [("deliver_no", "DELIVER_NO"), ("plan_time", "PLAN_TIME")]:
        store.upsert(FieldMapping(
            mapping_id=f"m_{field_id}", pack_id="tms",
            standard_field_id=field_id, data_source_id="ds_tms",
            physical_table="T", physical_column=col,
            source="auto", status="active",
            deployment_id=dep.deployment_id,
        ))
    coverage, status, reasons = store.compute_coverage(
        dep.deployment_id, ["deliver_no", "plan_time"]
    )
    assert coverage == 1.0
    assert status == "ready"
    assert reasons == []


def test_compute_coverage_partial(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "cov_partial.sqlite3")
    dep = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    store.upsert(FieldMapping(
        mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="ds_tms", physical_table="T", physical_column="C",
        source="auto", status="active", deployment_id=dep.deployment_id,
    ))
    coverage, status, reasons = store.compute_coverage(
        dep.deployment_id, ["deliver_no", "plan_time"]
    )
    assert coverage == 0.5
    assert status == "incomplete"
    assert any("plan_time" in r for r in reasons)


def test_compute_coverage_smoke_failed(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "cov_smoke_fail.sqlite3")
    dep = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    store.mark_smoke_result(dep.deployment_id, passed=False)
    store.upsert(FieldMapping(
        mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="ds_tms", physical_table="T", physical_column="C",
        source="auto", status="active", deployment_id=dep.deployment_id,
    ))
    coverage, status, reasons = store.compute_coverage(
        dep.deployment_id, ["deliver_no"]
    )
    assert coverage == 1.0
    assert status == "failed"
    assert any("smoke" in r.lower() for r in reasons)


def test_compute_coverage_no_required_fields(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "cov_empty.sqlite3")
    dep = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    coverage, status, reasons = store.compute_coverage(dep.deployment_id, [])
    assert coverage == 1.0
    assert status == "ready"


# ── compute_coverage_from_spaces tests (task 5.4, corrected 2026-07-09) ──
#
# Coverage measures whether the pack's *required standard fields* are
# actually mapped (active FieldMapping -> confirmed in-space target), not
# how curated the space itself is. See
# .design/asset_semantic_space_harness_operating_model.md §9.

def _make_space(field_specs: list[tuple[str, str, str | None]]) -> "SemanticSpace":
    """field_specs: list of (physical_table, physical_column, status)."""
    from sq_bi_contracts.semantic_profile import (
        SemanticEntity,
        SemanticField,
        SemanticSpace,
    )

    fields = [
        SemanticField(
            field_id=f"fld_{i}",
            entity_id="e1",
            physical_table=table,
            physical_column=column,
            business_name=f"字段{i}",
            origin="standard",
            status=status,
        )
        for i, (table, column, status) in enumerate(field_specs)
    ]
    entity = SemanticEntity(
        entity_id="e1", space_id="sp1", physical_table="delivery_order",
        business_name="发货单", fields=fields,
    )
    return SemanticSpace(space_id="sp1", snapshot_id="snap1", name="TMS 空间", entities=[entity])


def _map(deployment_id: str, standard_field_id: str, table: str, column: str) -> FieldMapping:
    return FieldMapping(
        mapping_id=f"m_{standard_field_id}", pack_id="tms",
        standard_field_id=standard_field_id, data_source_id="ds_tms",
        physical_table=table, physical_column=column,
        source="manual", status="active", deployment_id=deployment_id,
    )


def test_compute_coverage_from_spaces_all_required_mapped_and_confirmed(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "cov_spaces_ready.sqlite3")
    dep = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    store.mark_smoke_result(dep.deployment_id, passed=True)
    store.upsert(_map(dep.deployment_id, "deliver_no", "delivery_order", "col_0"))
    store.upsert(_map(dep.deployment_id, "apply_no", "delivery_order", "col_1"))
    space = _make_space([
        ("delivery_order", "col_0", "confirmed"),
        ("delivery_order", "col_1", "confirmed"),
    ])
    coverage, status, reasons = store.compute_coverage_from_spaces(
        dep.deployment_id, ["deliver_no", "apply_no"], [space]
    )
    assert coverage == 1.0
    assert status == "ready"
    assert reasons == []


def test_compute_coverage_from_spaces_missing_mapping(tmp_path: Path) -> None:
    """A required field with no FieldMapping at all is uncovered, even if
    the space has plenty of unrelated confirmed fields."""
    store = FieldMappingStore(tmp_path / "cov_spaces_missing.sqlite3")
    dep = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    store.upsert(_map(dep.deployment_id, "deliver_no", "delivery_order", "col_0"))
    space = _make_space([
        ("delivery_order", "col_0", "confirmed"),
        ("delivery_order", "col_1", "confirmed"),
    ])
    coverage, status, reasons = store.compute_coverage_from_spaces(
        dep.deployment_id, ["deliver_no", "apply_no"], [space]
    )
    assert coverage == 0.5
    assert status == "incomplete"
    assert any("apply_no" in r for r in reasons)


def test_compute_coverage_from_spaces_mapping_target_out_of_space(tmp_path: Path) -> None:
    """An active FieldMapping whose target isn't adopted into the bound
    space at all must not count as covered."""
    store = FieldMappingStore(tmp_path / "cov_spaces_out_of_scope.sqlite3")
    dep = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    store.upsert(_map(dep.deployment_id, "deliver_no", "other_table", "other_col"))
    space = _make_space([("delivery_order", "col_0", "confirmed")])
    coverage, status, reasons = store.compute_coverage_from_spaces(
        dep.deployment_id, ["deliver_no"], [space]
    )
    assert coverage == 0.0
    assert status == "unvalidated"


def test_compute_coverage_from_spaces_mapping_target_demoted(tmp_path: Path) -> None:
    """Space confirmation constrains a mapping: if the mapped target's field
    status is no longer 'confirmed' (pending/excluded/invalid), the mapping
    does not count even though it's active in field_mapping_store."""
    store = FieldMappingStore(tmp_path / "cov_spaces_demoted.sqlite3")
    dep = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    store.upsert(_map(dep.deployment_id, "deliver_no", "delivery_order", "col_0"))
    space = _make_space([("delivery_order", "col_0", "pending")])
    coverage, status, reasons = store.compute_coverage_from_spaces(
        dep.deployment_id, ["deliver_no"], [space]
    )
    assert coverage == 0.0
    assert status == "unvalidated"


def test_compute_coverage_from_spaces_empty_pack_requirements(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "cov_spaces_empty_reqs.sqlite3")
    dep = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    space = _make_space([("delivery_order", "col_0", "pending")])
    coverage, status, reasons = store.compute_coverage_from_spaces(dep.deployment_id, [], [space])
    assert coverage == 1.0
    assert status == "ready"


def test_compute_coverage_from_spaces_smoke_failed(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "cov_spaces_smoke_fail.sqlite3")
    dep = store.get_or_create_deployment("tms", "1.0.0", "ds_tms")
    store.mark_smoke_result(dep.deployment_id, passed=False)
    store.upsert(_map(dep.deployment_id, "deliver_no", "delivery_order", "col_0"))
    space = _make_space([("delivery_order", "col_0", "confirmed")])
    coverage, status, reasons = store.compute_coverage_from_spaces(
        dep.deployment_id, ["deliver_no"], [space]
    )
    assert coverage == 1.0
    assert status == "failed"
    assert any("smoke" in r.lower() for r in reasons)
