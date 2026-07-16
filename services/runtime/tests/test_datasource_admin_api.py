"""End-to-end tests for /api/v1/admin/data-sources CRUD, auto-scan-on-create,
and password-at-rest encryption.
"""
from __future__ import annotations

import json
from pathlib import Path

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
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return client, resp.json()["data"]["session_id"]


def _hdrs(sid: str) -> dict[str, str]:
    return {"X-Session-Id": sid}


def _create_payload(ds_id: str = "ds_admin_test") -> dict:
    return {
        "data_source_id": ds_id,
        "name": "Admin Test DS",
        "database_type": "oracle",
        "host": "localhost",
        "port": 1521,
        "database": "test_db",
        "username": "u",
        "password": "s3cret-pw",
        "is_read_only": True,
        "description": "生产 Oracle 只读账号",
        "connect_timeout_seconds": 8.0,
    }


def test_admin_list_requires_admin(tmp_path: Path) -> None:
    client, _ = _make_app_and_client(tmp_path)
    resp = client.get("/api/v1/admin/data-sources")
    assert resp.status_code == 401


def test_admin_get_single_requires_admin(tmp_path: Path) -> None:
    client, _ = _make_app_and_client(tmp_path)
    resp = client.get("/api/v1/admin/data-sources/ds_x")
    assert resp.status_code == 401


