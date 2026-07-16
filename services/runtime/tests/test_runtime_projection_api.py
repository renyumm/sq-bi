"""Focused tests for the P3 runtime asset projection admin endpoint
(GET /api/v1/admin/deployments/runtime-projection), which wires
`RuntimeAssetResolver` into the running app (openspec/changes/
runtime-asset-projection task 4.1)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from sq_bi_contracts.domain_pack import DomainPackManifest, PackAsset
from sq_bi_contracts.enterprise_pack import (
    EnterprisePackDraft,
    MetricFormula,
    PackEnterpriseMetric,
    PackSkill,
    PackSkillStep,
)
from sq_bi_runtime.api import create_app
from sq_bi_runtime.pack_loader import PackRegistry


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


def test_runtime_projection_requires_auth(tmp_path: Path) -> None:
    client, _ = _make_app_and_client(tmp_path)
    resp = client.get(
        "/api/v1/admin/deployments/runtime-projection",
        params={"data_source_id": "ds_none"},
    )
    assert resp.status_code == 401


def test_runtime_projection_empty_for_data_source_with_no_deployments(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.get(
        "/api/v1/admin/deployments/runtime-projection",
        headers=_hdrs(sid),
        params={"data_source_id": "ds_untouched"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["context"]["data_source_id"] == "ds_untouched"
    assert data["context"]["environment"] == "default"
    assert data["effective_asset_count"] == 0
    assert data["deployments"] == []
    assert data["resolved"] == []
    assert data["excluded"] == []


def test_runtime_projection_reports_inactive_deployment_exclusion_reason(tmp_path: Path) -> None:
    """A ready-but-never-activated deployment must not be runtime-visible,
    and the reason must be the machine-readable
    RuntimeVisibilityReason.DEPLOYMENT_INACTIVE — not a guess."""
    manifest = DomainPackManifest(
        pack_id="proj_pack", namespace="proj_pack", name="Projection Pack", version="1.0.0",
    )
    registry = PackRegistry()
    pack_dir = tmp_path / "packs" / "proj_pack"
    pack_dir.mkdir(parents=True)
    registry.install(manifest, pack_dir)

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        f"base_url: http://localhost/v1\nkey: test-key\nmodel: test-model\nstorage_path: {tmp_path}\n",
        encoding="utf-8",
    )
    with patch("sq_bi_runtime.api.get_registry", return_value=registry):
        app = create_app(cfg_path)
        client = TestClient(app, raise_server_exceptions=False)
        sid = client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
        ).json()["data"]["session_id"]

        create_resp = client.post(
            "/api/v1/admin/deployments",
            headers=_hdrs(sid),
            json={"pack_id": "proj_pack", "data_source_id": "ds_inactive"},
        )
        assert create_resp.status_code == 200, create_resp.text
        dep_id = create_resp.json()["data"]["deployment"]["deployment_id"]

        status = client.get(
            f"/api/v1/admin/deployments/{dep_id}/status", headers=_hdrs(sid)
        ).json()["data"]
        assert status["validation_status"] == "ready"
        assert status["is_active"] is False

        resp = client.get(
            "/api/v1/admin/deployments/runtime-projection",
            headers=_hdrs(sid),
            params={"data_source_id": "ds_inactive"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["effective_asset_count"] == 0
        assert data["resolved"] == []
        assert len(data["deployments"]) == 1
        entry = data["deployments"][0]
        assert entry["deployment_id"] == dep_id
        assert entry["source_type"] == "official_pack"
        assert entry["source_id"] == "proj_pack"
        assert entry["excluded"] is True
        assert entry["exclusion_reason"] == "deployment_inactive"
        assert len(data["excluded"]) == 1
        assert data["excluded"][0]["reason"] == "deployment_inactive"
        assert data["excluded"][0]["deployment_id"] == dep_id


def test_runtime_projection_resolves_active_enterprise_deployment_assets(tmp_path: Path) -> None:
    """An activated enterprise-pack deployment whose exact published version
    matches must contribute its assets to the projection, with correct
    per-deployment effective asset counts."""
    client, sid = _make_app_and_client(tmp_path)

    create_pack_resp = client.post(
        "/api/v1/admin/enterprise-packs",
        headers=_hdrs(sid),
        json={
            "name": "Finance pack",
            "mode": "blank",
            "created_by": "tester",
        },
    )
    assert create_pack_resp.status_code == 200, create_pack_resp.text
    pack_id = create_pack_resp.json()["data"]["pack_id"]

    draft = EnterprisePackDraft(
        metrics=[
            PackEnterpriseMetric(
                metric_code="total_revenue",
                name="Total revenue",
                definition="Published revenue definition",
                formula=MetricFormula(expression="select 1 as total_revenue from dual"),
            )
        ],
        skills=[
            PackSkill(
                skill_id="revenue_review",
                name="Revenue review",
                steps=[
                    PackSkillStep(
                        step_id="step-1",
                        description="Read revenue",
                        metric_codes=["total_revenue"],
                    )
                ],
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

    # admin_create_deployment cannot find pack_id in the official registry,
    # so it falls back to pack_version "1.0.0" — matching the version we
    # just published above.
    create_dep_resp = client.post(
        "/api/v1/admin/deployments",
        headers=_hdrs(sid),
        json={"pack_id": pack_id, "data_source_id": "ds_enterprise"},
    )
    assert create_dep_resp.status_code == 200, create_dep_resp.text
    dep_id = create_dep_resp.json()["data"]["deployment"]["deployment_id"]

    activate_resp = client.post(
        f"/api/v1/admin/deployments/{dep_id}/activate", headers=_hdrs(sid)
    )
    assert activate_resp.status_code == 200, activate_resp.text

    resp = client.get(
        "/api/v1/admin/deployments/runtime-projection",
        headers=_hdrs(sid),
        params={"data_source_id": "ds_enterprise"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["effective_asset_count"] == 2  # 1 metric + 1 skill
    assert data["excluded"] == []
    assert len(data["deployments"]) == 1
    entry = data["deployments"][0]
    assert entry["deployment_id"] == dep_id
    assert entry["source_type"] == "enterprise_pack"
    assert entry["source_id"] == pack_id
    assert entry["effective_asset_count"] == 2
    assert entry["excluded"] is False
    assert entry["exclusion_reason"] is None
    resolved_codes = {a["asset_ref"]["asset"]["local_code"] for a in data["resolved"]}
    assert resolved_codes == {"total_revenue", "revenue_review"}
    resolved_deployment_ids = {a["deployment_id"] for a in data["resolved"]}
    assert resolved_deployment_ids == {dep_id}


def test_runtime_projection_composes_active_base_and_extension_delta(tmp_path: Path) -> None:
    """An extension deployment projects its pinned base and delta under one
    deployment identity; no copied top-level enterprise pack is involved."""
    manifest = DomainPackManifest(
        pack_id="extension_base", namespace="extension_base", name="Extension Base", version="1.0.0",
        assets=[PackAsset(path="semantic.yaml", asset_type="semantic")],
    )
    registry = PackRegistry()
    pack_dir = tmp_path / "packs" / "extension_base"
    pack_dir.mkdir(parents=True)
    (pack_dir / "semantic.yaml").write_text(
        """metrics:
  - metric_code: base_metric
    name: Base metric
    definition: A base metric
    data_source_id: unbound
    owner: official
    formula:
      expression: select 1 from dual
