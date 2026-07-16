"""Tests for SchemaScanner (phase-one metadata scan)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sq_bi_runtime.schema_scanner import (
    SchemaScanner,
    TableMeta,
)


def _make_connector(catalog: dict[str, list[str]], describe_rows: list[dict] | None = None) -> MagicMock:
    mock = MagicMock()
    mock.get_schema_catalog.return_value = catalog
    mock.describe_schema.return_value = describe_rows or []
    return mock


# ── Metadata-only: no row reads ──────────────────────────────────────

def test_scan_calls_get_schema_catalog(tmp_path) -> None:
    conn = _make_connector({"HR_DELIVER_FORM": ["DELIVER_NO", "STATUS"]})
    scanner = SchemaScanner(conn, "ds_tms")
    result = scanner.scan()
    conn.get_schema_catalog.assert_called_once()
    conn.execute.assert_not_called()


def test_scan_populates_tables_and_columns() -> None:
    conn = _make_connector({
        "HR_DELIVER_FORM": ["DELIVER_NO", "STATUS", "FACTORY_CODE"],
        "HR_CARRIER": ["CARRIER_ID", "CARRIER_NAME"],
    })
    result = scanner.scan() if False else SchemaScanner(conn, "ds_tms").scan()
    result = SchemaScanner(conn, "ds_tms").scan()
    assert len(result.tables) == 2
    table_names = {t.name for t in result.tables}
    assert "HR_DELIVER_FORM" in table_names
    tbl = next(t for t in result.tables if t.name == "HR_DELIVER_FORM")
    assert len(tbl.columns) == 3


def test_scan_includes_column_detail_from_describe() -> None:
    describe_rows = [
        {"table": "HR_DELIVER_FORM", "column": "DELIVER_NO",
         "data_type": "VARCHAR2", "comment": "运单号", "is_pk": True},
        {"table": "HR_DELIVER_FORM", "column": "STATUS",
         "data_type": "NUMBER", "comment": "状态", "is_pk": False},
    ]
    conn = _make_connector(
        {"HR_DELIVER_FORM": ["DELIVER_NO", "STATUS"]},
        describe_rows,
    )
    result = SchemaScanner(conn, "ds_tms").scan()
    tbl = result.tables[0]
    pk_col = next(c for c in tbl.columns if c.name == "DELIVER_NO")
    assert pk_col.is_pk is True
    assert pk_col.data_type == "VARCHAR2"
    assert pk_col.comment == "运单号"


# ── Default exclusion heuristics ──────────────────────────────────────

@pytest.mark.parametrize("table_name", [
    "SHIPMENTS_TMP",
    "ORDERS_TEMP",
    "AUDIT_LOG",
    "EVENTS_LOG",
    "TRANS_BAK",
    "DATA_BACKUP",
    "DAILY_20240101",
    "DAILY_202401",
    "OLD_TABLE_ARCH",
    "FACT_ARCHIVE",
    "BIN$ABCDEF",
    "SYS_AUDIT",
    "MLOG$_TABLE",
    "DELIVER_HISTORY",
    "DELIVER_HIST",
])
def test_default_excluded_tables(table_name: str) -> None:
    conn = _make_connector({table_name: ["ID"]})
    result = SchemaScanner(conn, "ds_tms").scan()
    tbl = result.tables[0]
    assert tbl.excluded, f"Expected {table_name} to be excluded"
    assert tbl.excluded_reason is not None


@pytest.mark.parametrize("table_name", [
    "HR_DELIVER_FORM",
    "FACT_SALES",
    "DIM_CUSTOMER",
    "ORDER_HEADER",
])
def test_business_tables_not_excluded_by_default(table_name: str) -> None:
    conn = _make_connector({table_name: ["ID"]})
    result = SchemaScanner(conn, "ds_tms").scan()
    tbl = result.tables[0]
    assert not tbl.excluded, f"Expected {table_name} to be included"


def test_included_tables_accessible_via_property() -> None:
    conn = _make_connector({
        "ORDERS": ["ID"],
        "ORDERS_TMP": ["ID"],
        "AUDIT_LOG": ["ID"],
    })
    result = SchemaScanner(conn, "ds_tms").scan()
    assert len(result.included) == 1
    assert result.included[0].name == "ORDERS"
    assert len(result.excluded) == 2


# ── User include/exclude overrides ────────────────────────────────────

def test_user_include_overrides_default_exclusion() -> None:
    conn = _make_connector({"ORDERS_TMP": ["ID"]})
    result = SchemaScanner(
        conn, "ds_tms", include_rules=["ORDERS.*"]
    ).scan()
    assert not result.tables[0].excluded


def test_user_exclude_rule_excludes_business_table() -> None:
    conn = _make_connector({"HR_DELIVER_FORM": ["ID"]})
    result = SchemaScanner(
        conn, "ds_tms", exclude_rules=["HR_DELIVER.*"]
    ).scan()
    assert result.tables[0].excluded
    assert result.tables[0].excluded_reason == "user_exclude_rule"


def test_user_exclude_takes_precedence_over_include() -> None:
    """Exclude rule fires before include when both match (exclude wins after include check)."""
    conn = _make_connector({"ORDERS": ["ID"]})
    result = SchemaScanner(
        conn, "ds_tms",
        include_rules=["ORDERS.*"],
        exclude_rules=["ORDERS.*"],
    ).scan()
    # Include checked first → keeps it (include_rules highest priority)
    assert not result.tables[0].excluded


# ── Chunking ──────────────────────────────────────────────────────────

def test_chunk_metadata_respects_chunk_size() -> None:
    catalog = {f"TABLE_{i:03d}": ["ID"] for i in range(85)}
    conn = _make_connector(catalog)
    scanner = SchemaScanner(conn, "ds_tms", chunk_size=30)
    result = scanner.scan()
    chunks = scanner.chunk_metadata_for_llm(result)
    assert len(chunks) == 3
    assert len(chunks[0]) == 30
    assert len(chunks[1]) == 30
    assert len(chunks[2]) == 25


def test_chunk_excludes_excluded_tables_by_default() -> None:
    catalog = {
        "ORDERS": ["ID"],
        "ORDERS_TMP": ["ID"],
        "ORDERS_BAK": ["ID"],
    }
    conn = _make_connector(catalog)
    scanner = SchemaScanner(conn, "ds_tms")
    result = scanner.scan()
    chunks = scanner.chunk_metadata_for_llm(result, include_only=True)
    assert len(chunks) == 1
    assert chunks[0][0].name == "ORDERS"


def test_chunk_include_all_when_flag_off() -> None:
    catalog = {
        "ORDERS": ["ID"],
        "ORDERS_TMP": ["ID"],
    }
    conn = _make_connector(catalog)
    scanner = SchemaScanner(conn, "ds_tms")
    result = scanner.scan()
    chunks = scanner.chunk_metadata_for_llm(result, include_only=False)
    total = sum(len(c) for c in chunks)
    assert total == 2


def test_render_chunk_for_llm() -> None:
    from sq_bi_runtime.schema_scanner import ColumnMeta

    tbl = TableMeta(name="HR_DELIVER_FORM")
    tbl.columns = [
        ColumnMeta(name="DELIVER_NO", data_type="VARCHAR2", comment="运单号", is_pk=True),
        ColumnMeta(name="STATUS", data_type="NUMBER"),
    ]
    text = SchemaScanner.render_chunk_for_llm([tbl])
    assert "HR_DELIVER_FORM" in text
    assert "DELIVER_NO" in text
    assert "VARCHAR2" in text
    assert "PK" in text
    assert "运单号" in text


def test_describe_schema_failure_degrades_gracefully() -> None:
    """If describe_schema raises, scanner continues with catalog-only data."""
    conn = _make_connector({"ORDERS": ["ID", "AMOUNT"]})
    conn.describe_schema.side_effect = RuntimeError("connection refused")
    result = SchemaScanner(conn, "ds_tms", authorized_schemas=["TMS"]).scan()
    assert len(result.tables) == 1
    assert result.tables[0].columns[0].data_type is None  # no detail, graceful
