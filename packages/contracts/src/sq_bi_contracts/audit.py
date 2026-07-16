from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import ContractModel


class AuditRecord(ContractModel):
    """Append-only record of one query execution."""

    audit_id: str
    request_id: str
    user_id: str
    org_id: str
    data_source_id: str
    question: str | None = None
    executed_sql: str
    sql_fingerprint: str | None = None
    applied_rls_scope: list[str] = Field(default_factory=list)
    resolved_metrics: list[str] = Field(default_factory=list)
    resolved_skills: list[str] = Field(default_factory=list)
    result_row_count: int | None = None
    duration_ms: int | None = None
    status: str  # "success" | "error" | "rejected"
    error_message: str | None = None
    created_at: datetime


class AuditQuery(ContractModel):
    """Filter / pagination parameters for querying audit records."""

    request_id: str | None = None
    user_id: str | None = None
    org_id: str | None = None
    data_source_id: str | None = None
    status: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    page: int = 1
    page_size: int = 50
