"""Portable enterprise pack persistence tests."""

from __future__ import annotations

import sqlite3

import pytest

from sq_bi_contracts.enterprise_pack import (
    CreateEnterprisePackRequest,
    EnterprisePackDraft,
    ExtensionLayerState,
    PackCreateMode,
    PackEnterpriseField,
    PackVersionState,
)
from sq_bi_contracts.field_mount import FieldMapping
from sq_bi_runtime.enterprise_pack_store import EnterprisePackStore


@pytest.fixture
def store(tmp_path):
    return EnterprisePackStore(tmp_path / "enterprise_packs.db")


def _request(**updates: object) -> CreateEnterprisePackRequest:
    values: dict[str, object] = {"name": "运输扩展", "created_by": "tester"}
    values.update(updates)
    return CreateEnterprisePackRequest(**values)


def test_blank_definition_is_portable(store):
    pack = store.create(_request(business_context="用于运输履约管理"))
    assert pack.version_state is PackVersionState.draft
    assert "data_source_id" not in pack.model_dump()
    assert pack.business_context == "用于运输履约管理"
    assert pack.draft == EnterprisePackDraft()


def test_enterprise_pack_can_be_deleted(store):
    pack = store.create(_request())
    store.delete(pack.pack_id)
    assert store.get(pack.pack_id) is None


def test_extension_persists_only_pinned_base_and_delta(store):
    pack = store.create(_request(
        mode=PackCreateMode.extend_official,
        base_pack_id="tms",
        base_pack_version="1.2.0",
    ))
    assert pack.base_pack_id == "tms"
    assert pack.base_pack_version == "1.2.0"
    assert pack.draft.fields == []
    addition = PackEnterpriseField(field_id="project_name", business_name="项目名称", data_type="TEXT")
    updated = store.update_draft(pack.pack_id, EnterprisePackDraft(fields=[addition]))
    assert [item.field_id for item in updated.draft.fields] == ["project_name"]


def test_existing_connection_bound_row_migrates_to_review_evidence(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE enterprise_packs (
                pack_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
                data_source_id TEXT NOT NULL, version TEXT NOT NULL,
                version_state TEXT NOT NULL, base_pack_id TEXT,
                base_pack_version TEXT, create_mode TEXT NOT NULL,
                draft_json TEXT NOT NULL, created_by TEXT NOT NULL,
                created_at TEXT, updated_at TEXT
            )
        """)
        conn.execute("""
            INSERT INTO enterprise_packs VALUES
            ('legacy', '旧包', NULL, 'oracle_tms', '0.1.0', 'draft', NULL, NULL,
             'blank', '{}', 'tester', NULL, NULL)
        """)
    store = EnterprisePackStore(path)
    migrated = store.get("legacy")
    assert migrated is not None
    assert migrated.legacy_review_required is True
    assert migrated.legacy_authoring_evidence["data_source_id"] == "oracle_tms"


def test_retired_create_mode_migrates_to_blank_with_evidence(tmp_path):
    """Rows created under the old four-mode system (clone_enterprise,
    ai_from_profile) can no longer be represented by PackCreateMode. The
    migration must fold them into a review-required blank draft instead of
    crashing on load, preserving the original mode as evidence."""
    path = tmp_path / "legacy_modes.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE enterprise_packs (
                pack_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
                data_source_id TEXT NOT NULL, version TEXT NOT NULL,
                version_state TEXT NOT NULL, base_pack_id TEXT,
                base_pack_version TEXT, create_mode TEXT NOT NULL,
                draft_json TEXT NOT NULL, created_by TEXT NOT NULL,
                created_at TEXT, updated_at TEXT
            )
        """)
        conn.execute("""
            INSERT INTO enterprise_packs VALUES
            ('legacy_clone', '旧克隆包', NULL, 'oracle_tms', '0.1.0', 'draft', NULL, NULL,
             'clone_enterprise', '{}', 'tester', NULL, NULL)
        """)
        conn.execute("""
            INSERT INTO enterprise_packs VALUES
            ('legacy_ai', '旧AI草稿包', NULL, '', '0.1.0', 'draft', NULL, NULL,
             'ai_from_profile', '{}', 'tester', NULL, NULL)
        """)
    store = EnterprisePackStore(path)

    migrated_clone = store.get("legacy_clone")
    assert migrated_clone is not None
    assert migrated_clone.create_mode is PackCreateMode.blank
    assert migrated_clone.legacy_review_required is True
    assert migrated_clone.legacy_authoring_evidence["create_mode"] == "clone_enterprise"
    assert migrated_clone.legacy_authoring_evidence["data_source_id"] == "oracle_tms"

    migrated_ai = store.get("legacy_ai")
    assert migrated_ai is not None
    assert migrated_ai.create_mode is PackCreateMode.blank
    assert migrated_ai.legacy_review_required is True
    assert migrated_ai.legacy_authoring_evidence["create_mode"] == "ai_from_profile"

    # Re-opening the store (a second migration pass) must be idempotent.
    reopened = EnterprisePackStore(path).get("legacy_clone")
    assert reopened is not None
    assert reopened.create_mode is PackCreateMode.blank
    assert reopened.legacy_review_required is True


