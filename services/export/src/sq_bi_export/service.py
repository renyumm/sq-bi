from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Literal, Protocol, cast
from uuid import uuid4

from sq_bi_contracts.enums import ExportFormat, JobStatus
from sq_bi_contracts.exports import (
    CreateExportRequest,
    CreateShareRequest,
    CreateSubscriptionRequest,
    ExportArtifact,
    ExportAuditRecord,
    ExportDownload,
    ExportJob,
    ExportTemplate,
    ReportSnapshot,
    ShareLink,
    SharePreview,
    ShareVerificationResult,
    Subscription,
    SubscriptionRun,
    UpdateSubscriptionRequest,
    VerifyShareRequest,
)
from sq_bi_contracts.query import QueryResult

from .renderers import render_artifact
from .repository import SQLiteExportRepository


class ExportNotFoundError(Exception):
    pass


class ExportPermissionError(Exception):
    pass


class SummaryProvider(Protocol):
    def summarize(self, query_results: list[QueryResult], report_snapshot: ReportSnapshot | None) -> str:
        """Return a summary using only immutable snapshot data."""


@dataclass(frozen=True)
class _StoredArtifact:
    metadata: ExportArtifact
    content: bytes


@dataclass(frozen=True)
class _StoredShare:
    link: ShareLink
    password_salt: bytes | None
    password_hash: bytes | None


class TemplateRegistry:
    def __init__(self) -> None:
        self._templates: dict[str, ExportTemplate] = {}
        self.register(ExportTemplate(template_id="default-pdf", name="Default PDF", export_format=ExportFormat.PDF))

    def register(self, template: ExportTemplate) -> None:
        self._templates[template.template_id] = template

    def resolve(self, export_format: ExportFormat, template_id: str | None) -> ExportTemplate:
        selected_id = template_id or f"default-{export_format.value}"
        template = self._templates.get(selected_id)
        if template is None:
            raise ValueError(f"Unknown export template: {selected_id}")
        if template.export_format != export_format:
            raise ValueError(f"Template {selected_id} does not support {export_format.value}")
        return template

    def list_templates(self) -> list[ExportTemplate]:
        return list(self._templates.values())


