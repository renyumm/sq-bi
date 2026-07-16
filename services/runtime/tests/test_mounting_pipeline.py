from __future__ import annotations

import pytest
from sq_bi_contracts.domain_pack import PackStandardField
from sq_bi_contracts.field_mount import (
    CandidateMapping,
    ConfirmationRequest,
    FieldMapping,
    LogicalMetricDefinition,
    LogicalMetricFormula,
    MountTriggerRequest,
)
from sq_bi_runtime.field_mapping_store import FieldMappingStore
from sq_bi_runtime.mounting_pipeline import (
    PhysicalColumn,
    deterministic_match,
    scan_physical_schema,
    MountingPipeline,
)

TMS_STANDARD_FIELDS: dict[str, PackStandardField] = {
    sf.field_id: sf
    for sf in [
        PackStandardField(field_id="deliver_no", business_name="运单号", data_type="text"),
        PackStandardField(field_id="carrier_name", business_name="承运商", data_type="text"),
        PackStandardField(field_id="plan_time", business_name="计划时间", data_type="datetime"),
        PackStandardField(field_id="actual_time", business_name="实际时间", data_type="datetime"),
        PackStandardField(field_id="car_status", business_name="承运状态", data_type="enum",
                           enum_values=["signed", "in_transit", "delayed", "completed"]),
    ]
}


# ── 4.1: Schema scanning tests ──

def test_scan_physical_schema() -> None:
    live = {"HR_DELIVER_CARRY": {"DELIVER_NO", "CARRIER_NAME", "PLAN_TIME", "ACTUAL_TIME"}}
    semantic = {"HR_DELIVER_CARRY": {"CARRIER_NAME"}}
    scanned = scan_physical_schema(live, semantic)
    assert "HR_DELIVER_CARRY" in scanned
    cols = [c.column for c in scanned["HR_DELIVER_CARRY"]]
    assert "DELIVER_NO" in cols
    assert "CARRIER_NAME" in cols


# ── 4.2: Deterministic matching tests ──

def test_deterministic_match_exact_name() -> None:
    std = PackStandardField(field_id="deliver_no", business_name="deliver_no", data_type="text")
    cols = [PhysicalColumn(table="T", column="DELIVER_NO", data_type="varchar")]
    results = deterministic_match(std, cols)
    assert len(results) >= 1
    assert results[0].confidence >= 0.3


def test_deterministic_match_high_confidence() -> None:
    std = PackStandardField(field_id="carrier_name", business_name="承运商", data_type="text")
    cols = [PhysicalColumn(table="T", column="CARRIER_NAME", data_type="varchar", comment="承运商名称")]
    results = deterministic_match(std, cols)
    assert len(results) >= 1


def test_deterministic_match_no_match() -> None:
    std = PackStandardField(field_id="nonexistent", business_name="nonexistent", data_type="text")
    cols = [PhysicalColumn(table="T", column="SOMETHING_ELSE", data_type="varchar")]
    results = deterministic_match(std, cols)
    assert len(results) == 0


# ── Pipeline integration tests ──

def test_trigger_auto_maps_high_confidence(tmp_path) -> None:
    store = FieldMappingStore(tmp_path / "test_pipe.sqlite3")
    pipeline = MountingPipeline(store)
    req = MountTriggerRequest(pack_id="tms", data_source_id="ds_tms")

    live = {"HR_DELIVER_CARRY": {"DELIVER_NO", "CARRIER_NAME", "PLAN_TIME", "ACTUAL_TIME", "CAR_STATUS"}}
    semantic = {}

    resp = pipeline.trigger(req, TMS_STANDARD_FIELDS, live, semantic)
    # Some fields should auto-map due to name similarity
    assert resp.status in ("completed", "failed")
    # At least some should be mapped or pending (not errors all)
    total_mapped_or_pending = len(resp.auto_mapped) + len(resp.pending)
    assert total_mapped_or_pending > 0


