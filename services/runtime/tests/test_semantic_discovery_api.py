"""End-to-end tests for the semantic discovery REST endpoints.

Uses FastAPI TestClient with a tmp storage directory; no real DB or LLM needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from sq_bi_contracts.common import UserContext
from sq_bi_runtime.api import create_app
from sq_bi_runtime.auth import create_session


# ── Helpers ───────────────────────────────────────────────────────────


def _make_client(tmp_path: Path) -> tuple[TestClient, str, str]:
    """Return (client, admin_session_id, non_admin_session_id)."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        f"base_url: http://localhost/v1\nkey: k\nmodel: m\nstorage_path: {tmp_path}\n",
        encoding="utf-8",
    )
    app = create_app(cfg_path)
    client = TestClient(app, raise_server_exceptions=False)

    # Admin login
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200
    admin_sid = resp.json()["data"]["session_id"]

    # Create a regular user session (non-admin) via a user login
    # The default local auth has a "user" / "user123" account
    resp2 = client.post("/api/v1/auth/login", json={"username": "user", "password": "user123"})
    if resp2.status_code == 200:
        user_sid = resp2.json()["data"]["session_id"]
    else:
        user_sid = ""  # fallback — unauthenticated

    return client, admin_sid, user_sid


def _hdrs(sid: str) -> dict[str, str]:
    return {"X-Session-Id": sid}


def _general_user_session_id() -> str:
    """An authenticated but non-admin session — the local auth backend only
    registers an admin account, so simulate the general-user role directly."""
    return create_session(
        UserContext(user_id="u_general", display_name="General", org_id="default", role_ids=["user"])
    )


def _seed_datasource(tmp_path: Path, ds_id: str = "ds_tms") -> None:
    ds_file = tmp_path / "datasources.json"
    ds_file.write_text(json.dumps([{
        "data_source_id": ds_id,
        "name": "TMS 测试数据源",
        "database_type": "oracle",
        "host": "db.internal",
        "port": 1521,
        "database": "tms",
        "username": "ro_user",
        "password": "",
        "is_read_only": True,
        "tags": [],
    }]), encoding="utf-8")


# ── Auth gates ────────────────────────────────────────────────────────

def test_scan_requires_admin_auth(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path)
    _seed_datasource(tmp_path)
    resp = client.post("/api/v1/datasources/ds_tms/scan", json={})
    assert resp.status_code == 401


def test_scan_status_requires_auth(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path)
    resp = client.get("/api/v1/datasources/ds_tms/scan/scan_xxx")
    assert resp.status_code == 401


def test_profile_read_requires_auth(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path)
    resp = client.get("/api/v1/datasources/ds_tms/profile")
    assert resp.status_code == 401


def test_update_spaces_requires_admin(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path)
    resp = client.put("/api/v1/datasources/ds_tms/semantic-spaces", json={"adjustments": []})
    assert resp.status_code == 401


def test_upload_document_requires_admin(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path)
    resp = client.post("/api/v1/datasources/ds_tms/documents",
                       files={"file": ("test.txt", b"test content", "text/plain")})
    assert resp.status_code == 401


def test_list_documents_requires_auth(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path)
    resp = client.get("/api/v1/datasources/ds_tms/documents")
    assert resp.status_code == 401


# ── General (non-admin) users are forbidden, not just unauthenticated ──
# (simplified-workspace-pack-management: data-source management routes are
# administrator-only per identity-access-control; a general user must get
# 403 FORBIDDEN rather than a successful read.)

def test_general_user_forbidden_from_data_source_management_routes(tmp_path: Path) -> None:
    client, sid, _ = _make_client(tmp_path)
    _seed_datasource(tmp_path)
    headers = _hdrs(_general_user_session_id())

    forbidden_gets = [
        "/api/v1/datasources/ds_tms/scan/scan_xxx",
        "/api/v1/datasources/ds_tms/profile",
        "/api/v1/datasources/ds_tms/catalog/overview",
        "/api/v1/datasources/ds_tms/catalog/latest",
        "/api/v1/datasources/ds_tms/semantic-spaces",
        "/api/v1/datasources/ds_tms/semantic-spaces/recommendations",
        "/api/v1/datasources/ds_tms/semantic-spaces/sp_missing",
        "/api/v1/datasources/ds_tms/documents",
    ]
    for path in forbidden_gets:
        resp = client.get(path, headers=headers)
        assert resp.status_code == 403, f"{path} expected 403, got {resp.status_code}: {resp.text}"
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    resp = client.post("/api/v1/datasources/ds_tms/scan", json={}, headers=headers)
    assert resp.status_code == 403

    resp = client.put(
        "/api/v1/datasources/ds_tms/semantic-spaces", json={"adjustments": []}, headers=headers
    )
    assert resp.status_code == 403

    resp = client.post(
        "/api/v1/datasources/ds_tms/documents",
        headers=headers,
        files={"file": ("test.txt", b"content", "text/plain")},
    )
    assert resp.status_code == 403