class ExportService:
    def __init__(
        self,
        *,
        template_registry: TemplateRegistry | None = None,
        summary_provider: SummaryProvider | None = None,
        repository: SQLiteExportRepository | None = None,
        worker_count: int = 2,
    ) -> None:
        self._templates = template_registry or TemplateRegistry()
        self._summary_provider = summary_provider
        self._repository = repository
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=max(1, worker_count), thread_name_prefix="sqbi-export")
        self._futures: dict[str, Future[None]] = {}
        self._run_futures: dict[str, Future[None]] = {}
        self._jobs: dict[str, ExportJob] = {}
        self._artifacts_by_job: dict[str, _StoredArtifact] = {}
        self._snapshots_by_job: dict[str, list[QueryResult]] = {}
        self._shares: dict[str, _StoredShare] = {}
        self._subscriptions: dict[str, Subscription] = {}
        self._runs: dict[str, SubscriptionRun] = {}
        self._audit_records: list[ExportAuditRecord] = []
        self._restore()

    def create_export(self, request: CreateExportRequest) -> ExportJob:
        now = _now()
        template = self._templates.resolve(request.export_format, request.template_id)
        query_results = _snapshot_results(request)
        export_job_id = _id("exp")
        job = ExportJob(
            export_job_id=export_job_id,
            requested_by=request.user_id,
            export_format=request.export_format,
            status=JobStatus.PENDING,
            source_query_ids=[result.query_id for result in query_results],
            source_report_skill_id=request.report_snapshot.report_skill_id if request.report_snapshot else None,
            template_id=template.template_id,
            created_at=now,
        )
        with self._lock:
            self._jobs[job.export_job_id] = job
            self._snapshots_by_job[job.export_job_id] = query_results
            if self._repository is not None:
                self._repository.save_job(job, request_payload=request.model_dump(mode="json"))
                self._repository.save_snapshots(job.export_job_id, query_results)
            self._audit(job.export_job_id, request.user_id, "create_export", "pending", {"template_id": template.template_id})
            self._submit(job.export_job_id, request)
        return job

    def wait_for_export(self, export_job_id: str, timeout: float = 10) -> ExportJob:
        future = self._futures.get(export_job_id)
        if future is not None:
            future.result(timeout=timeout)
        return self.get_export(export_job_id)

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)

    def get_export(self, export_job_id: str) -> ExportJob:
        with self._lock:
            try:
                return self._jobs[export_job_id]
            except KeyError as exc:
                raise ExportNotFoundError("Export job not found.") from exc

    def download_export(self, export_job_id: str, *, actor_user_id: str = "anonymous") -> ExportDownload:
        stored = self._artifacts_by_job.get(export_job_id)
        if stored is None:
            raise ExportNotFoundError("Export artifact not found.")
        self._audit(export_job_id, actor_user_id, "download", "succeeded", {"artifact_id": stored.metadata.artifact_id})
        return ExportDownload(
            artifact=stored.metadata,
            content_base64=base64.b64encode(stored.content).decode("ascii"),
        )

    def create_share(self, request: CreateShareRequest) -> ShareLink:
        job = self.get_export(request.export_job_id)
        if job.status != JobStatus.SUCCEEDED:
            raise ValueError("Only succeeded exports can be shared.")
        if request.password is None and not request.allowed_user_ids:
            raise ValueError("CreateShareRequest requires a password or allowed_user_ids.")

        salt: bytes | None = None
        password_hash: bytes | None = None
        if request.password is not None:
            salt, password_hash = _hash_password(request.password.get_secret_value())

        share = ShareLink(
            share_id=_id("shr"),
            created_by=request.user_id,
            export_job_id=request.export_job_id,
            expires_at=request.expires_at,
            requires_password=request.password is not None,
            allowed_user_ids=request.allowed_user_ids,
        )
        self._shares[share.share_id] = _StoredShare(link=share, password_salt=salt, password_hash=password_hash)
        updated_job = job.model_copy(update={"share_id": share.share_id})
        self._jobs[job.export_job_id] = updated_job
        if self._repository is not None:
            self._repository.save_share(share, salt, password_hash)
            self._repository.save_job(updated_job)
        self._audit(job.export_job_id, request.user_id, "create_share", "succeeded", {"share_id": share.share_id})
        return share

    def get_share_preview(self, share_id: str) -> SharePreview:
        stored = self._get_share(share_id)
        self._ensure_share_active(stored.link)
        return self._preview(stored.link)

    def verify_share(self, share_id: str, request: VerifyShareRequest) -> ShareVerificationResult:
        stored = self._get_share(share_id)
        self._ensure_share_active(stored.link)
        if stored.link.allowed_user_ids and request.user_id not in stored.link.allowed_user_ids:
            self._audit(stored.link.export_job_id, request.user_id or "anonymous", "verify_share", "denied", {"share_id": share_id})
            raise ExportPermissionError("User is not allowed to access this share.")
        if stored.link.requires_password:
            password = request.password.get_secret_value() if request.password is not None else ""
            if stored.password_salt is None or stored.password_hash is None:
                raise ExportPermissionError("Share password is not configured.")
            if not _verify_password(password, stored.password_salt, stored.password_hash):
                self._audit(stored.link.export_job_id, request.user_id or "anonymous", "verify_share", "denied", {"share_id": share_id})
                raise ExportPermissionError("Share password verification failed.")
        actor = request.user_id or "anonymous"
        self._audit(stored.link.export_job_id, actor, "verify_share", "succeeded", {"share_id": share_id})
        return ShareVerificationResult(
            share_id=share_id,
            verified=True,
            preview=self._preview(stored.link),
            access_token=_id("sat"),
        )

    def create_subscription(self, request: CreateSubscriptionRequest) -> Subscription:
        next_run_at = calculate_next_run(request.cron, _now()) if request.enabled else None
        subscription = Subscription(
            subscription_id=_id("sub"),
            owner_user_id=request.owner_user_id,
            report_skill_id=request.report_skill_id,
            cron=request.cron,
            channels=request.channels,
            export_format=request.export_format,
            template_id=request.template_id,
            service_principal_id=request.service_principal_id,
            enabled=request.enabled,
            next_run_at=next_run_at,
        )
        self._subscriptions[subscription.subscription_id] = subscription
        if self._repository is not None:
            self._repository.save_subscription(subscription)
        self._audit(subscription.subscription_id, request.owner_user_id, "create_subscription", "succeeded", {"subscription_id": subscription.subscription_id})
        return subscription

    def list_subscriptions(self, *, owner_user_id: str | None = None) -> list[Subscription]:
        subscriptions = list(self._subscriptions.values())
        if owner_user_id is not None:
            subscriptions = [item for item in subscriptions if item.owner_user_id == owner_user_id]
        return subscriptions

    def update_subscription(self, subscription_id: str, request: UpdateSubscriptionRequest) -> Subscription:
        current = self._subscriptions.get(subscription_id)
        if current is None:
            raise ExportNotFoundError("Subscription not found.")
        updates = request.model_dump(exclude_unset=True)
        if "channels" in updates and not updates["channels"]:
            raise ValueError("Subscription channels cannot be empty.")
        candidate = current.model_copy(update=updates)
        next_run_at = calculate_next_run(candidate.cron, _now()) if candidate.enabled else None
        candidate = candidate.model_copy(update={"next_run_at": next_run_at})
        self._subscriptions[subscription_id] = candidate
        if self._repository is not None:
            self._repository.save_subscription(candidate)
        return candidate

    def run_subscription_now(self, subscription_id: str) -> SubscriptionRun:
        subscription = self._subscriptions.get(subscription_id)
        if subscription is None:
            raise ExportNotFoundError("Subscription not found.")
        actor = subscription.service_principal_id or subscription.owner_user_id
        now = _now()
        run = SubscriptionRun(
            run_id=_id("run"),
            subscription_id=subscription.subscription_id,
            actor_user_id=actor,
            status=JobStatus.PENDING,
            export_job_id=None,
            created_at=now,
        )
        self._runs[run.run_id] = run
        if self._repository is not None:
            self._repository.save_run(run)
        self._run_futures[run.run_id] = self._executor.submit(self._process_subscription_run, run.run_id)
        return run

    def get_subscription_run(self, run_id: str) -> SubscriptionRun:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise ExportNotFoundError("Subscription run not found.") from exc

    def wait_for_subscription_run(self, run_id: str, timeout: float = 10) -> SubscriptionRun:
        future = self._run_futures.get(run_id)
        if future is not None:
            future.result(timeout=timeout)
        return self.get_subscription_run(run_id)

    def audit_records(self) -> list[ExportAuditRecord]:
        return list(self._audit_records)

    def _summarize(
        self,
        query_results: list[QueryResult],
        report_snapshot: ReportSnapshot | None,
        integration_gaps: list[str],
    ) -> str | None:
        if self._summary_provider is not None:
            return self._summary_provider.summarize(query_results, report_snapshot)
        existing = [result.summary for result in query_results if result.summary]
        if existing:
            return "\n".join(existing)
        integration_gaps.append("LLM summary provider is not configured; no generated summary was added.")
        return None

    def _get_share(self, share_id: str) -> _StoredShare:
        stored = self._shares.get(share_id)
        if stored is None:
            raise ExportNotFoundError("Share not found.")
        return stored

    def _ensure_share_active(self, share: ShareLink) -> None:
        if share.expires_at is not None and _coerce_utc(share.expires_at) <= _now():
            raise ExportPermissionError("Share link has expired.")

    def _preview(self, share: ShareLink) -> SharePreview:
        job = self.get_export(share.export_job_id)
        columns: list[str] = []
        row_count = 0
        lineage_ids: list[str] = []
        for result in self._source_results_from_job(job):
            for column in result.columns:
                if column not in columns:
                    columns.append(column)
            row_count += len(result.rows)
            lineage_ids.append(result.lineage.lineage_id)
        return SharePreview(
            share_id=share.share_id,
            export_job_id=job.export_job_id,
            export_format=job.export_format,
            summary=job.summary,
            source_query_ids=job.source_query_ids,
            source_report_skill_id=job.source_report_skill_id,
            columns=columns,
            row_count=row_count,
            lineage_ids=lineage_ids,
            artifact=job.artifact,
        )

    def _source_results_from_job(self, job: ExportJob) -> list[QueryResult]:
        return self._snapshots_by_job.get(job.export_job_id, [])

    def _submit(self, export_job_id: str, request: CreateExportRequest) -> None:
        self._futures[export_job_id] = self._executor.submit(self._process_export, export_job_id, request)

    def _process_export(self, export_job_id: str, request: CreateExportRequest) -> None:
        with self._lock:
            current = self._jobs[export_job_id]
            running = current.model_copy(update={"status": JobStatus.RUNNING})
            self._jobs[export_job_id] = running
            if self._repository is not None:
                self._repository.save_job(running)
        try:
            query_results = self._snapshots_by_job[export_job_id]
            integration_gaps: list[str] = []
            summary = self._summarize(query_results, request.report_snapshot, integration_gaps)
            title = request.report_snapshot.title if request.report_snapshot else "SQ-BI Query Export"
            content, content_type = render_artifact(
                request.export_format,
                title,
                query_results,
                request.report_snapshot,
                summary,
            )
            now = _now()
            artifact = ExportArtifact(
                artifact_id=_id("art"),
                export_job_id=export_job_id,
                filename=f"{export_job_id}.{request.export_format.value}",
                content_type=content_type,
                byte_size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                created_at=now,
            )
            succeeded = running.model_copy(update={
                "status": JobStatus.SUCCEEDED,
                "artifact": artifact,
                "summary": summary,
                "integration_gaps": integration_gaps,
                "completed_at": now,
            })
            with self._lock:
                self._jobs[export_job_id] = succeeded
                self._artifacts_by_job[export_job_id] = _StoredArtifact(metadata=artifact, content=content)
                if self._repository is not None:
                    self._repository.save_artifact(export_job_id, artifact, content)
                    self._repository.save_job(succeeded)
                self._audit(export_job_id, request.user_id, "create_export", "succeeded", {"template_id": running.template_id})
        except Exception as exc:  # noqa: BLE001
            failed = running.model_copy(update={
                "status": JobStatus.FAILED,
                "integration_gaps": [str(exc)],
                "completed_at": _now(),
            })
            with self._lock:
                self._jobs[export_job_id] = failed
                if self._repository is not None:
                    self._repository.save_job(failed)
                self._audit(export_job_id, request.user_id, "create_export", "failed", {"error": str(exc)})

    def _restore(self) -> None:
        if self._repository is None:
            return
        self._jobs = {value.export_job_id: value for value in self._repository.load_jobs()}
        self._artifacts_by_job = {
            job_id: _StoredArtifact(metadata=metadata, content=content)
            for job_id, metadata, content in self._repository.load_artifacts()
        }
        self._snapshots_by_job = self._repository.load_snapshots()
        self._shares = {
            link.share_id: _StoredShare(link=link, password_salt=salt, password_hash=password_hash)
            for link, salt, password_hash in self._repository.load_shares()
        }
        self._subscriptions = {
            value.subscription_id: value for value in self._repository.load_subscriptions()
        }
        self._runs = {value.run_id: value for value in self._repository.load_runs()}
        self._audit_records = self._repository.load_audits()
        for job, request_payload in self._repository.load_pending_requests():
            request = CreateExportRequest.model_validate(request_payload)
            self._submit(job.export_job_id, request)
        for run in self._runs.values():
            if run.status in {JobStatus.PENDING, JobStatus.RUNNING}:
                self._run_futures[run.run_id] = self._executor.submit(
                    self._process_subscription_run,
                    run.run_id,
                )

    def _process_subscription_run(self, run_id: str) -> None:
        with self._lock:
            current = self._runs[run_id]
            running = current.model_copy(update={"status": JobStatus.RUNNING})
            self._runs[run_id] = running
            if self._repository is not None:
                self._repository.save_run(running)
        gaps = ["Report snapshot provider is not integrated; subscription run did not create an export."]
        failed = running.model_copy(update={
            "status": JobStatus.FAILED,
            "integration_gaps": gaps,
            "completed_at": _now(),
        })
        with self._lock:
            self._runs[run_id] = failed
            if self._repository is not None:
                self._repository.save_run(failed)
            self._audit(
                _id("subscription"),
                failed.actor_user_id,
                "run_subscription",
                "failed",
                {"subscription_id": failed.subscription_id, "integration_gaps": gaps},
            )

    def _audit(
        self,
        export_job_id: str,
        actor_user_id: str,
        action: str,
        status: str,
        details: dict[str, object] | None = None,
    ) -> None:
        record = ExportAuditRecord(
                audit_id=_id("aud"),
                export_job_id=export_job_id,
                actor_user_id=actor_user_id,
                action=cast(
                    Literal[
                        "create_export",
                        "download",
                        "create_share",
                        "verify_share",
                        "create_subscription",
                        "run_subscription",
                    ],
                    action,
                ),
                status=status,
                created_at=_now(),
                details=details or {},
            )
        self._audit_records.append(record)
        if self._repository is not None:
            self._repository.save_audit(record)