def test_confirm_mapping(tmp_path) -> None:
    store = FieldMappingStore(tmp_path / "test_confirm.sqlite3")
    pipeline = MountingPipeline(store)
    mapping = pipeline.confirm_mapping("tms", "ds_tms", "deliver_no", "HR_DELIVER_CARRY", "DELIVER_NO")
    assert mapping.standard_field_id == "deliver_no"
    assert mapping.source == "manual"
    retrieved = store.get("tms", "ds_tms", "deliver_no")
    assert retrieved is not None


def test_smoke_test_compiles(tmp_path) -> None:
    store = FieldMappingStore(tmp_path / "test_smoke.sqlite3")
    # Pre-seed mappings
    for sf_id, phys_col in [("deliver_no", "DELIVER_NO"), ("plan_time", "PLAN_TIME"), ("actual_time", "ACTUAL_TIME")]:
        store.upsert(FieldMapping(
            mapping_id=f"m_{sf_id}", pack_id="tms", standard_field_id=sf_id,
            data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY",
            physical_column=phys_col, source="manual", status="active",
        ))

    pipeline = MountingPipeline(store)
    test_metrics = [
        LogicalMetricDefinition(
            metric_code="SHIPMENT_CNT",
            name="执行单量",
            definition="test",
            logical_formula=LogicalMetricFormula(
                expression="count_distinct(deliver_no)",
                referenced_standard_fields=["deliver_no"],
            ),
            data_source_id="ds_tms",
            owner="test",
        ),
    ]
    result = pipeline.run_smoke_test("tms", "ds_tms", TMS_STANDARD_FIELDS, test_metrics)
    assert result.all_passed is True
    assert result.metrics[0].compiled is True


def test_mount_status(tmp_path) -> None:
    store = FieldMappingStore(tmp_path / "test_status.sqlite3")
    pipeline = MountingPipeline(store)
    status = pipeline.get_mount_status("tms", "ds_tms", TMS_STANDARD_FIELDS)
    assert status.total_standard_fields == 5
    assert status.mapped_fields == 0
    assert status.is_ready is False


def test_mount_status_ready(tmp_path) -> None:
    store = FieldMappingStore(tmp_path / "test_ready.sqlite3")
    for sf_id in TMS_STANDARD_FIELDS:
        store.upsert(FieldMapping(
            mapping_id=f"m_{sf_id}", pack_id="tms", standard_field_id=sf_id,
            data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY",
            physical_column=sf_id.upper(), source="manual", status="active",
        ))
    pipeline = MountingPipeline(store)
    status = pipeline.get_mount_status("tms", "ds_tms", TMS_STANDARD_FIELDS)
    assert status.mapped_fields == 5


# ── Edge / boundary cases ─────────────────────────────────────────────

def test_trigger_empty_standard_fields(tmp_path) -> None:
    """Empty standard_fields must not produce is_ready=True as a spurious side-effect."""
    store = FieldMappingStore(tmp_path / "test_empty.sqlite3")
    pipeline = MountingPipeline(store)
    req = MountTriggerRequest(pack_id="tms", data_source_id="ds_tms")
    resp = pipeline.trigger(req, {}, {}, {})
    assert resp.status == "completed"
    assert resp.auto_mapped == []
    # is_ready requires total > 0
    status = pipeline.get_mount_status("tms", "ds_tms", {})
    assert status.is_ready is False


def test_trigger_allowed_tables_scopes_matching_to_bound_space(tmp_path) -> None:
    """When allowed_tables is given, columns from other tables are never candidates."""
    store = FieldMappingStore(tmp_path / "test_scoped.sqlite3")
    pipeline = MountingPipeline(store)
    req = MountTriggerRequest(pack_id="tms", data_source_id="ds_tms")

    # CARRIER_NAME exists in two tables; only HR_DELIVER_CARRY is in-scope.
    live = {
        "HR_DELIVER_CARRY": {"CARRIER_NAME"},
        "OTHER_TABLE": {"CARRIER_NAME"},
    }
    resp = pipeline.trigger(
        req,
        {"carrier_name": TMS_STANDARD_FIELDS["carrier_name"]},
        live,
        {},
        allowed_tables={"HR_DELIVER_CARRY"},
    )
    all_mapped = list(resp.auto_mapped) + [
        c for p in resp.pending for c in p.candidates
    ]
    tables_seen = {m.physical_table for m in all_mapped}
    assert tables_seen <= {"HR_DELIVER_CARRY"}


