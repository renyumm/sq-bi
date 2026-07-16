from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sq_bi_contracts.common import ApiError, ApiResponse
from sq_bi_contracts.enums import ErrorCode
from sq_bi_contracts.exports import (
    CreateExportRequest,
    CreateShareRequest,
    CreateSubscriptionRequest,
    UpdateSubscriptionRequest,
    VerifyShareRequest,
)

from .service import ExportNotFoundError, ExportPermissionError, ExportService
from .repository import SQLiteExportRepository


LOCAL_DEV_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
)


def _request_id() -> str:
    return "req_" + uuid4().hex


def _response(data: Any) -> dict[str, Any]:
    return ApiResponse(request_id=_request_id(), data=data).model_dump(mode="json")


def _error_response(status_code: int, code: ErrorCode, message: str) -> JSONResponse:
    payload = ApiResponse[None](
        request_id=_request_id(),
        error=ApiError(code=code, message=message),
    ).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=payload)


def _handle_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, ExportNotFoundError):
        return _error_response(404, ErrorCode.NOT_FOUND, str(exc))
    if isinstance(exc, ExportPermissionError):
        return _error_response(403, ErrorCode.PERMISSION_DENIED, str(exc))
    if isinstance(exc, ValueError):
        return _error_response(400, ErrorCode.VALIDATION_ERROR, str(exc))
    return _error_response(500, ErrorCode.INTERNAL_ERROR, str(exc))


def create_app(service: ExportService | None = None) -> FastAPI:
    storage_path = Path(os.getenv("SQ_BI_EXPORT_STORAGE_PATH", ".local/export.sqlite3"))
    export_service = service or ExportService(repository=SQLiteExportRepository(storage_path))
    app = FastAPI(title="SQ-BI Export Service")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(LOCAL_DEV_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if hasattr(app, "add_event_handler"):
        app.add_event_handler("shutdown", export_service.close)
    elif hasattr(app.router, "add_event_handler"):
        app.router.add_event_handler("shutdown", export_service.close)
    elif hasattr(app, "on_event"):
        app.on_event("shutdown")(export_service.close)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/health", response_model=None)
    def api_health() -> Any:
        return _response({"status": "ok"})

    @app.get("/api/v1/version", response_model=None)
    def api_version() -> Any:
        return _response({"version": "0.1.0"})

    @app.post("/api/v1/exports", response_model=None)
    def create_export(request: CreateExportRequest) -> Any:
        try:
            return _response(export_service.create_export(request))
        except Exception as exc:  # noqa: BLE001
            return _handle_error(exc)

    @app.get("/api/v1/exports/{export_job_id}", response_model=None)
    def get_export(export_job_id: str) -> Any:
        try:
            return _response(export_service.get_export(export_job_id))
        except Exception as exc:  # noqa: BLE001
            return _handle_error(exc)

    @app.get("/api/v1/exports/{export_job_id}/download", response_model=None)
    def download_export(export_job_id: str, user_id: str = Query(default="anonymous")) -> Any:
        try:
            return _response(export_service.download_export(export_job_id, actor_user_id=user_id))
        except Exception as exc:  # noqa: BLE001
            return _handle_error(exc)

    @app.post("/api/v1/shares", response_model=None)
    def create_share(request: CreateShareRequest) -> Any:
        try:
            return _response(export_service.create_share(request))
        except Exception as exc:  # noqa: BLE001
            return _handle_error(exc)

    @app.get("/api/v1/shares/{share_id}", response_model=None)
    def get_share(share_id: str) -> Any:
        try:
            return _response(export_service.get_share_preview(share_id))
        except Exception as exc:  # noqa: BLE001
            return _handle_error(exc)

    @app.post("/api/v1/shares/{share_id}/verify", response_model=None)
    def verify_share(share_id: str, request: VerifyShareRequest) -> Any:
        try:
            return _response(export_service.verify_share(share_id, request))
        except Exception as exc:  # noqa: BLE001
            return _handle_error(exc)

    @app.post("/api/v1/subscriptions", response_model=None)
    def create_subscription(request: CreateSubscriptionRequest) -> Any:
        try:
            return _response(export_service.create_subscription(request))
        except Exception as exc:  # noqa: BLE001
            return _handle_error(exc)

    @app.get("/api/v1/subscriptions", response_model=None)
    def list_subscriptions(owner_user_id: str | None = None) -> Any:
        try:
            return _response(export_service.list_subscriptions(owner_user_id=owner_user_id))
        except Exception as exc:  # noqa: BLE001
            return _handle_error(exc)

    @app.patch("/api/v1/subscriptions/{subscription_id}", response_model=None)
    def update_subscription(subscription_id: str, request: UpdateSubscriptionRequest) -> Any:
        try:
            return _response(export_service.update_subscription(subscription_id, request))
        except Exception as exc:  # noqa: BLE001
            return _handle_error(exc)

    @app.post("/api/v1/subscriptions/{subscription_id}/run-now", response_model=None)
    def run_subscription_now(subscription_id: str) -> Any:
        try:
            return _response(export_service.run_subscription_now(subscription_id))
        except Exception as exc:  # noqa: BLE001
            return _handle_error(exc)

    @app.get("/api/v1/subscriptions/runs/{run_id}", response_model=None)
    def get_subscription_run(run_id: str) -> Any:
        try:
            return _response(export_service.get_subscription_run(run_id))
        except Exception as exc:  # noqa: BLE001
            return _handle_error(exc)

    return app


app = create_app()
