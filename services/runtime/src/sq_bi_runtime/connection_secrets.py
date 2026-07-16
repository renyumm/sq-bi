"""Encrypt/decrypt data-source connection passwords at rest.

Key resolution follows the existing ``_env_first`` pattern (config.py):
``SQ_BI_SECRET_KEY`` env var if set, otherwise a key file generated once
under ``storage_path`` and reused thereafter. Not a substitute for a real
KMS in production, but closes the "plaintext password on disk" gap for
local/dev deployments.

Values are pass-through-compatible with pre-existing unencrypted records:
``decrypt_password`` only decrypts values carrying the ``enc:`` prefix.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_ENC_PREFIX = "enc:"


def _resolve_key(storage_path: str | Path) -> bytes:
    env_key = os.getenv("SQ_BI_SECRET_KEY")
    if env_key:
        return env_key.encode("utf-8")
    key_path = Path(storage_path) / "secret.key"
    if key_path.exists():
        return key_path.read_bytes()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    return key


def encrypt_password(raw_password: str, storage_path: str | Path) -> str:
    """Encrypt a password for storage. Returns an ``enc:``-prefixed token."""
    if not raw_password:
        return ""
    fernet = Fernet(_resolve_key(storage_path))
    token = fernet.encrypt(raw_password.encode("utf-8")).decode("utf-8")
    return _ENC_PREFIX + token


def decrypt_password(stored_value: str, storage_path: str | Path) -> str:
    """Decrypt a password stored via ``encrypt_password``.

    Legacy plaintext values (no ``enc:`` prefix) pass through unchanged so
    existing unencrypted records keep working until next save.
    """
    if not stored_value or not stored_value.startswith(_ENC_PREFIX):
        return stored_value
    fernet = Fernet(_resolve_key(storage_path))
    try:
        return fernet.decrypt(stored_value[len(_ENC_PREFIX):].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""