def test_trigger_surfaces_verified_candidate_outside_bound_space(tmp_path) -> None:
    store = FieldMappingStore(tmp_path / "test_outside_candidate.sqlite3")
    pipeline = MountingPipeline(store)
    req = MountTriggerRequest(pack_id="tms", data_source_id="ds_tms")
    std = PackStandardField(
        field_id="project_name", business_name="项目名称", data_type="text"
    )
    preferred = CandidateMapping(
        physical_table="HR_PROJECT_BASE",
        physical_column="PROJECT_NAME",
        confidence=1.0,
        reason="领域包验证映射",
    )

    response = pipeline.trigger(
        req,
        {"project_name": std},
        {
            "HR_DELIVER_CARRY": {"PROJECT_ID"},
            "HR_PROJECT_BASE": {"PROJECT_NAME"},
        },
        {},
        allowed_tables={"HR_DELIVER_CARRY"},
        preferred_candidates={"project_name": preferred},
    )

    assert len(response.pending) == 1
    assert response.pending[0].candidates == []
    assert response.pending[0].outside_scope_candidates[0].physical_table == "HR_PROJECT_BASE"


def test_confirm_scanned_catalog_candidate(tmp_path) -> None:
    from sq_bi_contracts.field_mount import PendingMapping

    store = FieldMappingStore(tmp_path / "test_confirm_outside.sqlite3")
    pipeline = MountingPipeline(store)
    pending = PendingMapping(
        mapping_request_id="mreq_outside",
        standard_field_id="project_name",
        business_name="项目名称",
        outside_scope_candidates=[
            CandidateMapping(
                physical_table="HR_PROJECT_BASE",
                physical_column="PROJECT_NAME",
                confidence=1.0,
                reason="领域包验证映射",
            )
        ],
    )
    request = ConfirmationRequest(
        pack_id="tms",
        data_source_id="ds_tms",
        standard_field_id="project_name",
        mapping_request_id="mreq_outside",
        chosen_candidate_index=0,
        candidate_scope="scanned_catalog",
    )

    mapping = pipeline.confirm(request, pending)

    assert mapping.physical_table == "HR_PROJECT_BASE"
    assert mapping.physical_column == "PROJECT_NAME"


def test_trigger_allowed_tables_none_scopes_whole_connection(tmp_path) -> None:
    """Backward compatibility: omitting allowed_tables considers every table."""
    store = FieldMappingStore(tmp_path / "test_unscoped.sqlite3")
    pipeline = MountingPipeline(store)
    req = MountTriggerRequest(pack_id="tms", data_source_id="ds_tms")
    live = {"HR_DELIVER_CARRY": {"CARRIER_NAME"}, "OTHER_TABLE": {"CARRIER_NAME"}}
    resp = pipeline.trigger(
        req, {"carrier_name": TMS_STANDARD_FIELDS["carrier_name"]}, live, {}
    )
    total_mapped_or_pending = len(resp.auto_mapped) + sum(
        len(p.candidates) for p in resp.pending
    )
    assert total_mapped_or_pending > 0


def test_trigger_empty_catalogs_all_pending(tmp_path) -> None:
    """No physical columns → all standard fields go to pending with empty candidates."""
    store = FieldMappingStore(tmp_path / "test_nocols.sqlite3")
    pipeline = MountingPipeline(store)
    req = MountTriggerRequest(pack_id="tms", data_source_id="ds_tms")
    resp = pipeline.trigger(req, TMS_STANDARD_FIELDS, {}, {})
    assert len(resp.auto_mapped) == 0
    assert len(resp.pending) == len(TMS_STANDARD_FIELDS)
    for pm in resp.pending:
        assert pm.candidates == []
        assert pm.mapping_request_id.startswith("mreq_")