def test_publish_then_edit_uses_next_draft_same_identity(store):
    pack = store.create(_request())
    store.publish(pack.pack_id, version="1.0.0")
    forked = store.fork_for_edit(pack.pack_id)
    assert forked.pack_id == pack.pack_id
    assert forked.version == "1.0.1"
    assert forked.version_state is PackVersionState.draft


def test_reuse_active_base_mappings_into_extension_deployment(tmp_path):
    from sq_bi_runtime.field_mapping_store import FieldMappingStore

    mappings = FieldMappingStore(tmp_path / "mappings.db")
    base = mappings.get_or_create_deployment("tms", "1.2.0", "oracle", semantic_space_ids=["sps_tms"])
    extension = mappings.get_or_create_deployment("ep_extension", "0.1.0", "oracle", semantic_space_ids=["sps_tms"])
    mappings.upsert(FieldMapping(
        mapping_id="map_base", pack_id="tms", standard_field_id="shipment_no",
        data_source_id="oracle", physical_table="shipment", physical_column="shipment_no",
        deployment_id=base.deployment_id,
    ))
    assert mappings.reuse_deployment_mappings(base.deployment_id, extension.deployment_id, "ep_extension") == 1
    reused = mappings.get_mappings_dict_by_deployment(extension.deployment_id)
    assert reused["shipment_no"].physical_table == "shipment"
    assert reused["shipment_no"].pack_id == "ep_extension"


def test_base_owns_exactly_one_extension_layer_and_keeps_audit(store):
    first = store.get_or_create_extension(
        base_pack_id="tms", base_pack_version="1.0.0", base_kind="official", created_by="u1"
    )
    second = store.get_or_create_extension(
        base_pack_id="tms", base_pack_version="1.0.0", base_kind="official", created_by="u2"
    )
    assert first.extension_id == second.extension_id
    updated = store.update_extension_draft(
        first.extension_id,
        EnterprisePackDraft(fields=[PackEnterpriseField(
            field_id="project_name", business_name="项目名称", data_type="TEXT"
        )]),
        updated_by="u1",
    )
    assert updated.draft.fields[0].field_id == "project_name"
    assert updated.audit[-1]["action"] == "edited"
    assert store.publish_extension(first.extension_id, actor="u1").state is ExtensionLayerState.active


def test_extension_rejects_nesting_and_active_deployment_deletion(store):
    layer = store.get_or_create_extension(
        base_pack_id="tms", base_pack_version="1.0.0", base_kind="official"
    )
    with pytest.raises(ValueError, match="cannot own"):
        store.get_or_create_extension(
            base_pack_id=layer.extension_id, base_pack_version="0.1.0", base_kind="enterprise"
        )
    with pytest.raises(ValueError, match="active deployments"):
        store.delete_extension(layer.extension_id, active_deployment_ids=["dep_active"])
    assert store.delete_extension(layer.extension_id, active_deployment_ids=[])
