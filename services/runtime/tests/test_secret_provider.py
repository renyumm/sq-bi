from __future__ import annotations

import os
import pytest
from pathlib import Path
from sq_bi_runtime.secret_provider import (
    EnvSecretProvider,
    FileSecretProvider,
    is_secret_field,
    mask_secrets,
    resolve_provider,
)


def test_is_secret_field_password() -> None:
    assert is_secret_field("password") is True
    assert is_secret_field("db_password") is True
    assert is_secret_field("api_key") is True
    assert is_secret_field("SECRET") is True


def test_is_secret_field_non_secrets() -> None:
    assert is_secret_field("username") is False
    assert is_secret_field("has_password") is False
    assert is_secret_field("model") is False
    assert is_secret_field("base_url") is False


def test_mask_secrets_masks_string_values() -> None:
    data = {"username": "admin", "password": "secret123", "api_key": "sk-xxx"}
    masked = mask_secrets(data)
    assert masked["username"] == "admin"
    assert masked["password"] == "********"
    assert masked["api_key"] == "********"


def test_mask_secrets_leaves_non_strings_intact() -> None:
    data = {"port": 5432, "ssl": True, "password": "x"}
    masked = mask_secrets(data)
    assert masked["port"] == 5432
    assert masked["ssl"] is True


def test_env_provider_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_SECRET", "mysecretvalue")
    provider = EnvSecretProvider()
    assert provider.get("MY_SECRET") == "mysecretvalue"


def test_env_provider_returns_none_for_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_KEY_XYZ", raising=False)
    provider = EnvSecretProvider()
    assert provider.get("MISSING_KEY_XYZ") is None


def test_file_provider_reads_secret(tmp_path: Path) -> None:
    secret_file = tmp_path / "db_password"
    secret_file.write_text("hunter2\n")
    provider = FileSecretProvider(tmp_path)
    assert provider.get("db_password") == "hunter2"


def test_file_provider_missing_file(tmp_path: Path) -> None:
    provider = FileSecretProvider(tmp_path)
    assert provider.get("nonexistent_secret") is None


def test_resolve_provider_env() -> None:
    p = resolve_provider("env")
    assert isinstance(p, EnvSecretProvider)


def test_resolve_provider_file(tmp_path: Path) -> None:
    p = resolve_provider("file", secrets_dir=str(tmp_path))
    assert isinstance(p, FileSecretProvider)


def test_resolve_provider_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown secret provider"):
        resolve_provider("vault")


def test_resolve_provider_external_raises() -> None:
    with pytest.raises(NotImplementedError):
        resolve_provider("external")
