"""Unit tests for SemanticProfileStore."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sq_bi_contracts.semantic_profile import (
    EvidenceItem,
    EvidenceSource,
    FieldOrigin,
    ScanPhase,
    SemanticEntity,
    SemanticField,
    SemanticSpace,
    SemanticSpaceAdjustment,
    TableRecommendation,
)
from sq_bi_runtime.semantic_profile_store import SemanticProfileStore
from sq_bi_runtime.schema_scanner import ColumnMeta, TableMeta


@pytest.fixture
def store(tmp_path: Path) -> SemanticProfileStore:
    return SemanticProfileStore(tmp_path / "semantic_profile.db")


# ── Scan jobs ────────────────────────────────────────────────────────

def test_create_and_retrieve_scan_job(store: SemanticProfileStore) -> None:
    status = store.create_scan_job("ds_tms")
    assert status.scan_id.startswith("scan_")
    assert status.phase == ScanPhase.pending
    assert status.data_source_id == "ds_tms"

    retrieved = store.get_scan_status(status.scan_id)
    assert retrieved is not None
    assert retrieved.scan_id == status.scan_id


def test_update_scan_job_to_phase_one(store: SemanticProfileStore) -> None:
    status = store.create_scan_job("ds_tms")
    updated = store.update_scan_job(
        status.scan_id,
        ScanPhase.phase_one,
        progress_message="Scanning metadata…",
        table_count=80,
    )
    assert updated is not None
    assert updated.phase == ScanPhase.phase_one
    assert updated.table_count == 80
    assert updated.progress_message == "Scanning metadata…"


def test_update_scan_job_done_sets_completed_at(store: SemanticProfileStore) -> None:
    status = store.create_scan_job("ds_tms")
    updated = store.update_scan_job(status.scan_id, ScanPhase.done, table_count=50)
    assert updated is not None
    assert updated.completed_at is not None


def test_update_scan_job_failed_records_error(store: SemanticProfileStore) -> None:
    status = store.create_scan_job("ds_tms")
    updated = store.update_scan_job(
        status.scan_id, ScanPhase.failed, error="Connection timed out"
    )
    assert updated is not None
    assert updated.phase == ScanPhase.failed
    assert updated.error == "Connection timed out"


def test_get_missing_scan_job_returns_none(store: SemanticProfileStore) -> None:
    assert store.get_scan_status("scan_nonexistent") is None


# ── Snapshots ─────────────────────────────────────────────────────────

def test_create_snapshot_version_increments(store: SemanticProfileStore) -> None:
    snap1 = store.create_snapshot("ds_tms")
    snap2 = store.create_snapshot("ds_tms")
    assert snap1.version == 1
    assert snap2.version == 2


def test_get_latest_snapshot_returns_highest_version(store: SemanticProfileStore) -> None:
    store.create_snapshot("ds_tms")
    store.create_snapshot("ds_tms")
    latest = store.get_latest_snapshot("ds_tms")
    assert latest is not None
    assert latest.version == 2


def test_get_latest_snapshot_missing_returns_none(store: SemanticProfileStore) -> None:
    assert store.get_latest_snapshot("ds_missing") is None


def test_update_snapshot_sets_phase_and_counts(store: SemanticProfileStore) -> None:
    snap = store.create_snapshot("ds_tms")
    store.update_snapshot(
        snap.snapshot_id,
        scan_phase=ScanPhase.done,
        scanned_schemas=["TMS_SCHEMA"],
        table_count=100,
        included_table_count=70,
        excluded_table_count=30,
        recommendation_counts={"recommended_include": 60, "possibly_relevant": 10},
    )
    refreshed = store.get_snapshot(snap.snapshot_id)
    assert refreshed is not None
    assert refreshed.scan_phase == ScanPhase.done
    assert refreshed.table_count == 100
    assert refreshed.recommendation_counts["recommended_include"] == 60
    assert refreshed.completed_at is not None


def test_prior_versions_remain_after_new_snapshot(store: SemanticProfileStore) -> None:
    snap1 = store.create_snapshot("ds_tms")
    store.update_snapshot(snap1.snapshot_id, scan_phase=ScanPhase.done, table_count=50)
    snap2 = store.create_snapshot("ds_tms")
    store.update_snapshot(snap2.snapshot_id, scan_phase=ScanPhase.done, table_count=55)

    v1 = store.get_snapshot(snap1.snapshot_id)
    assert v1 is not None
    assert v1.version == 1
    assert v1.table_count == 50


# ── Spaces, entities, fields ──────────────────────────────────────────

def _make_field(fid: str, entity_id: str, origin: FieldOrigin = FieldOrigin.inferred) -> SemanticField:
    return SemanticField(
        field_id=fid,
        entity_id=entity_id,
        physical_table="T",
        physical_column=fid.upper(),
        business_name=f"业务名 {fid}",
        origin=origin,
        confidence=0.85,
        evidence=[EvidenceItem(source=EvidenceSource.name, detail="name match")],
    )


def _make_entity(eid: str, sid: str) -> SemanticEntity:
    return SemanticEntity(
        entity_id=eid,
        space_id=sid,
        physical_table="HR_DELIVER_FORM",
        business_name="运单实体",
        recommendation=TableRecommendation.recommended_include,
        fields=[_make_field(f"fld_{eid}_1", eid), _make_field(f"fld_{eid}_2", eid)],
    )


def _make_space(sid: str, snapshot_id: str) -> SemanticSpace:
    return SemanticSpace(
        space_id=sid,
        snapshot_id=snapshot_id,
        name="运输管理",
        entities=[_make_entity(f"ent_{sid}_1", sid), _make_entity(f"ent_{sid}_2", sid)],
    )


def test_save_and_load_profile(store: SemanticProfileStore) -> None:
    snap = store.create_snapshot("ds_tms")
    spaces = [_make_space("sp_001", snap.snapshot_id)]
    store.save_spaces(snap.snapshot_id, spaces)
    store.update_snapshot(snap.snapshot_id, scan_phase=ScanPhase.done)

    profile = store.load_profile("ds_tms")
    assert profile is not None
    assert len(profile.spaces) == 1
    assert profile.spaces[0].name == "运输管理"
    assert len(profile.spaces[0].entities) == 2
    assert len(profile.spaces[0].entities[0].fields) == 2


def test_field_evidence_round_trips(store: SemanticProfileStore) -> None:
    snap = store.create_snapshot("ds_tms")
    field = SemanticField(
        field_id="fld_ev_test",
        entity_id="ent_001",
        physical_table="T",
        physical_column="COL",
        business_name="测试字段",
        origin=FieldOrigin.inferred,
        confidence=0.72,
        evidence=[
            EvidenceItem(source=EvidenceSource.name, detail="column name hint"),
            EvidenceItem(source=EvidenceSource.comment, detail="DB comment"),
            EvidenceItem(source=EvidenceSource.ai_inference),
        ],
    )
    entity = SemanticEntity(
        entity_id="ent_001",
        space_id="sp_001",
        physical_table="T",
        business_name="测试实体",
        fields=[field],
    )
    space = SemanticSpace(
        space_id="sp_001",
        snapshot_id=snap.snapshot_id,
        name="测试空间",
        entities=[entity],
    )
    store.save_spaces(snap.snapshot_id, [space])
    store.update_snapshot(snap.snapshot_id, scan_phase=ScanPhase.done)

    profile = store.load_profile("ds_tms")
    assert profile is not None
    loaded_field = profile.spaces[0].entities[0].fields[0]
    assert loaded_field.confidence == 0.72
    assert len(loaded_field.evidence) == 3
    sources = {ev.source for ev in loaded_field.evidence}
    assert EvidenceSource.name in sources
    assert EvidenceSource.ai_inference in sources


def test_load_profile_hydrates_missing_field_type_and_filters_unproven_sample(
    store: SemanticProfileStore,
) -> None:
    snap = store.create_snapshot("ds_tms")
    store.save_catalog(
        snap.snapshot_id,
        [
            TableMeta(
                name="EC_TRANSPORT_APPLY",
                columns=[
                    ColumnMeta(
                        name="STATUS",
                        data_type="NUMBER",
                        comment="运输申请状态",
                    ),
                ],
            )
        ],
    )
    field = SemanticField(
        field_id="fld_status",
        entity_id="ent_apply",
        physical_table="EC_TRANSPORT_APPLY",
        physical_column="STATUS",
        business_name="运输申请状态",
        origin=FieldOrigin.inferred,
        semantic_role="dimension",
        evidence=[
            EvidenceItem(source=EvidenceSource.sample),
            EvidenceItem(source=EvidenceSource.name),
            EvidenceItem(source=EvidenceSource.ai_inference),
        ],
    )
    entity = SemanticEntity(
        entity_id="ent_apply",
        space_id="sp_apply",
        physical_table="EC_TRANSPORT_APPLY",
        business_name="运输申请",
        fields=[field],
    )
    store.save_spaces(
        snap.snapshot_id,
        [SemanticSpace(space_id="sp_apply", snapshot_id=snap.snapshot_id, name="运输申请", entities=[entity])],
    )
    store.update_snapshot(snap.snapshot_id, scan_phase=ScanPhase.done)

    profile = store.load_profile("ds_tms")
    assert profile is not None
    loaded = profile.spaces[0].entities[0].fields[0]
    assert loaded.data_type == "NUMBER"
    sources = {ev.source for ev in loaded.evidence}
    assert EvidenceSource.sample not in sources
    details_by_source = {ev.source: ev.detail for ev in loaded.evidence}
    assert "EC_TRANSPORT_APPLY.STATUS" in (details_by_source[EvidenceSource.name] or "")
    assert "dimension" in (details_by_source[EvidenceSource.ai_inference] or "")


def test_conflicting_candidates_retained(store: SemanticProfileStore) -> None:
    """Multiple fields for same physical column (candidates) are all kept."""
    snap = store.create_snapshot("ds_tms")
    f1 = SemanticField(
        field_id="fld_c1",
        entity_id="ent_001",
        physical_table="T",
        physical_column="STATUS",
        business_name="配送状态",
        origin=FieldOrigin.inferred,
        confidence=0.88,
        is_candidate=True,
    )
    f2 = SemanticField(
        field_id="fld_c2",
        entity_id="ent_001",
        physical_table="T",
        physical_column="STATUS",
        business_name="运单状态",
        origin=FieldOrigin.inferred,
        confidence=0.72,
        is_candidate=True,
    )
    entity = SemanticEntity(
        entity_id="ent_001",
        space_id="sp_001",
        physical_table="T",
        business_name="运单",
        fields=[f1, f2],
    )
    space = SemanticSpace(
        space_id="sp_001", snapshot_id=snap.snapshot_id, name="运输", entities=[entity]
    )
    store.save_spaces(snap.snapshot_id, [space])
    store.update_snapshot(snap.snapshot_id, scan_phase=ScanPhase.done)

    profile = store.load_profile("ds_tms")
    assert profile is not None
    fields = profile.spaces[0].entities[0].fields
    assert len(fields) == 2
    assert all(f.is_candidate for f in fields)


def test_resave_replaces_old_spaces(store: SemanticProfileStore) -> None:
    """save_spaces replaces previous spaces for the same snapshot_id."""
    snap = store.create_snapshot("ds_tms")
    store.save_spaces(snap.snapshot_id, [_make_space("sp_001", snap.snapshot_id)])
    store.save_spaces(snap.snapshot_id, [
        _make_space("sp_new_a", snap.snapshot_id),
        _make_space("sp_new_b", snap.snapshot_id),
    ])
    store.update_snapshot(snap.snapshot_id, scan_phase=ScanPhase.done)

    profile = store.load_profile("ds_tms")
    assert profile is not None
    assert len(profile.spaces) == 2
    space_ids = {s.space_id for s in profile.spaces}
    assert "sp_001" not in space_ids


# ── Space adjustments ─────────────────────────────────────────────────

def test_apply_space_adjustment_accepted(store: SemanticProfileStore) -> None:
    snap = store.create_snapshot("ds_tms")
    space = SemanticSpace(
        space_id="sp_adj", snapshot_id=snap.snapshot_id, name="运输管理"
    )
    store.save_spaces(snap.snapshot_id, [space])
    store.update_snapshot(snap.snapshot_id, scan_phase=ScanPhase.done)

    store.apply_space_adjustments(
        snap.snapshot_id,
        [SemanticSpaceAdjustment(space_id="sp_adj", accepted=True, name="运输管理（已确认）")],
    )

    profile = store.load_profile("ds_tms")
    assert profile is not None
    s = profile.spaces[0]
    assert s.accepted is True
    assert s.name == "运输管理（已确认）"


# ── Documents ─────────────────────────────────────────────────────────

def test_create_and_list_documents(store: SemanticProfileStore) -> None:
    doc = store.create_document(
        "ds_tms", "数据字典.xlsx", "application/vnd.ms-excel", 204800
    )
    assert doc.document_id.startswith("doc_")
    assert doc.upload_status == "pending"

    docs = store.list_documents("ds_tms")
    assert len(docs) == 1
    assert docs[0].filename == "数据字典.xlsx"


def test_update_document_status(store: SemanticProfileStore) -> None:
    doc = store.create_document("ds_tms", "dict.pdf", "application/pdf", 1024)
    store.update_document_status(doc.document_id, "ready")
    docs = store.list_documents("ds_tms")
    assert docs[0].upload_status == "ready"


def test_document_parse_failure_marked_failed(store: SemanticProfileStore) -> None:
    doc = store.create_document("ds_tms", "bad.bin", "application/octet-stream", 512)
    store.update_document_status(doc.document_id, "failed", error="Unsupported format")
    docs = store.list_documents("ds_tms")
    assert docs[0].upload_status == "failed"
    assert docs[0].error == "Unsupported format"


def test_no_documents_returns_empty_list(store: SemanticProfileStore) -> None:
    assert store.list_documents("ds_no_docs") == []


def test_get_document_by_id(store: SemanticProfileStore) -> None:
    doc = store.create_document("ds_tms", "dict.pdf", "application/pdf", 1024)
    fetched = store.get_document(doc.document_id)
    assert fetched is not None
    assert fetched.filename == "dict.pdf"
    assert store.get_document("doc_missing") is None


def test_delete_document_removes_it(store: SemanticProfileStore) -> None:
    doc = store.create_document("ds_tms", "dict.pdf", "application/pdf", 1024)
    assert store.delete_document(doc.document_id) is True
    assert store.list_documents("ds_tms") == []
    assert store.get_document(doc.document_id) is None


def test_delete_unknown_document_returns_false(store: SemanticProfileStore) -> None:
    assert store.delete_document("doc_missing") is False
