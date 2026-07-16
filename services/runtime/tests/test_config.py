from pathlib import Path

from fastapi.testclient import TestClient

from sq_bi_contracts.common import UserContext
from sq_bi_runtime.api import create_app
from sq_bi_runtime.auth import create_session
from sq_bi_runtime.config import load_config, resolve_storage_path


def test_relative_storage_path_is_stable_across_working_directories(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    legacy = repo_root / "services" / "runtime" / ".local"
    legacy.mkdir(parents=True)
    (legacy / "field_mappings.sqlite3").touch()

    assert resolve_storage_path(".local", repo_root) == legacy.resolve()
    explicit = tmp_path / "explicit-storage"
    assert resolve_storage_path(explicit, repo_root) == explicit.resolve()


def _admin_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    session_id = resp.json()["data"]["session_id"]
    return client, {"X-Session-Id": session_id}


def _general_user_headers() -> dict[str, str]:
    session_id = create_session(
        UserContext(user_id="u_general", display_name="General", org_id="default", role_ids=["user"])
    )
    return {"X-Session-Id": session_id}


def test_load_flat_config(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "base_url: https://example.com/v1\nkey: abc\nmodel: test-model\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.llm.base_url == "https://example.com/v1"
    assert config.llm.api_key == "abc"
    assert config.llm.model == "test-model"


def test_missing_config_uses_tms_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TMS_LLM_BASE_URL", "https://llm.example.com/v1")
    monkeypatch.setenv("TMS_LLM_API_KEY", "secret")
    monkeypatch.setenv("TMS_LLM_MODEL", "model-a")
    monkeypatch.setenv("TMS_DB_USERNAME", "tms_user")
    monkeypatch.setenv("TMS_DB_PASSWORD", "tms_password")
    monkeypatch.setenv("TMS_DB_DSN", "dbhost:1521/service")

    config = load_config("config.yaml")

    assert config.llm.base_url == "https://llm.example.com/v1"
    assert config.llm.api_key == "secret"
    assert config.llm.model == "model-a"
    assert config.db.user == "tms_user"
    assert config.db.password == "tms_password"
    assert config.db.dsn == "dbhost:1521/service"
    assert config.db.is_configured is True


def test_runtime_app_mounts_tms_semantic_routes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app()
    route_paths = {getattr(route, "path", "") for route in app.routes}

    assert "/api/v1/catalog/data-sources" in route_paths
    assert "/api/v1/metrics" in route_paths
    assert "/api/v1/skills" in route_paths
    assert "/api/v1/query/ask" in route_paths
    assert "/api/v1/ai/reports/{report_id}/generate" in route_paths
    assert "/api/v1/query/parse" not in route_paths
    assert "/api/v1/query/execute" not in route_paths


def test_runtime_llm_settings_can_be_updated_locally(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SQ_BI_STORAGE_PATH", str(tmp_path / ".local"))
    client, headers = _admin_client(tmp_path)

    initial = client.get("/api/v1/settings/llm", headers=headers)
    assert initial.status_code == 200
    assert initial.json()["data"]["has_api_key"] is False

    updated = client.patch(
        "/api/v1/settings/llm",
        headers=headers,
        json={
            "base_url": "https://llm.example.com/v1/",
            "model": "tms-model",
            "api_key": "sk-test-secret",
            "timeout_seconds": 42,
        },
    )
    assert updated.status_code == 200

    data = updated.json()["data"]
    assert data["base_url"] == "https://llm.example.com/v1"
    assert data["model"] == "tms-model"
    assert data["timeout_seconds"] == 42
    assert data["has_api_key"] is True
    assert data["api_key_mask"] == "sk-t...cret"
    assert (tmp_path / ".local" / "runtime_settings.json").exists()


def test_runtime_llm_probe_reports_latency_and_health(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sq_bi_runtime.llm_client.OpenAICompatClient.chat",
        lambda self, system_prompt, user_prompt, **kwargs: '{"status":"ok"}',
    )
    client, headers = _admin_client(tmp_path)

    response = client.post("/api/v1/settings/llm/probe", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"]["healthy"] is True
    assert response.json()["data"]["latency_ms"] >= 0


def test_runtime_llm_settings_requires_admin(tmp_path: Path) -> None:
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/settings/llm")
    assert resp.status_code == 401

    resp = client.patch("/api/v1/settings/llm", json={"model": "x"})
    assert resp.status_code == 401


def test_runtime_llm_settings_forbidden_for_general_user(tmp_path: Path) -> None:
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    headers = _general_user_headers()

    resp = client.get("/api/v1/settings/llm", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    resp = client.patch("/api/v1/settings/llm", json={"model": "x"}, headers=headers)
    assert resp.status_code == 403


def test_runtime_db_settings_can_be_updated_locally(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SQ_BI_STORAGE_PATH", str(tmp_path / ".local"))
    client, headers = _admin_client(tmp_path)

    initial = client.get("/api/v1/settings/db", headers=headers)
    assert initial.status_code == 200
    assert initial.json()["data"]["is_configured"] is False

    updated = client.patch(
        "/api/v1/settings/db",
        headers=headers,
        json={
            "connection_alias": "TMS_ORACLE_LOCAL",
            "user": "tms_user",
            "password": "tms_password",
            "dsn": "dbhost:1521/service",
        },
    )
    assert updated.status_code == 200

    data = updated.json()["data"]
    assert data["connection_alias"] == "TMS_ORACLE_LOCAL"
    assert data["is_configured"] is True
    assert data["user_mask"] == "tm...er"
    assert data["dsn_mask"] == "db...ce"
    assert data["has_password"] is True


def test_runtime_db_settings_requires_admin(tmp_path: Path) -> None:
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/settings/db")
    assert resp.status_code == 401

    resp = client.patch("/api/v1/settings/db", json={"user": "x"})
    assert resp.status_code == 401


def test_runtime_db_settings_forbidden_for_general_user(tmp_path: Path) -> None:
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    headers = _general_user_headers()

    resp = client.get("/api/v1/settings/db", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    resp = client.patch("/api/v1/settings/db", json={"user": "x"}, headers=headers)
    assert resp.status_code == 403
