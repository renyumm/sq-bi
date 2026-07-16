from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import Any, Callable

from fastapi import FastAPI, Request
from sq_bi_contracts.enums import ErrorCode

from .auth import is_admin, resolve_user_context
from .llm_client import OpenAICompatClient, parse_json_payload
from .settings import (
    LLMSettingsUpdate,
    as_response_payload,
    llm_settings_view,
    update_llm_settings,
)


def register_system_routes(
    app: FastAPI,
    *,
    llm_client: OpenAICompatClient,
    settings_path: Path,
    response: Callable[[Any], dict[str, Any]],
    error_response: Callable[..., Any],
) -> None:
    """Attach health and model configuration routes."""

    def require_admin(request: Request) -> Any:
        session_id = request.headers.get("X-Session-Id")
        user_context = resolve_user_context(session_id=session_id)
        if user_context is None:
            return error_response(401, ErrorCode.UNAUTHORIZED, "Authentication required.")
        if not is_admin(user_context):
            return error_response(403, ErrorCode.FORBIDDEN, "Admin role required.")
        return user_context

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/health", response_model=None)
    def api_health() -> Any:
        return response({"status": "ok"})

    @app.get("/api/v1/version", response_model=None)
    def api_version() -> Any:
        return response({"version": "0.1.0"})

    @app.get("/api/v1/settings/llm", response_model=None)
    def get_llm_settings(http_request: Request) -> Any:
        auth = require_admin(http_request)
        if not hasattr(auth, "user_id"):
            return auth
        return response(as_response_payload(llm_settings_view(llm_client.config)))

    @app.patch("/api/v1/settings/llm", response_model=None)
    def patch_llm_settings(request: LLMSettingsUpdate, http_request: Request) -> Any:
        auth = require_admin(http_request)
        if not hasattr(auth, "user_id"):
            return auth
        llm_client.config = update_llm_settings(llm_client.config, request, settings_path)
        llm_client.close()
        return response(as_response_payload(llm_settings_view(llm_client.config)))

    @app.post("/api/v1/settings/llm/probe", response_model=None)
    def probe_llm_settings(http_request: Request) -> Any:
        auth = require_admin(http_request)
        if not hasattr(auth, "user_id"):
            return auth
        started = monotonic()
        try:
            raw = llm_client.chat(
                "Return one JSON object only.",
                'Health check. Return {"status":"ok"}.',
                timeout_seconds=min(12.0, llm_client.config.timeout_seconds),
            )
            payload = parse_json_payload(raw)
            return response({
                "healthy": payload.get("status") == "ok",
                "latency_ms": round((monotonic() - started) * 1000),
                "model": llm_client.config.model,
                "message": "模型连接正常。",
            })
        except Exception as exc:  # noqa: BLE001
            return response({
                "healthy": False,
                "latency_ms": round((monotonic() - started) * 1000),
                "model": llm_client.config.model,
                "message": str(exc),
            })
