from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 60.0


@dataclass
class DBConfig:
    user: str | None = None
    password: str | None = None
    dsn: str | None = None
    pool_min: int = 1
    pool_max: int = 4
    pool_increment: int = 1
    pool_wait_timeout_ms: int = 15000
    tcp_connect_timeout_seconds: float = 5.0

    @property
    def is_configured(self) -> bool:
        return bool(self.user and self.password and self.dsn)


@dataclass
class AppConfig:
    """Centralized application configuration.

    Priority (highest to lowest):
    1. Environment variables (SQ_BI_* / legacy TMS_* / OPENAI_*)
    2. YAML config file (config.yaml)
    3. Default values below
    """

    llm: LLMConfig
    db: DBConfig
    skill_dir: Path
    app_title: str = "SQ-BI Query Runtime"
    # --- New commercial fields (3.1 / 3.2) ---
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    org_id: str = "default"
    org_name: str = "Default Organization"
    storage_path: str = ".local"
    enabled_packs: tuple[str, ...] = ()
    edition: str = "community"  # "community" | "enterprise"
    secret_provider: str = "env"  # "env" | "file" | "external"


def resolve_storage_path(storage_path: str | Path, repo_root: str | Path) -> Path:
    """Resolve runtime storage independently from the process working directory.

    Older local installations were normally started from ``services/runtime``
    and therefore wrote ``.local`` there. Keep using that populated directory
    when present; otherwise use the repository-level ``.local`` directory.
    Explicit absolute paths are never changed.
    """
    configured = Path(storage_path).expanduser()
    if configured.is_absolute():
        return configured.resolve()
    root = Path(repo_root).resolve()
    canonical = (root / configured).resolve()
    legacy = (root / "services" / "runtime" / configured).resolve()
    if configured == Path(".local") and legacy.exists():
        legacy_markers = (
            "datasources.json",
            "field_mappings.sqlite3",
            "semantic_profile.sqlite3",
            "local_users.json",
        )
        if any((legacy / marker).exists() for marker in legacy_markers):
            return legacy
    return canonical


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Config file must be a YAML mapping.")
    return data