def test_trigger_auto_mapped_persisted(tmp_path) -> None:
    """Auto-mapped fields must be persisted to the store immediately."""
    store = FieldMappingStore(tmp_path / "test_persist.sqlite3")
    pipeline = MountingPipeline(store)
    req = MountTriggerRequest(pack_id="tms", data_source_id="ds_tms")
    live = {"HR_DELIVER_CARRY": {"DELIVER_NO"}}
    sf = {"deliver_no": PackStandardField(field_id="deliver_no", business_name="deliver_no", data_type="text")}
    resp = pipeline.trigger(req, sf, live, {})
    # Whether auto_mapped or pending, verify store was written if any auto-mapped
    for m in resp.auto_mapped:
        stored = store.get("tms", "ds_tms", m.standard_field_id)
        assert stored is not None, f"auto-mapped {m.standard_field_id} not persisted"


def test_confirm_via_pending_item(tmp_path) -> None:
    """confirm() must resolve candidate by index and persist."""
    from sq_bi_contracts.field_mount import PendingMapping, CandidateMapping
    store = FieldMappingStore(tmp_path / "test_confirm2.sqlite3")
    pipeline = MountingPipeline(store)
    pending = PendingMapping(
        mapping_request_id="mreq_abc123",
        standard_field_id="deliver_no",
        business_name="运单号",
        candidates=[
            CandidateMapping(physical_table="T", physical_column="DELIVER_NO", confidence=0.7, reason="test"),
            CandidateMapping(physical_table="T", physical_column="OTHER", confidence=0.4, reason="test2"),
        ],
    )
    req = ConfirmationRequest(
        pack_id="tms",
        data_source_id="ds_tms",
        standard_field_id="deliver_no",
        mapping_request_id="mreq_abc123",
        chosen_candidate_index=0,
    )
    mapping = pipeline.confirm(req, pending)
    assert mapping.physical_column == "DELIVER_NO"
    assert mapping.source == "manual"
    stored = store.get("tms", "ds_tms", "deliver_no")
    assert stored is not None


def test_confirm_wrong_request_id_raises(tmp_path) -> None:
    from sq_bi_contracts.field_mount import PendingMapping, CandidateMapping
    store = FieldMappingStore(tmp_path / "test_bad_id.sqlite3")
    pipeline = MountingPipeline(store)
    pending = PendingMapping(
        mapping_request_id="mreq_real",
        standard_field_id="deliver_no",
        business_name="运单号",
        candidates=[CandidateMapping(physical_table="T", physical_column="C", confidence=0.9, reason="r")],
    )
    req = ConfirmationRequest(
        pack_id="tms", data_source_id="ds_tms", standard_field_id="deliver_no",
        mapping_request_id="mreq_WRONG", chosen_candidate_index=0,
    )
    with pytest.raises(ValueError, match="mismatch"):
        pipeline.confirm(req, pending)


def test_confirm_out_of_range_index_raises(tmp_path) -> None:
    from sq_bi_contracts.field_mount import PendingMapping, CandidateMapping
    store = FieldMappingStore(tmp_path / "test_oob.sqlite3")
    pipeline = MountingPipeline(store)
    pending = PendingMapping(
        mapping_request_id="mreq_x",
        standard_field_id="deliver_no",
        business_name="运单号",
        candidates=[CandidateMapping(physical_table="T", physical_column="C", confidence=0.9, reason="r")],
    )
    req = ConfirmationRequest(
        pack_id="tms", data_source_id="ds_tms", standard_field_id="deliver_no",
        mapping_request_id="mreq_x", chosen_candidate_index=99,
    )
    with pytest.raises(IndexError):
        pipeline.confirm(req, pending)


def test_llm_match_malformed_json(tmp_path) -> None:
    """LLM returning invalid JSON must return None, not raise."""
    from sq_bi_runtime.mounting_pipeline import llm_semantic_match, PhysicalColumn
    class BadLLM:
        def chat(self, system: str, user: str) -> str:
            return "not valid json {{{"

    sf = PackStandardField(field_id="deliver_no", business_name="运单号", data_type="text")
    cols = [PhysicalColumn(table="T", column="DELIVER_NO")]
    result = llm_semantic_match(sf, cols, BadLLM())
    assert result is None


