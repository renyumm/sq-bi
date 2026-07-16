from __future__ import annotations

import pytest
from sq_bi_contracts.field_mount import FieldMapping
from sq_bi_contracts.domain_pack import PackStandardField
from sq_bi_runtime.dsl_compiler import (
    DSLParseError,
    compile_for_dialect,
    compile_oracle,
    parse_expression,
    parse_full,
    validate_logical_expression,
    tokenize,
)

TMS_STANDARD_FIELDS: dict[str, PackStandardField] = {
    sf.field_id: sf
    for sf in [
        PackStandardField(field_id="deliver_no", business_name="运单号", data_type="text"),
        PackStandardField(field_id="carrier_name", business_name="承运商", data_type="text"),
        PackStandardField(field_id="shipment_cnt", business_name="承运量", data_type="integer"),
        PackStandardField(field_id="ontime_rate", business_name="准时率", data_type="percentage"),
        PackStandardField(field_id="plan_time", business_name="计划时间", data_type="datetime"),
        PackStandardField(field_id="actual_time", business_name="实际时间", data_type="datetime"),
        PackStandardField(field_id="factory_code", business_name="工厂代码", data_type="text"),
        PackStandardField(field_id="car_status", business_name="承运状态", data_type="enum",
                           enum_values=["signed", "in_transit", "delayed", "completed"]),
    ]
}

TMS_MAPPINGS: dict[str, FieldMapping] = {
    "deliver_no": FieldMapping(mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY", physical_column="DELIVER_NO",
        confidence=1.0, source="manual", status="active"),
    "carrier_name": FieldMapping(mapping_id="m2", pack_id="tms", standard_field_id="carrier_name",
        data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY", physical_column="CARRIER_NAME",
        confidence=1.0, source="manual", status="active"),
    "plan_time": FieldMapping(mapping_id="m4", pack_id="tms", standard_field_id="plan_time",
        data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY", physical_column="PLAN_TIME",
        confidence=1.0, source="manual", status="active"),
    "actual_time": FieldMapping(mapping_id="m5", pack_id="tms", standard_field_id="actual_time",
        data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY", physical_column="ACTUAL_TIME",
        confidence=1.0, source="manual", status="active"),
    "car_status": FieldMapping(mapping_id="m6", pack_id="tms", standard_field_id="car_status",
        data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY", physical_column="CAR_STATUS",
        confidence=1.0, source="manual", status="active",
        transform="enum:signed->'3',in_transit->'5',delayed->'9',completed->'7'"),
}


def test_tokenize_simple() -> None:
    tokens = tokenize("count(deliver_no)")
    assert [t["type"] for t in tokens] == ["FUNC", "LPAREN", "IDENT", "RPAREN"]


def test_parse_count() -> None:
    ast = parse_expression("count(deliver_no)")
    assert "AggFunc" in repr(ast)


def test_parse_count_distinct() -> None:
    ast = parse_expression("count_distinct(deliver_no)")
    assert "AggFunc" in repr(ast)


def test_parse_rate() -> None:
    ast = parse_expression("rate(actual_time <= plan_time)")
    assert "AggFunc" in repr(ast)


def test_parse_full_with_clauses() -> None:
    ast = parse_full("count_distinct(deliver_no) group_by(carrier_name)")
    assert "ClauseGroup" in repr(ast)


def test_parse_invalid_func() -> None:
    with pytest.raises(DSLParseError):
        parse_expression("unknown_func(x)")


def test_validate_valid() -> None:
    assert validate_logical_expression("count_distinct(deliver_no)", TMS_STANDARD_FIELDS) == []


def test_validate_undeclared_field() -> None:
    errors = validate_logical_expression("count_distinct(nonexistent)", TMS_STANDARD_FIELDS)
    assert "nonexistent" in errors[0]


def test_compile_count() -> None:
    sql = compile_oracle("count(deliver_no)", TMS_MAPPINGS, TMS_STANDARD_FIELDS)
    assert "DELIVER_NO" in sql and "HR_DELIVER_CARRY" in sql


