from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field
from sq_bi_contracts.auth import LoginRequest, LoginResponse
from sq_bi_contracts.enums import ErrorCode

from .auth import (
    LocalAuthBackend,
    _generate_token,
    create_session,
    destroy_session,
    is_admin,
    refresh_user_sessions,
    resolve_user_context,
)


class ManagedUserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8, max_length=256)
    display_name: str = Field(default="", max_length=128)
    role: str = Field(default="user")


class ManagedUserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, min_length=8, max_length=256)
    role: str | None = None
    new_username: str | None = Field(default=None, min_length=1, max_length=64)


def register_auth_routes(
    app: FastAPI,
    *,
    storage_path: str | Path,
    response: Callable[[Any], dict[str, Any]],
    error_response: Callable[..., Any],
) -> None:
    """Attach local identity endpoints without coupling them to query composition."""

    backend = LocalAuthBackend(storage_path=Path(storage_path) / "local_users.json")

    def require_admin(request: Request) -> Any:
        session_id = request.headers.get("X-Session-Id")
        user_context = resolve_user_context(session_id=session_id)
        if user_context is None:
            return error_response(401, ErrorCode.UNAUTHORIZED, "Authentication required.")
        if not is_admin(user_context):
            return error_response(403, ErrorCode.FORBIDDEN, "Admin role required.")
        return user_context

    @app.post("/api/v1/auth/login", response_model=None)
    def auth_login(request: LoginRequest) -> Any:
        user_context = backend.authenticate(request.username, request.password)
        if user_context is None:
            return error_response(401, ErrorCode.UNAUTHORIZED, "Invalid credentials.")
        session_id = create_session(user_context)
        return response(LoginResponse(
            session_id=session_id,
            token=_generate_token(user_context.user_id, user_context.org_id, user_context.role_ids),
            user_id=user_context.user_id,
            display_name=user_context.display_name,
            org_id=user_context.org_id,
            role_ids=user_context.role_ids,
            expires_at=datetime.now(UTC).replace(hour=23, minute=59, second=59),
        ))

    @app.post("/api/v1/auth/logout", response_model=None)
    def auth_logout(request: Request) -> Any:
        session_id = request.headers.get("X-Session-Id")
        if session_id:
            destroy_session(session_id)
        return response({"status": "logged_out"})

    @app.get("/api/v1/auth/session", response_model=None)
    def auth_session(request: Request) -> Any:
        session_id = request.headers.get("X-Session-Id")
        user_context = resolve_user_context(session_id=session_id) if session_id else None
        if user_context is None:
            return error_response(401, ErrorCode.UNAUTHORIZED, "No active session.")
        return response(user_context.model_dump(mode="json"))

    @app.get("/api/v1/admin/users", response_model=None)
    def list_users(request: Request) -> Any:
        auth = require_admin(request)
        if not hasattr(auth, "user_id"):
            return auth
        return response(backend.list_users())

    @app.post("/api/v1/admin/users", response_model=None)
    def create_user(payload: ManagedUserCreateRequest, request: Request) -> Any:
        auth = require_admin(request)
        if not hasattr(auth, "user_id"):
            return auth
        try:
            return response(backend.create_user(
                payload.username,
                payload.password,
                payload.display_name,
                payload.role,
            ))
        except ValueError as exc:
            return error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))

    @app.patch("/api/v1/admin/users/{username}", response_model=None)
    def update_user(username: str, payload: ManagedUserUpdateRequest, request: Request) -> Any:
        auth = require_admin(request)
        if not hasattr(auth, "user_id"):
            return auth
        try:
            updated = backend.update_user(
                username,
                payload.display_name,
                payload.role,
                payload.password,
                payload.new_username,
            )
            refresh_user_sessions(username, updated["user_id"], updated["display_name"], updated["role"])
            return response(updated)
        except ValueError as exc:
            return error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))

    @app.delete("/api/v1/admin/users/{username}", response_model=None)
    def delete_user(username: str, request: Request) -> Any:
        auth = require_admin(request)
        if not hasattr(auth, "user_id"):
            return auth
        if username == auth.user_id:
            return error_response(400, ErrorCode.VALIDATION_ERROR, "不能删除当前登录账户。")
        try:
            backend.delete_user(username)
            return response({"status": "deleted"})
        except ValueError as exc:
            return error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))

