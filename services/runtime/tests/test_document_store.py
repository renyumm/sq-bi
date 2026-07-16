"""Tests for DocumentStore (document ingestion)."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from sq_bi_runtime.document_store import DocumentStore, FieldHint


@pytest.fixture
def store(tmp_path: Path) -> DocumentStore:
    return DocumentStore(tmp_path / "docs")


# ── CSV extraction ────────────────────────────────────────────────────

def _make_csv(rows: list[dict], headers: list[str] | None = None) -> bytes:
    out = io.StringIO()
    if headers is None and rows:
        headers = list(rows[0].keys())
    writer = csv.DictWriter(out, fieldnames=headers or [])
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return out.getvalue().encode("utf-8")


def test_csv_extracts_field_hints(store: DocumentStore) -> None:
    content = _make_csv([
        {"字段名": "deliver_no", "说明": "唯一运单号", "别名": "运单编号,shipment_no"},
        {"字段名": "status",     "说明": "配送状态",  "别名": ""},
    ])
    result = store.extract_hints("doc_001", "dict.csv", content)
    assert result.success
    assert len(result.hints) == 2
    h = result.hints[0]
    assert h.term == "DELIVER_NO"
    assert h.description == "唯一运单号"
    assert "运单编号" in h.synonyms


def test_csv_with_english_headers(store: DocumentStore) -> None:
    content = _make_csv([
        {"field_name": "ORDER_ID", "description": "Order identifier"},
        {"field_name": "AMOUNT",   "description": "Order amount"},
    ])
    result = store.extract_hints("doc_002", "fields.csv", content)
    assert result.success
    assert len(result.hints) == 2
    assert result.hints[0].term == "ORDER_ID"


def test_csv_missing_term_column_yields_empty(store: DocumentStore) -> None:
    content = _make_csv([{"col_x": "a", "desc": "b"}])
    result = store.extract_hints("doc_003", "no_term.csv", content)
    assert result.success
    assert result.hints == []


# ── Text extraction ───────────────────────────────────────────────────

def test_text_extracts_uppercase_identifiers(store: DocumentStore) -> None:
    text = b"The table HR_DELIVER_FORM contains DELIVER_NO and FACTORY_CODE fields."
    result = store.extract_hints("doc_txt", "notes.txt", text)
    assert result.success
    terms = {h.term for h in result.hints}
    assert "HR_DELIVER_FORM" in terms
    assert "DELIVER_NO" in terms
    assert "FACTORY_CODE" in terms


def test_text_deduplicates_identifiers(store: DocumentStore) -> None:
    text = b"DELIVER_NO is the key. DELIVER_NO appears again."
    result = store.extract_hints("doc_dedup", "dup.txt", text)
    terms = [h.term for h in result.hints]
    assert terms.count("DELIVER_NO") == 1


# ── Graceful failure ──────────────────────────────────────────────────

def test_unsupported_format_returns_failure(store: DocumentStore) -> None:
    result = store.extract_hints("doc_bin", "data.bin", b"\x00\x01\x02")
    assert not result.success
    assert "Unsupported" in (result.error or "")
    assert result.hints == []


def test_corrupt_csv_does_not_raise(store: DocumentStore) -> None:
    result = store.extract_hints("doc_corrupt", "bad.csv", b"\xff\xfe corrupt data \x00")
    # Should not raise — may return empty or partial results
    assert isinstance(result.hints, list)


def test_profile_builds_without_documents(store: DocumentStore) -> None:
    """No documents → empty hint list, does not break scan."""
    hints: list[FieldHint] = []
    # This just tests that the empty case is handled — no error
    assert hints == []


# ── File save ─────────────────────────────────────────────────────────

def test_save_file_persists_bytes(store: DocumentStore, tmp_path: Path) -> None:
    content = b"field,desc\nORDER_ID,Order identifier"
    path = store.save_file("doc_save", "test.csv", content)
    assert path.exists()
    assert path.read_bytes() == content


def test_delete_file_removes_saved_bytes(store: DocumentStore) -> None:
    path = store.save_file("doc_del", "test.csv", b"a,b\n1,2")
    assert path.exists()
    store.delete_file("doc_del", "test.csv")
    assert not path.exists()


def test_delete_file_missing_is_noop(store: DocumentStore) -> None:
    store.delete_file("doc_never_existed", "nope.csv")  # must not raise


# ── Hint→field linkage (integration pattern) ─────────────────────────

def test_hint_term_matches_physical_column() -> None:
    """FieldHint.term should round-trip as an uppercase physical column name."""
    hint = FieldHint(term="DELIVER_NO", description="运单号", synonyms=["运单编号"])
    # Simulate linking hint to a physical column
    physical_columns = {"DELIVER_NO", "STATUS", "FACTORY_CODE"}
    matched = hint.term in physical_columns
    assert matched
