from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from sq_bi_contracts import ApiResponse, ApiError
from sq_bi_contracts.enums import ErrorCode, MetricVisibility, SkillVisibility
from sq_bi_contracts.catalog import DataSource, SemanticTable, SemanticField
from sq_bi_contracts.metrics import (
    MetricDefinition,
    CreateUserMetricRequest,
)
from sq_bi_contracts.skills import (
    SkillDefinition,
    SkillResolveRequest,
    SkillResolveResult,
)

from .repository import FileBackedSemanticRepository
from .product_repository import (
    DEFAULT_STORE_PATH,
    ChatMessageRecord,
    ChatSessionRecord,
    GeneratedFileRecord,
    MetricDependencyRecord,
    ReportRecord,
    ScheduledJobRecord,
    SQLiteProductRepository,
)

router = APIRouter(prefix="/api/v1")

_repo_instance: FileBackedSemanticRepository | SQLiteProductRepository | None = None


class VisibilityUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: MetricVisibility | SkillVisibility | str
    user_id: str = "anonymous"
    role_ids: list[str] = Field(default_factory=list)


class CopyEntityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = "anonymous"
    role_ids: list[str] = Field(default_factory=list)


class MetricPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = "anonymous"
    role_ids: list[str] = Field(default_factory=list)
    name: str | None = None
    definition: str | None = None
    formula: dict[str, Any] | None = None
    update_frequency: str | None = None
    synonyms: list[str] | None = None
    permission_tags: list[str] | None = None
    execution_contract: dict[str, Any] | None = None
    build_trace: list[dict[str, Any]] | None = None
    validation_evidence: list[dict[str, Any]] | None = None


class SkillPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = "anonymous"
    name: str | None = None
    description: str | None = None
    parameters: list[dict[str, Any]] | None = None
    output_schema: dict[str, Any] | None = None
    permission_tags: list[str] | None = None
    synonyms: list[str] | None = None
    execution_contract: dict[str, Any] | None = None
    build_trace: list[dict[str, Any]] | None = None
    validation_evidence: list[dict[str, Any]] | None = None
    data_source_bindings: list[dict[str, Any]] | None = None


class ReportPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = "anonymous"
    role_ids: list[str] = Field(default_factory=list)
    name: str | None = None
    description: str | None = None
    outputTypes: list[str] | None = None
    channels: list[str] | None = None
    flow: str | None = None
    sections: list[str] | None = None
    analysis_chain: list[dict[str, Any]] | None = None
    tags: list[str] | None = None
    parameters: list[dict[str, Any]] | None = None
    schedule: dict[str, Any] | None = None
    artifact_url: str | None = None
    publish_url: str | None = None
    version: str | None = None
    execution_contract: dict[str, Any] | None = None
    build_trace: list[dict[str, Any]] | None = None
    validation_evidence: list[dict[str, Any]] | None = None
    data_source_bindings: list[dict[str, Any]] | None = None


class GenerateReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = "anonymous"
    output_type: str
    title: str | None = None
    content: str | None = None
    bound_metric_codes: list[str] = []
    bound_skill_ids: list[str] = []


class ScheduledJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = "anonymous"
    entity_type: str
    entity_id: str
    schedule_text: str
    payload: dict[str, Any] = {}


class ChatMessageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = "anonymous"
    text: str
    session_id: str | None = None
    sender: str = "user"
    payload: dict[str, Any] = Field(default_factory=dict)


class ChatSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = "anonymous"
    title: str | None = None


def get_repository() -> FileBackedSemanticRepository | SQLiteProductRepository:
    global _repo_instance
    if _repo_instance is None:
        data_file = Path(__file__).parent.parent.parent / "data" / "tms_semantic.yaml"
        use_sqlite = os.getenv("SQBI_USE_SQLITE_STORE", "1") != "0"
        if use_sqlite:
            store_path = Path(os.getenv("SQBI_STORE_PATH", str(DEFAULT_STORE_PATH)))
            _repo_instance = SQLiteProductRepository(data_file=data_file, store_path=store_path)
        else:
            user_metrics_file = os.getenv("USER_METRICS_FILE")
            _repo_instance = FileBackedSemanticRepository(
                data_file=data_file,
                user_metrics_file=user_metrics_file,
            )
    return _repo_instance