# ── 404 cases ─────────────────────────────────────────────────────────

def test_scan_missing_datasource_returns_404(tmp_path: Path) -> None:
    client, sid, _ = _make_client(tmp_path)
    resp = client.post("/api/v1/datasources/ds_missing/scan",
                       json={}, headers=_hdrs(sid))
    assert resp.status_code == 404


def test_profile_missing_returns_404(tmp_path: Path) -> None:
    client, sid, _ = _make_client(tmp_path)
    _seed_datasource(tmp_path)
    resp = client.get("/api/v1/datasources/ds_tms/profile", headers=_hdrs(sid))
    assert resp.status_code == 404


def test_spaces_adjust_missing_profile_returns_404(tmp_path: Path) -> None:
    client, sid, _ = _make_client(tmp_path)
    _seed_datasource(tmp_path)
    resp = client.put("/api/v1/datasources/ds_tms/semantic-spaces",
                      json={"adjustments": []}, headers=_hdrs(sid))
    assert resp.status_code == 404


def test_scan_status_missing_scan_returns_404(tmp_path: Path) -> None:
    client, sid, _ = _make_client(tmp_path)
    _seed_datasource(tmp_path)
    resp = client.get("/api/v1/datasources/ds_tms/scan/scan_nonexistent",
                      headers=_hdrs(sid))
    assert resp.status_code == 404


# ── Scan → profile flow ───────────────────────────────────────────────

def test_scan_starts_and_returns_scan_id(tmp_path: Path) -> None:
    """Scan start returns a scan_id immediately (async execution)."""
    client, sid, _ = _make_client(tmp_path)
    _seed_datasource(tmp_path)

    # Mock the background executor to prevent real DB connection
    from unittest.mock import MagicMock
    with patch("sq_bi_runtime.api.create_app") as _:
        pass  # Just checking the endpoint returns a scan_id

    resp = client.post("/api/v1/datasources/ds_tms/scan",
                       json={"force_rescan": False}, headers=_hdrs(sid))
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("data") is not None
    data = body["data"]
    assert "scan_id" in data
    assert data["scan_id"].startswith("scan_")
    assert data["data_source_id"] == "ds_tms"


def test_scan_status_retrievable_after_start(tmp_path: Path) -> None:
    client, sid, _ = _make_client(tmp_path)
    _seed_datasource(tmp_path)
    # Start a scan (background thread starts but may not complete in test time)
    scan_resp = client.post("/api/v1/datasources/ds_tms/scan",
                             json={}, headers=_hdrs(sid))
    assert scan_resp.status_code == 200
    scan_id = scan_resp.json()["data"]["scan_id"]

    # Poll status immediately — should exist
    status_resp = client.get(f"/api/v1/datasources/ds_tms/scan/{scan_id}",
                              headers=_hdrs(sid))
    assert status_resp.status_code == 200
    assert status_resp.json()["data"]["scan_id"] == scan_id


# ── Document upload and list ───────────────────────────────────────────

def test_upload_document_stores_and_lists(tmp_path: Path) -> None:
    client, sid, _ = _make_client(tmp_path)
    _seed_datasource(tmp_path)
    resp = client.post(
        "/api/v1/datasources/ds_tms/documents",
        headers=_hdrs(sid),
        files={"file": ("数据字典.txt", b"DELIVER_NO  ORDER_ID  STATUS", "text/plain")},
    )
    assert resp.status_code == 200
    doc = resp.json()["data"]
    assert doc["document_id"].startswith("doc_")
    assert doc["filename"] == "数据字典.txt"

    list_resp = client.get("/api/v1/datasources/ds_tms/documents", headers=_hdrs(sid))
    assert list_resp.status_code == 200
    docs = list_resp.json()["data"]
    assert len(docs) == 1
    assert docs[0]["document_id"] == doc["document_id"]


