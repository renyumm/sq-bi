"""Phase 3 regression tests: TMS logical formula migration.

Verifies that:
1. Each DSL-migrated metric compiles without error given the default oracle_tms mappings.
2. Compiled SQL contains the expected physical columns (structural equivalence).
3. Official pack validation accepts the migrated tms pack.yaml.
4. Escape-hatch metrics are correctly identified and skipped.
"""
from __future__ import annotations

from pathlib import Path

import yaml
import pytest

from sq_bi_contracts.domain_pack import PackStandardField
from sq_bi_contracts.field_mount import FieldMapping
from sq_bi_runtime.dsl_compiler import compile_oracle
from sq_bi_runtime.pack_loader import load_manifest, validate_official_pack_semantics

# ── Fixtures ──────────────────────────────────────────────────────────

TMS_PACK_DIR = Path(__file__).parents[3] / "domain-packs" / "tms"

STANDARD_FIELDS: dict[str, PackStandardField] = {
    sf.field_id: sf
    for sf in [
        PackStandardField(field_id="deliver_no", business_name="发货单号", data_type="text", required=True),
        PackStandardField(field_id="apply_no", business_name="发货申请编号", data_type="text", required=True),
        PackStandardField(field_id="carrier_name", business_name="承运商名称", data_type="text"),
        PackStandardField(field_id="plan_time", business_name="计划到货时间", data_type="datetime"),
        PackStandardField(field_id="actual_time", business_name="实际到货时间", data_type="datetime"),
        PackStandardField(field_id="car_status", business_name="车辆状态", data_type="enum"),
        PackStandardField(field_id="transport_type", business_name="运输方式", data_type="enum"),
        PackStandardField(field_id="enquiry_no", business_name="询价单号", data_type="text"),
    ]
}

# Default mappings matching oracle_tms.yaml
ORACLE_TMS_MAPPINGS: dict[str, FieldMapping] = {
    "deliver_no": FieldMapping(
        mapping_id="m_deliver_no", pack_id="tms", standard_field_id="deliver_no",
        data_source_id="oracle_tms", physical_table="HR_DELIVER_CARRY",
        physical_column="DELIVER_NO", source="auto", status="active",
    ),
    "apply_no": FieldMapping(
        mapping_id="m_apply_no", pack_id="tms", standard_field_id="apply_no",
        data_source_id="oracle_tms", physical_table="HR_DELIVER_APPLY",
        physical_column="APPLY_NO", source="auto", status="active",
    ),
    "carrier_name": FieldMapping(
        mapping_id="m_carrier_name", pack_id="tms", standard_field_id="carrier_name",
        data_source_id="oracle_tms", physical_table="HR_DELIVER_FORM",
        physical_column="CARRIER_NAME", source="auto", status="active",
    ),
    "plan_time": FieldMapping(
        mapping_id="m_plan_time", pack_id="tms", standard_field_id="plan_time",
        data_source_id="oracle_tms", physical_table="HR_DELIVER_CARRY",
        physical_column="PLAN_TIME", source="auto", status="active",
    ),
    "actual_time": FieldMapping(
        mapping_id="m_actual_time", pack_id="tms", standard_field_id="actual_time",
        data_source_id="oracle_tms", physical_table="HR_DELIVER_CARRY",
        physical_column="ACTUAL_TIME", source="auto", status="active",
    ),
    "car_status": FieldMapping(
        mapping_id="m_car_status", pack_id="tms", standard_field_id="car_status",
        data_source_id="oracle_tms", physical_table="HR_DELIVER_CARRY",
        physical_column="CAR_STATUS", source="auto", status="active",
    ),
    "transport_type": FieldMapping(
        mapping_id="m_transport_type", pack_id="tms", standard_field_id="transport_type",
        data_source_id="oracle_tms", physical_table="HR_DELIVER_APPLY",
        physical_column="TRANSPORT_TYPE", source="auto", status="active",
    ),
    "enquiry_no": FieldMapping(
        mapping_id="m_enquiry_no", pack_id="tms", standard_field_id="enquiry_no",
        data_source_id="oracle_tms", physical_table="RFQ_ENQUIRY_INFO",
        physical_column="ENQUIRY_NO", source="auto", status="active",
    ),
}


def _load_semantic() -> dict:
    path = TMS_PACK_DIR / "semantic" / "tms_semantic.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _compile(expression: str) -> str:
    return compile_oracle(expression, ORACLE_TMS_MAPPINGS, STANDARD_FIELDS)


# ── Compilation equivalence tests ────────────────────────────────────


def test_apply_count_compiles() -> None:
    # Use only the mappings referenced by this expression to avoid table-vote ambiguity
    sql = compile_oracle("count_distinct(apply_no)", {"apply_no": ORACLE_TMS_MAPPINGS["apply_no"]}, STANDARD_FIELDS)
    assert "APPLY_NO" in sql
    assert "HR_DELIVER_APPLY" in sql


def test_execution_count_compiles() -> None:
    sql = _compile("count_distinct(deliver_no)")
    assert "DELIVER_NO" in sql
    assert "HR_DELIVER_CARRY" in sql


def test_ontime_rate_compiles() -> None:
    sql = _compile("rate(actual_time <= plan_time)")
    assert "ACTUAL_TIME" in sql
    assert "PLAN_TIME" in sql
    assert "case when" in sql.lower()