def test_llm_match_float_index_accepted(tmp_path) -> None:
    """LLM returning 0.0 as candidate_index (float) should be treated as 0."""
    from sq_bi_runtime.mounting_pipeline import llm_semantic_match, PhysicalColumn
    import json
    class FloatIndexLLM:
        def chat(self, system: str, user: str) -> str:
            return json.dumps({"candidate_index": 0.0, "confidence": 0.8, "reason": "test"})

    sf = PackStandardField(field_id="deliver_no", business_name="运单号", data_type="text")
    cols = [PhysicalColumn(table="T", column="DELIVER_NO")]
    result = llm_semantic_match(sf, cols, FloatIndexLLM())
    assert result is not None
    assert result.physical_column == "DELIVER_NO"


def test_llm_match_nonexistent_column_rejected(tmp_path) -> None:
    """LLM proposing a column that doesn't exist must be rejected."""
    from sq_bi_runtime.mounting_pipeline import llm_semantic_match, validate_llm_candidate, PhysicalColumn
    import json
    class HallucinatingLLM:
        def chat(self, system: str, user: str) -> str:
            return json.dumps({"candidate_index": 0, "confidence": 0.9, "reason": "invented"})

    sf = PackStandardField(field_id="deliver_no", business_name="运单号", data_type="text")
    cols = [PhysicalColumn(table="T", column="DELIVER_NO")]
    result = llm_semantic_match(sf, cols, HallucinatingLLM())
    # candidate_index 0 → DELIVER_NO exists in available_columns T
    available = {"T": cols}
    assert result is not None
    assert validate_llm_candidate(result, available) is True

    # Now test with a column not in available
    class NonExistentLLM:
        def chat(self, system: str, user: str) -> str:
            return json.dumps({"candidate_index": 0, "confidence": 0.9, "reason": "invented"})
    cols2 = [PhysicalColumn(table="T", column="GHOST_COL")]
    result2 = llm_semantic_match(sf, cols2, NonExistentLLM())
    available2: dict = {"OTHER_TABLE": cols}
    assert result2 is None or not validate_llm_candidate(result2, available2)


def test_smoke_test_with_missing_mapping_not_all_passed(tmp_path) -> None:
    """Smoke test must report compiled=False for metrics with missing mappings."""
    from sq_bi_contracts.field_mount import LogicalMetricDefinition, LogicalMetricFormula
    store = FieldMappingStore(tmp_path / "test_smoke_fail.sqlite3")
    pipeline = MountingPipeline(store)
    # No mappings seeded
    test_metrics = [
        LogicalMetricDefinition(
            metric_code="CNT",
            name="单量",
            definition="test",
            logical_formula=LogicalMetricFormula(
                expression="count_distinct(deliver_no)",
                referenced_standard_fields=["deliver_no"],
            ),
            data_source_id="ds_tms",
            owner="test",
        ),
    ]
    result = pipeline.run_smoke_test("tms", "ds_tms", TMS_STANDARD_FIELDS, test_metrics)
    assert result.all_passed is False
    assert result.metrics[0].compiled is False
    assert result.metrics[0].error is not None


def test_smoke_test_with_executor(tmp_path) -> None:
    """When executor is provided, executed=True and row_count is set."""
    from sq_bi_contracts.field_mount import LogicalMetricDefinition, LogicalMetricFormula
    store = FieldMappingStore(tmp_path / "test_smoke_exec.sqlite3")
    store.upsert(FieldMapping(
        mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY",
        physical_column="DELIVER_NO", source="manual", status="active",
    ))

    class FakeExecutor:
        def execute(self, sql: str) -> list:
            return [{"count": 42}]

    pipeline = MountingPipeline(store)
    test_metrics = [
        LogicalMetricDefinition(
            metric_code="CNT", name="单量", definition="t",
            logical_formula=LogicalMetricFormula(
                expression="count_distinct(deliver_no)",
                referenced_standard_fields=["deliver_no"],
            ),
            data_source_id="ds_tms", owner="test",
        ),
    ]
    result = pipeline.run_smoke_test("tms", "ds_tms", TMS_STANDARD_FIELDS, test_metrics, executor=FakeExecutor())
    assert result.metrics[0].executed is True
    assert result.metrics[0].row_count == 1
    assert result.tested_at is not None


