"""TestClient tests for enterprise domain pack admin endpoints.

Covers portable pack creation (two modes only), extension-base identity,
and admin/general-user role denial (openspec: simplified-workspace-pack-management).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from sq_bi_contracts.common import UserContext
from sq_bi_contracts.metrics import MetricDefinition, MetricFormula, MetricVisibility
from sq_bi_runtime.api import create_app
from sq_bi_runtime.auth import create_session


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_client(tmp_path: Path) -> tuple[TestClient, str]:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"base_url: http://localhost/v1\nkey: k\nmodel: m\nstorage_path: {tmp_path}\n",
        encoding="utf-8",
    )
    app = create_app(cfg)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200
    sid = resp.json()["data"]["session_id"]
    return client, sid


def _hdrs(sid: str) -> dict[str, str]:
    return {"X-Session-Id": sid}


def _general_user_session_id() -> str:
    """Simulate an authenticated general (non-admin) user session directly,
    since the default local auth backend only registers an admin account."""
    return create_session(
        UserContext(user_id="u_general", display_name="General", org_id="default", role_ids=["user"])
    )


def _blank_create_body(name: str = "测试企业包") -> dict:
    return {
        "name": name,
        "mode": "blank",
        "created_by": "tester",
    }


def _extend_official_body(base_pack_id: str = "tms", base_pack_version: str | None = None) -> dict:
    body = {
        "name": "TMS 扩展包",
        "mode": "extend_official",
        "base_pack_id": base_pack_id,
        "created_by": "tester",
    }
    if base_pack_version is not None:
        body["base_pack_version"] = base_pack_version
    return body


# ── Auth guard: admin/general-user role boundary ───────────────────────────────

def test_list_enterprise_packs_requires_auth(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    resp = client.get("/api/v1/admin/enterprise-packs")
    assert resp.status_code == 401


def test_general_user_denied_on_enterprise_pack_management_routes(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    headers = _hdrs(_general_user_session_id())

    list_resp = client.get("/api/v1/admin/enterprise-packs", headers=headers)
    assert list_resp.status_code == 403
    assert list_resp.json()["error"]["code"] == "FORBIDDEN"

    create_resp = client.post(
        "/api/v1/admin/enterprise-packs", headers=headers, json=_blank_create_body()
    )
    assert create_resp.status_code == 403
    assert create_resp.json()["error"]["code"] == "FORBIDDEN"


def test_general_user_denied_on_publish_and_fork(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    create_resp = client.post(
        "/api/v1/admin/enterprise-packs", headers=_hdrs(sid), json=_blank_create_body()
    )
    pack_id = create_resp.json()["data"]["pack_id"]

    headers = _hdrs(_general_user_session_id())
    pub_resp = client.post(
        f"/api/v1/admin/enterprise-packs/{pack_id}/publish",
        headers=headers,
        json={"version": "1.0.0", "published_by": "u_general"},
    )
    assert pub_resp.status_code == 403

    fork_resp = client.post(f"/api/v1/admin/enterprise-packs/{pack_id}/fork", headers=headers)
    assert fork_resp.status_code == 403


def test_admin_can_manage_enterprise_packs(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    resp = client.post(
        "/api/v1/admin/enterprise-packs", headers=_hdrs(sid), json=_blank_create_body()
    )
    assert resp.status_code == 200


def test_admin_can_delete_unused_enterprise_pack(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    headers = _hdrs(sid)
    created = client.post(
        "/api/v1/admin/enterprise-packs", headers=headers, json=_blank_create_body()
    )
    pack_id = created.json()["data"]["pack_id"]

    deleted = client.delete(f"/api/v1/admin/enterprise-packs/{pack_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"] == {"pack_id": pack_id, "deleted": True}
    assert client.get(f"/api/v1/admin/enterprise-packs/{pack_id}", headers=headers).status_code == 404


def test_domain_pack_extension_api_composes_effective_content(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    headers = _hdrs(sid)
    created = client.post(
        "/api/v1/admin/domain-packs/tms/extension-layer",
        headers=headers,
        json={"base_kind": "official", "created_by": "tester"},
    )
    assert created.status_code == 200, created.text
    layer = created.json()["data"]
    assert layer["base_pack_id"] == "tms"

    updated = client.put(
        f"/api/v1/admin/extension-layers/{layer['extension_id']}",
        headers=headers,
        json={"draft": {"fields": [{
            "field_id": "extension_route_hint", "business_name": "扩建路线提示", "data_type": "TEXT"
        }]}},
    )
    assert updated.status_code == 200, updated.text
    published = client.post(
        f"/api/v1/admin/extension-layers/{layer['extension_id']}/publish", headers=headers
    )
    assert published.status_code == 200, published.text
    effective = client.get(
        "/api/v1/admin/domain-packs/tms/effective-content", headers=headers
    )
    assert effective.status_code == 200, effective.text
    assets = effective.json()["data"]["fields"]
    assert any(item["asset_id"] == "extension_route_hint" and item["source"] == "extension" for item in assets)


# ── Portable pack creation (blank) ──────────────────────────────────────────────

def test_create_blank_pack(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    resp = client.post(
        "/api/v1/admin/enterprise-packs",
        headers=_hdrs(sid),
        json=_blank_create_body(),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["pack_id"].startswith("ep_")
    assert data["create_mode"] == "blank"
    assert data["version_state"] == "draft"
    assert "data_source_id" not in data
    assert data["draft"]["fields"] == []


def test_list_packs_after_create(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    client.post("/api/v1/admin/enterprise-packs", headers=_hdrs(sid), json=_blank_create_body("包A"))
    client.post("/api/v1/admin/enterprise-packs", headers=_hdrs(sid), json=_blank_create_body("包B"))
    resp = client.get("/api/v1/admin/enterprise-packs", headers=_hdrs(sid))
    assert resp.status_code == 200
    packs = resp.json()["data"]
    assert len(packs) >= 2


def test_get_pack_by_id(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    create_resp = client.post(
        "/api/v1/admin/enterprise-packs",
        headers=_hdrs(sid),
        json=_blank_create_body(),
    )
    pack_id = create_resp.json()["data"]["pack_id"]
    resp = client.get(f"/api/v1/admin/enterprise-packs/{pack_id}", headers=_hdrs(sid))
    assert resp.status_code == 200
    assert resp.json()["data"]["pack_id"] == pack_id


def test_get_nonexistent_pack_returns_404(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    resp = client.get("/api/v1/admin/enterprise-packs/ep_nonexistent", headers=_hdrs(sid))
    assert resp.status_code == 404


# ── Creation is restricted to exactly two modes ─────────────────────────────────

def test_create_supports_only_blank_and_extend_official_modes(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)

    blank_resp = client.post(
        "/api/v1/admin/enterprise-packs", headers=_hdrs(sid), json=_blank_create_body()
    )
    assert blank_resp.status_code == 200, blank_resp.text
    assert blank_resp.json()["data"]["create_mode"] == "blank"

    extend_resp = client.post(
        "/api/v1/admin/enterprise-packs", headers=_hdrs(sid), json=_extend_official_body()
    )
    assert extend_resp.status_code == 200, extend_resp.text
    assert extend_resp.json()["data"]["create_mode"] == "extend_official"

    # Removed modes are rejected by request-body validation (422), not accepted.
    for removed_mode in ("clone_enterprise", "ai_from_profile"):
        resp = client.post(
            "/api/v1/admin/enterprise-packs",
            headers=_hdrs(sid),
            json={"name": "旧模式包", "mode": removed_mode, "created_by": "tester"},
        )
        assert resp.status_code == 422, f"mode={removed_mode} should be rejected: {resp.text}"


def test_extend_official_requires_base_pack_id(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    resp = client.post(
        "/api/v1/admin/enterprise-packs",
        headers=_hdrs(sid),
        json={"name": "缺少基础包", "mode": "extend_official", "created_by": "tester"},
    )
    assert resp.status_code == 400


def test_extend_official_with_unknown_base_pack_id_rejected(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    resp = client.post(
        "/api/v1/admin/enterprise-packs",
        headers=_hdrs(sid),
        json=_extend_official_body(base_pack_id="does_not_exist"),
    )
    assert resp.status_code == 400


def test_extend_official_with_mismatched_version_rejected(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    resp = client.post(
        "/api/v1/admin/enterprise-packs",
        headers=_hdrs(sid),
        json=_extend_official_body(base_pack_id="tms", base_pack_version="9.9.9"),
    )
    assert resp.status_code == 400


# ── Extension-base identity: exact official base ref, no copied assets ─────────

def test_extend_official_records_exact_base_identity(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    resp = client.post(
        "/api/v1/admin/enterprise-packs", headers=_hdrs(sid), json=_extend_official_body()
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["base_pack_id"] == "tms"
    assert data["base_pack_version"] == "1.0.0"
    # Delta layers never copy the official base's standard fields.
    assert data["draft"]["fields"] == []
    assert data["draft"]["metrics"] == []


def test_extend_official_does_not_mutate_official_pack(tmp_path: Path) -> None:
    """Creating and editing an extension never alters the official pack source."""
    client, sid = _make_client(tmp_path)
    before_resp = client.get("/api/v1/admin/packs", headers=_hdrs(sid))
    before_packs = before_resp.json().get("data") or []

    create_resp = client.post(
        "/api/v1/admin/enterprise-packs", headers=_hdrs(sid), json=_extend_official_body()
    )
    pack_id = create_resp.json()["data"]["pack_id"]
    client.put(
        f"/api/v1/admin/enterprise-packs/{pack_id}",
        headers=_hdrs(sid),
        json={"draft": {"fields": [{"field_id": "f1", "business_name": "新增字段", "data_type": "TEXT"}]}},
    )

    after_resp = client.get("/api/v1/admin/packs", headers=_hdrs(sid))
    after_packs = after_resp.json().get("data") or []
    assert before_packs == after_packs


# ── Effective extension view: read-only base + editable delta ──────────────────

def test_effective_view_shows_pinned_base_and_enterprise_additions(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    create_resp = client.post(
        "/api/v1/admin/enterprise-packs", headers=_hdrs(sid), json=_extend_official_body()
    )
    pack_id = create_resp.json()["data"]["pack_id"]
    client.put(
        f"/api/v1/admin/enterprise-packs/{pack_id}",
        headers=_hdrs(sid),
        json={"draft": {"fields": [{"field_id": "region", "business_name": "区域", "data_type": "TEXT"}]}},
    )

    resp = client.get(f"/api/v1/admin/enterprise-packs/{pack_id}/effective", headers=_hdrs(sid))
    assert resp.status_code == 200, resp.text
    view = resp.json()["data"]
    assert view["pack_id"] == pack_id
    assert view["base_pack_id"] == "tms"
    assert view["base_pack_version"] == "1.0.0"

    base_field_ids = {f["asset_id"] for f in view["base_standard_fields"]}
    assert "deliver_no" in base_field_ids
    assert all(f["source"] == "official" for f in view["base_standard_fields"])

    enterprise_field_ids = {f["asset_id"] for f in view["enterprise_standard_fields"]}
    assert enterprise_field_ids == {"region"}
    assert all(f["source"] == "enterprise" for f in view["enterprise_standard_fields"])

    # The base list is never polluted by enterprise additions or vice versa.
    assert base_field_ids.isdisjoint(enterprise_field_ids)


def test_effective_view_for_blank_pack_has_no_base(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    create_resp = client.post(
        "/api/v1/admin/enterprise-packs", headers=_hdrs(sid), json=_blank_create_body()
    )
    pack_id = create_resp.json()["data"]["pack_id"]

    resp = client.get(f"/api/v1/admin/enterprise-packs/{pack_id}/effective", headers=_hdrs(sid))
    assert resp.status_code == 200
    view = resp.json()["data"]
    assert view["base_pack_id"] is None
    assert view["base_standard_fields"] == []
    assert view["base_metrics"] == []


def test_effective_view_requires_admin(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    create_resp = client.post(
        "/api/v1/admin/enterprise-packs", headers=_hdrs(sid), json=_blank_create_body()
    )
    pack_id = create_resp.json()["data"]["pack_id"]

    headers = _hdrs(_general_user_session_id())
    resp = client.get(f"/api/v1/admin/enterprise-packs/{pack_id}/effective", headers=headers)
    assert resp.status_code == 403


def test_effective_view_missing_pack_returns_404(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    resp = client.get("/api/v1/admin/enterprise-packs/ep_missing/effective", headers=_hdrs(sid))
    assert resp.status_code == 404


# ── Definition creation is database-independent, then deploys through
#    mapping/smoke/activation (simplified-workspace-pack-management task 4.3) ──

def test_blank_pack_creation_requires_field_mapping_before_activation(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)

    # Definition creation: no data source is required or accepted.
    create_resp = client.post(
        "/api/v1/admin/enterprise-packs", headers=_hdrs(sid), json=_blank_create_body()
    )
    assert create_resp.status_code == 200, create_resp.text
    pack_id = create_resp.json()["data"]["pack_id"]
    assert "data_source_id" not in create_resp.json()["data"]

    update_resp = client.put(
        f"/api/v1/admin/enterprise-packs/{pack_id}",
        headers=_hdrs(sid),
        json={"draft": {"fields": [{"field_id": "region", "business_name": "区域", "data_type": "TEXT"}]}},
    )
    assert update_resp.status_code == 200

    publish_resp = client.post(
        f"/api/v1/admin/enterprise-packs/{pack_id}/publish",
        headers=_hdrs(sid),
        json={"version": "1.0.0", "published_by": "tester"},
    )
    assert publish_resp.status_code == 200, publish_resp.text

    # Deployment (not the definition) is where a data source enters the picture.
    deploy_resp = client.post(
        "/api/v1/admin/deployments",
        headers=_hdrs(sid),
        json={"pack_id": pack_id, "data_source_id": "ds_blank_flow"},
    )
    assert deploy_resp.status_code == 200, deploy_resp.text
    dep_id = deploy_resp.json()["data"]["deployment"]["deployment_id"]

    # Smoke test must not 404 for an enterprise-pack deployment.
    smoke_resp = client.post(f"/api/v1/admin/deployments/{dep_id}/smoke-test", headers=_hdrs(sid))
    assert smoke_resp.status_code == 200, smoke_resp.text
    assert smoke_resp.json()["error"] is None

    activate_resp = client.post(f"/api/v1/admin/deployments/{dep_id}/activate", headers=_hdrs(sid))
    assert activate_resp.status_code == 400, activate_resp.text
    assert "region" in activate_resp.json()["error"]["message"]


# ── AI draft endpoint ─────────────────────────────────────────────────────────

def test_draft_endpoint_returns_pack_draft_result(tmp_path: Path) -> None:
    """Draft endpoint is reachable and returns a PackDraftResult shape.
    LLM call fails gracefully (client not configured), so empty draft is returned."""
    client, sid = _make_client(tmp_path)
    create_resp = client.post(
        "/api/v1/admin/enterprise-packs",
        headers=_hdrs(sid),
        json=_blank_create_body(),
    )
    pack_id = create_resp.json()["data"]["pack_id"]

    resp = client.post(
        "/api/v1/admin/enterprise-packs/draft",
        headers=_hdrs(sid),
        json={"data_source_id": "ds_tms", "pack_id": pack_id, "document_ids": [], "user_id": "tester"},
    )
    # Drafter handles LLM failure gracefully — should return 200 with empty/failed draft
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "draft" in data


# ── Publish lifecycle ─────────────────────────────────────────────────────────

def test_publish_pack_lifecycle(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    create_resp = client.post(
        "/api/v1/admin/enterprise-packs",
        headers=_hdrs(sid),
        json=_blank_create_body(),
    )
    pack_id = create_resp.json()["data"]["pack_id"]

    # Publish
    pub_resp = client.post(
        f"/api/v1/admin/enterprise-packs/{pack_id}/publish",
        headers=_hdrs(sid),
        json={"version": "1.0.0", "published_by": "tester"},
    )
    assert pub_resp.status_code == 200
    pub_data = pub_resp.json()["data"]
    assert pub_data["version_state"] == "published"
    assert pub_data["version"] == "1.0.0"


def test_publish_then_fork_uses_next_draft_same_identity(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    cr = client.post("/api/v1/admin/enterprise-packs", headers=_hdrs(sid), json=_blank_create_body())
    pack_id = cr.json()["data"]["pack_id"]
    client.post(f"/api/v1/admin/enterprise-packs/{pack_id}/publish", headers=_hdrs(sid),
                json={"version": "1.0.0", "published_by": "tester"})
    fork_resp = client.post(f"/api/v1/admin/enterprise-packs/{pack_id}/fork", headers=_hdrs(sid))
    assert fork_resp.status_code == 200
    fork_data = fork_resp.json()["data"]
    assert fork_data["pack_id"] == pack_id
    assert fork_data["version_state"] == "draft"
    assert fork_data["version"] != "1.0.0"


def test_official_pack_untouched_after_create(tmp_path: Path) -> None:
    """Official packs are never modified by enterprise pack operations."""
    client, sid = _make_client(tmp_path)
    # List official packs before
    before_resp = client.get("/api/v1/admin/packs", headers=_hdrs(sid))
    before_packs = before_resp.json().get("data") or []

    # Create enterprise pack
    client.post("/api/v1/admin/enterprise-packs", headers=_hdrs(sid), json=_blank_create_body())

    # Official packs unchanged
    after_resp = client.get("/api/v1/admin/packs", headers=_hdrs(sid))
    after_packs = after_resp.json().get("data") or []
    assert before_packs == after_packs


# ── Sedimentation with target pack ────────────────────────────────────────────

def test_sedimentation_into_target_pack(tmp_path: Path) -> None:
    client, sid = _make_client(tmp_path)
    cr = client.post("/api/v1/admin/enterprise-packs", headers=_hdrs(sid), json=_blank_create_body())
    pack_id = cr.json()["data"]["pack_id"]

    mock_metric = MetricDefinition(
        metric_code="exp_tester::total_freight",
        name="总运费",
        definition="运费之和",
        visibility=MetricVisibility.SHARED,
        formula=MetricFormula(expression="SELECT NULL AS placeholder -- exploration: 总运费"),
        data_source_id="ds_tms",
        owner="tester",
    )

    with patch("sq_bi_runtime.api.get_repository") as mock_repo:
        mock_repo.return_value.create_user_metric.return_value = mock_metric
        resp = client.post(
            "/api/v1/query/exploration/save-metric",
            json={
                "business_name": "总运费",
                "definition": "运费之和",
                "data_source_id": "ds_tms",
                "aggregation": "sum",
                "filters": [],
                "synonyms": [],
                "field_mapping": [],
                "lineage": {},
                "visibility": "enterprise",
                "user_id": "tester",
                "target_pack_id": pack_id,
            },
        )
    assert resp.status_code == 200

    # P5: save never mutates an enterprise draft directly. The response
    # hands off to the explicit preview/confirm promotion workflow.
    assert resp.json()["data"]["promotion_required"] is True
    assert resp.json()["data"]["next_action"] == "preview_promotion"
    pack_resp = client.get(f"/api/v1/admin/enterprise-packs/{pack_id}", headers=_hdrs(sid))
    pack_data = pack_resp.json()["data"]
    metric_codes = [m["metric_code"] for m in pack_data["draft"].get("metrics", [])]
    assert metric_codes == []


def test_sedimentation_without_target_pack_unchanged(tmp_path: Path) -> None:
    """Save without target_pack_id behaves exactly as Phase 3 standalone."""
    client, _ = _make_client(tmp_path)
    mock_metric = MetricDefinition(
        metric_code="exp_anon::standalone",
        name="standalone",
        definition="test",
        visibility=MetricVisibility.PRIVATE,
        formula=MetricFormula(expression="SELECT NULL AS placeholder -- exploration: standalone"),
        data_source_id="ds_tms",
        owner="anonymous",
    )
    with patch("sq_bi_runtime.api.get_repository") as mock_repo:
        mock_repo.return_value.create_user_metric.return_value = mock_metric
        resp = client.post(
            "/api/v1/query/exploration/save-metric",
            json={
                "business_name": "standalone",
                "definition": "test",
                "data_source_id": "ds_tms",
                "aggregation": "sum",
                "filters": [],
                "synonyms": [],
                "field_mapping": [],
                "lineage": {},
                "visibility": "private",
                "user_id": "anonymous",
            },
        )
    assert resp.status_code == 200
    assert "standalone" in resp.json()["data"]["metric"]["metric_code"]
    assert resp.json()["data"]["personal_asset"]["workspace_id"] == "anonymous"
