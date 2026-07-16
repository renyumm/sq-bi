"""Tests for PackDrafter: grounding, field dropping, metric rejection, no SQL."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from sq_bi_runtime.pack_drafter import PackDrafter, _contains_raw_sql


def _llm(response: dict) -> MagicMock:
    client = MagicMock()
    client.chat.return_value = json.dumps(response)
    return client


_GOOD_RESPONSE = {
    "entities": [
        {"entity_id": "ent_shipment", "name": "运单", "physical_table": "SHIPMENT", "tags": ["core"]}
    ],
    "fields": [
        {
            "field_id": "ef_freight",
            "business_name": "运费",
            "physical_table": "BILLING_DETAIL",
            "physical_column": "FREIGHT_CHARGE",
            "data_type": "DECIMAL",
            "entity_id": "ent_shipment",
            "synonyms": ["实付运费"],
        },
        {
            "field_id": "ef_unknown",
            "business_name": "未知字段",
            "physical_table": "NONEXISTENT_TABLE",
            "physical_column": "UNKNOWN_COL",
            "data_type": "TEXT",
            "entity_id": "ent_shipment",
            "synonyms": [],
        },
    ],
    "terms": [
        {"term_id": "t_otd", "term": "准时交付", "definition": "按时完成的比例", "synonyms": ["OTD"]}
    ],
    "metrics": [
        {
            "metric_code": "total_freight",
            "name": "总运费",
            "definition": "统计期内运费之和",
            "formula_expression": "SUM(BILLING_DETAIL.FREIGHT_CHARGE)",
            "filters": [],
            "time_field": None,
            "entity_id": "ent_shipment",
            "synonyms": ["运费汇总"],
        }
    ],
    "acceptance_questions": [
        {"question_id": "aq1", "question": "本月总运费是多少？", "expected_metric_code": "total_freight"}
    ],
}

_PROFILE_COLUMNS = {("BILLING_DETAIL", "FREIGHT_CHARGE"), ("SHIPMENT", "SHIPMENT_NO")}


def _drafter(response: dict, profile_columns: set | None = None) -> tuple[PackDrafter, set]:
    drafter = PackDrafter(llm_client=_llm(response), profile_store_path=None)
    cols = profile_columns if profile_columns is not None else _PROFILE_COLUMNS
    return drafter, cols


def test_draft_grounded_in_profile() -> None:
    drafter, cols = _drafter(_GOOD_RESPONSE)
    result = drafter._validate_and_assemble(_GOOD_RESPONSE, cols)
    assert len(result.draft.entities) == 1
    assert len(result.draft.terms) == 1
    assert len(result.draft.acceptance_questions) == 1


def test_unknown_field_dropped() -> None:
    drafter, cols = _drafter(_GOOD_RESPONSE)
    result = drafter._validate_and_assemble(_GOOD_RESPONSE, cols)
    field_ids = [f.field_id for f in result.draft.fields]
    assert "ef_freight" in field_ids
    assert "ef_unknown" not in field_ids
    assert "ef_unknown" in result.dropped_fields


def test_valid_metric_kept() -> None:
    drafter, cols = _drafter(_GOOD_RESPONSE)
    result = drafter._validate_and_assemble(_GOOD_RESPONSE, cols)
    assert any(m.metric_code == "total_freight" for m in result.draft.metrics)
    assert "total_freight" not in result.rejected_metrics


def test_non_compiling_metric_rejected() -> None:
    bad_response = {
        **_GOOD_RESPONSE,
        "metrics": [
            {
                "metric_code": "bad_metric",
                "name": "坏指标",
                "definition": "会失败",
                "formula_expression": "INVALID (((BROKEN SQL",
                "filters": [],
                "time_field": None,
                "entity_id": None,
                "synonyms": [],
            }
        ],
    }
    drafter, cols = _drafter(bad_response)
    result = drafter._validate_and_assemble(bad_response, cols)
    assert "bad_metric" in result.rejected_metrics
    assert "bad_metric" in result.rejection_reasons


def test_raw_select_statement_rejected() -> None:
    sql_response = {
        **_GOOD_RESPONSE,
        "metrics": [
            {
                "metric_code": "sql_metric",
                "name": "SQL指标",
                "definition": "不合规",
                "formula_expression": "SELECT SUM(freight_charge) FROM billing_detail",
                "filters": [],
                "time_field": None,
                "entity_id": None,
                "synonyms": [],
            }
        ],
    }
    drafter, cols = _drafter(sql_response)
    result = drafter._validate_and_assemble(sql_response, cols)
    assert "sql_metric" in result.rejected_metrics


def test_no_sql_emitted_by_planner_stage() -> None:
    """The LLM stage result should contain no raw SELECT SQL in entities/fields/terms."""
    drafter, cols = _drafter(_GOOD_RESPONSE)
    result = drafter._validate_and_assemble(_GOOD_RESPONSE, cols)
    for entity in result.draft.entities:
        assert "SELECT" not in entity.name.upper()
    for term in result.draft.terms:
        assert "SELECT" not in term.definition.upper()


def test_empty_profile_skips_field_dropping() -> None:
    """When no profile is loaded, keep all fields (no column set to validate against)."""
    drafter, _ = _drafter(_GOOD_RESPONSE, profile_columns=set())
    result = drafter._validate_and_assemble(_GOOD_RESPONSE, set())
    assert len(result.draft.fields) == 2
    assert result.dropped_fields == []


def test_llm_failure_returns_empty_draft() -> None:
    bad_client = MagicMock()
    bad_client.chat.side_effect = RuntimeError("LLM error")
    drafter = PackDrafter(llm_client=bad_client, profile_store_path=None)
    result = drafter.draft("ds_tms")
    assert result.draft.entities == []
    assert "__llm__" in result.rejection_reasons


def test_contains_raw_sql_helper() -> None:
    assert _contains_raw_sql("SELECT SUM(x) FROM t") is True
    assert _contains_raw_sql("SUM(billing_detail.freight_charge)") is False
    assert _contains_raw_sql("COUNT(DISTINCT shipment.id)") is False


def test_documents_included_in_user_prompt() -> None:
    captured: list[str] = []
    client = MagicMock()
    def _chat(system: str, user: str) -> str:
        captured.append(user)
        return json.dumps(_GOOD_RESPONSE)
    client.chat.side_effect = _chat
    drafter = PackDrafter(llm_client=client, profile_store_path=None)
    drafter.draft("ds_tms", document_texts=["指标文档内容：运费 = 承运商实际结算金额"])
    assert any("运费" in u for u in captured)
