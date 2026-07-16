"""Tests for SchemaProfiler (phase-two) and SemanticDiscovery."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from sq_bi_contracts.semantic_profile import (
    EvidenceSource,
    FieldOrigin,
    TableRecommendation,
)
from sq_bi_runtime.schema_profiler import (
    ColumnProfile,
    SchemaProfiler,
    TableProfile,
    _is_sensitive_column,
    select_profile_targets,
)
from sq_bi_runtime.schema_scanner import ColumnMeta, TableMeta
from sq_bi_runtime.semantic_discovery import (
    SemanticDiscovery,
    _count_recommendations,
    _parse_llm_spaces,
)


# ── SchemaProfiler ────────────────────────────────────────────────────

def _make_table(name: str, *columns: str, excluded: bool = False) -> TableMeta:
    tbl = TableMeta(name=name, excluded=excluded)
    tbl.columns = [ColumnMeta(name=c) for c in columns]
    return tbl


def _mock_connector_for_profile() -> MagicMock:
    conn = MagicMock()
    conn.execute.return_value = [{"total": 1000, "nulls": 50, "dcount": 800, "cnt": 1000, "min_v": "1", "max_v": "999"}]
    return conn


def test_profiler_skips_excluded_table() -> None:
    conn = _mock_connector_for_profile()
    profiler = SchemaProfiler(conn)
    tbl = _make_table("ORDERS_TMP", "ID", excluded=True)
    with pytest.raises(ValueError, match="excluded"):
        profiler.profile_table(tbl)


def test_profiler_masks_sensitive_columns() -> None:
    conn = _mock_connector_for_profile()
    profiler = SchemaProfiler(conn)
    tbl = _make_table("USERS", "USER_ID", "PASSWORD", "EMAIL")
    profile = profiler.profile_table(tbl)
    col_names = {c.name for c in profile.columns}
    assert "PASSWORD" in col_names
    assert "EMAIL" in col_names
    pwd = next(c for c in profile.columns if c.name == "PASSWORD")
    email = next(c for c in profile.columns if c.name == "EMAIL")
    assert pwd.is_sensitive
    assert email.is_sensitive
    # execute should not have been called for sensitive columns
    # (the null rate call happens for non-sensitive only)
    calls = [str(call) for call in conn.execute.call_args_list]
    assert not any("PASSWORD" in c for c in calls)
    assert not any("EMAIL" in c for c in calls)


def test_profiler_computes_null_rate() -> None:
    conn = MagicMock()
    conn.execute.side_effect = [
        [{"total": 100, "nulls": 20}],   # null rate
        [{"dcount": 70}],                  # unique count
        [],                                # samples
        [],                                # range
    ]
    profiler = SchemaProfiler(conn)
    tbl = _make_table("ORDERS", "STATUS")
    profile = profiler.profile_table(tbl)
    col = profile.columns[0]
    assert col.null_rate == pytest.approx(0.20)
    assert col.unique_rate == pytest.approx(0.70)


def test_profiler_degrades_gracefully_on_query_error() -> None:
    conn = MagicMock()
    conn.execute.side_effect = RuntimeError("DB error")
    profiler = SchemaProfiler(conn)
    tbl = _make_table("ORDERS", "STATUS", "AMOUNT")
    profile = profiler.profile_table(tbl)
    # No exception; columns present but null_rate is None
    assert len(profile.columns) == 2
    assert profile.columns[0].null_rate is None


def test_sensitive_column_detection() -> None:
    assert _is_sensitive_column("PASSWORD")
    assert _is_sensitive_column("USER_EMAIL")
    assert _is_sensitive_column("MOBILE_PHONE")
    assert _is_sensitive_column("BANK_ACCT_NO")
    assert not _is_sensitive_column("DELIVER_NO")
    assert not _is_sensitive_column("STATUS")
    assert not _is_sensitive_column("FACTORY_CODE")


def test_profiler_does_not_sample_excluded_table_columns() -> None:
    conn = _mock_connector_for_profile()
    profiler = SchemaProfiler(conn)
    tbl = _make_table("ORDERS_TMP", "ID", "STATUS", excluded=True)
    with pytest.raises(ValueError):
        profiler.profile_table(tbl)
    conn.execute.assert_not_called()


def test_profiler_capped_samples() -> None:
    many_values = [{"STATUS": str(i)} for i in range(50)]
    conn = MagicMock()
    conn.execute.side_effect = [
        [{"total": 1000, "nulls": 0}],
        [{"dcount": 50}],
        many_values,
        [],  # range
    ]
    profiler = SchemaProfiler(conn, max_sample_rows=30)
    tbl = _make_table("ORDERS", "STATUS")
    profile = profiler.profile_table(tbl)
    col = profile.columns[0]
    assert len(col.sample_values) <= 20


def test_candidate_fk_detection() -> None:
    conn = _mock_connector_for_profile()
    profiler = SchemaProfiler(conn)
    tbl = _make_table("ORDERS", "ORDER_ID", "CARRIER_ID", "FACTORY_ID")
    tbl.columns[0] = ColumnMeta(name="ORDER_ID", is_pk=True)
    tbl.columns[1] = ColumnMeta(name="CARRIER_ID")
    tbl.columns[2] = ColumnMeta(name="FACTORY_ID")
    profile = profiler.profile_table(tbl)
    fk_cols = {pair[0] for pair in profile.candidate_fk_pairs}
    assert "CARRIER_ID" in fk_cols
    assert "FACTORY_ID" in fk_cols


def test_profile_targets_are_bounded_and_keep_high_signal_columns() -> None:
    tables = []
    for table_index in range(20):
        table = _make_table(
            f"TABLE_{table_index}",
            *[f"COLUMN_{column_index}" for column_index in range(12)],
        )
        table.columns[10] = ColumnMeta(name="BUSINESS_ID", is_pk=True)
        table.columns[11] = ColumnMeta(name="STATUS", comment="业务状态")
        tables.append(table)

    targets = select_profile_targets(tables, max_tables=4, max_columns_per_table=3)

    assert len(targets) == 4
    assert all(len(table.columns) == 3 for table in targets)
    assert all(table.columns[0].name == "BUSINESS_ID" for table in targets)
    assert all(any(column.name == "STATUS" for column in table.columns) for table in targets)
    assert len(tables[0].columns) == 12


# ── SemanticDiscovery ─────────────────────────────────────────────────

def _llm_response(spaces_json: list[dict]) -> str:
    return json.dumps({"spaces": spaces_json})


def _make_llm(response: str) -> MagicMock:
    llm = MagicMock()
    llm.chat.return_value = response
    return llm


def test_discovery_parses_spaces_and_entities() -> None:
    spaces_json = [
        {
            "name": "运输管理",
            "description": "运单相关表",
            "entities": [
                {
                    "physical_table": "HR_DELIVER_FORM",
                    "business_name": "运单",
                    "description": "运单主表",
                    "recommendation": "recommended_include",
                    "fields": [
                        {
                            "physical_column": "DELIVER_NO",
                            "business_name": "运单号",
                            "description": "唯一运单编号",
                            "semantic_role": "identifier",
                            "default_aggregation": "count",
                            "synonyms": ["运单编号"],
                            "confidence": 0.92,
                            "evidence_sources": ["name", "comment", "ai_inference"],
                        }
                    ],
                }
            ],
        }
    ]
    snapshot_id = "snap_001"
    source_tables = {"HR_DELIVER_FORM"}
    spaces = _parse_llm_spaces({"spaces": spaces_json}, snapshot_id, source_tables)

    assert len(spaces) == 1
    assert spaces[0].name == "运输管理"
    assert spaces[0].snapshot_id == snapshot_id
    assert not spaces[0].accepted

    entity = spaces[0].entities[0]
    assert entity.physical_table == "HR_DELIVER_FORM"
    assert entity.recommendation == TableRecommendation.recommended_include

    field = entity.fields[0]
    assert field.origin == FieldOrigin.inferred
    assert field.confidence == pytest.approx(0.92)
    assert field.semantic_role == "identifier"
    assert "运单编号" in field.synonyms
    ev_sources = {ev.source for ev in field.evidence}
    assert EvidenceSource.name in ev_sources
    assert EvidenceSource.ai_inference in ev_sources


def test_discovery_hydrates_field_metadata_and_real_evidence_from_scan_context() -> None:
    spaces_json = [
        {
            "name": "运输管理",
            "entities": [
                {
                    "physical_table": "HR_DELIVER_FORM",
                    "business_name": "运单",
                    "fields": [
                        {
                            "physical_column": "STATUS",
                            "business_name": "配送状态",
                            "semantic_role": "dimension",
                            "evidence_sources": ["sample"],
                        }
                    ],
                }
            ],
        }
    ]
    table = TableMeta(
        name="HR_DELIVER_FORM",
        columns=[
            ColumnMeta(name="STATUS", data_type="NUMBER", comment="配送状态编码"),
        ],
    )
    profile = TableProfile(
        table_name="HR_DELIVER_FORM",
        columns=[
            ColumnProfile(name="STATUS", sample_values=["10", "20", "30"]),
        ],
    )

    spaces = _parse_llm_spaces(
        {"spaces": spaces_json},
        "snap",
        {"HR_DELIVER_FORM"},
        table_metas={"HR_DELIVER_FORM": table},
        profiles={"HR_DELIVER_FORM": profile},
    )

    field = spaces[0].entities[0].fields[0]
    assert field.data_type == "NUMBER"
    assert field.physical_reference == "HR_DELIVER_FORM.STATUS"
    details_by_source = {ev.source: ev.detail for ev in field.evidence}
    assert "配送状态编码" in (details_by_source[EvidenceSource.comment] or "")
    assert "HR_DELIVER_FORM.STATUS" in (details_by_source[EvidenceSource.name] or "")
    assert "10" in (details_by_source[EvidenceSource.sample] or "")
    assert "dimension" in (details_by_source[EvidenceSource.ai_inference] or "")


def test_discovery_ignores_llm_field_not_in_scanned_columns() -> None:
    spaces_json = [
        {
            "name": "运输管理",
            "entities": [
                {
                    "physical_table": "HR_DELIVER_FORM",
                    "business_name": "运单",
                    "fields": [
                        {"physical_column": "GHOST_COL", "business_name": "幽灵字段"},
                    ],
                }
            ],
        }
    ]
    table = TableMeta(
        name="HR_DELIVER_FORM",
        columns=[ColumnMeta(name="STATUS", data_type="NUMBER")],
    )
    spaces = _parse_llm_spaces(
        {"spaces": spaces_json},
        "snap",
        {"HR_DELIVER_FORM"},
        table_metas={"HR_DELIVER_FORM": table},
    )
    assert spaces[0].entities[0].fields == []


def test_discovery_drops_table_not_in_source() -> None:
    """Tables not present in the scan are silently dropped from the response."""
    spaces_json = [
        {
            "name": "测试",
            "entities": [
                {
                    "physical_table": "GHOST_TABLE",
                    "business_name": "不存在的表",
                    "fields": [],
                }
            ],
        }
    ]
    spaces = _parse_llm_spaces({"spaces": spaces_json}, "snap", {"HR_DELIVER_FORM"})
    assert spaces[0].entities == []


def test_discovery_clamps_confidence_out_of_range() -> None:
    spaces_json = [
        {
            "name": "测试",
            "entities": [
                {
                    "physical_table": "T",
                    "business_name": "T",
                    "fields": [
                        {
                            "physical_column": "COL",
                            "business_name": "字段",
                            "confidence": 1.5,  # out of range
                            "evidence_sources": ["ai_inference"],
                        }
                    ],
                }
            ],
        }
    ]
    spaces = _parse_llm_spaces({"spaces": spaces_json}, "snap", {"T"})
    assert spaces[0].entities[0].fields[0].confidence == pytest.approx(1.0)


def test_discovery_retains_conflicting_candidates() -> None:
    """Two fields for the same physical column should both be kept."""
    spaces_json = [
        {
            "name": "测试",
            "entities": [
                {
                    "physical_table": "T",
                    "business_name": "T",
                    "fields": [
                        {
                            "physical_column": "STATUS",
                            "business_name": "配送状态",
                            "confidence": 0.88,
                            "evidence_sources": ["comment"],
                        },
                        {
                            "physical_column": "STATUS",
                            "business_name": "订单状态",
                            "confidence": 0.60,
                            "evidence_sources": ["name"],
                        },
                    ],
                }
            ],
        }
    ]
    spaces = _parse_llm_spaces({"spaces": spaces_json}, "snap", {"T"})
    fields = spaces[0].entities[0].fields
    assert len(fields) == 2


def test_discovery_marks_failure_when_llm_retries_are_exhausted() -> None:
    llm = MagicMock()
    llm.chat.side_effect = RuntimeError("LLM timed out")
    discovery = SemanticDiscovery(llm)
    tbl = _make_table("ORDERS", "ID")
    with pytest.raises(RuntimeError, match="模型调用已重试 3 次"):
        discovery.discover("snap_001", [[tbl]], profiles={})
    assert llm.chat.call_count == 3


def test_discovery_retries_transient_llm_failure() -> None:
    response = _llm_response([
        {
            "name": "订单域",
            "entities": [{
                "physical_table": "ORDERS",
                "business_name": "订单",
                "recommendation": "recommended_include",
                "fields": [],
            }],
        }
    ])
    llm = MagicMock()
    llm.chat.side_effect = [RuntimeError("temporary failure"), response]
    discovery = SemanticDiscovery(llm)
    orders = _make_table("ORDERS", "ID")
    spaces, counts = discovery.discover("snap_001", [[orders]], profiles={})
    assert spaces[0].entities[0].physical_table == "ORDERS"
    assert counts["recommended_include"] == 1
    assert llm.chat.call_count == 2


def test_recommendation_counts() -> None:
    from sq_bi_contracts.semantic_profile import SemanticEntity, SemanticSpace

    spaces = [
        SemanticSpace(
            space_id="s1",
            snapshot_id="snap",
            name="A",
            entities=[
                SemanticEntity(
                    entity_id="e1",
                    space_id="s1",
                    physical_table="T1",
                    business_name="T1",
                    recommendation=TableRecommendation.recommended_include,
                ),
                SemanticEntity(
                    entity_id="e2",
                    space_id="s1",
                    physical_table="T2",
                    business_name="T2",
                    recommendation=TableRecommendation.possibly_relevant,
                ),
                SemanticEntity(
                    entity_id="e3",
                    space_id="s1",
                    physical_table="T3",
                    business_name="T3",
                    recommendation=TableRecommendation.not_relevant,
                ),
            ],
        )
    ]
    counts = _count_recommendations(spaces)
    assert counts["recommended_include"] == 1
    assert counts["possibly_relevant"] == 1
    assert counts["not_relevant"] == 1


def test_discovery_full_pipeline_mocked() -> None:
    spaces_json = [
        {
            "name": "运输",
            "entities": [
                {
                    "physical_table": "ORDERS",
                    "business_name": "订单",
                    "recommendation": "recommended_include",
                    "fields": [
                        {
                            "physical_column": "ORDER_ID",
                            "business_name": "订单号",
                            "confidence": 0.9,
                            "evidence_sources": ["name"],
                        }
                    ],
                }
            ],
        }
    ]
    llm = _make_llm(_llm_response(spaces_json))
    discovery = SemanticDiscovery(llm)
    tbl = _make_table("ORDERS", "ORDER_ID", "STATUS")
    spaces, counts = discovery.discover("snap_001", [[tbl]], profiles={})
    assert len(spaces) == 1
    assert counts["recommended_include"] == 1
