from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest

from sq_bi_contracts.enums import ChartType
from sq_bi_contracts.exports import (
    CreateExportRequest,
    CreateShareRequest,
    CreateSubscriptionRequest,
    UpdateSubscriptionRequest,
    VerifyShareRequest,
)
from sq_bi_contracts.query import ChartSuggestion, Lineage, QueryResult
from sq_bi_export.service import ExportPermissionError, ExportService
from sq_bi_export.repository import SQLiteExportRepository


def _query_result() -> QueryResult:
    return QueryResult(
        query_id="qry_1",
        audit_id="aud_1",
        columns=["factory", "otd_rate"],
        rows=[["Tianjin", 98.2], ["Suzhou", 96.8]],
        chart_suggestion=ChartSuggestion(chart_type=ChartType.BAR, title="OTD"),
        lineage=Lineage(
            lineage_id="lin_1",
            source_system="TMS_SAMPLE",
            data_source_id="ds_tms",
            metric_codes=["OTD_RATE"],
            physical_tables=["fact_delivery"],
            physical_fields=["factory", "otd_rate"],
            executed_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )


def test_create_export_downloads_pdf_with_lineage() -> None:
    service = ExportService()
    pending = service.create_export(
        CreateExportRequest(
            user_id="u1",
            export_format="pdf",
            query_snapshots=[_query_result()],
        )
    )
    assert pending.status in {"pending", "running"}
    job = service.wait_for_export(pending.export_job_id)

    assert job.status == "succeeded"
    assert job.source_query_ids == ["qry_1"]
    assert job.artifact is not None
    assert job.artifact.byte_size > 0
    assert job.integration_gaps == ["LLM summary provider is not configured; no generated summary was added."]

    downloaded = service.download_export(job.export_job_id, actor_user_id="u1")
    content = base64.b64decode(downloaded.content_base64).decode("utf-8", errors="ignore")
    assert "lin_1" in content
    assert "factory, otd_rate" in content


def test_share_preview_and_password_verification_do_not_expose_rows() -> None:
    service = ExportService()
    pending = service.create_export(
        CreateExportRequest(user_id="u1", export_format="pdf", query_snapshots=[_query_result()])
    )
    job = service.wait_for_export(pending.export_job_id)
    share = service.create_share(
        CreateShareRequest(user_id="u1", export_job_id=job.export_job_id, password="secret")
    )

    preview = service.get_share_preview(share.share_id)
    assert preview.columns == ["factory", "otd_rate"]
    assert preview.row_count == 2
    assert preview.lineage_ids == ["lin_1"]
    assert not hasattr(preview, "rows")

    with pytest.raises(ExportPermissionError):
        service.verify_share(share.share_id, VerifyShareRequest(password="bad"))

    verified = service.verify_share(share.share_id, VerifyShareRequest(password="secret"))
    assert verified.verified is True
    assert verified.access_token is not None
    assert verified.access_token.startswith("sat_")


def test_subscription_next_run_and_run_now_records_gap() -> None:
    service = ExportService()
    subscription = service.create_subscription(
        CreateSubscriptionRequest(
            owner_user_id="u1",
            report_skill_id="rpt_1",
            cron="*/15 * * * *",
            channels=["email"],
            service_principal_id="sp_export",
        )
    )
    assert subscription.next_run_at is not None

    updated = service.update_subscription(subscription.subscription_id, UpdateSubscriptionRequest(enabled=False))
    assert updated.next_run_at is None

    pending_run = service.run_subscription_now(subscription.subscription_id)
    assert pending_run.status in {"pending", "running"}
    run = service.wait_for_subscription_run(pending_run.run_id)
    assert run.actor_user_id == "sp_export"
    assert run.status == "failed"
    assert run.export_job_id is None
    assert run.integration_gaps


def test_jobs_artifacts_shares_and_subscriptions_survive_restart(tmp_path) -> None:
    repository = SQLiteExportRepository(tmp_path / "export.sqlite3")
    first = ExportService(repository=repository)
    pending = first.create_export(
        CreateExportRequest(user_id="u1", export_format="pdf", query_snapshots=[_query_result()])
    )
    job = first.wait_for_export(pending.export_job_id)
    share = first.create_share(
        CreateShareRequest(user_id="u1", export_job_id=job.export_job_id, password="secret")
    )
    subscription = first.create_subscription(
        CreateSubscriptionRequest(
            owner_user_id="u1",
            report_skill_id="rpt_1",
            cron="0 8 * * *",
            channels=["email"],
        )
    )
    pending_run = first.run_subscription_now(subscription.subscription_id)
    run = first.wait_for_subscription_run(pending_run.run_id)
    first.close()

    restored = ExportService(repository=SQLiteExportRepository(tmp_path / "export.sqlite3"))
    assert restored.get_export(job.export_job_id).status == "succeeded"
    assert restored.download_export(job.export_job_id).artifact.sha256 == job.artifact.sha256
    assert restored.verify_share(share.share_id, VerifyShareRequest(password="secret")).verified
    assert [item.subscription_id for item in restored.list_subscriptions()] == [subscription.subscription_id]
    assert restored.get_subscription_run(run.run_id).status == "failed"
    restored.close()
