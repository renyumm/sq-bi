"""Focused tests for runtime-eligible personal-creation templates
(GET /api/v1/personal-assets/templates) and personal-workspace isolation
(simplified-workspace-pack-management tasks 2.6, 4.2).

Templates expose official/enterprise assets that are actually runtime
resolvable (active, ready deployments) as source-versioned creation
templates, without ever listing them as personal assets.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from sq_bi_contracts.enterprise_pack import (
    EnterprisePackDraft,
    MetricFormula,
    PackEnterpriseMetric,
)
from sq_bi_runtime.api import create_app


def _make_app_and_client(tmp_path: Path) -> tuple[TestClient, str]:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        f"base_url: http://localhost/v1\nkey: test-key\nmodel: test-model\nstorage_path: {tmp_path}\n",
        encoding="utf-8",
    )
    app = create_app(cfg_path)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return client, resp.json()["data"]["session_id"]


def _hdrs(session_id: str) -> dict[str, str]:
    return {"X-Session-Id": session_id}


def _activate_enterprise_metric_deployment(
    client: TestClient, sid: str, data_source_id: str, metric_code: str = "total_revenue"
) -> tuple[str, str]:
    """Create, publish, deploy, and activate a blank enterprise pack with one
    metric. Returns (pack_id, deployment_id)."""
    create_resp = client.post(
        "/api/v1/admin/enterprise-packs",
        headers=_hdrs(sid),
        json={"name": "Finance pack", "mode": "blank", "created_by": "tester"},
    )
    assert create_resp.status_code == 200, create_resp.text
    pack_id = create_resp.json()["data"]["pack_id"]

    draft = EnterprisePackDraft(
        metrics=[
            PackEnterpriseMetric(
                metric_code=metric_code,
                name="Total revenue",
                definition="Published revenue definition",
                formula=MetricFormula(expression="select 1 as total_revenue from dual"),
            )
        ],
    )
    update_resp = client.put(
        f"/api/v1/admin/enterprise-packs/{pack_id}",
        headers=_hdrs(sid),
        json={"draft": draft.model_dump(mode="json")},
    )
    assert update_resp.status_code == 200, update_resp.text

    publish_resp = client.post(
        f"/api/v1/admin/enterprise-packs/{pack_id}/publish",
        headers=_hdrs(sid),
        json={"version": "1.0.0", "published_by": "tester"},
    )
    assert publish_resp.status_code == 200, publish_resp.text

    create_dep_resp = client.post(
        "/api/v1/admin/deployments",
        headers=_hdrs(sid),
        json={"pack_id": pack_id, "data_source_id": data_source_id},
    )
    assert create_dep_resp.status_code == 200, create_dep_resp.text
    dep_id = create_dep_resp.json()["data"]["deployment"]["deployment_id"]

    activate_resp = client.post(f"/api/v1/admin/deployments/{dep_id}/activate", headers=_hdrs(sid))
    assert activate_resp.status_code == 200, activate_resp.text
    return pack_id, dep_id


# ── Auth ─────────────────────────────────────────────────────────────────

def test_templates_requires_auth(tmp_path: Path) -> None:
    client, _ = _make_app_and_client(tmp_path)
    resp = client.get("/api/v1/personal-assets/templates", params={"data_source_id": "ds_x"})
    assert resp.status_code == 401


def test_templates_empty_when_no_active_deployments(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.get(
        "/api/v1/personal-assets/templates",
        headers=_hdrs(sid),
        params={"data_source_id": "ds_untouched"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []


# ── Runtime-eligible templates ──────────────────────────────────────────

def test_active_enterprise_metric_is_offered_as_a_template(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    pack_id, _dep_id = _activate_enterprise_metric_deployment(client, sid, "ds_templates")

    resp = client.get(
        "/api/v1/personal-assets/templates",
        headers=_hdrs(sid),
        params={"data_source_id": "ds_templates"},
    )
    assert resp.status_code == 200, resp.text
    templates = resp.json()["data"]
    assert len(templates) == 1
    template = templates[0]
    assert template["source_type"] == "enterprise_pack"
    assert template["source_id"] == pack_id
    assert template["version"] == "1.0.0"
    assert template["asset_ref"]["asset"]["local_code"] == "total_revenue"
    assert template["asset_type"] == "metric"


def test_inactive_deployment_metric_is_not_offered_as_a_template(tmp_path: Path) -> None:
    """A pack with a draft/unpublished/unactivated deployment must never
    surface as a template — only runtime-eligible (active+ready) assets do."""
    client, sid = _make_app_and_client(tmp_path)
    create_resp = client.post(
        "/api/v1/admin/enterprise-packs",
        headers=_hdrs(sid),
        json={"name": "Draft pack", "mode": "blank", "created_by": "tester"},
    )
    pack_id = create_resp.json()["data"]["pack_id"]
    draft = EnterprisePackDraft(
        metrics=[
            PackEnterpriseMetric(
                metric_code="unpublished_metric",
                name="Unpublished",
                definition="Not yet deployed",
                formula=MetricFormula(expression="select 1 from dual"),
            )
        ],
    )
    client.put(
        f"/api/v1/admin/enterprise-packs/{pack_id}",
        headers=_hdrs(sid),
        json={"draft": draft.model_dump(mode="json")},
    )

    resp = client.get(
        "/api/v1/personal-assets/templates",
        headers=_hdrs(sid),
        params={"data_source_id": "ds_draft_only"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []


# ── Task 4.2: personal-workspace isolation from template sources ───────

def test_personal_asset_list_never_includes_pack_content(tmp_path: Path) -> None:
    """Runtime-eligible official/enterprise assets are selectable as
    templates but MUST NOT ever be listed as personal assets — the
    Personal Workspace lists only the owner's own private assets."""
    client, sid = _make_app_and_client(tmp_path)
    _activate_enterprise_metric_deployment(client, sid, "ds_isolation")

    templates_resp = client.get(
        "/api/v1/personal-assets/templates",
        headers=_hdrs(sid),
        params={"data_source_id": "ds_isolation"},
    )
    assert len(templates_resp.json()["data"]) == 1

    workspace_id = "admin"
    personal_resp = client.get(
        "/api/v1/personal-assets",
        headers=_hdrs(sid),
        params={"workspace_id": workspace_id},
    )
    assert personal_resp.status_code == 200
    personal_assets = personal_resp.json()["data"]
    assert all(
        item["asset_ref"]["asset"]["source_type"] == "personal_workspace"
        for item in personal_assets
    )
    assert not any(
        item["asset_ref"]["asset"]["source_id"] == "ds_isolation" for item in personal_assets
    )


def test_personal_asset_provenance_persists_deduplicated_dependencies(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    _activate_enterprise_metric_deployment(client, sid, "ds_harness")
    templates_resp = client.get(
        "/api/v1/personal-assets/templates",
        headers=_hdrs(sid),
        params={"data_source_id": "ds_harness"},
    )
    dependency_ref = templates_resp.json()["data"][0]["asset_ref"]

    save_resp = client.post(
        "/api/v1/personal-assets/provenance",
        headers=_hdrs(sid),
        json={
            "asset_type": "skill",
            "local_code": "carrier_harness",
            "name": "Carrier harness",
            "data_source_id": "ds_harness",
            "template_asset_ref": dependency_ref,
            "dependency_refs": [dependency_ref, dependency_ref],
        },
    )
    assert save_resp.status_code == 200, save_resp.text
    record = save_resp.json()["data"]
    assert record["template_asset_ref"] == dependency_ref
    assert record["dependency_refs"] == [dependency_ref]

    list_resp = client.get(
        "/api/v1/personal-assets",
        headers=_hdrs(sid),
        params={"workspace_id": "admin"},
    )
    stored = next(item for item in list_resp.json()["data"] if item["name"] == "Carrier harness")
    assert stored["dependency_refs"] == [dependency_ref]
