from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sq_bi_contracts.audit import AuditQuery, AuditRecord
from sq_bi_runtime.audit_store import SQLiteAuditStore
from sq_bi_runtime.telemetry import (
    add_span,
    format_prometheus_metrics,
    get_metrics_snapshot,
    get_trace,
    incr_metric,
    log_info,
    record_duration,
    start_trace,
    trace_span,
)


def test_incr_metric() -> None:
    snapshot = get_metrics_snapshot()
    before = snapshot.get("requests_total", 0)
    incr_metric("requests_total")
    after = get_metrics_snapshot()["requests_total"]
    assert after == before + 1


def test_record_duration() -> None:
    record_duration("llm_call", 42.5)
    snapshot = get_metrics_snapshot()
    assert snapshot["llm_call_total"] >= 1
    assert snapshot["llm_call_duration_ms_total"] >= 42.5


def test_prometheus_format() -> None:
    output = format_prometheus_metrics()
    assert "sq_bi_requests_total" in output


def test_trace_span() -> None:
    request_id = "req_test"
    start_trace(request_id)
    with trace_span(request_id, "test_op", detail="hello"):
        time.sleep(0.001)
    spans = get_trace(request_id)
    assert len(spans) == 1
    assert spans[0]["operation"] == "test_op"
    assert spans[0]["duration_ms"] > 0


def test_add_span() -> None:
    request_id = "req_span"
    start_trace(request_id)
    add_span(request_id, "query", 15.0, {"table": "users"})
    spans = get_trace(request_id)
    assert len(spans) == 1
    assert spans[0]["metadata"]["table"] == "users"


# ── Audit store tests ──

def test_audit_store_append_and_query(tmp_path: Path) -> None:
    store = SQLiteAuditStore(tmp_path / "test_audit.sqlite3")
    record = AuditRecord(
        audit_id="aud_001",
        request_id="req_1",
        user_id="u1",
        org_id="o1",
        data_source_id="ds1",
        executed_sql="SELECT 1",
        status="success",
        created_at=datetime.now(timezone.utc),
    )
    store.append(record)
    results = store.query(AuditQuery(request_id="req_1"))
    assert len(results) == 1
    assert results[0].audit_id == "aud_001"


def test_audit_store_get(tmp_path: Path) -> None:
    store = SQLiteAuditStore(tmp_path / "test_get.sqlite3")
    record = AuditRecord(
        audit_id="aud_002",
        request_id="req_2",
        user_id="u1",
        org_id="o1",
        data_source_id="ds1",
        executed_sql="SELECT * FROM users",
        status="success",
        created_at=datetime.now(timezone.utc),
    )
    store.append(record)
    found = store.get("aud_002")
    assert found is not None
    assert found.executed_sql == "SELECT * FROM users"


def test_audit_store_append_only_not_modifiable(tmp_path: Path) -> None:
    store = SQLiteAuditStore(tmp_path / "test_append.sqlite3")
    record = AuditRecord(
        audit_id="aud_003",
        request_id="req_3",
        user_id="u1",
        org_id="o1",
        data_source_id="ds1",
        executed_sql="SELECT 1",
        status="success",
        created_at=datetime.now(timezone.utc),
    )
    store.append(record)
    # Verify it's there
    assert store.get("aud_003") is not None
    # Appending doesn't update existing records (append-only)
    record2 = AuditRecord(
        audit_id="aud_003",  # same id, different data
        request_id="req_3",
        user_id="u2",
        org_id="o2",
        data_source_id="ds1",
        executed_sql="SELECT 2",
        status="success",
        created_at=datetime.now(timezone.utc),
    )
    with pytest.raises(Exception):
        store.append(record2)  # should raise UNIQUE constraint violation


def test_audit_store_pagination(tmp_path: Path) -> None:
    store = SQLiteAuditStore(tmp_path / "test_pag.sqlite3")
    for i in range(5):
        store.append(AuditRecord(
            audit_id=f"aud_{i:03d}",
            request_id="req_pag",
            user_id="u1",
            org_id="o1",
            data_source_id="ds1",
            executed_sql="SELECT 1",
            status="success",
            created_at=datetime.now(timezone.utc),
        ))
    page1 = store.query(AuditQuery(page=1, page_size=2))
    assert len(page1) == 2
    page2 = store.query(AuditQuery(page=2, page_size=2))
    assert len(page2) == 2


def test_trace_store_eviction_when_full() -> None:
    from sq_bi_runtime.telemetry import _trace_store, _TRACE_STORE_MAX_ENTRIES, start_trace
    _trace_store.clear()
    for i in range(_TRACE_STORE_MAX_ENTRIES + 5):
        start_trace(f"req_{i:06d}")
    assert len(_trace_store) <= _TRACE_STORE_MAX_ENTRIES


def test_structured_log_masks_secrets(capsys: pytest.CaptureFixture[str]) -> None:
    import logging
    from sq_bi_runtime.telemetry import configure_structured_logging, log_info
    configure_structured_logging()
    log_info("test event", password="should_be_masked", username="alice")
    captured = capsys.readouterr()
    # The structured logger writes to stderr; password must be masked
    assert "should_be_masked" not in captured.err
    assert "********" in captured.err


def test_audit_store_empty_list_fields_roundtrip(tmp_path: Path) -> None:
    """Empty list fields should round-trip as [] not ['']."""
    store = SQLiteAuditStore(tmp_path / "test_empty.sqlite3")
    record = AuditRecord(
        audit_id="aud_empty",
        request_id="req_e",
        user_id="u1",
        org_id="o1",
        data_source_id="ds1",
        executed_sql="SELECT 1",
        status="success",
        applied_rls_scope=[],
        resolved_metrics=[],
        resolved_skills=[],
        created_at=datetime.now(timezone.utc),
    )
    store.append(record)
    found = store.get("aud_empty")
    assert found is not None
    assert found.applied_rls_scope == []
    assert found.resolved_metrics == []
    assert found.resolved_skills == []


def test_audit_store_time_range_filter(tmp_path: Path) -> None:
    """Time-range query filters by created_at correctly."""
    from datetime import timedelta
    store = SQLiteAuditStore(tmp_path / "test_time.sqlite3")
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(hours=2)
    recent_time = now - timedelta(minutes=5)

    store.append(AuditRecord(
        audit_id="old_rec",
        request_id="req_old",
        user_id="u1",
        org_id="o1",
        data_source_id="ds1",
        executed_sql="SELECT 1",
        status="success",
        created_at=old_time,
    ))
    store.append(AuditRecord(
        audit_id="recent_rec",
        request_id="req_new",
        user_id="u1",
        org_id="o1",
        data_source_id="ds1",
        executed_sql="SELECT 2",
        status="success",
        created_at=recent_time,
    ))
    results = store.query(AuditQuery(start_time=now - timedelta(hours=1)))
    ids = [r.audit_id for r in results]
    assert "recent_rec" in ids
    assert "old_rec" not in ids