def test_in_transit_count_compiles() -> None:
    sql = _compile("count_distinct(deliver_no) filter(car_status = '3')")
    assert "CAR_STATUS" in sql
    assert "'3'" in sql
    assert "DELIVER_NO" in sql


def test_unloaded_count_compiles() -> None:
    sql = _compile("count_distinct(deliver_no) filter(car_status = '5')")
    assert "CAR_STATUS" in sql
    assert "'5'" in sql


def test_transport_mode_apply_count_compiles() -> None:
    sql = _compile("count_distinct(apply_no) group_by(transport_type)")
    assert "TRANSPORT_TYPE" in sql
    assert "APPLY_NO" in sql
    assert "GROUP BY" in sql.upper()


def test_delayed_count_compiles() -> None:
    sql = _compile("count_distinct(deliver_no) filter(actual_time > plan_time)")
    assert "ACTUAL_TIME" in sql
    assert "PLAN_TIME" in sql
    assert ">" in sql


def test_delayed_rate_compiles() -> None:
    sql = _compile("rate(actual_time > plan_time)")
    assert "ACTUAL_TIME" in sql
    assert "PLAN_TIME" in sql
    assert "case when" in sql.lower()


def test_enquiry_count_compiles() -> None:
    sql = compile_oracle("count_distinct(enquiry_no)", {"enquiry_no": ORACLE_TMS_MAPPINGS["enquiry_no"]}, STANDARD_FIELDS)
    assert "ENQUIRY_NO" in sql
    assert "RFQ_ENQUIRY_INFO" in sql


# ── Semantic YAML structural tests ───────────────────────────────────


def test_all_official_metrics_have_logical_formula_or_escape_hatch() -> None:
    """Every metric in the TMS semantic YAML must have logical_formula or escape_hatch."""
    semantic = _load_semantic()
    violations = []
    for m in semantic.get("metrics") or []:
        if not m.get("logical_formula") and not m.get("escape_hatch"):
            violations.append(m.get("metric_code", "<unknown>"))
    assert violations == [], f"Metrics missing logical_formula or escape_hatch: {violations}"


def test_dsl_metrics_list() -> None:
    """Spot-check that expected DSL-expressible metrics have logical_formula."""
    semantic = _load_semantic()
    metrics_by_code = {m["metric_code"]: m for m in semantic.get("metrics") or []}
    expected_dsl = [
        "apply_count", "form_count", "execution_count", "ontime_rate",
        "in_transit_count", "unloaded_count", "signed_count",
        "transport_mode_apply_count", "delayed_count", "enquiry_count",
        "delayed_rate",
    ]
    for code in expected_dsl:
        assert code in metrics_by_code, f"Metric '{code}' not found in semantic YAML"
        assert metrics_by_code[code].get("logical_formula"), f"Metric '{code}' missing logical_formula"


def test_escape_hatch_metrics_list() -> None:
    """Spot-check that expected non-DSL metrics have escape_hatch: true."""
    semantic = _load_semantic()
    metrics_by_code = {m["metric_code"]: m for m in semantic.get("metrics") or []}
    expected_escape = [
        "unsigned_count", "carrier_ontime_rate", "project_shipment_count",
        "supplier_quotation_count", "avg_delay_hours", "signed_rate",
        "unsigned_rate", "carrier_delay_count", "rfq_response_rate",
        "carrier_shipment_count",
    ]
    for code in expected_escape:
        assert code in metrics_by_code, f"Metric '{code}' not found"
        assert metrics_by_code[code].get("escape_hatch"), f"Metric '{code}' missing escape_hatch"


# ── Official pack validation ──────────────────────────────────────────


def test_official_pack_validation_passes() -> None:
    """validate_official_pack_semantics must return no violations for migrated TMS pack."""
    manifest_path = TMS_PACK_DIR / "pack.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    violations = validate_official_pack_semantics(TMS_PACK_DIR, raw)
    assert violations == [], f"Unexpected violations: {violations}"


def test_load_manifest_tms_succeeds() -> None:
    """load_manifest must succeed and return standard_fields for the TMS pack."""
    manifest = load_manifest(TMS_PACK_DIR)
    assert manifest.pack_id == "tms"
    assert len(manifest.standard_fields) >= 8
    field_ids = {sf.field_id for sf in manifest.standard_fields}
    assert "deliver_no" in field_ids
    assert "plan_time" in field_ids
    assert "car_status" in field_ids


def test_official_pack_validation_fails_on_bare_physical_sql(tmp_path: Path) -> None:
    """A fake official pack with bare physical SQL must fail validation."""
    pack_dir = tmp_path / "fake_pack"
    pack_dir.mkdir()
    semantic_dir = pack_dir / "semantic"
    semantic_dir.mkdir()
    (semantic_dir / "fake.yaml").write_text(
        "metrics:\n"
        "  - metric_code: bare_metric\n"
        "    name: Bare Metric\n"
        "    formula:\n"
        "      expression: 'select count(*) from SOME_TABLE'\n",
        encoding="utf-8",
    )
    raw = {
        "official": True,
        "assets": [{"asset_type": "semantic", "path": "semantic/fake.yaml"}],
    }
    violations = validate_official_pack_semantics(pack_dir, raw)
    assert any("bare_metric" in v for v in violations)