def test_compile_count_distinct() -> None:
    sql = compile_oracle("count_distinct(deliver_no)", TMS_MAPPINGS, TMS_STANDARD_FIELDS)
    assert "count(distinct" in sql.lower()


def test_compile_rate() -> None:
    sql = compile_oracle("rate(actual_time <= plan_time)", TMS_MAPPINGS, TMS_STANDARD_FIELDS)
    assert "case when" in sql.lower()


def test_compile_missing_mapping_fails() -> None:
    with pytest.raises(ValueError, match="no active mapping"):
        compile_oracle("count_distinct(deliver_no)", {}, TMS_STANDARD_FIELDS)


def test_compile_group_by() -> None:
    sql = compile_for_dialect("count_distinct(deliver_no) group_by(carrier_name)",
                               TMS_MAPPINGS, TMS_STANDARD_FIELDS, dialect="oracle")
    assert "GROUP BY" in sql.upper() and "CARRIER_NAME" in sql.upper()


def test_compile_enum_transform() -> None:
    sql = compile_oracle("rate(car_status = 'signed')", TMS_MAPPINGS, TMS_STANDARD_FIELDS)
    assert "CAR_STATUS" in sql


def test_compile_unsupported_dialect() -> None:
    with pytest.raises(NotImplementedError):
        compile_for_dialect("count(x)", TMS_MAPPINGS, TMS_STANDARD_FIELDS, dialect="mysql")


# ── Edge / boundary cases ────────────────────────────────────────────

def test_parse_expression_empty_string() -> None:
    with pytest.raises(DSLParseError):
        parse_expression("")


def test_parse_full_empty_string() -> None:
    with pytest.raises(DSLParseError):
        parse_full("")


def test_tokenize_star_raises() -> None:
    """* is not a valid DSL token."""
    with pytest.raises(DSLParseError):
        tokenize("count(*)")


def test_parse_full_filter_requires_comparison() -> None:
    """filter() with a bare field (no operator) should raise."""
    with pytest.raises(DSLParseError, match="filter"):
        parse_full("count(deliver_no) filter(carrier_name)")


def test_compile_pending_mapping_treated_as_missing() -> None:
    """A pending-status mapping must not be used by the compiler."""
    pending_mappings = {
        "deliver_no": FieldMapping(
            mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
            data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY",
            physical_column="DELIVER_NO", confidence=1.0, source="manual", status="pending",
        )
    }
    with pytest.raises(ValueError, match="no active mapping"):
        compile_oracle("count_distinct(deliver_no)", pending_mappings, TMS_STANDARD_FIELDS)


def test_compile_stale_mapping_treated_as_missing() -> None:
    stale_mappings = {
        "deliver_no": FieldMapping(
            mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
            data_source_id="ds_tms", physical_table="HR_DELIVER_CARRY",
            physical_column="DELIVER_NO", confidence=1.0, source="manual", status="stale",
        )
    }
    with pytest.raises(ValueError, match="status='stale'"):
        compile_oracle("count_distinct(deliver_no)", stale_mappings, TMS_STANDARD_FIELDS)


def test_infer_from_table_empty_mappings() -> None:
    """Empty mappings triggers 'no active mapping' on first field resolution."""
    with pytest.raises(ValueError, match="no active mapping"):
        compile_oracle("count(deliver_no)", {}, TMS_STANDARD_FIELDS)


def test_infer_from_table_blank_physical_table_ignored() -> None:
    """A mapping with blank physical_table must be rejected at model creation."""
    with pytest.raises(Exception):
        FieldMapping(
            mapping_id="m1", pack_id="tms", standard_field_id="deliver_no",
            data_source_id="ds_tms", physical_table="",
            physical_column="DELIVER_NO", status="active",
        )


def test_multi_clause_group_by_and_filter() -> None:
    """Two trailing clauses should both be present in the compiled SQL."""
    sql = compile_oracle(
        "count_distinct(deliver_no) group_by(carrier_name)",
        TMS_MAPPINGS,
        TMS_STANDARD_FIELDS,
    )
    assert "GROUP BY" in sql.upper()
    assert "CARRIER_NAME" in sql.upper()


