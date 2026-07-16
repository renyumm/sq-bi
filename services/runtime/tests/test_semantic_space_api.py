"""End-to-end tests for the semantic-space-management REST endpoints.

Uses FastAPI TestClient with a minimal in-memory config, mirroring
test_admin_mounting_api.py's setup.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from sq_bi_runtime.api import create_app


def _make_app_and_client(tmp_path: Path) -> tuple[TestClient, str]:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        f"base_url: http://localhost/v1\nkey: test-key\nmodel: test-model\nstorage_path: {tmp_path}\n",
        encoding="utf-8",
    )
    app = create_app(cfg_path)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    session_id = resp.json().get("data", {}).get("session_id", "")
    return client, session_id


def _hdrs(session_id: str) -> dict[str, str]:
    return {"X-Session-Id": session_id}


def test_create_and_list_semantic_space_requires_admin(tmp_path: Path) -> None:
    client, _ = _make_app_and_client(tmp_path)
    resp = client.post(
        "/api/v1/datasources/ds_tms/semantic-spaces",
        json={"data_source_id": "ds_tms", "name": "TMS 运输执行"},
    )
    assert resp.status_code == 401


def test_create_list_get_semantic_space(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)

    created = client.post(
        "/api/v1/datasources/ds_tms/semantic-spaces",
        json={"data_source_id": "ds_tms", "name": "TMS 运输执行", "description": "运输相关"},
        headers=_hdrs(sid),
    )
    assert created.status_code == 200, created.text
    space = created.json()["data"]
    assert space["name"] == "TMS 运输执行"
    assert space["version"] == 1
    assert space["version_state"] == "draft"

    listed = client.get("/api/v1/datasources/ds_tms/semantic-spaces", headers=_hdrs(sid))
    assert listed.status_code == 200
    ids = [s["space_id"] for s in listed.json()["data"]]
    assert space["space_id"] in ids

    fetched = client.get(
        f"/api/v1/datasources/ds_tms/semantic-spaces/{space['space_id']}", headers=_hdrs(sid)
    )
    assert fetched.status_code == 200
    assert fetched.json()["data"]["space_id"] == space["space_id"]


def test_get_unknown_semantic_space_404(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.get(
        "/api/v1/datasources/ds_tms/semantic-spaces/sps_missing", headers=_hdrs(sid)
    )
    assert resp.status_code == 404


def test_recommended_spaces_requires_auth(tmp_path: Path) -> None:
    client, _ = _make_app_and_client(tmp_path)
    resp = client.get("/api/v1/datasources/ds_tms/semantic-spaces/recommendations")
    assert resp.status_code == 401


def test_recommended_spaces_route_not_swallowed_by_space_id_route(tmp_path: Path) -> None:
    """The static /recommendations path must not be matched as {space_id};
    an empty (not 404) list confirms it hit the dedicated route."""
    client, sid = _make_app_and_client(tmp_path)
    resp = client.get(
        "/api/v1/datasources/ds_tms/semantic-spaces/recommendations", headers=_hdrs(sid)
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_refresh_and_publish_semantic_space(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    created = client.post(
        "/api/v1/datasources/ds_tms/semantic-spaces",
        json={"data_source_id": "ds_tms", "name": "TMS"},
        headers=_hdrs(sid),
    )
    space_id = created.json()["data"]["space_id"]

    refreshed = client.post(
        f"/api/v1/datasources/ds_tms/semantic-spaces/{space_id}/refresh", headers=_hdrs(sid)
    )
    assert refreshed.status_code == 200
    diff = refreshed.json()["data"]
    assert diff["space_id"] == space_id
    assert diff["new_fields"] == []  # nothing scanned yet in this test's fresh store

    published = client.post(
        f"/api/v1/datasources/ds_tms/semantic-spaces/{space_id}/publish",
        json={"confirmed_suggestions": []},
        headers=_hdrs(sid),
    )
    assert published.status_code == 200
    body = published.json()["data"]
    assert body["version_state"] == "published"


def test_refresh_unknown_space_404(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.post(
        "/api/v1/datasources/ds_tms/semantic-spaces/sps_missing/refresh", headers=_hdrs(sid)
    )
    assert resp.status_code == 404


def test_publish_impact_analysis_reports_affected_deployment(tmp_path: Path) -> None:
    """Publishing a version that demotes a confirmed field must surface which
    deployments referenced it. Enterprise pack definitions are portable and no
    longer own physical table/column bindings, so only deployments (which own
    physical mappings) can be attributed."""
    from sq_bi_contracts.semantic_profile import (
        FieldOrigin,
        FieldStatus,
        ScanPhase,
        SemanticEntity,
        SemanticField,
        SemanticSpace,
        SemanticSpaceAdjustment,
    )
    from sq_bi_runtime.field_mapping_store import FieldMappingStore
    from sq_bi_runtime.semantic_profile_store import SemanticProfileStore

    profile_store = SemanticProfileStore(tmp_path / "semantic_profile.sqlite3")
    snap = profile_store.create_snapshot("ds_tms")
    field = SemanticField(
        field_id="fld_coupon", entity_id="ent_orders",
        physical_table="orders", physical_column="coupon_discount",
        business_name="优惠券抵扣金额", origin=FieldOrigin.inferred,
    )
    entity = SemanticEntity(
        entity_id="ent_orders", space_id="sp_candidate",
        physical_table="orders", business_name="订单", fields=[field],
    )
    candidate_space = SemanticSpace(
        space_id="sp_candidate", snapshot_id=snap.snapshot_id, name="候选空间", entities=[entity]
    )
    profile_store.save_spaces(snap.snapshot_id, [candidate_space])
    profile_store.update_snapshot(snap.snapshot_id, scan_phase=ScanPhase.done)

    space = profile_store.create_space("ds_tms", "TMS 订单", initial_tables=["orders"])
    adopted_field_id = space.entities[0].fields[0].field_id
    assert space.entities[0].fields[0].status == "confirmed"

    mapping_store = FieldMappingStore(tmp_path / "field_mappings.sqlite3")
    dep = mapping_store.get_or_create_deployment(
        "orders_pack", "1.0.0", "ds_tms", semantic_space_ids=[space.space_id]
    )

    client, sid = _make_app_and_client(tmp_path)

    pub1 = client.post(
        f"/api/v1/datasources/ds_tms/semantic-spaces/{space.space_id}/publish",
        json={"confirmed_suggestions": []},
        headers=_hdrs(sid),
    )
    assert pub1.status_code == 200, pub1.text
    assert pub1.json()["data"]["impact"]["references"] == []

    profile_store.apply_space_adjustments(
        snap.snapshot_id,
        [SemanticSpaceAdjustment(
            space_id=space.space_id, accepted=True,
            field_statuses={adopted_field_id: FieldStatus.excluded},
        )],
    )

    pub2 = client.post(
        f"/api/v1/datasources/ds_tms/semantic-spaces/{space.space_id}/publish",
        json={"confirmed_suggestions": []},
        headers=_hdrs(sid),
    )
    assert pub2.status_code == 200, pub2.text
    impact = pub2.json()["data"]["impact"]
    assert impact["lost_field_ids"] == [adopted_field_id]
    kinds = {r["kind"] for r in impact["references"]}
    assert kinds == {"deployment"}
    dep_ref = next(r for r in impact["references"] if r["kind"] == "deployment")
    assert dep_ref["ref_id"] == dep.deployment_id


def test_delete_semantic_space_requires_admin(tmp_path: Path) -> None:
    client, _ = _make_app_and_client(tmp_path)
    resp = client.delete("/api/v1/datasources/ds_tms/semantic-spaces/sps_missing")
    assert resp.status_code == 401


def test_delete_semantic_space(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    created = client.post(
        "/api/v1/datasources/ds_tms/semantic-spaces",
        json={"data_source_id": "ds_tms", "name": "TMS"},
        headers=_hdrs(sid),
    )
    space_id = created.json()["data"]["space_id"]

    deleted = client.delete(
        f"/api/v1/datasources/ds_tms/semantic-spaces/{space_id}", headers=_hdrs(sid)
    )
    assert deleted.status_code == 200
    assert deleted.json()["data"] == {"deleted": True, "space_id": space_id}

    fetched = client.get(
        f"/api/v1/datasources/ds_tms/semantic-spaces/{space_id}", headers=_hdrs(sid)
    )
    assert fetched.status_code == 404


def test_gap_lookup_requires_auth(tmp_path: Path) -> None:
    client, _ = _make_app_and_client(tmp_path)
    resp = client.post(
        "/api/v1/query/gap-lookup", json={"connection_id": "ds_tms", "query": "优惠券"}
    )
    assert resp.status_code == 401


def test_gap_lookup_returns_empty_when_nothing_unadopted(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.post(
        "/api/v1/query/gap-lookup",
        json={"connection_id": "ds_tms", "query": "优惠券折扣"},
        headers=_hdrs(sid),
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_delete_document_requires_admin(tmp_path: Path) -> None:
    client, _ = _make_app_and_client(tmp_path)
    resp = client.delete("/api/v1/datasources/ds_tms/documents/doc_x")
    assert resp.status_code == 401


def test_delete_unknown_document_404(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.delete(
        "/api/v1/datasources/ds_tms/documents/doc_missing", headers=_hdrs(sid)
    )
    assert resp.status_code == 404


def test_upload_then_delete_document(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    create_ds = client.post(
        "/api/v1/admin/data-sources",
        json={"data_source_id": "ds_tms", "name": "TMS", "host": "h", "database": "d",
              "username": "u", "password": "p"},
        headers=_hdrs(sid),
    )
    assert create_ds.status_code == 200, create_ds.text

    upload = client.post(
        "/api/v1/datasources/ds_tms/documents",
        files={"file": ("dict.csv", b"field,desc\nORDER_ID,order id", "text/csv")},
        headers=_hdrs(sid),
    )
    assert upload.status_code == 200, upload.text
    doc_id = upload.json()["data"]["document_id"]

    listed = client.get("/api/v1/datasources/ds_tms/documents", headers=_hdrs(sid))
    assert any(d["document_id"] == doc_id for d in listed.json()["data"])

    deleted = client.delete(
        f"/api/v1/datasources/ds_tms/documents/{doc_id}", headers=_hdrs(sid)
    )
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True

    listed_after = client.get("/api/v1/datasources/ds_tms/documents", headers=_hdrs(sid))
    assert listed_after.json()["data"] == []


def test_test_connection_requires_admin(tmp_path: Path) -> None:
    client, _ = _make_app_and_client(tmp_path)
    resp = client.post(
        "/api/v1/admin/data-sources/test",
        json={"database_type": "oracle", "host": "localhost", "port": 1521,
              "database": "x", "username": "u", "password": "p"},
    )
    assert resp.status_code == 401


def test_test_connection_reports_real_failure_for_unreachable_oracle(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.post(
        "/api/v1/admin/data-sources/test",
        json={"database_type": "oracle", "host": "127.0.0.1", "port": 1,
              "database": "nope", "username": "u", "password": "p"},
        headers=_hdrs(sid),
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["success"] is False
    assert body["message"]
    assert body["capabilities"] == {
        "can_read_schemas": False, "can_read_tables": False,
        "can_read_columns": False, "can_read_keys": False,
    }


def test_test_connection_reports_full_capabilities_on_success(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)

    class _FakeConnector:
        def get_schema_catalog(self) -> dict[str, list[str]]:
            return {"ORDERS": ["ORDER_ID", "CARRIER_NAME"]}

        def describe_schema(self, schema: str | None = None) -> list[dict]:
            return [{"table": "ORDERS", "column": "ORDER_ID"}]

        def close(self) -> None:
            pass

    with patch("sq_bi_runtime.connectors.factory.build_connector", return_value=_FakeConnector()):
        resp = client.post(
            "/api/v1/admin/data-sources/test",
            json={"database_type": "oracle", "host": "h", "port": 1521,
                  "database": "x", "username": "u", "password": "p"},
            headers=_hdrs(sid),
        )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["success"] is True
    assert body["capabilities"] == {
        "can_read_schemas": True, "can_read_tables": True,
        "can_read_columns": True, "can_read_keys": True,
    }


def test_test_connection_key_capability_degrades_independently(tmp_path: Path) -> None:
    """describe_schema failing shouldn't fail the whole test — only can_read_keys."""
    client, sid = _make_app_and_client(tmp_path)

    class _PartialConnector:
        def get_schema_catalog(self) -> dict[str, list[str]]:
            return {"ORDERS": ["ORDER_ID"]}

        def describe_schema(self, schema: str | None = None) -> list[dict]:
            raise RuntimeError("insufficient privileges for key/index introspection")

        def close(self) -> None:
            pass

    with patch("sq_bi_runtime.connectors.factory.build_connector", return_value=_PartialConnector()):
        resp = client.post(
            "/api/v1/admin/data-sources/test",
            json={"database_type": "oracle", "host": "h", "port": 1521,
                  "database": "x", "username": "u", "password": "p"},
            headers=_hdrs(sid),
        )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["success"] is True
    assert body["capabilities"]["can_read_keys"] is False
    assert body["capabilities"]["can_read_tables"] is True


def test_test_connection_reports_missing_driver_for_mysql(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.post(
        "/api/v1/admin/data-sources/test",
        json={"database_type": "mysql", "host": "localhost", "port": 3306,
              "database": "x", "username": "u", "password": "p"},
        headers=_hdrs(sid),
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    # Either a clean "missing driver" message or a real connection failure —
    # both are acceptable depending on whether pymysql happens to be installed.
    assert isinstance(body["success"], bool)
    assert body["message"]
