from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from sq_bi_contracts.audit import AuditQuery, AuditRecord


@runtime_checkable
class AuditStore(Protocol):
    """Pluggable append-only audit storage backend."""

    def append(self, record: AuditRecord) -> None: ...

    def query(self, query: AuditQuery) -> list[AuditRecord]: ...

    def get(self, audit_id: str) -> AuditRecord | None: ...


class SQLiteAuditStore:
    """Default audit store backed by SQLite (append-only)."""

    def __init__(self, db_path: str | Path = ".local/audit.sqlite3") -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    audit_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    org_id TEXT NOT NULL,
                    data_source_id TEXT NOT NULL,
                    question TEXT,
                    executed_sql TEXT NOT NULL,
                    sql_fingerprint TEXT,
                    applied_rls_scope TEXT,
                    resolved_metrics TEXT,
                    resolved_skills TEXT,
                    result_row_count INTEGER,
                    duration_ms INTEGER,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def append(self, record: AuditRecord) -> None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                """
                INSERT INTO audit_log (
                    audit_id, request_id, user_id, org_id, data_source_id,
                    question, executed_sql, sql_fingerprint,
                    applied_rls_scope, resolved_metrics, resolved_skills,
                    result_row_count, duration_ms, status, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.audit_id,
                    record.request_id,
                    record.user_id,
                    record.org_id,
                    record.data_source_id,
                    record.question,
                    record.executed_sql,
                    record.sql_fingerprint,
                    ",".join(record.applied_rls_scope) if record.applied_rls_scope else None,
                    ",".join(record.resolved_metrics) if record.resolved_metrics else None,
                    ",".join(record.resolved_skills) if record.resolved_skills else None,
                    record.result_row_count,
                    record.duration_ms,
                    record.status,
                    record.error_message,
                    record.created_at.isoformat() if record.created_at else datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()

    def query(self, query: AuditQuery) -> list[AuditRecord]:
        clauses: list[str] = ["1=1"]
        params: list[object] = []
        if query.request_id:
            clauses.append("request_id = ?")
            params.append(query.request_id)
        if query.user_id:
            clauses.append("user_id = ?")
            params.append(query.user_id)
        if query.org_id:
            clauses.append("org_id = ?")
            params.append(query.org_id)
        if query.data_source_id:
            clauses.append("data_source_id = ?")
            params.append(query.data_source_id)
        if query.status:
            clauses.append("status = ?")
            params.append(query.status)
        if query.start_time:
            clauses.append("created_at >= ?")
            params.append(query.start_time.isoformat())
        if query.end_time:
            clauses.append("created_at <= ?")
            params.append(query.end_time.isoformat())

        offset = (query.page - 1) * query.page_size
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM audit_log WHERE {' AND '.join(clauses)} "
                f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*params, query.page_size, offset],
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get(self, audit_id: str) -> AuditRecord | None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM audit_log WHERE audit_id = ?", (audit_id,)
            ).fetchone()
        return self._row_to_record(row) if row else None

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> AuditRecord:
        return AuditRecord(
            audit_id=str(row["audit_id"]),
            request_id=str(row["request_id"]),
            user_id=str(row["user_id"]),
            org_id=str(row["org_id"]),
            data_source_id=str(row["data_source_id"]),
            question=row["question"],
            executed_sql=str(row["executed_sql"]),
            sql_fingerprint=row["sql_fingerprint"],
            applied_rls_scope=[x for x in (row["applied_rls_scope"] or "").split(",") if x],
            resolved_metrics=[x for x in (row["resolved_metrics"] or "").split(",") if x],
            resolved_skills=[x for x in (row["resolved_skills"] or "").split(",") if x],
            result_row_count=row["result_row_count"],
            duration_ms=row["duration_ms"],
            status=str(row["status"]),
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )
