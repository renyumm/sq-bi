from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class SecretProvider(Protocol):
    """Abstraction for sourcing secrets (passwords, API keys)."""

    def get(self, key: str) -> str | None: ...

    def get_or_raise(self, key: str) -> str:
        value = self.get(key)
        if value is None:
            raise KeyError(f"Secret not found: {key}")
        return value


class EnvSecretProvider:
    """Reads secrets from environment variables."""

    def get(self, key: str) -> str | None:
        return os.getenv(key)


class FileSecretProvider:
    """Reads secrets from a directory of flat files (Docker secrets style).

    Each file is named after the secret key; its content (minus trailing
    whitespace) is the secret value.
    """

    def __init__(self, secrets_dir: str | Path = "/run/secrets") -> None:
        self._dir = Path(secrets_dir)

    def get(self, key: str) -> str | None:
        path = self._dir / key
        if path.is_file():
            return path.read_text(encoding="utf-8").rstrip("\n\r ")
        return None


def resolve_provider(provider_type: str = "env", **kwargs: str) -> SecretProvider:
    """Factory: return a secret provider by type name."""
    if provider_type == "env":
        return EnvSecretProvider()
    if provider_type == "file":
        return FileSecretProvider(**kwargs)  # type: ignore[arg-type]
    if provider_type == "external":
        # External providers (Vault, AWS Secrets Manager, etc.) are
        # wired by the deployment — this is the extension point.
        msg = (
            f"External secret provider '{provider_type}' is not built in. "
            "Implement SecretProvider protocol and register it."
        )
        raise NotImplementedError(msg)
    msg = f"Unknown secret provider type: {provider_type}"
    raise ValueError(msg)


MASK = "********"

SECRET_FIELD_SUFFIXES = (
    "password",
    "api_key",
    "api-key",
    "secret",
    "token",
    "credential",
    "connection_string",
    "private_key",
    "access_key",
    "access_key_id",
    "secret_access_key",
)
def is_secret_field(field_name: str) -> bool:
    """Heuristic: return True if *field_name* looks like a raw secret value.

    Avoids matching booleans or pre-masked fields (has_*, *_mask).
    """
    lower = field_name.lower().replace("-", "_")
    # Skip boolean flags and pre-masked output fields
    if lower.startswith("has_") or lower.endswith("_mask"):
        return False
    return any(lower.endswith(suffix) for suffix in SECRET_FIELD_SUFFIXES)

def mask_secrets(data: dict[str, object]) -> dict[str, object]:
    """Return a copy of *data* with known secret fields masked.

    Only string values are masked; non-string fields (booleans, ints) pass through.
    """
    return {
        key: (MASK if (is_secret_field(key) and isinstance(value, str)) else value)
        for key, value in data.items()
    }
