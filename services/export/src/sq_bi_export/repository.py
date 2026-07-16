from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import TypeAdapter
from sq_bi_contracts.exports import (
    ExportArtifact,
    ExportAuditRecord,
    ExportJob,
    ShareLink,
    Subscription,
    SubscriptionRun,
)
from sq_bi_contracts.query import QueryResult


_QUERY_RESULTS = TypeAdapter(list[QueryResult])


class SQLiteExportRepository:
    """Durable single-node repository for export jobs and delivery metadata."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def save_job(self, job: ExportJob, *, request_payload: dict[str, Any] | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO export_jobs(job_id, payload, request_payload) VALUES (?, ?, COALESCE(?, (SELECT request_payload FROM export_jobs WHERE job_id = ?)))",
                (
                    job.export_job_id,
                    job.model_dump_json(),
                    json.dumps(request_payload, ensure_ascii=False) if request_payload is not None else None,
                    job.export_job_id,
                ),
            )

    def load_jobs(self) -> list[ExportJob]:
        return [ExportJob.model_validate_json(payload) for payload in self._payloads("export_jobs")]

    def load_pending_requests(self) -> list[tuple[ExportJob, dict[str, Any]]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload, request_payload FROM export_jobs WHERE request_payload IS NOT NULL"
            ).fetchall()
        values: list[tuple[ExportJob, dict[str, Any]]] = []
        for payload, request_payload in rows:
            job = ExportJob.model_validate_json(payload)
            if job.status.value in {"pending", "running"}:
                values.append((job, json.loads(request_payload)))
        return values

    def save_artifact(self, job_id: str, metadata: ExportArtifact, content: bytes) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO artifacts(job_id, metadata, content) VALUES (?, ?, ?)",
                (job_id, metadata.model_dump_json(), content),
            )

    def load_artifacts(self) -> list[tuple[str, ExportArtifact, bytes]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT job_id, metadata, content FROM artifacts").fetchall()
        return [(job_id, ExportArtifact.model_validate_json(metadata), bytes(content)) for job_id, metadata, content in rows]

    def save_snapshots(self, job_id: str, values: list[QueryResult]) -> None:
        self._put_document("snapshots", job_id, _QUERY_RESULTS.dump_json(values).decode())

    def load_snapshots(self) -> dict[str, list[QueryResult]]:
        return {key: _QUERY_RESULTS.validate_json(payload) for key, payload in self._documents("snapshots")}

    def save_share(self, share: ShareLink, salt: bytes | None, password_hash: bytes | None) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO shares(share_id, payload, password_salt, password_hash) VALUES (?, ?, ?, ?)",
                (share.share_id, share.model_dump_json(), salt, password_hash),
            )

    def load_shares(self) -> list[tuple[ShareLink, bytes | None, bytes | None]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload, password_salt, password_hash FROM shares"
            ).fetchall()
        return [(ShareLink.model_validate_json(payload), salt, password_hash) for payload, salt, password_hash in rows]

    def save_subscription(self, value: Subscription) -> None:
        self._put_document("subscriptions", value.subscription_id, value.model_dump_json())

    def load_subscriptions(self) -> list[Subscription]:
        return [Subscription.model_validate_json(payload) for _, payload in self._documents("subscriptions")]

    def save_run(self, value: SubscriptionRun) -> None:
        self._put_document("runs", value.run_id, value.model_dump_json())

    def load_runs(self) -> list[SubscriptionRun]:
        return [SubscriptionRun.model_validate_json(payload) for _, payload in self._documents("runs")]

    def save_audit(self, value: ExportAuditRecord) -> None:
        self._put_document("audits", value.audit_id, value.model_dump_json())

    def load_audits(self) -> list[ExportAuditRecord]:
        return [ExportAuditRecord.model_validate_json(payload) for _, payload in self._documents("audits")]

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS export_jobs (
                    job_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    request_payload TEXT
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    job_id TEXT PRIMARY KEY,
                    metadata TEXT NOT NULL,
                    content BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS shares (
                    share_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    password_salt BLOB,
                    password_hash BLOB
                );
                CREATE TABLE IF NOT EXISTS documents (
                    kind TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY(kind, document_id)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _put_document(self, kind: str, document_id: str, payload: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO documents(kind, document_id, payload) VALUES (?, ?, ?)",
                (kind, document_id, payload),
            )

    def _documents(self, kind: str) -> list[tuple[str, str]]:
        with self._lock, self._connect() as connection:
            return list(connection.execute(
                "SELECT document_id, payload FROM documents WHERE kind = ? ORDER BY rowid",
                (kind,),
            ).fetchall())

    def _payloads(self, table: str) -> list[str]:
        if table != "export_jobs":
            raise ValueError("Unsupported payload table.")
        with self._lock, self._connect() as connection:
            return [row[0] for row in connection.execute("SELECT payload FROM export_jobs ORDER BY rowid")]
