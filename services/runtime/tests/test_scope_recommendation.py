"""Unit tests for scope_recommendation.recommend_scope_for_pack.

Covers the P1-remainder "smart candidate-scope recommendation" behavior:
replacing the blunt "include every scanned table not classified
not_relevant" default with pack-aware tiering (recommended/ambiguous/
excluded), per .design/asset_semantic_space_harness_operating_model.md §2.3.
"""

from __future__ import annotations

from sq_bi_contracts.domain_pack import PackStandardField
from sq_bi_contracts.semantic_profile import (
    CatalogColumnRecord,
    CatalogTableRecord,
    TableRecommendation,
)

from sq_bi_runtime.scope_recommendation import recommend_scope_for_pack


def _table(
    name: str,
    columns: list[tuple[str, str]],
    classification: TableRecommendation = TableRecommendation.recommended_include,
    excluded: bool = False,
) -> CatalogTableRecord:
    return CatalogTableRecord(
        table_name=name,
        classification=classification,
        excluded=excluded,
        columns=[
            CatalogColumnRecord(table_name=name, column_name=col, data_type=dtype)
            for col, dtype in columns
        ],
    )


def _field(field_id: str, business_name: str) -> PackStandardField:
    return PackStandardField(field_id=field_id, business_name=business_name, data_type="text")


def _tiers(candidates) -> dict[str, str]:
    return {c.table_name: c.tier for c in candidates}


def test_table_with_pack_field_match_is_recommended() -> None:
    tables = [_table("shipment", [("shipment_id", "NUMBER"), ("carrier_name", "VARCHAR2")])]
    fields = [_field("carrier_name", "承运商名称")]

    result = recommend_scope_for_pack(fields, tables)

    assert _tiers(result) == {"shipment": "recommended"}
    assert result[0].matched_field_ids == ["carrier_name"]


def test_recommended_include_table_without_pack_match_is_downgraded_to_ambiguous() -> None:
    """Core smart-recommendation behavior: in a multi-domain DB, generic
    scan classification alone is not enough — a table the LLM scan flagged
    as generically business-relevant, but which shows zero evidence for
    *this* pack's fields, must not be silently swept into the implicit
    space just because some OTHER table in the same connection matched."""
    tables = [
        _table("shipment", [("shipment_id", "NUMBER"), ("carrier_name", "VARCHAR2")]),
        _table("hr_employee", [("employee_id", "NUMBER"), ("salary", "NUMBER")]),
    ]
    fields = [_field("carrier_name", "承运商名称")]

    result = recommend_scope_for_pack(fields, tables)

    assert _tiers(result) == {"shipment": "recommended", "hr_employee": "ambiguous"}


def test_not_relevant_classification_with_no_pack_match_is_excluded() -> None:
    tables = [
        _table("shipment", [("carrier_name", "VARCHAR2")]),
        _table("audit_log", [("event_id", "NUMBER")], classification=TableRecommendation.not_relevant),
    ]
    fields = [_field("carrier_name", "承运商名称")]

    result = recommend_scope_for_pack(fields, tables)

    assert _tiers(result) == {"shipment": "recommended", "audit_log": "excluded"}


def test_explicitly_excluded_table_stays_excluded_even_with_strong_pack_match() -> None:
    tables = [_table("tmp_staging", [("carrier_name", "VARCHAR2")], excluded=True)]
    fields = [_field("carrier_name", "承运商名称")]

    result = recommend_scope_for_pack(fields, tables)

    assert result[0].tier == "excluded"


def test_no_pack_signal_anywhere_falls_back_to_generic_classification() -> None:
    """When the pack's fields don't textually match anything in this schema
    at all, there is no pack-specific evidence to add — fall back to the
    generic classification wholesale instead of flagging every table
    ambiguous for no reason."""
    tables = [
        _table("shipment", [("shipment_id", "NUMBER")], classification=TableRecommendation.recommended_include),
        _table("lookup_status", [("status_code", "VARCHAR2")], classification=TableRecommendation.possibly_relevant),
        _table("audit_log", [("event_id", "NUMBER")], classification=TableRecommendation.not_relevant),
    ]
    fields = [_field("totally_unrelated_field_xyz", "完全不相关字段")]

    result = recommend_scope_for_pack(fields, tables)

    assert _tiers(result) == {
        "shipment": "recommended",
        "lookup_status": "recommended",
        "audit_log": "excluded",
    }


def test_empty_standard_fields_falls_back_to_generic_classification() -> None:
    tables = [_table("shipment", [("shipment_id", "NUMBER")])]

    result = recommend_scope_for_pack([], tables)

    assert result[0].tier == "recommended"
    assert result[0].matched_field_ids == []


def test_possibly_relevant_table_with_pack_match_is_upgraded_to_recommended() -> None:
    tables = [
        _table(
            "carrier_lookup",
            [("carrier_name", "VARCHAR2")],
            classification=TableRecommendation.possibly_relevant,
        ),
    ]
    fields = [_field("carrier_name", "承运商名称")]

    result = recommend_scope_for_pack(fields, tables)

    assert result[0].tier == "recommended"
    assert result[0].matched_field_ids == ["carrier_name"]