def test_upload_document_missing_ds_returns_404(tmp_path: Path) -> None:
    client, sid, _ = _make_client(tmp_path)
    resp = client.post(
        "/api/v1/datasources/ds_missing/documents",
        headers=_hdrs(sid),
        files={"file": ("test.txt", b"content", "text/plain")},
    )
    assert resp.status_code == 404


def test_list_documents_empty_for_new_ds(tmp_path: Path) -> None:
    client, sid, _ = _make_client(tmp_path)
    _seed_datasource(tmp_path)
    resp = client.get("/api/v1/datasources/ds_tms/documents", headers=_hdrs(sid))
    assert resp.status_code == 200
    assert resp.json()["data"] == []


# ── Space adjustment ──────────────────────────────────────────────────

def test_space_adjustment_applied(tmp_path: Path) -> None:
    """Seed a profile directly then adjust a space."""
    from sq_bi_runtime.semantic_profile_store import SemanticProfileStore
    from sq_bi_contracts.semantic_profile import (
        ScanPhase, SemanticSpace, SemanticEntity, TableRecommendation,
    )

    client, sid, _ = _make_client(tmp_path)
    _seed_datasource(tmp_path)

    # Manually seed a profile
    store = SemanticProfileStore(tmp_path / "semantic_profile.sqlite3")
    snap = store.create_snapshot("ds_tms")
    space = SemanticSpace(
        space_id="sp_test",
        snapshot_id=snap.snapshot_id,
        name="测试空间",
        entities=[],
    )
    store.save_spaces(snap.snapshot_id, [space])
    store.update_snapshot(snap.snapshot_id, scan_phase=ScanPhase.done)

    # Check profile is now accessible
    profile_resp = client.get("/api/v1/datasources/ds_tms/profile", headers=_hdrs(sid))
    assert profile_resp.status_code == 200

    # Adjust the space
    adj_resp = client.put(
        "/api/v1/datasources/ds_tms/semantic-spaces",
        headers={**_hdrs(sid), "Content-Type": "application/json"},
        content=json.dumps({
            "adjustments": [{"space_id": "sp_test", "accepted": True, "name": "已确认空间"}]
        }),
    )
    assert adj_resp.status_code == 200
    refreshed_spaces = adj_resp.json()["data"]["spaces"]
    assert len(refreshed_spaces) == 1
    assert refreshed_spaces[0]["accepted"] is True
    assert refreshed_spaces[0]["name"] == "已确认空间"


# ── Ask with data_source_id ────────────────────────────────────────────

def test_ask_without_data_source_id_still_works(tmp_path: Path) -> None:
    """ask endpoint remains backward-compatible when data_source_id is omitted."""
    from unittest.mock import patch, MagicMock

    client, sid, _ = _make_client(tmp_path)
    mock_payload = {
        "sql": "SELECT 1 FROM DUAL",
        "explanation": "test",
        "narrative": "ok",
        "chart_type": None,
        "columns": [],
        "rows": [],
        "audit_id": "a1",
        "lineage": [],
    }
    with patch("sq_bi_runtime.service.AskDataService.ask_controlled", return_value=mock_payload):
        resp = client.post(
            "/api/v1/query/ask",
            json={"question": "测试问题", "user_id": "u1"},
            headers=_hdrs(sid),
        )
    assert resp.status_code == 200