def calculate_next_run(cron: str, after: datetime) -> datetime:
    minute, hour, day, month, weekday = _parse_cron(cron)
    candidate = _coerce_utc(after).replace(second=0, microsecond=0) + timedelta(minutes=1)
    deadline = candidate + timedelta(days=366)
    while candidate <= deadline:
        cron_weekday = (candidate.weekday() + 1) % 7
        if (
            candidate.minute in minute
            and candidate.hour in hour
            and candidate.day in day
            and candidate.month in month
            and cron_weekday in weekday
        ):
            return candidate
        candidate += timedelta(minutes=1)
    raise ValueError("Cron expression has no run time within one year.")


def _snapshot_results(request: CreateExportRequest) -> list[QueryResult]:
    results = list(request.query_snapshots)
    if request.report_snapshot is not None:
        results.extend(request.report_snapshot.query_results)
    if not results:
        raise ValueError("CreateExportRequest requires immutable query or report snapshots.")
    return results


def _parse_cron(cron: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    parts = cron.split()
    if len(parts) != 5:
        raise ValueError("Cron expression must contain five fields.")
    return (
        _parse_field(parts[0], 0, 59),
        _parse_field(parts[1], 0, 23),
        _parse_field(parts[2], 1, 31),
        _parse_field(parts[3], 1, 12),
        _parse_field(parts[4], 0, 7, normalize_seven=True),
    )


def _parse_field(value: str, minimum: int, maximum: int, *, normalize_seven: bool = False) -> set[int]:
    selected: set[int] = set()
    for token in value.split(","):
        if token == "*":
            selected.update(range(minimum, maximum + 1))
        elif token.startswith("*/"):
            step = int(token[2:])
            if step <= 0:
                raise ValueError("Cron step must be positive.")
            selected.update(range(minimum, maximum + 1, step))
        else:
            number = int(token)
            if normalize_seven and number == 7:
                number = 0
            if number < minimum or number > maximum:
                raise ValueError(f"Cron field value {number} is out of range.")
            selected.add(number)
    if normalize_seven:
        selected = {0 if value == 7 else value for value in selected}
    return selected


def _hash_password(password: str) -> tuple[bytes, bytes]:
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return salt, password_hash


def _verify_password(password: str, salt: bytes, expected_hash: bytes) -> bool:
    actual_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return hmac.compare_digest(actual_hash, expected_hash)


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _now() -> datetime:
    return datetime.now(UTC)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"