def _req_id() -> str:
    return f"req_{uuid.uuid4().hex[:8]}"


def _api_error(req_id: str, code: ErrorCode, message: str) -> ApiResponse[Any]:
    return ApiResponse(request_id=req_id, error=ApiError(code=code, message=message))


@router.get("/catalog/data-sources", response_model=ApiResponse[list[DataSource]])
def list_data_sources(repo: FileBackedSemanticRepository = Depends(get_repository)) -> ApiResponse[list[DataSource]]:
    req_id = _req_id()
    return ApiResponse(request_id=req_id, data=repo.list_data_sources())


@router.get("/catalog/tables", response_model=ApiResponse[list[SemanticTable]])
def list_tables(
    data_source_id: str | None = None,
    repo: FileBackedSemanticRepository = Depends(get_repository),
) -> ApiResponse[list[SemanticTable]]:
    req_id = _req_id()
    return ApiResponse(request_id=req_id, data=repo.list_tables(data_source_id=data_source_id))


@router.get("/catalog/fields", response_model=ApiResponse[list[SemanticField]])
def list_fields(
    table_id: str | None = None,
    repo: FileBackedSemanticRepository = Depends(get_repository),
) -> ApiResponse[list[SemanticField]]:
    req_id = _req_id()
    return ApiResponse(request_id=req_id, data=repo.list_fields(table_id=table_id))


@router.get("/users/current", response_model=ApiResponse[dict[str, Any]])
def get_current_user(
    request: Request,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[dict[str, Any]]:
    req_id = _req_id()
    if isinstance(repo, SQLiteProductRepository):
        return ApiResponse(request_id=req_id, data=repo.get_current_user())
    # Resolve from request headers or return anonymous fallback
    session_id = request.headers.get("X-Session-Id")
    if session_id:
        from sq_bi_runtime.auth import resolve_user_context as _resolve

        ctx = _resolve(session_id=session_id)
        if ctx is not None:
            return ApiResponse(request_id=req_id, data=ctx.model_dump(mode="json"))
    # Generic anonymous fallback (no hardcoded credentials)
    return ApiResponse(
        request_id=req_id,
        data={
            "user_id": "anonymous",
            "display_name": "Anonymous User",
            "org_id": "default",
            "org_name": "Default Organization",
            "role_ids": ["anonymous"],
            "locale": "zh-CN",
            "timezone": "Asia/Shanghai",
        },
    )


@router.get("/metrics", response_model=ApiResponse[list[MetricDefinition]])
def list_metrics(
    visibility: MetricVisibility | None = None,
    repo: FileBackedSemanticRepository = Depends(get_repository),
) -> ApiResponse[list[MetricDefinition]]:
    req_id = _req_id()
    return ApiResponse(request_id=req_id, data=repo.list_metrics(visibility=visibility))


@router.post("/metrics/user-defined", response_model=ApiResponse[MetricDefinition])
def create_user_metric(
    request: CreateUserMetricRequest,
    repo: FileBackedSemanticRepository = Depends(get_repository),
) -> ApiResponse[MetricDefinition]:
    req_id = _req_id()
    try:
        # Check name conflict with official metrics before generating code
        normalized_name = re.sub(r"\s+", "", request.draft.name).lower()
        for off_metric in repo.official_metrics.values():
            if re.sub(r"\s+", "", off_metric.name).lower() == normalized_name:
                return _api_error(
                    req_id,
                    ErrorCode.CONFLICT,
                    f"Metric name '{request.draft.name}' conflicts with official metric '{off_metric.name}'",
                )

        name_slug = re.sub(r"[^\w\u4e00-\u9fa5-]", "_", request.draft.name).strip("_").lower()
        if not name_slug:
            name_slug = "metric"
        user_slug = re.sub(r"[^\w-]", "_", request.user_id).strip("_").lower() or "anonymous"
        metric_code = f"user_{user_slug}::{name_slug}"

        vis = request.visibility or MetricVisibility.PRIVATE
        metric_def = MetricDefinition(
            metric_code=metric_code,
            name=request.draft.name,
            definition=request.draft.explanation,
            visibility=vis,
            formula=request.draft.formula,
            data_source_id=request.data_source_id,
            owner=request.user_id,
            execution_contract=request.draft.execution_contract,
            build_trace=request.draft.build_trace,
            validation_evidence=request.draft.validation_evidence,
        )

        if request.confirmed_by_user:
            persisted = repo.create_user_metric(metric_def)
            return ApiResponse(request_id=req_id, data=persisted)
        else:
            return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "Metric creation was not confirmed by the user.")
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.CONFLICT, str(exc))


