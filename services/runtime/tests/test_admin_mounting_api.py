"""End-to-end tests for /api/v1/admin/* mounting endpoints.

Uses FastAPI TestClient with a minimal in-memory config so no real DB or LLM
is required. Admin auth is via the default local credentials (admin/admin123).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from sq_bi_contracts.semantic_profile import TableRecommendation
from sq_bi_runtime.api import create_app


# ── Helpers ────────────────────────────────────────────────────────────


def _make_app_and_client(tmp_path: Path) -> tuple[TestClient, str]:
    """Create a TestClient with tmp storage. Returns (client, session_id)."""
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


# ── Tests ──────────────────────────────────────────────────────────────


def test_admin_list_packs_requires_auth(tmp_path: Path) -> None:
    client, _ = _make_app_and_client(tmp_path)
    resp = client.get("/api/v1/admin/packs")  # no session header → 401
    assert resp.status_code == 401


def test_admin_list_packs_empty(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.get("/api/v1/admin/packs", headers=_hdrs(sid))
    assert resp.status_code == 200
    body = resp.json()
    # Default registry has no packs
    assert body.get("data") is not None


def test_admin_get_deployment_status_not_found(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.get(
        "/api/v1/admin/deployments/dep_nonexistent/status",
        headers=_hdrs(sid),
    )
    assert resp.status_code == 404


def test_admin_get_pending_not_found(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.get(
        "/api/v1/admin/deployments/dep_nonexistent/pending",
        headers=_hdrs(sid),
    )
    assert resp.status_code == 404


def test_admin_smoke_test_not_found(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.post(
        "/api/v1/admin/deployments/dep_nonexistent/smoke-test",
        headers=_hdrs(sid),
    )
    assert resp.status_code == 404


def test_admin_confirm_not_found(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.post(
        "/api/v1/admin/deployments/dep_nonexistent/confirm",
        headers=_hdrs(sid),
        json={
            "pack_id": "test",
            "data_source_id": "ds",
            "standard_field_id": "deliver_no",
            "mapping_request_id": "req_x",
            "chosen_candidate_index": 0,
        },
    )
    assert resp.status_code == 404


def test_admin_full_deployment_flow(tmp_path: Path) -> None:
    """create deployment → check status → pending → smoke-test (compile-only)."""
    from sq_bi_contracts.domain_pack import DomainPackManifest, PackStandardField
    from sq_bi_runtime.pack_loader import PackRegistry

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        f"base_url: http://localhost/v1\nkey: test-key\nmodel: test-model\nstorage_path: {tmp_path}\n",
        encoding="utf-8",
    )

    manifest = DomainPackManifest(
        pack_id="test_pack",
        namespace="test",
        name="Test Pack",
        version="1.0.0",
        standard_fields=[
            PackStandardField(
                field_id="deliver_no",
                business_name="运单号",
                data_type="text",
                required=True,
            )
        ],
    )
    registry = PackRegistry()
    pack_dir = tmp_path / "packs" / "test_pack"
    pack_dir.mkdir(parents=True)
    registry.install(manifest, pack_dir)

    # Patch get_registry for the duration of app creation AND all requests
    with patch("sq_bi_runtime.api.get_registry", return_value=registry):
        app = create_app(cfg_path)
        client = TestClient(app, raise_server_exceptions=False)

        login_resp = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        sid = login_resp.json().get("data", {}).get("session_id", "")

        # List packs — expect our test_pack
        packs_resp = client.get("/api/v1/admin/packs", headers=_hdrs(sid))
        assert packs_resp.status_code == 200
        packs_body = packs_resp.json()
        assert packs_body.get("error") is None
        packs = packs_body.get("data", [])
        assert any(p.get("pack_id") == "test_pack" for p in packs)

        # Create deployment (no physical schema → deliver_no stays pending)
        create_resp = client.post(
            "/api/v1/admin/deployments",
            headers=_hdrs(sid),
            json={"pack_id": "test_pack", "data_source_id": "ds_test"},
        )
        assert create_resp.status_code == 200
        create_body = create_resp.json()
        assert create_body.get("error") is None, f"Unexpected error: {create_body}"
        deployment = create_body.get("data", {}).get("deployment", {})
        dep_id = deployment.get("deployment_id", "")
        assert dep_id, "Expected deployment_id in response"

        # Status
        status_resp = client.get(
            f"/api/v1/admin/deployments/{dep_id}/status",
            headers=_hdrs(sid),
        )
        assert status_resp.status_code == 200
        status_data = status_resp.json().get("data", {})
        assert status_data.get("deployment_id") == dep_id
        assert status_data.get("validation_status") in ("unvalidated", "incomplete", "failed", "ready")

        # Pending list
        pending_resp = client.get(
            f"/api/v1/admin/deployments/{dep_id}/pending",
            headers=_hdrs(sid),
        )
        assert pending_resp.status_code == 200
        assert pending_resp.json().get("error") is None

        # Smoke test (no active mappings → compiles nothing → all_passed=False but no crash)
        smoke_resp = client.post(
            f"/api/v1/admin/deployments/{dep_id}/smoke-test",
            headers=_hdrs(sid),
        )
        assert smoke_resp.status_code == 200
        assert smoke_resp.json().get("error") is None


def test_admin_create_deployment_persists_and_lists_semantic_space_ids(tmp_path: Path) -> None:
    """A deployment created with semantic_space_ids returns and lists them."""
    from sq_bi_contracts.domain_pack import DomainPackManifest, PackStandardField
    from sq_bi_runtime.pack_loader import PackRegistry

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        f"base_url: http://localhost/v1\nkey: test-key\nmodel: test-model\nstorage_path: {tmp_path}\n",
        encoding="utf-8",
    )
    manifest = DomainPackManifest(
        pack_id="test_pack2", namespace="test", name="Test Pack 2", version="1.0.0",
        standard_fields=[
            PackStandardField(field_id="deliver_no", business_name="运单号", data_type="text")
        ],
    )
    registry = PackRegistry()
    pack_dir = tmp_path / "packs" / "test_pack2"
    pack_dir.mkdir(parents=True)
    registry.install(manifest, pack_dir)

    with patch("sq_bi_runtime.api.get_registry", return_value=registry):
        app = create_app(cfg_path)
        client = TestClient(app, raise_server_exceptions=False)
        sid = client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
        ).json()["data"]["session_id"]

        create_resp = client.post(
            "/api/v1/admin/deployments",
            headers=_hdrs(sid),
            json={
                "pack_id": "test_pack2",
                "data_source_id": "ds_test2",
                "semantic_space_ids": ["sps_a", "sps_b"],
            },
        )
        assert create_resp.status_code == 200, create_resp.text
        deployment = create_resp.json()["data"]["deployment"]
        assert deployment["semantic_space_ids"] == ["sps_a", "sps_b"]

        packs_resp = client.get("/api/v1/admin/packs", headers=_hdrs(sid))
        pack_entry = next(p for p in packs_resp.json()["data"] if p["pack_id"] == "test_pack2")
        listed = pack_entry["deployments"][0]
        assert listed["semantic_space_ids"] == ["sps_a", "sps_b"]
        assert listed["binding_status"] == "unavailable"
        assert listed["unavailable_semantic_space_ids"] == ["sps_a", "sps_b"]

        status_resp = client.get(
            f"/api/v1/admin/deployments/{deployment['deployment_id']}/status",
            headers=_hdrs(sid),
        )
        status = status_resp.json()["data"]
        assert status["binding_status"] == "unavailable"
        assert "绑定语义空间已删除" in status["blocking_reasons"][0]


def test_admin_confirms_scanned_candidate_and_expands_bound_space(tmp_path: Path) -> None:
    from sq_bi_contracts.domain_pack import DomainPackManifest, PackStandardField
    from sq_bi_runtime.pack_loader import PackRegistry
    from sq_bi_runtime.schema_scanner import ColumnMeta, TableMeta
    from sq_bi_runtime.semantic_profile_store import SemanticProfileStore

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        f"base_url: http://localhost/v1\nkey: test-key\nmodel: test-model\nstorage_path: {tmp_path}\n",
        encoding="utf-8",
    )
    profile_store = SemanticProfileStore(tmp_path / "semantic_profile.sqlite3")
    snapshot = profile_store.create_snapshot("ds_tms")
    profile_store.save_catalog(
        snapshot.snapshot_id,
        [
            TableMeta(name="HR_DELIVER_CARRY", columns=[ColumnMeta(name="PROJECT_ID")]),
            TableMeta(name="HR_PROJECT_BASE", columns=[ColumnMeta(name="PROJECT_NAME")]),
        ],
    )
    space = profile_store.create_space(
        "ds_tms", "运输执行", initial_tables=["HR_DELIVER_CARRY"]
    )
    manifest = DomainPackManifest(
        pack_id="test_project_pack",
        namespace="test",
        name="Project Pack",
        standard_fields=[
            PackStandardField(
                field_id="project_name",
                business_name="项目名称",
                data_type="text",
            )
        ],
    )
    registry = PackRegistry()
    pack_dir = tmp_path / "packs" / "test_project_pack"
    pack_dir.mkdir(parents=True)
    registry.install(manifest, pack_dir)

    with patch("sq_bi_runtime.api.get_registry", return_value=registry):
        client = TestClient(create_app(cfg_path), raise_server_exceptions=False)
        sid = client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
        ).json()["data"]["session_id"]
        created = client.post(
            "/api/v1/admin/deployments",
            headers=_hdrs(sid),
            json={
                "pack_id": "test_project_pack",
                "data_source_id": "ds_tms",
                "semantic_space_ids": [space.space_id],
            },
        )
        assert created.status_code == 200, created.text
        deployment_id = created.json()["data"]["deployment"]["deployment_id"]
        pending = created.json()["data"]["pending"][0]
        assert pending["outside_scope_candidates"][0]["physical_column"] == "PROJECT_NAME"

        confirmed = client.post(
            f"/api/v1/admin/deployments/{deployment_id}/confirm",
            headers=_hdrs(sid),
            json={
                "pack_id": "test_project_pack",
                "data_source_id": "ds_tms",
                "standard_field_id": "project_name",
                "mapping_request_id": pending["mapping_request_id"],
                "chosen_candidate_index": 0,
                "candidate_scope": "scanned_catalog",
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        expanded = profile_store.get_space(space.space_id)
        assert expanded is not None
        assert "HR_PROJECT_BASE" in {entity.physical_table for entity in expanded.entities}

        remap = client.post(
            f"/api/v1/admin/deployments/{deployment_id}/mappings/project_name/remap",
            headers=_hdrs(sid),
        )
        assert remap.status_code == 200, remap.text
        remap_pending = remap.json()["data"]
        assert remap_pending["standard_field_id"] == "project_name"
        assert remap_pending["candidates"][0]["physical_column"] == "PROJECT_NAME"

        changed = client.post(
            f"/api/v1/admin/deployments/{deployment_id}/confirm",
            headers=_hdrs(sid),
            json={
                "pack_id": "test_project_pack",
                "data_source_id": "ds_tms",
                "standard_field_id": "project_name",
                "mapping_request_id": remap_pending["mapping_request_id"],
                "chosen_candidate_index": 0,
                "candidate_scope": "bound_space",
            },
        )
        assert changed.status_code == 200, changed.text
        status = client.get(
            f"/api/v1/admin/deployments/{deployment_id}/status",
            headers=_hdrs(sid),
        ).json()["data"]
        assert status["is_active"] is False


# ── P1: implicit default space (pack-first mounting) ─────────────────────


def test_admin_create_deployment_no_spaces_at_all_auto_creates_implicit_space(
    tmp_path: Path,
) -> None:
    """Omitting semantic_space_ids with zero existing spaces must not block
    mounting — the backend creates an implicit default space rather than
    requiring a manual pre-step (see design doc §2.3). An unscanned data
    source still gets a placeholder space (empty until the next scan)."""
    client, sid = _make_app_and_client(tmp_path)
    create_resp = client.post(
        "/api/v1/admin/deployments",
        headers=_hdrs(sid),
        json={"pack_id": "tms", "data_source_id": "ds_implicit"},
    )
    assert create_resp.status_code == 200, create_resp.text
    data = create_resp.json()["data"]
    assert len(data["deployment"]["semantic_space_ids"]) == 1
    assert data["auto_created_semantic_space_id"] == data["deployment"]["semantic_space_ids"][0]

    spaces_resp = client.get(
        "/api/v1/datasources/ds_implicit/semantic-spaces", headers=_hdrs(sid)
    )
    spaces = spaces_resp.json()["data"]
    assert len(spaces) == 1
    assert spaces[0]["name"] == "TMS 运输管理系统领域包 · 自动适配"
    assert "ds_implicit 默认语义空间" not in spaces[0]["name"]


def test_admin_create_deployment_one_existing_space_reused_without_creating_another(
    tmp_path: Path,
) -> None:
    """A single unambiguous existing space is reused implicitly; no new
    space is created."""
    from sq_bi_runtime.semantic_profile_store import SemanticProfileStore

    profile_store = SemanticProfileStore(tmp_path / "semantic_profile.sqlite3")
    space = profile_store.create_space("ds_single", "已有空间")

    client, sid = _make_app_and_client(tmp_path)
    create_resp = client.post(
        "/api/v1/admin/deployments",
        headers=_hdrs(sid),
        json={"pack_id": "tms", "data_source_id": "ds_single"},
    )
    assert create_resp.status_code == 200, create_resp.text
    data = create_resp.json()["data"]
    assert data["deployment"]["semantic_space_ids"] == [space.space_id]
    assert data["auto_created_semantic_space_id"] is None

    spaces_resp = client.get(
        "/api/v1/datasources/ds_single/semantic-spaces", headers=_hdrs(sid)
    )
    assert len(spaces_resp.json()["data"]) == 1


def test_admin_create_deployment_multiple_existing_spaces_requires_explicit_choice(
    tmp_path: Path,
) -> None:
    """A mixed-domain connection with several spaces must not be guessed at
    — this is exactly the ambiguity semantic spaces exist to prevent."""
    from sq_bi_runtime.semantic_profile_store import SemanticProfileStore

    profile_store = SemanticProfileStore(tmp_path / "semantic_profile.sqlite3")
    profile_store.create_space("ds_multi", "空间 A")
    profile_store.create_space("ds_multi", "空间 B")

    client, sid = _make_app_and_client(tmp_path)
    create_resp = client.post(
        "/api/v1/admin/deployments",
        headers=_hdrs(sid),
        json={"pack_id": "tms", "data_source_id": "ds_multi"},
    )
    assert create_resp.status_code == 400
    body = create_resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


# ── P1 remainder: smart candidate-scope recommendation ────────────────────


def _seed_multi_domain_catalog(tmp_path: Path, ds_id: str) -> None:
    """Two tables that clearly relate to the "tms" pack (carrier_name maps
    to its carrier_name standard field), plus one generically-classified but
    pack-irrelevant table — simulating a multi-domain connection where the
    blunt "include everything not not_relevant" default would have wrongly
    swept the unrelated table into the implicit space."""
    from sq_bi_runtime.schema_scanner import ColumnMeta, TableMeta
    from sq_bi_runtime.semantic_profile_store import SemanticProfileStore

    store = SemanticProfileStore(tmp_path / "semantic_profile.sqlite3")
    snap = store.create_snapshot(ds_id)
    store.save_catalog(
        snap.snapshot_id,
        [
            TableMeta(
                name="tms_shipment",
                recommendation=TableRecommendation.recommended_include,
                columns=[
                    ColumnMeta(name="shipment_id", data_type="NUMBER", is_pk=True),
                    ColumnMeta(name="carrier_name", data_type="VARCHAR2"),
                ],
            ),
            TableMeta(
                name="hr_employee",
                recommendation=TableRecommendation.recommended_include,
                columns=[
                    ColumnMeta(name="employee_id", data_type="NUMBER", is_pk=True),
                    ColumnMeta(name="salary", data_type="NUMBER"),
                ],
            ),
            TableMeta(
                name="audit_log",
                recommendation=TableRecommendation.not_relevant,
                columns=[ColumnMeta(name="event_id", data_type="NUMBER")],
            ),
        ],
    )


def test_admin_recommend_scope_returns_pack_aware_tiers(tmp_path: Path) -> None:
    _seed_multi_domain_catalog(tmp_path, "ds_scope_preview")
    client, sid = _make_app_and_client(tmp_path)

    resp = client.get(
        "/api/v1/admin/deployments/recommend-scope",
        headers=_hdrs(sid),
        params={"pack_id": "tms", "data_source_id": "ds_scope_preview"},
    )
    assert resp.status_code == 200, resp.text
    by_table = {c["table_name"]: c for c in resp.json()["data"]}
    assert by_table["tms_shipment"]["tier"] == "recommended"
    assert "carrier_name" in by_table["tms_shipment"]["matched_field_ids"]
    assert by_table["hr_employee"]["tier"] == "ambiguous"
    assert by_table["audit_log"]["tier"] == "excluded"


def test_admin_recommend_scope_pack_not_found(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.get(
        "/api/v1/admin/deployments/recommend-scope",
        headers=_hdrs(sid),
        params={"pack_id": "no_such_pack", "data_source_id": "ds_x"},
    )
    assert resp.status_code == 404


def test_admin_create_deployment_implicit_space_uses_pack_aware_recommendation(
    tmp_path: Path,
) -> None:
    """The auto-created implicit space must only include the pack-aware
    "recommended" tier, not every generically-classified table — this is
    the behavior delta from the old blunt default."""
    _seed_multi_domain_catalog(tmp_path, "ds_scope_autocreate")
    client, sid = _make_app_and_client(tmp_path)

    create_resp = client.post(
        "/api/v1/admin/deployments",
        headers=_hdrs(sid),
        json={"pack_id": "tms", "data_source_id": "ds_scope_autocreate"},
    )
    assert create_resp.status_code == 200, create_resp.text

    spaces_resp = client.get(
        "/api/v1/datasources/ds_scope_autocreate/semantic-spaces", headers=_hdrs(sid)
    )
    space = spaces_resp.json()["data"][0]
    included_tables = {e["physical_table"] for e in space["entities"]}
    assert included_tables == {"tms_shipment"}


def test_admin_create_deployment_implicit_space_tables_override(tmp_path: Path) -> None:
    """An admin who reviewed the recommend-scope preview can explicitly
    confirm which tables to include, overriding the automatic tiering
    (e.g. deliberately keeping an "ambiguous" table)."""
    _seed_multi_domain_catalog(tmp_path, "ds_scope_override")
    client, sid = _make_app_and_client(tmp_path)

    create_resp = client.post(
        "/api/v1/admin/deployments",
        headers=_hdrs(sid),
        json={
            "pack_id": "tms",
            "data_source_id": "ds_scope_override",
            "implicit_space_tables": ["tms_shipment", "hr_employee"],
        },
    )
    assert create_resp.status_code == 200, create_resp.text

    spaces_resp = client.get(
        "/api/v1/datasources/ds_scope_override/semantic-spaces", headers=_hdrs(sid)
    )
    space = spaces_resp.json()["data"][0]
    included_tables = {e["physical_table"] for e in space["entities"]}
    assert included_tables == {"tms_shipment", "hr_employee"}


# ── P0 remainder: deployment activation (independent from validation_status) ──


def _make_zero_required_field_deployment(tmp_path: Path, client: TestClient, sid: str) -> str:
    """A pack with no `required=True` standard fields makes coverage/
    validation_status trivially 'ready' with zero mappings — the minimal
    fixture for exercising activation without a full mounting flow."""
    create_resp = client.post(
        "/api/v1/admin/deployments",
        headers=_hdrs(sid),
        json={"pack_id": "test_pack2", "data_source_id": "ds_activate_test"},
    )
    assert create_resp.status_code == 200, create_resp.text
    return create_resp.json()["data"]["deployment"]["deployment_id"]


def test_admin_activate_deployment_requires_ready_status(tmp_path: Path) -> None:
    """The "tms" pack has required standard fields; a fresh deployment with
    no mappings is not ready, so activation must be rejected — activation
    and validation are independent states, but activation still gates on
    validation being satisfied first."""
    client, sid = _make_app_and_client(tmp_path)
    create_resp = client.post(
        "/api/v1/admin/deployments",
        headers=_hdrs(sid),
        json={"pack_id": "tms", "data_source_id": "ds_not_ready"},
    )
    dep_id = create_resp.json()["data"]["deployment"]["deployment_id"]

    activate_resp = client.post(
        f"/api/v1/admin/deployments/{dep_id}/activate", headers=_hdrs(sid)
    )
    assert activate_resp.status_code == 400
    assert activate_resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_admin_activate_deployment_not_found(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.post(
        "/api/v1/admin/deployments/dep_nonexistent/activate", headers=_hdrs(sid)
    )
    assert resp.status_code == 404


def test_admin_activate_deployment_succeeds_when_ready(tmp_path: Path) -> None:
    from sq_bi_contracts.domain_pack import DomainPackManifest, PackStandardField
    from sq_bi_runtime.pack_loader import PackRegistry

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        f"base_url: http://localhost/v1\nkey: test-key\nmodel: test-model\nstorage_path: {tmp_path}\n",
        encoding="utf-8",
    )
    manifest = DomainPackManifest(
        pack_id="test_pack2", namespace="test", name="Test Pack 2", version="1.0.0",
        standard_fields=[
            PackStandardField(field_id="deliver_no", business_name="运单号", data_type="text")
        ],
    )
    registry = PackRegistry()
    pack_dir = tmp_path / "packs" / "test_pack2"
    pack_dir.mkdir(parents=True)
    registry.install(manifest, pack_dir)

    with patch("sq_bi_runtime.api.get_registry", return_value=registry):
        app = create_app(cfg_path)
        client = TestClient(app, raise_server_exceptions=False)
        sid = client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
        ).json()["data"]["session_id"]

        dep_id = _make_zero_required_field_deployment(tmp_path, client, sid)

        status_before = client.get(
            f"/api/v1/admin/deployments/{dep_id}/status", headers=_hdrs(sid)
        ).json()["data"]
        assert status_before["validation_status"] == "ready"
        assert status_before["is_active"] is False

        activate_resp = client.post(
            f"/api/v1/admin/deployments/{dep_id}/activate", headers=_hdrs(sid)
        )
        assert activate_resp.status_code == 200, activate_resp.text
        activated = activate_resp.json()["data"]
        assert activated["is_active"] is True
        assert activated["activated_by"] == "admin"
        assert activated["activated_at"] is not None

        # Reflected in both the status endpoint and the pack listing.
        status_after = client.get(
            f"/api/v1/admin/deployments/{dep_id}/status", headers=_hdrs(sid)
        ).json()["data"]
        assert status_after["is_active"] is True

        packs_resp = client.get("/api/v1/admin/packs", headers=_hdrs(sid))
        pack_entry = next(p for p in packs_resp.json()["data"] if p["pack_id"] == "test_pack2")
        assert pack_entry["deployments"][0]["is_active"] is True


def test_admin_deactivate_deployment_always_allowed(tmp_path: Path) -> None:
    """Deactivation is not gated on validation_status — an admin can pull a
    live deployment offline at any time."""
    from sq_bi_contracts.domain_pack import DomainPackManifest, PackStandardField
    from sq_bi_runtime.pack_loader import PackRegistry

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        f"base_url: http://localhost/v1\nkey: test-key\nmodel: test-model\nstorage_path: {tmp_path}\n",
        encoding="utf-8",
    )
    manifest = DomainPackManifest(
        pack_id="test_pack2", namespace="test", name="Test Pack 2", version="1.0.0",
        standard_fields=[
            PackStandardField(field_id="deliver_no", business_name="运单号", data_type="text")
        ],
    )
    registry = PackRegistry()
    pack_dir = tmp_path / "packs" / "test_pack2"
    pack_dir.mkdir(parents=True)
    registry.install(manifest, pack_dir)

    with patch("sq_bi_runtime.api.get_registry", return_value=registry):
        app = create_app(cfg_path)
        client = TestClient(app, raise_server_exceptions=False)
        sid = client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
        ).json()["data"]["session_id"]

        dep_id = _make_zero_required_field_deployment(tmp_path, client, sid)
        client.post(f"/api/v1/admin/deployments/{dep_id}/activate", headers=_hdrs(sid))

        deactivate_resp = client.post(
            f"/api/v1/admin/deployments/{dep_id}/deactivate", headers=_hdrs(sid)
        )
        assert deactivate_resp.status_code == 200, deactivate_resp.text
        assert deactivate_resp.json()["data"]["is_active"] is False

        status_after = client.get(
            f"/api/v1/admin/deployments/{dep_id}/status", headers=_hdrs(sid)
        ).json()["data"]
        assert status_after["is_active"] is False


def test_admin_deactivate_deployment_not_found(tmp_path: Path) -> None:
    client, sid = _make_app_and_client(tmp_path)
    resp = client.post(
        "/api/v1/admin/deployments/dep_nonexistent/deactivate", headers=_hdrs(sid)
    )
    assert resp.status_code == 404
