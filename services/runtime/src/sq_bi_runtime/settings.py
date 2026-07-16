from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import BaseModel, Field
from .config import DBConfig, LLMConfig
from .secret_provider import mask_secrets


DEFAULT_SETTINGS_PATH = Path(".local/runtime_settings.json")
DEFAULT_TMS_CONNECTION_ALIAS = "TMS_ORACLE"


@dataclass
class LLMSettingsView:
    base_url: str
    model: str
    timeout_seconds: float
    has_api_key: bool
    api_key_mask: str | None = None


@dataclass
class DBSettingsView:
    data_source_id: str
    name: str
    database_type: str
    connection_alias: str
    is_read_only: bool
    is_configured: bool
    user_mask: str | None = None
    dsn_mask: str | None = None
    has_password: bool = False


class LLMSettingsUpdate(BaseModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)


class DBSettingsUpdate(BaseModel):
    connection_alias: str | None = None
    user: str | None = None
    password: str | None = None
    dsn: str | None = None


def mask_key(api_key: str) -> str:
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


def mask_value(value: str) -> str:
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:2]}...{value[-2:]}"


def read_runtime_settings(path: Path = DEFAULT_SETTINGS_PATH) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8") or "{}")


def write_runtime_settings(settings: dict, path: Path = DEFAULT_SETTINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_local_llm_settings(config: LLMConfig, path: Path = DEFAULT_SETTINGS_PATH) -> LLMConfig:
    settings = read_runtime_settings(path).get("llm", {})
    if not isinstance(settings, dict):
        return config
    return LLMConfig(
        base_url=str(settings.get("base_url") or config.base_url).rstrip("/"),
        api_key=str(settings.get("api_key") or config.api_key),
        model=str(settings.get("model") or config.model),
        timeout_seconds=float(settings.get("timeout_seconds") or config.timeout_seconds),
    )


def apply_local_db_settings(config: DBConfig, path: Path = DEFAULT_SETTINGS_PATH) -> DBConfig:
    settings = read_runtime_settings(path).get("db", {})
    if not isinstance(settings, dict):
        return config
    return DBConfig(
        user=str(settings.get("user") or config.user) if settings.get("user") or config.user else None,
        password=str(settings.get("password") or config.password) if settings.get("password") or config.password else None,
        dsn=str(settings.get("dsn") or config.dsn) if settings.get("dsn") or config.dsn else None,
        pool_min=int(settings.get("pool_min") or config.pool_min),
        pool_max=int(settings.get("pool_max") or config.pool_max),
        pool_increment=int(settings.get("pool_increment") or config.pool_increment),
        pool_wait_timeout_ms=int(settings.get("pool_wait_timeout_ms") or config.pool_wait_timeout_ms),
        tcp_connect_timeout_seconds=float(
            settings.get("tcp_connect_timeout_seconds") or config.tcp_connect_timeout_seconds
        ),
    )


def llm_settings_view(config: LLMConfig) -> LLMSettingsView:
    has_api_key = bool(config.api_key and config.api_key != "disabled")
    return LLMSettingsView(
        base_url=config.base_url,
        model=config.model,
        timeout_seconds=config.timeout_seconds,
        has_api_key=has_api_key,
        api_key_mask=mask_key(config.api_key) if has_api_key else None,
    )


def db_settings_view(config: DBConfig, path: Path = DEFAULT_SETTINGS_PATH) -> DBSettingsView:
    settings = read_runtime_settings(path).get("db", {})
    if not isinstance(settings, dict):
        settings = {}
    alias = str(settings.get("connection_alias") or DEFAULT_TMS_CONNECTION_ALIAS)
    return DBSettingsView(
        data_source_id="oracle_tms",
        name="TMS Oracle",
        database_type="oracle",
        connection_alias=alias,
        is_read_only=True,
        is_configured=config.is_configured,
        user_mask=mask_value(config.user) if config.user else None,
        dsn_mask=mask_value(config.dsn) if config.dsn else None,
        has_password=bool(config.password),
    )


def update_llm_settings(config: LLMConfig, update: LLMSettingsUpdate, path: Path = DEFAULT_SETTINGS_PATH) -> LLMConfig:
    settings = read_runtime_settings(path)
    llm = settings.get("llm", {})
    if not isinstance(llm, dict):
        llm = {}

    if update.base_url is not None:
        llm["base_url"] = update.base_url.rstrip("/")
    if update.model is not None:
        llm["model"] = update.model
    if update.timeout_seconds is not None:
        llm["timeout_seconds"] = update.timeout_seconds
    if update.api_key:
        llm["api_key"] = update.api_key

    settings["llm"] = llm
    write_runtime_settings(settings, path)

    return apply_local_llm_settings(config, path)


def update_db_settings(config: DBConfig, update: DBSettingsUpdate, path: Path = DEFAULT_SETTINGS_PATH) -> DBConfig:
    settings = read_runtime_settings(path)
    db = settings.get("db", {})
    if not isinstance(db, dict):
        db = {}

    if update.connection_alias is not None:
        db["connection_alias"] = update.connection_alias
    if update.user is not None:
        db["user"] = update.user
    if update.dsn is not None:
        db["dsn"] = update.dsn
    if update.password:
        db["password"] = update.password
    settings["db"] = db
    write_runtime_settings(settings, path)

    return apply_local_db_settings(config, path)

def as_response_payload(view: LLMSettingsView | DBSettingsView) -> dict:
    return mask_secrets(asdict(view))