def test_admin_get_single_missing_returns_404(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.get("/api/v1/admin/data-sources/ds_missing", headers=_hdrs(sid))
    assert resp.status_code == 404


def test_create_list_get_single_round_trip(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    created = client.post(
        "/api/v1/admin/data-sources", json=_create_payload(), headers=_hdrs(sid)
    )
    assert created.status_code == 200, created.text
    body = created.json()["data"]
    assert body["data_source_id"] == "ds_admin_test"
    assert "password" not in body  # masked
    assert body["user_mask"]

    listed = client.get("/api/v1/admin/data-sources", headers=_hdrs(sid))
    assert listed.status_code == 200
    assert any(d["data_source_id"] == "ds_admin_test" for d in listed.json()["data"])

    fetched = client.get("/api/v1/admin/data-sources/ds_admin_test", headers=_hdrs(sid))
    assert fetched.status_code == 200
    assert fetched.json()["data"]["data_source_id"] == "ds_admin_test"


def test_create_persists_technical_fields_only(tmp_path: Path) -> None:
    """service_name/sid/dsn/connect_timeout_seconds/metadata_scan_enabled must
    survive a save; business_description/authorized_schemas/include_rules/
    exclude_rules must NOT be accepted on the connection (they belong to
    semantic-space configuration)."""
    client, sid = _make_app_and_client(tmp_path)
    payload = {
        **_create_payload(),
        "service_name": "ORCLPDB1",
        "metadata_scan_enabled": False,
        # These would have been persisted by the old model — must be ignored now.
        "business_description": "TMS 运输管理系统",
        "authorized_schemas": ["TMS_SCHEDULING"],
    }
    client.post("/api/v1/admin/data-sources", json=payload, headers=_hdrs(sid))

    raw = json.loads((tmp_path / "datasources.json").read_text(encoding="utf-8"))
    record = next(r for r in raw if r["data_source_id"] == "ds_admin_test")
    assert record["service_name"] == "ORCLPDB1"
    assert record["connect_timeout_seconds"] == 8.0
    assert record["metadata_scan_enabled"] is False
    assert record["description"] == "生产 Oracle 只读账号"
    assert "business_description" not in record
    assert "authorized_schemas" not in record
    assert "include_rules" not in record
    assert "exclude_rules" not in record


def test_update_persists_technical_fields(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    client.post("/api/v1/admin/data-sources", json=_create_payload(), headers=_hdrs(sid))

    updated = client.put(
        "/api/v1/admin/data-sources/ds_admin_test",
        json={"description": "备用只读账号", "service_name": "ORCLPDB2"},
        headers=_hdrs(sid),
    )
    assert updated.status_code == 200

    raw = json.loads((tmp_path / "datasources.json").read_text(encoding="utf-8"))
    record = next(r for r in raw if r["data_source_id"] == "ds_admin_test")
    assert record["description"] == "备用只读账号"
    assert record["service_name"] == "ORCLPDB2"


def test_password_not_stored_in_plaintext(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    client.post("/api/v1/admin/data-sources", json=_create_payload(), headers=_hdrs(sid))

    raw_text = (tmp_path / "datasources.json").read_text(encoding="utf-8")
    assert "s3cret-pw" not in raw_text

    raw = json.loads(raw_text)
    record = next(r for r in raw if r["data_source_id"] == "ds_admin_test")
    assert record["password"].startswith("enc:")

    # Round-trips back to plaintext through the admin API's internal load path
    # (verified indirectly: a second update that doesn't touch the password
    # must not corrupt it — re-fetching after update keeps the connection usable).
    updated = client.put(
        "/api/v1/admin/data-sources/ds_admin_test",
        json={"name": "Renamed"}, headers=_hdrs(sid),
    )
    assert updated.status_code == 200
    raw_after = json.loads((tmp_path / "datasources.json").read_text(encoding="utf-8"))
    record_after = next(r for r in raw_after if r["data_source_id"] == "ds_admin_test")
    assert record_after["password"].startswith("enc:")


def test_create_triggers_scan_automatically(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    created = client.post(
        "/api/v1/admin/data-sources", json=_create_payload(), headers=_hdrs(sid)
    )
    assert created.status_code == 200
    body = created.json()["data"]
    assert body.get("scan_id", "").startswith("scan_")
    assert body.get("snapshot_id", "").startswith("snap_")

    # The scan job must be immediately queryable — no separate manual
    # POST .../scan call should be required.
    status_resp = client.get(
        f"/api/v1/datasources/ds_admin_test/scan/{body['scan_id']}", headers=_hdrs(sid)
    )
    assert status_resp.status_code == 200


def test_create_respects_metadata_scan_disabled(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    payload = {**_create_payload(), "metadata_scan_enabled": False}
    created = client.post("/api/v1/admin/data-sources", json=payload, headers=_hdrs(sid))
    assert created.status_code == 200
    assert "scan_id" not in created.json()["data"]


def test_update_connection_critical_field_triggers_rescan(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    client.post("/api/v1/admin/data-sources", json=_create_payload(), headers=_hdrs(sid))

    updated = client.put(
        "/api/v1/admin/data-sources/ds_admin_test",
        json={"host": "new-host.internal"},
        headers=_hdrs(sid),
    )
    assert updated.status_code == 200
    body = updated.json()["data"]
    assert body["connection_changed"] is True
    assert body.get("scan_id", "").startswith("scan_")


def test_update_cosmetic_field_does_not_trigger_rescan(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    client.post("/api/v1/admin/data-sources", json=_create_payload(), headers=_hdrs(sid))

    updated = client.put(
        "/api/v1/admin/data-sources/ds_admin_test",
        json={"name": "Renamed DS", "description": "新的连接说明"},
        headers=_hdrs(sid),
    )
    assert updated.status_code == 200
    body = updated.json()["data"]
    assert body["connection_changed"] is False
    assert "scan_id" not in body


def test_update_password_change_triggers_rescan(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    client.post("/api/v1/admin/data-sources", json=_create_payload(), headers=_hdrs(sid))

    updated = client.put(
        "/api/v1/admin/data-sources/ds_admin_test",
        json={"password": "a-new-password"},
        headers=_hdrs(sid),
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["connection_changed"] is True


def test_update_blank_password_is_not_a_change(tmp_path: Path) -> None:
    """Leaving password blank on edit must not be treated as a credential change."""
    client, sid = _make_app_and_client(tmp_path)
    client.post("/api/v1/admin/data-sources", json=_create_payload(), headers=_hdrs(sid))

    updated = client.put(
        "/api/v1/admin/data-sources/ds_admin_test",
        json={"name": "Renamed", "password": ""},
        headers=_hdrs(sid),
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["connection_changed"] is False
