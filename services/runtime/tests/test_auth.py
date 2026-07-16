from __future__ import annotations

import pytest
from sq_bi_contracts.common import UserContext
from sq_bi_runtime.auth import (
    LocalAuthBackend,
    check_access,
    create_session,
    destroy_session,
    get_session,
    is_admin,
    refresh_user_sessions,
    resolve_user_context,
    set_admin_roles,
)


def test_local_auth_backend_valid_credentials() -> None:
    backend = LocalAuthBackend()
    ctx = backend.authenticate("admin", "admin123")
    assert ctx is not None
    assert ctx.user_id == "admin"
    assert "admin" in ctx.role_ids


def test_local_auth_backend_invalid_credentials() -> None:
    backend = LocalAuthBackend()
    ctx = backend.authenticate("admin", "wrong")
    assert ctx is None


def test_local_auth_backend_unknown_user() -> None:
    backend = LocalAuthBackend()
    ctx = backend.authenticate("nobody", "x")
    assert ctx is None


def test_session_create_and_retrieve() -> None:
    ctx = UserContext(user_id="u1", display_name="U1", org_id="o1")
    session_id = create_session(ctx)
    retrieved = get_session(session_id)
    assert retrieved is not None
    assert retrieved.user_id == "u1"


def test_session_destroy() -> None:
    ctx = UserContext(user_id="u2", display_name="U2", org_id="o1")
    session_id = create_session(ctx)
    assert get_session(session_id) is not None
    destroy_session(session_id)
    assert get_session(session_id) is None


def test_local_user_can_be_renamed_and_active_session_is_refreshed(tmp_path) -> None:
    backend = LocalAuthBackend(storage_path=tmp_path / "users.json")
    backend.create_user("analyst", "password123", "分析员", "user")
    session_id = create_session(
        UserContext(user_id="analyst", display_name="分析员", org_id="default", role_ids=["user"])
    )

    updated = backend.update_user(
        "analyst",
        display_name="高级分析员",
        role="admin",
        password="newpassword123",
        new_username="senior_analyst",
    )
    refresh_user_sessions("analyst", updated["user_id"], updated["display_name"], updated["role"])

    assert backend.authenticate("analyst", "password123") is None
    assert backend.authenticate("senior_analyst", "newpassword123") is not None
    session = get_session(session_id)
    assert session is not None
    assert session.user_id == "senior_analyst"
    assert session.display_name == "高级分析员"
    assert session.role_ids == ["admin"]
    destroy_session(session_id)


def test_is_admin_with_admin_role() -> None:
    set_admin_roles({"admin"})
    ctx = UserContext(user_id="u1", display_name="U1", org_id="o1", role_ids=["admin"])
    assert is_admin(ctx) is True


def test_is_admin_without_admin_role() -> None:
    set_admin_roles({"admin"})
    ctx = UserContext(user_id="u2", display_name="U2", org_id="o1", role_ids=["user"])
    assert is_admin(ctx) is False


def test_is_admin_none() -> None:
    assert is_admin(None) is False


def test_check_access_admin_override() -> None:
    set_admin_roles({"admin"})
    ctx = UserContext(user_id="u1", display_name="U1", org_id="o1", role_ids=["admin"])
    assert check_access(ctx, "read") is True
    assert check_access(ctx, "execute") is True
    assert check_access(ctx, "admin") is True


def test_check_access_unauthenticated_denied() -> None:
    assert check_access(None, "read") is False


def test_check_access_list_filters_by_role() -> None:
    ctx = UserContext(user_id="u1", display_name="U1", org_id="o1", role_ids=["analyst"])
    assert check_access(ctx, "read", asset_roles=["analyst"]) is True
    assert check_access(ctx, "read", asset_roles=["admin"]) is False


def test_resolve_user_context_unknown_session() -> None:
    ctx = resolve_user_context(session_id="nonexistent")
    assert ctx is None


def test_token_generate_and_verify() -> None:
    from sq_bi_runtime.auth import _generate_token, _verify_token
    token = _generate_token("u1", "o1", ["analyst"])
    claims = _verify_token(token)
    assert claims is not None
    assert claims.sub == "u1"
    assert claims.org_id == "o1"
    assert "analyst" in claims.role_ids


def test_token_tampered_rejected() -> None:
    from sq_bi_runtime.auth import _generate_token, _verify_token
    token = _generate_token("u1", "o1", [])
    tampered = token[:-4] + "xxxx"
    assert _verify_token(tampered) is None


def test_token_invalid_json_rejected() -> None:
    from sq_bi_runtime.auth import _verify_token
    assert _verify_token("not.a.valid.token") is None


def test_session_eviction_when_full() -> None:
    from sq_bi_runtime.auth import _SESSION_STORE, _MAX_SESSIONS, create_session
    from sq_bi_contracts.common import UserContext
    # Overflow the session store
    initial = len(_SESSION_STORE)
    for i in range(_MAX_SESSIONS - initial + 5):
        create_session(UserContext(user_id=f"bulk_{i}", display_name="", org_id="o"))
    # After eviction, store should be well below max + buffer
    assert len(_SESSION_STORE) < _MAX_SESSIONS + 100


def test_local_auth_role_map_custom() -> None:
    from sq_bi_runtime.auth import LocalAuthBackend
    backend = LocalAuthBackend(
        user_store={"alice": "pw1"},
        role_map={"alice": ["finance"], "__default__": ["viewer"]},
    )
    ctx = backend.authenticate("alice", "pw1")
    assert ctx is not None
    assert "finance" in ctx.role_ids