def _env_first(*names: str) -> str | None:
    """Return the first non-empty env var from *names, or None."""
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def load_config(config_path: str | Path = "config.yaml") -> AppConfig:
    """Load config from YAML + env var overrides.

    Priority: env var > YAML file > defaults.
    Documented env vars:
      LLM:          LLM_BASE_URL / TMS_LLM_BASE_URL / OPENAI_BASE_URL,
                    LLM_API_KEY / TMS_LLM_API_KEY / OPENAI_API_KEY,
                    LLM_MODEL / TMS_LLM_MODEL / OPENAI_MODEL
      DB:           TMS_DB_USER / TMS_DB_USERNAME, TMS_DB_PASSWORD, TMS_DB_DSN
      CORS:         SQ_BI_CORS_ORIGINS (comma-separated)
      Org:          SQ_BI_ORG_ID, SQ_BI_ORG_NAME
      Storage:      SQ_BI_STORAGE_PATH
      Packs:        SQ_BI_ENABLED_PACKS (comma-separated)
      Edition:      SQ_BI_EDITION
      Secret:       SQ_BI_SECRET_PROVIDER
    """
    path = Path(config_path)
    raw = _read_yaml(path) if path.exists() else {}

    # ── LLM ──
    llm_section = raw.get("llm", raw)
    base_url = llm_section.get("base_url") or _env_first(
        "LLM_BASE_URL", "TMS_LLM_BASE_URL", "OPENAI_BASE_URL"
    )
    api_key = (
        llm_section.get("key")
        or llm_section.get("api_key")
        or _env_first("LLM_API_KEY", "TMS_LLM_API_KEY", "OPENAI_API_KEY")
    )
    model = (
        llm_section.get("model")
        or _env_first("LLM_MODEL", "TMS_LLM_MODEL", "OPENAI_MODEL")
        or "turing/gpt-5.4"
    )
    timeout_seconds = float(llm_section.get("timeout_seconds", 60.0))
    if not (base_url and api_key and model):
        raise ValueError("LLM config requires base_url, key/api_key, and model.")

    # ── DB ──
    db_section = raw.get("db", {})
    db = DBConfig(
        user=db_section.get("user") or _env_first("TMS_DB_USER", "TMS_DB_USERNAME"),
        password=db_section.get("password") or _env_first("TMS_DB_PASSWORD"),
        dsn=db_section.get("dsn") or _env_first("TMS_DB_DSN"),
        pool_min=int(
            db_section.get("pool_min")
            or _env_first("TMS_DB_POOL_MIN", "SQ_BI_DB_POOL_MIN")
            or 1
        ),
        pool_max=int(
            db_section.get("pool_max")
            or _env_first("TMS_DB_POOL_MAX", "SQ_BI_DB_POOL_MAX")
            or 4
        ),
        pool_increment=int(
            db_section.get("pool_increment")
            or _env_first("TMS_DB_POOL_INCREMENT", "SQ_BI_DB_POOL_INCREMENT")
            or 1
        ),
        pool_wait_timeout_ms=int(
            db_section.get("pool_wait_timeout_ms")
            or _env_first(
                "TMS_DB_POOL_WAIT_TIMEOUT_MS", "SQ_BI_DB_POOL_WAIT_TIMEOUT_MS"
            )
            or 15000
        ),
        tcp_connect_timeout_seconds=float(
            db_section.get("tcp_connect_timeout_seconds")
            or _env_first(
                "TMS_DB_TCP_CONNECT_TIMEOUT_SECONDS",
                "SQ_BI_DB_TCP_CONNECT_TIMEOUT_SECONDS",
            )
            or 5.0
        ),
    )

    # ── Skill dir ──
    skill_dir_value = (
        raw.get("skill_dir")
        or _env_first("TMS_SKILL_DIR")
        or "skills/tms-system-askdata"
    )
    skill_dir = (path.parent / skill_dir_value).resolve()

    # ── General ──
    app_title = raw.get("app_title", "SQ-BI Query Runtime")

    # ── CORS origins (3.2) ──
    cors_value = raw.get("cors_origins")
    if isinstance(cors_value, list):
        cors_origins = tuple(str(o) for o in cors_value)
    else:
        env_cors = _env_first("SQ_BI_CORS_ORIGINS") or ""
        cors_origins = (
            tuple(v.strip() for v in env_cors.split(",") if v.strip())
            or ("http://localhost:5173", "http://127.0.0.1:5173")
        )

    # ── Org defaults (3.2) ──
    org_id = str(raw.get("org_id") or _env_first("SQ_BI_ORG_ID") or "default")
    org_name = str(
        raw.get("org_name") or _env_first("SQ_BI_ORG_NAME") or "Default Organization"
    )

    # ── Storage path (3.2) ──
    storage_path = str(
        raw.get("storage_path") or _env_first("SQ_BI_STORAGE_PATH") or ".local"
    )

    # ── Domain packs (3.2) ──
    packs_raw = raw.get("enabled_packs")
    if isinstance(packs_raw, list):
        enabled_packs = tuple(str(p) for p in packs_raw)
    else:
        packs_env = _env_first("SQ_BI_ENABLED_PACKS") or ""
        enabled_packs = tuple(p.strip() for p in packs_env.split(",") if p.strip())

    # ── Edition ──
    edition = str(
        raw.get("edition") or _env_first("SQ_BI_EDITION") or "community"
    )

    # ── Secret provider ──
    secret_provider = str(
        raw.get("secret_provider") or _env_first("SQ_BI_SECRET_PROVIDER") or "env"
    )

    return AppConfig(
        llm=LLMConfig(
            base_url=str(base_url).rstrip("/"),
            api_key=str(api_key),
            model=str(model),
            timeout_seconds=timeout_seconds,
        ),
        db=db,
        skill_dir=skill_dir,
        app_title=app_title,
        cors_origins=cors_origins,
        org_id=org_id,
        org_name=org_name,
        storage_path=storage_path,
        enabled_packs=enabled_packs,
        edition=edition,
        secret_provider=secret_provider,
    )