def test_enum_transform_no_pairs_returns_column() -> None:
    """A malformed enum transform (no -> pairs) returns the raw column."""
    from sq_bi_runtime.dsl_compiler import _apply_enum_transform
    result = _apply_enum_transform("COL", "enum:NOARROW")
    assert result == "COL"


def test_enum_transform_single_pair() -> None:
    from sq_bi_runtime.dsl_compiler import _apply_enum_transform
    result = _apply_enum_transform("STATUS", "enum:open->'1'")
    assert "CASE STATUS" in result
    assert "'1'" in result


def test_validate_expression_with_dsl_keyword_not_flagged() -> None:
    """DSL keywords like 'and', 'or' must not be flagged as undeclared fields."""
    errors = validate_logical_expression(
        "rate(actual_time <= plan_time)",
        TMS_STANDARD_FIELDS,
    )
    assert errors == []


def test_enum_transform_json_format() -> None:
    """JSON DSL enum_map format must produce the same CASE expression as legacy format."""
    from sq_bi_runtime.dsl_compiler import _apply_enum_transform
    transform = '{"type": "enum_map", "mapping": {"signed": "3", "in_transit": "5"}}'
    result = _apply_enum_transform("STATUS", transform)
    assert "CASE STATUS" in result
    assert "'signed'" in result
    assert "'3'" in result
    assert "'in_transit'" in result
    assert "'5'" in result
    assert "ELSE STATUS END" in result


def test_enum_transform_json_empty_mapping_returns_column() -> None:
    from sq_bi_runtime.dsl_compiler import _apply_enum_transform
    result = _apply_enum_transform("COL", '{"type": "enum_map", "mapping": {}}')
    assert result == "COL"


def test_enum_transform_json_malformed_returns_column() -> None:
    from sq_bi_runtime.dsl_compiler import _apply_enum_transform
    result = _apply_enum_transform("COL", '{"type": "enum_map", "mapping": "NOT_A_DICT"}')
    assert result == "COL"


def test_enum_transform_json_invalid_json_returns_column() -> None:
    from sq_bi_runtime.dsl_compiler import _apply_enum_transform
    result = _apply_enum_transform("COL", '{bad json')
    assert result == "COL"


def test_compile_with_json_enum_transform() -> None:
    """End-to-end: JSON enum_map transform applied during logical-to-physical compile."""
    from sq_bi_runtime.dsl_compiler import compile_oracle
    from sq_bi_contracts.field_mount import FieldMapping
    transform = '{"type": "enum_map", "mapping": {"signed": "3", "delayed": "9"}}'
    mappings = {
        "car_status": FieldMapping(
            mapping_id="m1", pack_id="tms", standard_field_id="car_status",
            data_source_id="ds_tms", physical_table="T",
            physical_column="CAR_STATUS", transform=transform,
            source="auto", status="active",
        )
    }
    sql = compile_oracle("count(car_status)", mappings, TMS_STANDARD_FIELDS)
    assert "CASE" in sql
    assert "'signed'" in sql


def test_compile_infers_table_only_from_referenced_mappings() -> None:
    mappings = dict(TMS_MAPPINGS)
    mappings["deliver_no"] = mappings["deliver_no"].model_copy(
        update={"physical_table": "SHIPMENT_FACT"}
    )
    mappings["carrier_name"] = mappings["carrier_name"].model_copy(
        update={"physical_table": "CARRIER_DIM"}
    )

    sql = compile_oracle("count_distinct(deliver_no)", mappings, TMS_STANDARD_FIELDS)

    assert "FROM SHIPMENT_FACT" in sql


def test_compile_rejects_undeclared_cross_table_expression() -> None:
    mappings = dict(TMS_MAPPINGS)
    mappings["carrier_name"] = mappings["carrier_name"].model_copy(
        update={"physical_table": "CARRIER_DIM"}
    )

    with pytest.raises(ValueError, match="multiple physical tables"):
        compile_oracle(
            "count_distinct(deliver_no) group_by(carrier_name)",
            mappings,
            TMS_STANDARD_FIELDS,
        )
