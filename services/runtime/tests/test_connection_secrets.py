from __future__ import annotations

from pathlib import Path

import pytest

from sq_bi_runtime.connection_secrets import decrypt_password, encrypt_password


def test_encrypt_then_decrypt_round_trips(tmp_path: Path) -> None:
    token = encrypt_password("s3cret!", tmp_path)
    assert token.startswith("enc:")
    assert token != "s3cret!"
    assert decrypt_password(token, tmp_path) == "s3cret!"


def test_empty_password_is_not_encrypted(tmp_path: Path) -> None:
    assert encrypt_password("", tmp_path) == ""


def test_legacy_plaintext_passes_through_decrypt(tmp_path: Path) -> None:
    """A password saved before encryption was added should still decrypt (pass-through)."""
    assert decrypt_password("legacy-plaintext-pw", tmp_path) == "legacy-plaintext-pw"


def test_key_persisted_and_reused_across_calls(tmp_path: Path) -> None:
    token = encrypt_password("pw1", tmp_path)
    assert (tmp_path / "secret.key").exists()
    # A second call must reuse the same persisted key, not generate a new one.
    assert decrypt_password(token, tmp_path) == "pw1"


def test_env_key_overrides_file_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.fernet import Fernet

    env_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("SQ_BI_SECRET_KEY", env_key)
    token = encrypt_password("pw-env", tmp_path)
    assert not (tmp_path / "secret.key").exists()
    assert decrypt_password(token, tmp_path) == "pw-env"


def test_corrupted_token_decrypts_to_empty_string(tmp_path: Path) -> None:
    encrypt_password("seed", tmp_path)  # ensure a key file exists
    assert decrypt_password("enc:not-a-real-token", tmp_path) == ""