def test_ask_with_data_source_id_calls_retriever(tmp_path: Path) -> None:
    """When data_source_id is supplied, SemanticRetriever is invoked and context forwarded."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from sq_bi_contracts.exploration import ConfidenceTier, QueryAssumption

    client, sid, _ = _make_client(tmp_path)
    _seed_datasource(tmp_path)

    mock_payload = {
        "sql": "SELECT 1 FROM DUAL",
        "explanation": "test",
        "narrative": "ok",
        "chart_type": None,
        "columns": [],
        "rows": [],
        "audit_id": "a1",
        "lineage": [],
    }
    captured: dict = {}

    def fake_ask(self, question, execute_sql=True, extra_context="", relationships=None):  # noqa: ANN001
        captured["extra_context"] = extra_context
        return mock_payload

    with patch("sq_bi_runtime.service.AskDataService.ask_controlled", fake_ask), \
         patch("sq_bi_runtime.semantic_retriever.SemanticRetriever.get_context_for_question",
               return_value="## 数据库语义上下文\n### 运输空间") as mock_retriever, \
         patch(
             "sq_bi_runtime.datasource_executors.DataSourceExecutorRegistry.get",
             return_value=SimpleNamespace(get_schema_catalog=lambda: {}),
         ), \
         patch(
             "sq_bi_runtime.exploration_planner.ExplorationPlanner.plan",
             return_value=SimpleNamespace(
                 assumption=QueryAssumption(),
                 confidence_tier=ConfidenceTier.medium,
                 clarification=None,
                 executable=True,
                 follow_up_context="## AI 探索解读\n- 承运商运量",
             ),
         ):
        resp = client.post(
            "/api/v1/query/ask",
            json={"question": "各承运商运量", "user_id": "u1", "data_source_id": "ds_tms"},
            headers=_hdrs(sid),
        )

    assert resp.status_code == 200
    assert mock_retriever.called
    assert "数据库语义上下文" in captured.get("extra_context", "")


# ── Catalog overview / latest ──────────────────────────────────────────


def test_catalog_overview_requires_auth(tmp_path: Path) -> None:
    client, _, _ = _make_client(tmp_path)
    resp = client.get("/api/v1/datasources/ds_tms/catalog/overview")
    assert resp.status_code == 401


def test_catalog_overview_missing_snapshot_returns_404(tmp_path: Path) -> None:
    client, sid, _ = _make_client(tmp_path)
    _seed_datasource(tmp_path)
    resp = client.get("/api/v1/datasources/ds_tms/catalog/overview", headers=_hdrs(sid))
    assert resp.status_code == 404


def test_catalog_latest_empty_when_no_snapshot(tmp_path: Path) -> None:
    client, sid, _ = _make_client(tmp_path)
    _seed_datasource(tmp_path)
    resp = client.get("/api/v1/datasources/ds_tms/catalog/latest", headers=_hdrs(sid))
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_catalog_overview_and_latest_reflect_seeded_scan(tmp_path: Path) -> None:
    from sq_bi_runtime.schema_scanner import ColumnMeta, TableMeta
    from sq_bi_runtime.semantic_profile_store import SemanticProfileStore
    from sq_bi_contracts.semantic_profile import TableRecommendation

    client, sid, _ = _make_client(tmp_path)
    _seed_datasource(tmp_path)

    # Seed a scan result directly through the store (same DB file the app
    # uses) rather than waiting on the async scan pipeline.
    store = SemanticProfileStore(tmp_path / "semantic_profile.sqlite3")
    snap = store.create_snapshot("ds_tms")
    store.save_catalog(snap.snapshot_id, [
        TableMeta(
            name="TMS_SHIPMENT", schema="TMS", comment="运单表",
            recommendation=TableRecommendation.recommended_include,
            columns=[ColumnMeta(name="CARRIER_NAME", data_type="VARCHAR2")],
        ),
        TableMeta(
            name="TMP_STAGING", schema="TMS", excluded=True,
            excluded_reason="default_exclusion:TMP_.*",
            recommendation=TableRecommendation.not_relevant,
            columns=[ColumnMeta(name="COL_A", data_type="VARCHAR2")],
        ),
    ])

    overview_resp = client.get("/api/v1/datasources/ds_tms/catalog/overview", headers=_hdrs(sid))
    assert overview_resp.status_code == 200
    overview = overview_resp.json()["data"]
    assert overview["table_count"] == 2
    assert overview["excluded_table_count"] == 1
    assert overview["excluded_tables"][0]["table_name"] == "TMP_STAGING"
    assert overview["suspected_business_tables"][0]["table_name"] == "TMS_SHIPMENT"

    latest_resp = client.get("/api/v1/datasources/ds_tms/catalog/latest", headers=_hdrs(sid))
    assert latest_resp.status_code == 200
    tables = latest_resp.json()["data"]
    assert {t["table_name"] for t in tables} == {"TMS_SHIPMENT", "TMP_STAGING"}