""",
        encoding="utf-8",
    )
    registry.install(manifest, pack_dir)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        f"base_url: http://localhost/v1\nkey: test-key\nmodel: test-model\nstorage_path: {tmp_path}\n",
        encoding="utf-8",
    )
    with patch("sq_bi_runtime.api.get_registry", return_value=registry):
        client = TestClient(create_app(cfg_path), raise_server_exceptions=False)
        sid = client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
        ).json()["data"]["session_id"]
        headers = _hdrs(sid)
        base = client.post(
            "/api/v1/admin/deployments", headers=headers,
            json={"pack_id": "extension_base", "data_source_id": "ds_extension"},
        )
        assert base.status_code == 200, base.text
        base_dep_id = base.json()["data"]["deployment"]["deployment_id"]
        assert client.post(f"/api/v1/admin/deployments/{base_dep_id}/activate", headers=headers).status_code == 200

        layer_resp = client.post(
            "/api/v1/admin/domain-packs/extension_base/extension-layer",
            headers=headers, json={"base_kind": "official", "created_by": "tester"},
        )
        assert layer_resp.status_code == 200, layer_resp.text
        layer_id = layer_resp.json()["data"]["extension_id"]
        update = client.put(
            f"/api/v1/admin/extension-layers/{layer_id}", headers=headers,
            json={"draft": {"metrics": [{
                "metric_code": "extension_metric", "name": "Extension metric",
                "definition": "A delta metric", "formula": {"expression": "select 1 from dual"},
            }]}},
        )
        assert update.status_code == 200, update.text
        assert client.post(f"/api/v1/admin/extension-layers/{layer_id}/publish", headers=headers).status_code == 200
        extension = client.post(
            "/api/v1/admin/deployments", headers=headers,
            json={
                "pack_id": "extension_base", "data_source_id": "ds_extension",
                "extension_layer_id": layer_id,
            },
        )
        assert extension.status_code == 200, extension.text
        extension_dep_id = extension.json()["data"]["deployment"]["deployment_id"]
        assert client.post(
            f"/api/v1/admin/deployments/{extension_dep_id}/activate", headers=headers
        ).status_code == 200
        projection = client.get(
            "/api/v1/admin/deployments/runtime-projection", headers=headers,
            params={"data_source_id": "ds_extension"},
        )
        assert projection.status_code == 200, projection.text
        data = projection.json()["data"]
        resolved_codes = {
            item["asset_ref"]["asset"]["local_code"] for item in data["resolved"]
        }
        assert {"base_metric", "extension_metric"} <= resolved_codes
        assert any(item["deployment_id"] == extension_dep_id for item in data["resolved"])
