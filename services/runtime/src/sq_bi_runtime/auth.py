from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from fastapi import Depends, Header, HTTPException
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from sq_bi_contracts.auth import AuthBackendConfig, TokenClaims
from sq_bi_contracts.common import UserContext
from sq_bi_contracts.enums import AuthBackendType


# ── In-memory session store (replace with redis/DB for production) ──────

_SESSION_STORE: dict[str, UserContext] = {}
_MAX_SESSIONS = 10_000
_EVICT_BATCH = 1_000


def _evict_sessions_if_needed() -> None:
    if len(_SESSION_STORE) >= _MAX_SESSIONS:
        to_evict = list(_SESSION_STORE.keys())[:_EVICT_BATCH]
        for k in to_evict:
            _SESSION_STORE.pop(k, None)
_TOKEN_SECRET: str = os.environ.get("SQBI_TOKEN_SECRET") or secrets.token_hex(32)


def _generate_session_id() -> str:
    return f"sess_{secrets.token_hex(16)}"


def _generate_token(user_id: str, org_id: str, role_ids: list[str]) -> str:
    """Simple HMAC-signed token (replace with JWT library for production)."""
    payload = json.dumps(
        {"sub": user_id, "org_id": org_id, "role_ids": role_ids, "iat": time.time()},
        separators=(",", ":"),
    )
    sig = hmac.new(_TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}.{sig}"


def _verify_token(token: str) -> TokenClaims | None:
    try:
        payload_b64, sig = token.rsplit(".", 1)
        expected = hmac.new(_TOKEN_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(payload_b64)
        return TokenClaims(
            sub=data["sub"],
            org_id=data.get("org_id", ""),
            role_ids=data.get("role_ids", []),
        )
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def create_session(user_context: UserContext) -> str:
    _evict_sessions_if_needed()
    session_id = _generate_session_id()
    _SESSION_STORE[session_id] = user_context
    return session_id


def get_session(session_id: str) -> UserContext | None:
    return _SESSION_STORE.get(session_id)


def destroy_session(session_id: str) -> None:
    _SESSION_STORE.pop(session_id, None)


def refresh_user_sessions(
    old_username: str,
    new_username: str,
    display_name: str,
    role: str,
) -> None:
    """Keep active local sessions coherent after an administrator edits a user."""
    for session_id, context in list(_SESSION_STORE.items()):
        if context.user_id != old_username:
            continue
        _SESSION_STORE[session_id] = UserContext(
            user_id=new_username,
            display_name=display_name,
            org_id=context.org_id,
            role_ids=[role],
            data_scope=context.data_scope,
            locale=context.locale,
            timezone=context.timezone,
        )


# ── Authentication backends ────────────────────────────────────────────

_LOCAL_USERS: dict[str, str] = {"admin": "admin123"}
_PASSWORD_ITERATIONS = 210_000


def _password_hash(password: str, salt: str | None = None) -> tuple[str, str]:
    password_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), password_salt.encode("utf-8"), _PASSWORD_ITERATIONS
    ).hex()
    return password_salt, digest


@runtime_checkable
class AuthBackend(Protocol):
    """Interface for pluggable authentication backends."""

    def authenticate(self, username: str, password: str) -> UserContext | None: ...


