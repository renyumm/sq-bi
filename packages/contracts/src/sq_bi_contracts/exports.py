from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, SecretStr, model_validator

from .common import ContractModel
from .enums import ExportFormat, JobStatus
from .query import QueryResult


class ExportTemplate(ContractModel):
    template_id: str
    name: str
    export_format: ExportFormat
    version: str = "1"
    description: str | None = None


class ReportSnapshot(ContractModel):
    report_skill_id: str
    title: str
    generated_by: str
    generated_at: datetime
    parameters: dict[str, object] = Field(default_factory=dict)
    query_results: list[QueryResult] = Field(min_length=1)


class ExportArtifact(ContractModel):
    artifact_id: str
    export_job_id: str
    filename: str
    content_type: str
    byte_size: int = Field(ge=0)
    sha256: str
    created_at: datetime


class ExportAuditRecord(ContractModel):
    audit_id: str
    export_job_id: str
    actor_user_id: str
    action: Literal["create_export", "download", "create_share", "verify_share", "create_subscription", "run_subscription"]
    status: str
    created_at: datetime
    details: dict[str, object] = Field(default_factory=dict)


class ExportJob(ContractModel):
    export_job_id: str
    requested_by: str
    export_format: ExportFormat
    status: JobStatus
    source_query_ids: list[str] = Field(default_factory=list)
    source_report_skill_id: str | None = None
    template_id: str | None = None
    share_id: str | None = None
    artifact: ExportArtifact | None = None
    summary: str | None = None
    integration_gaps: list[str] = Field(default_factory=list)
    created_at: datetime
    completed_at: datetime | None = None


class CreateExportRequest(ContractModel):
    user_id: str
    export_format: ExportFormat
    query_snapshots: list[QueryResult] = Field(default_factory=list)
    report_snapshot: ReportSnapshot | None = None
    template_id: str | None = None

    @model_validator(mode="after")
    def requires_immutable_snapshot(self) -> "CreateExportRequest":
        if not self.query_snapshots and self.report_snapshot is None:
            raise ValueError("CreateExportRequest requires query_snapshots or report_snapshot.")
        return self


class ExportDownload(ContractModel):
    artifact: ExportArtifact
    content_base64: str


class CreateShareRequest(ContractModel):
    user_id: str
    export_job_id: str
    expires_at: datetime | None = None
    password: SecretStr | None = None
    allowed_user_ids: list[str] = Field(default_factory=list)


class ShareLink(ContractModel):
    share_id: str
    created_by: str
    export_job_id: str
    expires_at: datetime | None = None
    requires_password: bool = True
    allowed_user_ids: list[str] = Field(default_factory=list)


class SharePreview(ContractModel):
    share_id: str
    export_job_id: str
    export_format: ExportFormat
    summary: str | None = None
    source_query_ids: list[str] = Field(default_factory=list)
    source_report_skill_id: str | None = None
    columns: list[str] = Field(default_factory=list)
    row_count: int = 0
    lineage_ids: list[str] = Field(default_factory=list)
    artifact: ExportArtifact | None = None


class VerifyShareRequest(ContractModel):
    user_id: str | None = None
    password: SecretStr | None = None


class ShareVerificationResult(ContractModel):
    share_id: str
    verified: bool
    preview: SharePreview | None = None
    access_token: str | None = None


class CreateSubscriptionRequest(ContractModel):
    owner_user_id: str
    report_skill_id: str
    cron: str
    channels: list[str] = Field(min_length=1)
    export_format: ExportFormat = ExportFormat.PDF
    template_id: str | None = None
    service_principal_id: str | None = None
    enabled: bool = True


class UpdateSubscriptionRequest(ContractModel):
    cron: str | None = None
    channels: list[str] | None = None
    export_format: ExportFormat | None = None
    template_id: str | None = None
    enabled: bool | None = None


class Subscription(ContractModel):
    subscription_id: str
    owner_user_id: str
    report_skill_id: str
    cron: str
    channels: list[str]
    export_format: ExportFormat = ExportFormat.PDF
    template_id: str | None = None
    service_principal_id: str | None = None
    enabled: bool = True
    next_run_at: datetime | None = None


class SubscriptionRun(ContractModel):
    run_id: str
    subscription_id: str
    actor_user_id: str
    status: JobStatus
    export_job_id: str | None = None
    integration_gaps: list[str] = Field(default_factory=list)
    created_at: datetime
    completed_at: datetime | None = None