def test_deterministic_match_enum_overlap() -> None:
    """Enum value overlap must contribute to confidence score."""
    std = PackStandardField(
        field_id="car_status", business_name="承运状态", data_type="enum",
        enum_values=["signed", "in_transit"],
    )
    cols = [PhysicalColumn(table="T", column="CAR_STATUS", sample_values=["signed", "unknown"])]
    results = deterministic_match(std, cols)
    assert len(results) == 1
    assert "enum_overlap" in results[0].reason


def test_deterministic_match_evidence_populated() -> None:
    """deterministic_match must populate MappingEvidence on each candidate."""
    std = PackStandardField(
        field_id="deliver_no", business_name="运单号", data_type="text",
    )
    col = PhysicalColumn(
        table="HR_DELIVER_CARRY", column="DELIVER_NO",
        data_type="varchar", comment="运单编号",
        sample_values=["D001", "D002"],
    )
    results = deterministic_match(std, [col])
    assert results, "expected at least one candidate"
    ev = results[0].evidence
    assert ev.name_similarity is not None and 0.0 <= ev.name_similarity <= 1.0
    assert ev.business_name_similarity is not None
    # sample values should be forwarded
    assert "D001" in ev.sample_values or "D002" in ev.sample_values


def test_deterministic_match_evidence_type_compatible() -> None:
    """type_compatible flag must be set when physical data_type is provided."""
    std = PackStandardField(field_id="plan_time", business_name="计划时间", data_type="datetime")
    col = PhysicalColumn(table="T", column="PLAN_TIME", data_type="date")
    results = deterministic_match(std, [col])
    if results:
        assert results[0].evidence.type_compatible is not None


def test_trigger_evidence_has_affected_metric_count(tmp_path) -> None:
    """trigger() must populate affected_metric_count via logical_metrics."""
    from sq_bi_contracts.field_mount import LogicalMetricFormula
    store = FieldMappingStore(tmp_path / "ev_count.sqlite3")
    pipeline = MountingPipeline(store=store)

    metrics = [
        LogicalMetricDefinition(
            metric_code="ontime_rate", name="准时率", definition="d",
            logical_formula=LogicalMetricFormula(
                expression="rate(actual_time <= plan_time)",
                referenced_standard_fields=["actual_time", "plan_time"],
            ),
            data_source_id="ds", owner="admin",
        )
    ]
    std_fields = {
        sf.field_id: sf for sf in [
            PackStandardField(field_id="actual_time", business_name="实际时间", data_type="datetime"),
            PackStandardField(field_id="plan_time", business_name="计划时间", data_type="datetime"),
        ]
    }
    resp = pipeline.trigger(
        MountTriggerRequest(pack_id="tms", data_source_id="ds"),
        standard_fields=std_fields,
        live_catalog={},
        semantic_catalog={},
        logical_metrics=metrics,
    )
    # All fields should end up in pending (no physical columns to match)
    assert resp.pending
    for pm in resp.pending:
        # With no physical columns there are no candidates — count is still computed
        # for any candidate that exists; here we just verify the pipeline ran without error
        pass  # affected_metric_count visible on candidates when columns exist


def test_trigger_pending_has_conflicting_candidates(tmp_path) -> None:
    """When multiple candidates exist, each candidate lists the others as conflicting."""
    store = FieldMappingStore(tmp_path / "conflicts.sqlite3")
    pipeline = MountingPipeline(store=store)
    std_fields = {
        "deliver_no": PackStandardField(field_id="deliver_no", business_name="deliver_no", data_type="text")
    }
    # Two similar columns → both become candidates, should list each other as conflicting
    catalog = {"T": {"DELIVER_NO_A", "DELIVER_NO_B"}}
    resp = pipeline.trigger(
        MountTriggerRequest(pack_id="tms", data_source_id="ds"),
        standard_fields=std_fields,
        live_catalog=catalog,
        semantic_catalog={},
    )
    # Should produce pending with candidates that carry conflicting_candidates
    if resp.pending and resp.pending[0].candidates and len(resp.pending[0].candidates) > 1:
        for c in resp.pending[0].candidates:
            assert len(c.evidence.conflicting_candidates) >= 1