@router.patch("/metrics/{metric_code}", response_model=ApiResponse[MetricDefinition])
def update_metric(
    metric_code: str,
    request: MetricPatchRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[MetricDefinition]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        patch = request.model_dump(exclude={"user_id", "role_ids"}, exclude_none=True)
        return ApiResponse(
            request_id=req_id,
            data=repo.update_metric(metric_code, patch, request.user_id, request.role_ids),
        )
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.patch("/metrics/{metric_code}/visibility", response_model=ApiResponse[MetricDefinition])
def update_metric_visibility(
    metric_code: str,
    request: VisibilityUpdateRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[MetricDefinition]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        visibility = MetricVisibility(str(request.visibility))
        return ApiResponse(
            request_id=req_id,
            data=repo.update_metric_visibility(metric_code, visibility, request.user_id, request.role_ids),
        )
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.get("/metrics/{metric_code}/dependencies", response_model=ApiResponse[list[MetricDependencyRecord]])
def list_metric_dependencies(
    metric_code: str,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[list[MetricDependencyRecord]]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    if repo.get_metric_by_code(metric_code) is None:
        return _api_error(req_id, ErrorCode.NOT_FOUND, "Metric not found.")
    return ApiResponse(request_id=req_id, data=repo.list_metric_dependencies(metric_code))


@router.delete("/metrics/{metric_code}", response_model=ApiResponse[MetricDefinition])
def delete_metric(
    metric_code: str,
    request: CopyEntityRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[MetricDefinition]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        return ApiResponse(request_id=req_id, data=repo.delete_metric(metric_code, request.user_id, request.role_ids))
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.post("/metrics/{metric_code}/copy", response_model=ApiResponse[MetricDefinition])
def copy_metric(
    metric_code: str,
    request: CopyEntityRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[MetricDefinition]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        return ApiResponse(request_id=req_id, data=repo.copy_metric(metric_code, request.user_id))
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.get("/skills", response_model=ApiResponse[list[SkillDefinition]])
def list_skills(
    visibility: SkillVisibility | None = None,
    repo: FileBackedSemanticRepository = Depends(get_repository),
) -> ApiResponse[list[SkillDefinition]]:
    req_id = _req_id()
    return ApiResponse(request_id=req_id, data=repo.list_skills(visibility=visibility))


@router.post("/skills", response_model=ApiResponse[SkillDefinition])
def create_skill(
    request: SkillDefinition,
    user_id: str = Query(default="anonymous"),
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[SkillDefinition]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        return ApiResponse(request_id=req_id, data=repo.create_skill(request, user_id))
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.patch("/skills/{skill_id}", response_model=ApiResponse[SkillDefinition])
def update_skill(
    skill_id: str,
    request: SkillPatchRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[SkillDefinition]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        patch = request.model_dump(exclude={"user_id"}, exclude_none=True)
        return ApiResponse(request_id=req_id, data=repo.update_skill(skill_id, patch, request.user_id))
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.patch("/skills/{skill_id}/visibility", response_model=ApiResponse[SkillDefinition])
def update_skill_visibility(
    skill_id: str,
    request: VisibilityUpdateRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[SkillDefinition]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        visibility = SkillVisibility(str(request.visibility))
        return ApiResponse(request_id=req_id, data=repo.update_skill_visibility(skill_id, visibility, request.user_id))
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.post("/skills/{skill_id}/copy", response_model=ApiResponse[SkillDefinition])
def copy_skill(
    skill_id: str,
    request: CopyEntityRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[SkillDefinition]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        return ApiResponse(request_id=req_id, data=repo.copy_skill(skill_id, request.user_id))
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.delete("/skills/{skill_id}", response_model=ApiResponse[dict[str, str]])
def delete_skill(
    skill_id: str,
    request: CopyEntityRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[dict[str, str]]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        repo.delete_skill(skill_id, request.user_id, request.role_ids)
        return ApiResponse(request_id=req_id, data={"status": "deleted", "skill_id": skill_id})
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.post("/skills/resolve", response_model=ApiResponse[SkillResolveResult])
def resolve_skill(
    request: SkillResolveRequest,
    repo: FileBackedSemanticRepository = Depends(get_repository),
) -> ApiResponse[SkillResolveResult]:
    req_id = _req_id()
    result = repo.resolve_skill(request)
    return ApiResponse(request_id=req_id, data=result)


@router.get("/reports", response_model=ApiResponse[list[ReportRecord]])
def list_reports(
    visibility: str | None = None,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[list[ReportRecord]]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return ApiResponse(request_id=req_id, data=[])
    return ApiResponse(request_id=req_id, data=repo.list_reports(visibility=visibility))


@router.post("/reports", response_model=ApiResponse[ReportRecord])
def create_report(
    request: ReportRecord,
    user_id: str = Query(default="anonymous"),
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[ReportRecord]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        return ApiResponse(request_id=req_id, data=repo.create_report(request, user_id))
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.patch("/reports/{report_id}", response_model=ApiResponse[ReportRecord])
def update_report(
    report_id: str,
    request: ReportPatchRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[ReportRecord]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        patch = request.model_dump(exclude={"user_id", "role_ids"}, exclude_none=True)
        return ApiResponse(request_id=req_id, data=repo.update_report(report_id, patch, request.user_id, request.role_ids))
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.patch("/reports/{report_id}/visibility", response_model=ApiResponse[ReportRecord])
def update_report_visibility(
    report_id: str,
    request: VisibilityUpdateRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[ReportRecord]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        visibility = str(request.visibility)
        if visibility not in {"private", "shared", "official"}:
            raise ValueError("Invalid report visibility.")
        return ApiResponse(request_id=req_id, data=repo.update_report_visibility(report_id, visibility, request.user_id))
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.post("/reports/{report_id}/copy", response_model=ApiResponse[ReportRecord])
def copy_report(
    report_id: str,
    request: CopyEntityRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[ReportRecord]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        return ApiResponse(request_id=req_id, data=repo.copy_report(report_id, request.user_id))
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.delete("/reports/{report_id}", response_model=ApiResponse[dict[str, str]])
def delete_report(
    report_id: str,
    request: CopyEntityRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[dict[str, str]]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        repo.delete_report(report_id, request.user_id, request.role_ids)
        return ApiResponse(request_id=req_id, data={"status": "deleted", "report_id": report_id})
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.post("/reports/{report_id}/generate", response_model=ApiResponse[GeneratedFileRecord])
def generate_report(
    report_id: str,
    request: GenerateReportRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[GeneratedFileRecord]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        generated = repo.generate_report_file(
            report_id,
            user_id=request.user_id,
            output_type=request.output_type,
            title=request.title,
            content=request.content,
            bound_metric_codes=request.bound_metric_codes,
            bound_skill_ids=request.bound_skill_ids,
        )
        return ApiResponse(request_id=req_id, data=generated)
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.get("/files/{file_id}/download", response_model=None)
def download_file(
    file_id: str,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> FileResponse | ApiResponse[Any]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        record, path = repo.get_generated_file(file_id)
        return FileResponse(path, media_type=record.content_type, filename=record.filename)
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))


@router.get("/files/{file_id}/view", response_model=None)
def view_file(
    file_id: str,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> FileResponse | ApiResponse[Any]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        record, path = repo.get_generated_file(file_id)
        return FileResponse(path, media_type=record.content_type)
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))


@router.post("/jobs", response_model=ApiResponse[ScheduledJobRecord])
def create_scheduled_job(
    request: ScheduledJobRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[ScheduledJobRecord]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        job = repo.create_scheduled_job(
            user_id=request.user_id,
            entity_type=request.entity_type,
            entity_id=request.entity_id,
            schedule_text=request.schedule_text,
            payload=request.payload,
        )
        return ApiResponse(request_id=req_id, data=job)
    except ValueError as exc:
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))


@router.patch("/jobs/{job_id}/stop", response_model=ApiResponse[ScheduledJobRecord])
def stop_scheduled_job(
    job_id: str,
    request: CopyEntityRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[ScheduledJobRecord]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        return ApiResponse(request_id=req_id, data=repo.stop_scheduled_job(job_id, request.user_id))
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))


@router.get("/chat/sessions", response_model=ApiResponse[list[ChatSessionRecord]])
def list_chat_sessions(
    user_id: str = Query(default="anonymous"),
    include_archived: bool = Query(default=False),
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[list[ChatSessionRecord]]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return ApiResponse(request_id=req_id, data=[])
    return ApiResponse(request_id=req_id, data=repo.list_chat_sessions(user_id, include_archived=include_archived))


@router.post("/chat/sessions", response_model=ApiResponse[ChatSessionRecord])
def create_chat_session(
    request: ChatSessionCreateRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[ChatSessionRecord]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    return ApiResponse(request_id=req_id, data=repo.create_chat_session(request.user_id, request.title))


@router.patch("/chat/sessions/{session_id}/archive", response_model=ApiResponse[ChatSessionRecord])
def archive_chat_session(
    session_id: str,
    request: CopyEntityRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[ChatSessionRecord]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        return ApiResponse(request_id=req_id, data=repo.archive_chat_session(session_id, request.user_id))
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))


@router.get("/chat/messages", response_model=ApiResponse[list[ChatMessageRecord]])
def list_chat_messages(
    user_id: str = Query(default="anonymous"),
    include_archived: bool = Query(default=False),
    session_id: str | None = Query(default=None),
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[list[ChatMessageRecord]]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return ApiResponse(request_id=req_id, data=[])
    return ApiResponse(request_id=req_id, data=repo.list_chat_messages(user_id, include_archived=include_archived, session_id=session_id))


@router.post("/chat/messages", response_model=ApiResponse[ChatMessageRecord])
def create_chat_message(
    request: ChatMessageCreateRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[ChatMessageRecord]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    if not request.text.strip():
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "Chat message text is required.")
    return ApiResponse(
        request_id=req_id,
        data=repo.create_chat_message(
            request.user_id,
            request.text.strip(),
            request.session_id,
            request.sender,
            request.payload,
        ),
    )


@router.patch("/chat/messages/{message_id}/archive", response_model=ApiResponse[ChatMessageRecord])
def archive_chat_message(
    message_id: str,
    request: CopyEntityRequest,
    repo: FileBackedSemanticRepository | SQLiteProductRepository = Depends(get_repository),
) -> ApiResponse[ChatMessageRecord]:
    req_id = _req_id()
    if not isinstance(repo, SQLiteProductRepository):
        return _api_error(req_id, ErrorCode.VALIDATION_ERROR, "SQLite product store is not enabled.")
    try:
        return ApiResponse(request_id=req_id, data=repo.archive_chat_message(message_id, request.user_id))
    except KeyError as exc:
        return _api_error(req_id, ErrorCode.NOT_FOUND, str(exc))