class LocalAuthBackend:
    """Persistent local account store with administrator and user roles.

    The store is intentionally small and local for single-node deployments.  It
    is a clear boundary for replacing with SSO/LDAP later, while passwords are
    never written to disk in plaintext.
    """

    def __init__(
        self,
        user_store: dict[str, str] | None = None,
        role_map: dict[str, list[str]] | None = None,
        storage_path: Path | None = None,
    ) -> None:
        self._storage_path = storage_path
        self._role_map = role_map or {"admin": ["admin"], "__default__": ["user"]}
        self._users = dict(user_store or _LOCAL_USERS)
        self._records: dict[str, dict[str, str]] = {}
        if storage_path is not None:
            self._load_records()

    def _load_records(self) -> None:
        if self._storage_path is not None and self._storage_path.exists():
            try:
                payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
                records = payload.get("users", [])
                self._records = {record["username"]: record for record in records if "username" in record}
            except (OSError, ValueError, TypeError):
                self._records = {}
        if self._records:
            return
        self._records = {}
        self._upsert_record("admin", "admin123", "系统管理员", "admin")
        self._upsert_record("user", "user123", "普通用户", "user")
        self._save_records()

    def _save_records(self) -> None:
        if self._storage_path is None:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"users": list(self._records.values())}
        self._storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _upsert_record(self, username: str, password: str, display_name: str, role: str) -> None:
        salt, digest = _password_hash(password)
        self._records[username] = {
            "username": username,
            "display_name": display_name or username,
            "role": role,
            "password_salt": salt,
            "password_hash": digest,
        }

    def authenticate(self, username: str, password: str) -> UserContext | None:
        if self._storage_path is not None:
            record = self._records.get(username)
            if record is None:
                return None
            _salt, digest = _password_hash(password, record["password_salt"])
            if not hmac.compare_digest(record["password_hash"], digest):
                return None
            return UserContext(
                user_id=username,
                display_name=record.get("display_name") or username,
                org_id="default",
                role_ids=[record.get("role", "user")],
            )
        expected = self._users.get(username)
        if expected is None or not hmac.compare_digest(expected, password):
            return None
        role_ids = self._role_map.get(username) or self._role_map.get("__default__", ["user"])
        return UserContext(
            user_id=username,
            display_name=username,
            org_id="default",
            role_ids=role_ids,
        )

    def list_users(self) -> list[dict[str, str]]:
        return [
            {
                "user_id": record["username"],
                "display_name": record.get("display_name") or record["username"],
                "role": record.get("role", "user"),
            }
            for record in sorted(self._records.values(), key=lambda item: item["username"])
        ]

    def create_user(self, username: str, password: str, display_name: str, role: str) -> dict[str, str]:
        if self._storage_path is None:
            raise ValueError("User management requires a persistent local store.")
        normalized = username.strip()
        if not normalized or len(normalized) > 64 or not normalized.replace("_", "").replace("-", "").isalnum():
            raise ValueError("用户名只能包含字母、数字、下划线或连字符。")
        if len(password) < 8:
            raise ValueError("密码至少需要 8 个字符。")
        if role not in {"admin", "user"}:
            raise ValueError("用户角色无效。")
        if normalized in self._records:
            raise ValueError("该用户名已存在。")
        self._upsert_record(normalized, password, display_name.strip() or normalized, role)
        self._save_records()
        return next(item for item in self.list_users() if item["user_id"] == normalized)

    @staticmethod
    def _normalized_username(username: str) -> str:
        normalized = username.strip()
        if not normalized or len(normalized) > 64 or not normalized.replace("_", "").replace("-", "").isalnum():
            raise ValueError("用户名只能包含字母、数字、下划线或连字符。")
        return normalized

    def update_user(
        self,
        username: str,
        display_name: str | None = None,
        role: str | None = None,
        password: str | None = None,
        new_username: str | None = None,
    ) -> dict[str, str]:
        record = self._records.get(username)
        if record is None:
            raise ValueError("用户不存在。")
        normalized_username = self._normalized_username(new_username) if new_username is not None else username
        if normalized_username != username and normalized_username in self._records:
            raise ValueError("该用户名已存在。")
        if role is not None:
            if role not in {"admin", "user"}:
                raise ValueError("用户角色无效。")
            if record.get("role") == "admin" and role != "admin" and self._admin_count() <= 1:
                raise ValueError("系统至少需要保留一个管理员。")
            record["role"] = role
        if display_name is not None:
            record["display_name"] = display_name.strip() or normalized_username
        if password:
            if len(password) < 8:
                raise ValueError("密码至少需要 8 个字符。")
            salt, digest = _password_hash(password)
            record["password_salt"] = salt
            record["password_hash"] = digest
        if normalized_username != username:
            self._records.pop(username)
            record["username"] = normalized_username
            self._records[normalized_username] = record
        self._save_records()
        return next(item for item in self.list_users() if item["user_id"] == normalized_username)

    def delete_user(self, username: str) -> None:
        record = self._records.get(username)
        if record is None:
            raise ValueError("用户不存在。")
        if record.get("role") == "admin" and self._admin_count() <= 1:
            raise ValueError("系统至少需要保留一个管理员。")
        self._records.pop(username)
        self._save_records()

    def _admin_count(self) -> int:
        return sum(record.get("role") == "admin" for record in self._records.values())


# ── RBAC ───────────────────────────────────────────────────────────────

# Global set of admin role ids
_ADMIN_ROLES: set[str] = {"admin"}


def set_admin_roles(roles: set[str]) -> None:
    _ADMIN_ROLES.clear()
    _ADMIN_ROLES.update(roles)


def is_admin(user_context: UserContext | None) -> bool:
    if user_context is None:
        return False
    return bool(set(user_context.role_ids) & _ADMIN_ROLES)


def check_access(
    user_context: UserContext | None,
    required_permission: str = "read",
    asset_roles: list[str] | None = None,
) -> bool:
    """Check if *user_context* has *required_permission*.

    Args:
        user_context: The requesting user.
        required_permission: "read" | "execute" | "admin"
        asset_roles: Role tags on the target asset. None = unrestricted.

    Returns True if permitted, False if denied.
    """
    if user_context is None:
        return False

    # Admin overrides everything
    if is_admin(user_context):
        return True

    # No asset-level restriction → anyone with a valid session may read
    if asset_roles is None and required_permission == "read":
        return True

    # Asset tagged with specific roles → user must hold at least one
    if asset_roles is not None:
        return bool(set(user_context.role_ids) & set(asset_roles))

    # Execute/admin permission requires specific role tagging
    if required_permission in ("execute", "admin"):
        return False

    return True


# ── FastAPI dependency helpers ─────────────────────────────────────────

AUTH_HEADER = "X-Session-Id"
TOKEN_HEADER = "Authorization"


def resolve_user_context(
    session_id: str | None = None,
    token: str | None = None,
) -> UserContext | None:
    """Resolve UserContext from session or token."""
    if session_id:
        ctx = get_session(session_id)
        if ctx is not None:
            return ctx
    if token:
        claims = _verify_token(token)
        if claims is not None:
            return UserContext(
                user_id=claims.sub,
                display_name=claims.sub,
                org_id=claims.org_id,
                role_ids=claims.role_ids,
            )
    return None


# ── FastAPI dependency ───────────────────────────────────────────────


def get_current_user(
    x_session_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> UserContext | None:
    """FastAPI dependency that resolves UserContext from request headers.

    When used as Depends(get_current_user), returns None for anonymous
    access (the caller checks permissions).

    Raise 401 explicitly for required-auth endpoints.
    """
    token: str | None = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    return resolve_user_context(session_id=x_session_id, token=token)


def require_user(
    user: UserContext | None = Depends(get_current_user),
) -> UserContext:
    """FastAPI dependency that rejects unauthenticated requests."""
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Authentication required."})
    return user


def admin_required(
    user: UserContext | None = Depends(get_current_user),
) -> UserContext:
    """FastAPI dependency: require admin role."""
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Authentication required."})
    if not is_admin(user):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Admin role required."})
    return user
