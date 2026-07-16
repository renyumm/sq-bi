from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from sq_bi_runtime.api import create_app


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    config = tmp_path / "config.yaml"
    config.write_text(
        f"base_url: http://localhost/v1\nkey: test\nmodel: test\nstorage_path: {tmp_path}\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(config), raise_server_exceptions=False)
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    return client, {"X-Session-Id": login.json()["data"]["session_id"]}


def test_save_preview_confirm_does_not_mutate_source_and_requires_lifecycle(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    pack = client.post(
        "/api/v1/admin/enterprise-packs",
        headers=headers,
        json={
            "name": "Operations",
            "mode": "blank",
            "created_by": "admin",
        },
    ).json()["data"]
    saved_response = client.post(
        "/api/v1/query/exploration/save-metric",
        json={
            "business_name": "Order Count",
            "definition": "Count orders",
            "data_source_id": "ds1",
            "aggregation": "count",
            "filters": [],
            "synonyms": [],
            "field_mapping": [],
            "lineage": {
                "physical_tables": ["ORDERS"],
                "physical_fields": ["ORDERS.ID"],
            },
            "sql": "SELECT COUNT(ID) AS ORDER_COUNT FROM ORDERS",
            "user_id": "admin",
            "execution_provenance": {
                "data_source_id": "ds1",
                "environment": "default",
                "semantic_space_ids": ["space_orders"],
            },
        },
    )
    assert saved_response.status_code == 200, saved_response.text
    saved = saved_response.json()["data"]
    ref = saved["personal_asset"]["asset_ref"]

    request = {
        "workspace_id": "admin",
        "target_pack_id": pack["pack_id"],
        "asset_refs": [ref],
        "requested_by": "admin",
    }
    preview = client.post(
        "/api/v1/personal-assets/promotions/preview", headers=headers, json=request
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["eligible"] is True
    assert preview.json()["data"]["standard_fields"][0]["physical_column"] == "ID"

    confirmed = client.post(
        "/api/v1/personal-assets/promotions/confirm", headers=headers, json=request
    )
    assert confirmed.status_code == 200, confirmed.text
    promotion_id = confirmed.json()["data"]["promotion_id"]
    status = client.get(
        f"/api/v1/personal-assets/promotions/{promotion_id}", headers=headers
    )
    assert status.json()["data"]["lifecycle"] == "draft"
    assert status.json()["data"]["next_action"] == "publish_pack"

    pack_after = client.get(
        f"/api/v1/admin/enterprise-packs/{pack['pack_id']}", headers=headers
    ).json()["data"]
    assert pack_after["draft"]["metrics"][0]["metric_code"] == ref["asset"]["local_code"]
    # Source remains independently personal and workspace-scoped.
    assert saved["personal_asset"]["workspace_id"] == "admin"

    published = client.post(
        f"/api/v1/admin/enterprise-packs/{pack['pack_id']}/publish",
        headers=headers,
        json={"version": "1.0.0", "published_by": "admin"},
    )
    assert published.status_code == 200, published.text
    status = client.get(
        f"/api/v1/personal-assets/promotions/{promotion_id}", headers=headers
    ).json()["data"]
    assert status["lifecycle"] == "published"
    assert status["next_action"] == "create_deployment"

    deployment = client.post(
        "/api/v1/admin/deployments",
        headers=headers,
        json={"pack_id": pack["pack_id"], "data_source_id": "ds1"},
    )
    assert deployment.status_code == 200, deployment.text
    deployment_id = deployment.json()["data"]["deployment"]["deployment_id"]
    activated = client.post(
        f"/api/v1/admin/deployments/{deployment_id}/activate", headers=headers
    )
    # Publishing and creating a deployment must not bypass field mapping and
    # smoke validation. Activation remains blocked until those steps complete.
    assert activated.status_code == 400, activated.text
    assert "not ready" in activated.json()["error"]["message"].lower()
    status = client.get(
        f"/api/v1/personal-assets/promotions/{promotion_id}", headers=headers
    ).json()["data"]
    assert status["lifecycle"] == "deployed"
    assert status["next_action"] == "validate_deployment"
