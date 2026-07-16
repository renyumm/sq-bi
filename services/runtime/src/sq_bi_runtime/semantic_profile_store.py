"""SQLite-backed store for the database semantic profile.

Schema
------
  snapshots      — versioned scan results per data source
  semantic_spaces — clustered business spaces, one per snapshot
  semantic_entities — physical-table semantic entity in a space
  semantic_fields   — column-level semantic facts, keyed by entity
  evidence        — evidence items per field (multi-source)
  scan_jobs       — async scan tracking (scan_id → status)
  ds_documents    — uploaded data-dictionary files per data source
  catalog_tables  — every scanned physical table, ground truth independent
                    of whatever the LLM discovery pass chose to cluster
  catalog_columns — every scanned physical column, keyed by catalog_table
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sq_bi_contracts.semantic_profile import (
    CatalogColumnRecord,
    CatalogOverview,
    CatalogTableRecord,
    DataSourceDocument,
    EvidenceItem,
    EvidenceSource,
    FieldOrigin,
    ProfileView,
    ScanPhase,
    ScanStatus,
    SchemaSnapshot,
    SemanticEntity,
    SemanticField,
    SemanticSpace,
    SemanticSpaceAdjustment,
    SemanticSpaceVersionState,
    TableRecommendation,
)
from sq_bi_contracts.semantic_space import ChangedFieldEntry, SemanticGapCandidate, SemanticSpaceDiff

from .schema_scanner import TableMeta

logger = logging.getLogger(__name__)


class SemanticProfileStore:
    """Persists and retrieves the database semantic profile for each data source."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._lock = threading.Lock()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"Cannot create semantic-profile store directory {self._path.parent}: {exc}"
            ) from exc
        self._init_db()

    # ── Init ──────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    data_source_id TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    scanned_schemas TEXT NOT NULL DEFAULT '[]',
                    table_count INTEGER NOT NULL DEFAULT 0,
                    included_table_count INTEGER NOT NULL DEFAULT 0,
                    excluded_table_count INTEGER NOT NULL DEFAULT 0,
                    recommendation_counts TEXT NOT NULL DEFAULT '{}',
                    scan_phase TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT,
                    completed_at TEXT,
                    error TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_ds_version
                ON snapshots (data_source_id, version);

                CREATE TABLE IF NOT EXISTS scan_jobs (
                    scan_id TEXT PRIMARY KEY,
                    data_source_id TEXT NOT NULL,
                    snapshot_id TEXT REFERENCES snapshots(snapshot_id),
                    phase TEXT NOT NULL DEFAULT 'pending',
                    progress_message TEXT,
                    table_count INTEGER NOT NULL DEFAULT 0,
                    included_table_count INTEGER NOT NULL DEFAULT 0,
                    recommendation_counts TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT,
                    completed_at TEXT,
                    error TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_scan_jobs_ds
                ON scan_jobs (data_source_id);

                CREATE TABLE IF NOT EXISTS semantic_spaces (
                    space_id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
                    name TEXT NOT NULL,
                    description TEXT,
                    accepted INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_spaces_snapshot
                ON semantic_spaces (snapshot_id);

                CREATE TABLE IF NOT EXISTS semantic_entities (
                    entity_id TEXT PRIMARY KEY,
                    space_id TEXT NOT NULL REFERENCES semantic_spaces(space_id),
                    snapshot_id TEXT NOT NULL,
                    physical_table TEXT NOT NULL,
                    business_name TEXT NOT NULL,
                    description TEXT,
                    recommendation TEXT NOT NULL DEFAULT 'recommended_include'
                );

                CREATE INDEX IF NOT EXISTS idx_entities_space
                ON semantic_entities (space_id);

                CREATE TABLE IF NOT EXISTS semantic_fields (
                    field_id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL REFERENCES semantic_entities(entity_id),
                    physical_table TEXT NOT NULL,
                    physical_column TEXT NOT NULL,
                    business_name TEXT NOT NULL,
                    description TEXT,
                    data_type TEXT,
                    origin TEXT NOT NULL DEFAULT 'inferred',
                    semantic_role TEXT,
                    default_aggregation TEXT,
                    synonyms TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    physical_reference TEXT,
                    is_candidate INTEGER NOT NULL DEFAULT 0,
                    CHECK (confidence >= 0.0 AND confidence <= 1.0)
                );

                CREATE INDEX IF NOT EXISTS idx_fields_entity
                ON semantic_fields (entity_id);

                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY,
                    field_id TEXT NOT NULL REFERENCES semantic_fields(field_id),
                    source TEXT NOT NULL,
                    detail TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_evidence_field
                ON evidence (field_id);

                CREATE TABLE IF NOT EXISTS ds_documents (
                    document_id TEXT PRIMARY KEY,
                    data_source_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL DEFAULT 0,
                    upload_status TEXT NOT NULL DEFAULT 'pending',
                    uploaded_at TEXT,
                    error TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_docs_ds
                ON ds_documents (data_source_id);

                CREATE TABLE IF NOT EXISTS semantic_space_versions (
                    version_id TEXT PRIMARY KEY,
                    space_id TEXT NOT NULL REFERENCES semantic_spaces(space_id),
                    version INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    published_by TEXT,
                    published_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_space_versions
                ON semantic_space_versions (space_id, version);

                CREATE TABLE IF NOT EXISTS catalog_tables (
                    catalog_table_id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
                    schema_name TEXT,
                    table_name TEXT NOT NULL,
                    table_type TEXT NOT NULL DEFAULT 'table',
                    comment TEXT,
                    row_count_estimate INTEGER,
                    classification TEXT NOT NULL DEFAULT 'recommended_include',
                    excluded INTEGER NOT NULL DEFAULT 0,
                    excluded_reason TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_catalog_tables_snapshot
                ON catalog_tables (snapshot_id);

                CREATE TABLE IF NOT EXISTS catalog_columns (
                    catalog_column_id TEXT PRIMARY KEY,
                    catalog_table_id TEXT NOT NULL REFERENCES catalog_tables(catalog_table_id),
                    column_name TEXT NOT NULL,
                    data_type TEXT,
                    comment TEXT,
                    nullable INTEGER NOT NULL DEFAULT 1,
                    is_pk INTEGER NOT NULL DEFAULT 0,
                    is_fk INTEGER NOT NULL DEFAULT 0,
                    has_index INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_catalog_columns_table
                ON catalog_columns (catalog_table_id);
            """)
            self._migrate_space_versioning(conn)
        logger.info("semantic_profile_store.init", extra={"db_path": str(self._path)})

    def _migrate_space_versioning(self, conn: sqlite3.Connection) -> None:
        """Add the semantic-space-management overlay columns to older DBs.

        SQLite has no ``ADD COLUMN IF NOT EXISTS``; each statement is retried
        and the "duplicate column" error is swallowed so this is idempotent.
        """
        for stmt in (
            "ALTER TABLE semantic_spaces ADD COLUMN version INTEGER",
            "ALTER TABLE semantic_spaces ADD COLUMN version_state TEXT",
            "ALTER TABLE semantic_spaces ADD COLUMN created_at TEXT",
            "ALTER TABLE semantic_spaces ADD COLUMN published_at TEXT",
            "ALTER TABLE semantic_fields ADD COLUMN status TEXT",
        ):
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already present

    # ── Scan jobs ────────────────────────────────────────────────────

    def create_scan_job(self, data_source_id: str) -> ScanStatus:
        scan_id = f"scan_{uuid4().hex[:16]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                """
                INSERT INTO scan_jobs (scan_id, data_source_id, phase, started_at)
                VALUES (?, ?, 'pending', ?)
                """,
                (scan_id, data_source_id, now),
            )
            conn.commit()
        return ScanStatus(
            scan_id=scan_id,
            data_source_id=data_source_id,
            phase=ScanPhase.pending,
            started_at=now,
        )

    def update_scan_job(
        self,
        scan_id: str,
        phase: ScanPhase,
        *,
        snapshot_id: str | None = None,
        progress_message: str | None = None,
        table_count: int = 0,
        included_table_count: int = 0,
        recommendation_counts: dict[str, int] | None = None,
        error: str | None = None,
    ) -> ScanStatus | None:
        completed_at = None
        if phase in (ScanPhase.done, ScanPhase.failed):
            completed_at = datetime.now(timezone.utc).isoformat()
        counts_json = json.dumps(recommendation_counts or {})
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                UPDATE scan_jobs SET
                    phase=?, snapshot_id=?, progress_message=?,
                    table_count=?, included_table_count=?,
                    recommendation_counts=?,
                    completed_at=COALESCE(?, completed_at),
                    error=?
                WHERE scan_id=?
                """,
                (
                    phase.value, snapshot_id, progress_message,
                    table_count, included_table_count,
                    counts_json, completed_at, error,
                    scan_id,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM scan_jobs WHERE scan_id=?", (scan_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_scan_status(row)

    def get_scan_status(self, scan_id: str) -> ScanStatus | None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM scan_jobs WHERE scan_id=?", (scan_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_scan_status(row)

    def _row_to_scan_status(self, row: sqlite3.Row) -> ScanStatus:
        return ScanStatus(
            scan_id=row["scan_id"],
            data_source_id=row["data_source_id"],
            snapshot_id=row["snapshot_id"],
            phase=ScanPhase(row["phase"]),
            progress_message=row["progress_message"],
            table_count=row["table_count"] or 0,
            included_table_count=row["included_table_count"] or 0,
            recommendation_counts=json.loads(row["recommendation_counts"] or "{}"),
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            error=row["error"],
        )

    # ── Snapshots ────────────────────────────────────────────────────

    def create_snapshot(self, data_source_id: str) -> SchemaSnapshot:
        """Create a new snapshot version for this data source."""
        snapshot_id = f"snap_{uuid4().hex[:16]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            row = conn.execute(
                "SELECT MAX(version) as v FROM snapshots WHERE data_source_id=?",
                (data_source_id,),
            ).fetchone()
            version = (row[0] or 0) + 1
            conn.execute(
                """
                INSERT INTO snapshots
                    (snapshot_id, data_source_id, version, scan_phase, created_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (snapshot_id, data_source_id, version, now),
            )
            conn.commit()
        return SchemaSnapshot(
            snapshot_id=snapshot_id,
            data_source_id=data_source_id,
            version=version,
            scan_phase=ScanPhase.pending,
            created_at=now,
        )

    def update_snapshot(
        self,
        snapshot_id: str,
        *,
        scan_phase: ScanPhase,
        scanned_schemas: list[str] | None = None,
        table_count: int = 0,
        included_table_count: int = 0,
        excluded_table_count: int = 0,
        recommendation_counts: dict[str, int] | None = None,
        error: str | None = None,
    ) -> None:
        completed_at = None
        if scan_phase in (ScanPhase.done, ScanPhase.failed):
            completed_at = datetime.now(timezone.utc).isoformat()
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                """
                UPDATE snapshots SET
                    scan_phase=?,
                    scanned_schemas=?,
                    table_count=?,
                    included_table_count=?,
                    excluded_table_count=?,
                    recommendation_counts=?,
                    completed_at=COALESCE(?, completed_at),
                    error=?
                WHERE snapshot_id=?
                """,
                (
                    scan_phase.value,
                    json.dumps(scanned_schemas or []),
                    table_count,
                    included_table_count,
                    excluded_table_count,
                    json.dumps(recommendation_counts or {}),
                    completed_at,
                    error,
                    snapshot_id,
                ),
            )
            conn.commit()

    def get_latest_snapshot(self, data_source_id: str) -> SchemaSnapshot | None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM snapshots
                WHERE data_source_id=?
                ORDER BY version DESC LIMIT 1
                """,
                (data_source_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_snapshot(row)

    def get_snapshot(self, snapshot_id: str) -> SchemaSnapshot | None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_snapshot(row)

    def _row_to_snapshot(self, row: sqlite3.Row) -> SchemaSnapshot:
        return SchemaSnapshot(
            snapshot_id=row["snapshot_id"],
            data_source_id=row["data_source_id"],
            version=row["version"],
            scanned_schemas=json.loads(row["scanned_schemas"] or "[]"),
            table_count=row["table_count"] or 0,
            included_table_count=row["included_table_count"] or 0,
            excluded_table_count=row["excluded_table_count"] or 0,
            recommendation_counts=json.loads(row["recommendation_counts"] or "{}"),
            scan_phase=ScanPhase(row["scan_phase"]),
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            error=row["error"],
        )

    # ── Whole-database catalog (ground truth, independent of LLM clustering) ──

    def save_catalog(self, snapshot_id: str, tables: list[TableMeta]) -> None:
        """Persist every scanned table/column for this snapshot.

        Unlike ``save_spaces`` (which only stores whatever the LLM discovery
        pass chose to cluster), this is the full scan result — the ground
        truth used for catalog overview, scope validation, and semantic-gap
        detection against tables/columns the LLM never mentioned.
        """
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                "DELETE FROM catalog_columns WHERE catalog_table_id IN "
                "(SELECT catalog_table_id FROM catalog_tables WHERE snapshot_id=?)",
                (snapshot_id,),
            )
            conn.execute("DELETE FROM catalog_tables WHERE snapshot_id=?", (snapshot_id,))
            for table in tables:
                table_id = f"ctbl_{uuid4().hex[:16]}"
                conn.execute(
                    """
                    INSERT INTO catalog_tables
                        (catalog_table_id, snapshot_id, schema_name, table_name, table_type,
                         comment, row_count_estimate, classification, excluded, excluded_reason)
                    VALUES (?, ?, ?, ?, 'table', ?, ?, ?, ?, ?)
                    """,
                    (
                        table_id, snapshot_id, table.schema, table.name,
                        table.comment, table.row_count_approx, table.recommendation.value,
                        int(table.excluded), table.excluded_reason,
                    ),
                )
                for col in table.columns:
                    conn.execute(
                        """
                        INSERT INTO catalog_columns
                            (catalog_column_id, catalog_table_id, column_name, data_type,
                             comment, nullable, is_pk, is_fk, has_index)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"ccol_{uuid4().hex[:16]}", table_id, col.name, col.data_type,
                            col.comment, int(col.nullable), int(col.is_pk), int(col.is_fk),
                            int(col.has_index),
                        ),
                    )
            conn.commit()

    def _load_catalog_tables(
        self, conn: sqlite3.Connection, snapshot_id: str
    ) -> list[CatalogTableRecord]:
        conn.row_factory = sqlite3.Row
        table_rows = conn.execute(
            "SELECT * FROM catalog_tables WHERE snapshot_id=? ORDER BY rowid", (snapshot_id,)
        ).fetchall()
        tables: list[CatalogTableRecord] = []
        for row in table_rows:
            col_rows = conn.execute(
                "SELECT * FROM catalog_columns WHERE catalog_table_id=? ORDER BY rowid",
                (row["catalog_table_id"],),
            ).fetchall()
            columns = [
                CatalogColumnRecord(
                    schema_name=row["schema_name"],
                    table_name=row["table_name"],
                    column_name=c["column_name"],
                    data_type=c["data_type"],
                    comment=c["comment"],
                    nullable=bool(c["nullable"]),
                    is_pk=bool(c["is_pk"]),
                    is_fk=bool(c["is_fk"]),
                    has_index=bool(c["has_index"]),
                )
                for c in col_rows
            ]
            tables.append(
                CatalogTableRecord(
                    schema_name=row["schema_name"],
                    table_name=row["table_name"],
                    table_type=row["table_type"],
                    comment=row["comment"],
                    row_count_estimate=row["row_count_estimate"],
                    classification=TableRecommendation(row["classification"]),
                    excluded=bool(row["excluded"]),
                    excluded_reason=row["excluded_reason"],
                    columns=columns,
                )
            )
        return tables

    def list_catalog_tables(self, data_source_id: str) -> list[CatalogTableRecord]:
        """Every scanned table/column for a data source's latest snapshot."""
        snapshot = self.get_latest_snapshot(data_source_id)
        if not snapshot:
            return []
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            return self._load_catalog_tables(conn, snapshot.snapshot_id)

    def get_catalog_overview(self, data_source_id: str) -> CatalogOverview | None:
        snapshot = self.get_latest_snapshot(data_source_id)
        if not snapshot:
            return None
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            tables = self._load_catalog_tables(conn, snapshot.snapshot_id)
            column_count = sum(len(t.columns) for t in tables)

        schema_names = {t.schema_name for t in tables if t.schema_name}
        excluded_tables = [t for t in tables if t.excluded]
        suspected_business_tables = [
            t for t in tables
            if not t.excluded and t.classification == TableRecommendation.recommended_include
        ]
        return CatalogOverview(
            data_source_id=data_source_id,
            snapshot_id=snapshot.snapshot_id,
            version=snapshot.version,
            schema_count=len(schema_names) or len(snapshot.scanned_schemas),
            table_count=len(tables),
            column_count=column_count,
            included_table_count=len(tables) - len(excluded_tables),
            excluded_table_count=len(excluded_tables),
            excluded_tables=excluded_tables,
            suspected_business_tables=suspected_business_tables,
            recommendation_counts=snapshot.recommendation_counts,
            scan_phase=snapshot.scan_phase,
            created_at=snapshot.created_at,
        )

    # ── Spaces, Entities, Fields ──────────────────────────────────────

    def save_spaces(
        self, snapshot_id: str, spaces: list[SemanticSpace]
    ) -> None:
        """Persist a list of spaces (with nested entities and fields) for a snapshot."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                "DELETE FROM evidence WHERE field_id IN "
                "(SELECT f.field_id FROM semantic_fields f "
                " JOIN semantic_entities e ON f.entity_id=e.entity_id "
                " JOIN semantic_spaces s ON e.space_id=s.space_id "
                " WHERE s.snapshot_id=?)",
                (snapshot_id,),
            )
            conn.execute(
                "DELETE FROM semantic_fields WHERE entity_id IN "
                "(SELECT e.entity_id FROM semantic_entities e "
                " JOIN semantic_spaces s ON e.space_id=s.space_id "
                " WHERE s.snapshot_id=?)",
                (snapshot_id,),
            )
            conn.execute(
                "DELETE FROM semantic_entities WHERE space_id IN "
                "(SELECT space_id FROM semantic_spaces WHERE snapshot_id=?)",
                (snapshot_id,),
            )
            conn.execute(
                "DELETE FROM semantic_spaces WHERE snapshot_id=?", (snapshot_id,)
            )

            for space in spaces:
                conn.execute(
                    """
                    INSERT INTO semantic_spaces
                        (space_id, snapshot_id, name, description, accepted)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (space.space_id, snapshot_id, space.name,
                     space.description, int(space.accepted)),
                )
                for entity in space.entities:
                    conn.execute(
                        """
                        INSERT INTO semantic_entities
                            (entity_id, space_id, snapshot_id, physical_table,
                             business_name, description, recommendation)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (entity.entity_id, space.space_id, snapshot_id,
                         entity.physical_table, entity.business_name,
                         entity.description, entity.recommendation.value),
                    )
                    for field in entity.fields:
                        conn.execute(
                            """
                            INSERT INTO semantic_fields
                                (field_id, entity_id, physical_table, physical_column,
                                 business_name, description, data_type, origin,
                                 semantic_role, default_aggregation, synonyms,
                                 confidence, physical_reference, is_candidate)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                field.field_id, entity.entity_id,
                                field.physical_table, field.physical_column,
                                field.business_name, field.description,
                                field.data_type, field.origin.value,
                                field.semantic_role, field.default_aggregation,
                                json.dumps(field.synonyms),
                                field.confidence, field.physical_reference,
                                int(field.is_candidate),
                            ),
                        )
                        for ev in field.evidence:
                            ev_id = f"ev_{uuid4().hex[:12]}"
                            conn.execute(
                                """
                                INSERT INTO evidence (evidence_id, field_id, source, detail)
                                VALUES (?, ?, ?, ?)
                                """,
                                (ev_id, field.field_id, ev.source.value, ev.detail),
                            )
            conn.commit()

    def load_profile(self, data_source_id: str) -> ProfileView | None:
        """Load the latest profile as a nested ProfileView."""
        snapshot = self.get_latest_snapshot(data_source_id)
        if not snapshot:
            return None
        return self._load_profile_for_snapshot(snapshot)

    def _load_profile_for_snapshot(self, snapshot: SchemaSnapshot) -> ProfileView:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            spaces = self._load_spaces(conn, snapshot.snapshot_id)
        return ProfileView(
            data_source_id=snapshot.data_source_id,
            snapshot_id=snapshot.snapshot_id,
            version=snapshot.version,
            spaces=spaces,
            scan_phase=snapshot.scan_phase,
            created_at=snapshot.created_at,
        )

    def _load_spaces(self, conn: sqlite3.Connection, snapshot_id: str) -> list[SemanticSpace]:
        space_rows = conn.execute(
            "SELECT * FROM semantic_spaces WHERE snapshot_id=? ORDER BY rowid",
            (snapshot_id,),
        ).fetchall()
        spaces: list[SemanticSpace] = []
        for sr in space_rows:
            entities = self._load_entities(conn, sr["space_id"])
            spaces.append(self._row_to_space(sr, entities))
        return spaces

    def _row_to_space(self, row: sqlite3.Row, entities: list[SemanticEntity]) -> SemanticSpace:
        version_state = row["version_state"] if "version_state" in row.keys() else None
        return SemanticSpace(
            space_id=row["space_id"],
            snapshot_id=row["snapshot_id"],
            name=row["name"],
            description=row["description"],
            entities=entities,
            accepted=bool(row["accepted"]),
            version=row["version"] if "version" in row.keys() else None,
            version_state=SemanticSpaceVersionState(version_state) if version_state else None,
            created_at=row["created_at"] if "created_at" in row.keys() else None,
            published_at=row["published_at"] if "published_at" in row.keys() else None,
        )

    def _load_entities(
        self, conn: sqlite3.Connection, space_id: str
    ) -> list[SemanticEntity]:
        rows = conn.execute(
            "SELECT * FROM semantic_entities WHERE space_id=? ORDER BY rowid",
            (space_id,),
        ).fetchall()
        entities: list[SemanticEntity] = []
        for row in rows:
            fields = self._load_fields(conn, row["entity_id"], row["snapshot_id"])
            entities.append(
                SemanticEntity(
                    entity_id=row["entity_id"],
                    space_id=space_id,
                    physical_table=row["physical_table"],
                    business_name=row["business_name"],
                    description=row["description"],
                    recommendation=TableRecommendation(row["recommendation"]),
                    fields=fields,
                )
            )
        return entities

    def _catalog_column_index(
        self, conn: sqlite3.Connection, snapshot_id: str
    ) -> dict[tuple[str, str], sqlite3.Row]:
        rows = conn.execute(
            """
            SELECT t.schema_name, t.table_name, c.column_name, c.data_type, c.comment
            FROM catalog_columns c
            JOIN catalog_tables t ON c.catalog_table_id = t.catalog_table_id
            WHERE t.snapshot_id=?
            """,
            (snapshot_id,),
        ).fetchall()
        index: dict[tuple[str, str], sqlite3.Row] = {}
        for row in rows:
            column_key = str(row["column_name"] or "").lower()
            for table_key in self._table_match_keys(row["table_name"], row["schema_name"]):
                index[(table_key, column_key)] = row
        return index

    def _catalog_row_for_field(
        self,
        catalog_index: dict[tuple[str, str], sqlite3.Row],
        physical_table: str,
        physical_column: str,
    ) -> sqlite3.Row | None:
        column_key = str(physical_column or "").lower()
        for table_key in self._table_match_keys(physical_table):
            row = catalog_index.get((table_key, column_key))
            if row is not None:
                return row
        return None

    def _hydrate_evidence_details(
        self,
        evidence: list[EvidenceItem],
        *,
        physical_table: str,
        physical_column: str,
        catalog_row: sqlite3.Row | None,
        semantic_role: str | None,
    ) -> list[EvidenceItem]:
        hydrated: list[EvidenceItem] = []
        for item in evidence:
            detail = item.detail
            if item.source == EvidenceSource.sample and not detail:
                # Old scans accepted LLM-declared "sample" without storing the
                # actual sampled values. Do not present that as a real source.
                continue
            if item.source == EvidenceSource.name and not detail:
                type_suffix = (
                    f"，类型 {catalog_row['data_type']}"
                    if catalog_row is not None and catalog_row["data_type"]
                    else ""
                )
                detail = f"扫描到物理列 {physical_table}.{physical_column}{type_suffix}"
            elif item.source == EvidenceSource.comment and not detail:
                if catalog_row is None or not catalog_row["comment"]:
                    continue
                detail = f"列注释: {catalog_row['comment']}"
            elif item.source == EvidenceSource.ai_inference and not detail:
                role = semantic_role or "未指定角色"
                detail = f"系统基于扫描元数据、业务背景和字段画像推断业务名/语义角色: {role}"
            hydrated.append(EvidenceItem(source=item.source, detail=detail))

        if not hydrated:
            type_suffix = (
                f"，类型 {catalog_row['data_type']}"
                if catalog_row is not None and catalog_row["data_type"]
                else ""
            )
            hydrated.append(
                EvidenceItem(
                    source=EvidenceSource.name,
                    detail=f"扫描到物理列 {physical_table}.{physical_column}{type_suffix}",
                )
            )
        return hydrated

    def _load_fields(
        self, conn: sqlite3.Connection, entity_id: str, snapshot_id: str
    ) -> list[SemanticField]:
        rows = conn.execute(
            "SELECT * FROM semantic_fields WHERE entity_id=? ORDER BY rowid",
            (entity_id,),
        ).fetchall()
        catalog_index = self._catalog_column_index(conn, snapshot_id)
        fields: list[SemanticField] = []
        for row in rows:
            catalog_row = self._catalog_row_for_field(
                catalog_index,
                row["physical_table"],
                row["physical_column"],
            )
            data_type = row["data_type"] or (catalog_row["data_type"] if catalog_row else None)
            ev_rows = conn.execute(
                "SELECT * FROM evidence WHERE field_id=? ORDER BY rowid",
                (row["field_id"],),
            ).fetchall()
            evidence = [
                EvidenceItem(source=EvidenceSource(ev["source"]), detail=ev["detail"])
                for ev in ev_rows
            ]
            evidence = self._hydrate_evidence_details(
                evidence,
                physical_table=row["physical_table"],
                physical_column=row["physical_column"],
                catalog_row=catalog_row,
                semantic_role=row["semantic_role"],
            )
            fields.append(
                SemanticField(
                    field_id=row["field_id"],
                    entity_id=entity_id,
                    physical_table=row["physical_table"],
                    physical_column=row["physical_column"],
                    business_name=row["business_name"],
                    description=row["description"],
                    data_type=data_type,
                    origin=FieldOrigin(row["origin"]),
                    semantic_role=row["semantic_role"],
                    default_aggregation=row["default_aggregation"],
                    synonyms=json.loads(row["synonyms"] or "[]"),
                    confidence=row["confidence"],
                    physical_reference=row["physical_reference"],
                    is_candidate=bool(row["is_candidate"]),
                    status=row["status"] if row["status"] else None,
                    evidence=evidence,
                )
            )
        return fields

    # ── Space adjustments ─────────────────────────────────────────────

    def apply_space_adjustments(
        self, snapshot_id: str, adjustments: list[SemanticSpaceAdjustment]
    ) -> None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            for adj in adjustments:
                params: list[object] = [int(adj.accepted)]
                set_clauses = ["accepted=?"]
                if adj.name is not None:
                    set_clauses.append("name=?")
                    params.append(adj.name)
                if adj.description is not None:
                    set_clauses.append("description=?")
                    params.append(adj.description)
                params.extend([adj.space_id, snapshot_id])
                conn.execute(
                    f"UPDATE semantic_spaces SET {', '.join(set_clauses)} "
                    f"WHERE space_id=? AND snapshot_id=?",
                    params,
                )
                for field_id, status in adj.field_statuses.items():
                    status_value = status.value if hasattr(status, "value") else str(status)
                    conn.execute(
                        """
                        UPDATE semantic_fields
                        SET status=?
                        WHERE field_id=?
                          AND entity_id IN (
                              SELECT entity_id
                              FROM semantic_entities
                              WHERE space_id=? AND snapshot_id=?
                          )
                        """,
                        (status_value, field_id, adj.space_id, snapshot_id),
                    )
                for field_id, update in adj.field_updates.items():
                    field_clauses: list[str] = []
                    field_params: list[object] = []
                    if update.business_name is not None:
                        field_clauses.append("business_name=?")
                        field_params.append(update.business_name)
                    if update.description is not None:
                        field_clauses.append("description=?")
                        field_params.append(update.description)
                    if update.semantic_role is not None:
                        field_clauses.append("semantic_role=?")
                        field_params.append(update.semantic_role)
                    if update.default_aggregation is not None:
                        field_clauses.append("default_aggregation=?")
                        field_params.append(update.default_aggregation)
                    if update.synonyms is not None:
                        field_clauses.append("synonyms=?")
                        field_params.append(json.dumps(update.synonyms, ensure_ascii=False))
                    if not field_clauses:
                        continue
                    field_params.extend([field_id, adj.space_id, snapshot_id])
                    conn.execute(
                        f"""
                        UPDATE semantic_fields
                        SET {', '.join(field_clauses)}
                        WHERE field_id=?
                          AND entity_id IN (
                              SELECT entity_id
                              FROM semantic_entities
                              WHERE space_id=? AND snapshot_id=?
                          )
                        """,
                        field_params,
                    )
            conn.commit()

    # ── Managed semantic spaces (semantic-space-management) ────────────
    #
    # A "managed" space is one explicitly created via create_space(): its
    # version_state is never NULL. Scan-time candidate clusters produced by
    # save_spaces() keep version_state NULL and are untouched by any of the
    # methods below, so existing scan/profile behavior is unaffected.

    @staticmethod
    def _table_match_keys(table_name: str, schema_name: str | None = None) -> set[str]:
        raw = (table_name or "").strip()
        if not raw:
            return set()
        keys = {raw.lower()}
        leaf = raw.split(".")[-1]
        keys.add(leaf.lower())
        if schema_name:
            keys.add(f"{schema_name}.{leaf}".lower())
        return keys

    @staticmethod
    def _semantic_role_for_type(data_type: str | None) -> tuple[str, str | None]:
        raw = (data_type or "").upper()
        is_measure = any(
            marker in raw
            for marker in ("NUMBER", "NUMERIC", "DECIMAL", "INT", "FLOAT", "DOUBLE", "REAL")
        )
        return ("measure", "sum") if is_measure else ("dimension", None)

    def _insert_field_copy(
        self,
        conn: sqlite3.Connection,
        *,
        source: SemanticField,
        entity_id: str,
        status: str = "confirmed",
    ) -> None:
        field_id = f"fld_{uuid4().hex[:16]}"
        conn.execute(
            """
            INSERT INTO semantic_fields
                (field_id, entity_id, physical_table, physical_column,
                 business_name, description, data_type, origin,
                 semantic_role, default_aggregation, synonyms,
                 confidence, physical_reference, is_candidate, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                field_id, entity_id, source.physical_table, source.physical_column,
                source.business_name, source.description, source.data_type,
                source.origin.value, source.semantic_role, source.default_aggregation,
                json.dumps(source.synonyms), source.confidence,
                source.physical_reference, status,
            ),
        )
        for ev in source.evidence:
            conn.execute(
                "INSERT INTO evidence (evidence_id, field_id, source, detail) VALUES (?, ?, ?, ?)",
                (f"ev_{uuid4().hex[:12]}", field_id, ev.source.value, ev.detail),
            )

    def _insert_catalog_column_field(
        self,
        conn: sqlite3.Connection,
        *,
        column: CatalogColumnRecord,
        entity_id: str,
        physical_table: str,
    ) -> None:
        semantic_role, default_aggregation = self._semantic_role_for_type(column.data_type)
        business_name = column.comment or column.column_name
        evidence_source = EvidenceSource.comment if column.comment else EvidenceSource.name
        evidence_detail = column.comment or f"物理字段名 {column.column_name}"
        field_id = f"fld_{uuid4().hex[:16]}"
        conn.execute(
            """
            INSERT INTO semantic_fields
                (field_id, entity_id, physical_table, physical_column,
                 business_name, description, data_type, origin,
                 semantic_role, default_aggregation, synonyms,
                 confidence, physical_reference, is_candidate, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'confirmed')
            """,
            (
                field_id, entity_id, physical_table, column.column_name,
                business_name, column.comment, column.data_type,
                FieldOrigin.inferred.value, semantic_role, default_aggregation,
                json.dumps([]), 0.72 if column.comment else 0.55,
                f"{physical_table}.{column.column_name}",
            ),
        )
        conn.execute(
            "INSERT INTO evidence (evidence_id, field_id, source, detail) VALUES (?, ?, ?, ?)",
            (f"ev_{uuid4().hex[:12]}", field_id, evidence_source.value, evidence_detail),
        )

    def create_space(
        self,
        data_source_id: str,
        name: str,
        description: str | None = None,
        initial_tables: list[str] | None = None,
    ) -> SemanticSpace:
        """Create a standalone, explicitly-managed semantic space (draft, v1).

        ``initial_tables`` is not just a shell list: when possible we seed the
        space with field semantics copied from scan-time recommendations, and
        fall back to raw catalog columns if no recommendation exists yet.
        """
        snapshot = self.get_latest_snapshot(data_source_id) or self.create_snapshot(data_source_id)
        space_id = f"sps_{uuid4().hex[:16]}"
        now = datetime.now(timezone.utc).isoformat()
        selected_tables: list[str] = []
        seen_tables: set[str] = set()
        for raw_table in initial_tables or []:
            table = str(raw_table).strip()
            if not table:
                continue
            key = table.lower()
            if key in seen_tables:
                continue
            seen_tables.add(key)
            selected_tables.append(table)

        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO semantic_spaces
                    (space_id, snapshot_id, name, description, accepted,
                     version, version_state, created_at)
                VALUES (?, ?, ?, ?, 1, 1, 'draft', ?)
                """,
                (space_id, snapshot.snapshot_id, name, description, now),
            )

            candidate_by_table: dict[str, dict[str, SemanticField]] = {}
            for field in self._candidate_pool(conn, data_source_id):
                for key in self._table_match_keys(field.physical_table):
                    candidate_by_table.setdefault(key, {})[field.field_id] = field

            catalog_by_table: dict[str, CatalogTableRecord] = {}
            for catalog_table in self._load_catalog_tables(conn, snapshot.snapshot_id):
                for key in self._table_match_keys(catalog_table.table_name, catalog_table.schema_name):
                    catalog_by_table.setdefault(key, catalog_table)

            for table in selected_tables:
                entity_id = f"ent_{uuid4().hex[:16]}"
                matched_catalog = next(
                    (catalog_by_table[key] for key in self._table_match_keys(table) if key in catalog_by_table),
                    None,
                )
                physical_table = (
                    f"{matched_catalog.schema_name}.{matched_catalog.table_name}"
                    if matched_catalog and matched_catalog.schema_name
                    else (matched_catalog.table_name if matched_catalog else table)
                )
                conn.execute(
                    """
                    INSERT INTO semantic_entities
                        (entity_id, space_id, snapshot_id, physical_table, business_name, recommendation)
                    VALUES (?, ?, ?, ?, ?, 'recommended_include')
                    """,
                    (entity_id, space_id, snapshot.snapshot_id, physical_table, table),
                )

                copied: dict[str, SemanticField] = {}
                for key in self._table_match_keys(table):
                    copied.update(candidate_by_table.get(key, {}))
                for field in copied.values():
                    self._insert_field_copy(conn, source=field, entity_id=entity_id)

                # Recommendation output can be partial. Always merge every
                # scanned catalog column that was not present in the copied
                # recommendation so pack mappings never point at fields that
                # disappeared merely because one candidate field existed.
                copied_columns = {
                    field.physical_column.upper() for field in copied.values()
                }
                if matched_catalog:
                    for column in matched_catalog.columns:
                        if column.column_name.upper() in copied_columns:
                            continue
                        self._insert_catalog_column_field(
                            conn,
                            column=column,
                            entity_id=entity_id,
                            physical_table=physical_table,
                        )
            conn.commit()
        space = self.get_space(space_id)
        if space is None:  # pragma: no cover - defensive, cannot happen post-insert
            raise RuntimeError(f"Failed to create semantic space for {data_source_id}")
        return space

    def delete_space(self, space_id: str) -> bool:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            exists = conn.execute(
                "SELECT 1 FROM semantic_spaces WHERE space_id=?", (space_id,)
            ).fetchone()
            if not exists:
                return False
            conn.execute(
                "DELETE FROM evidence WHERE field_id IN "
                "(SELECT f.field_id FROM semantic_fields f "
                " JOIN semantic_entities e ON f.entity_id=e.entity_id "
                " WHERE e.space_id=?)",
                (space_id,),
            )
            conn.execute(
                "DELETE FROM semantic_fields WHERE entity_id IN "
                "(SELECT entity_id FROM semantic_entities WHERE space_id=?)",
                (space_id,),
            )
            conn.execute("DELETE FROM semantic_entities WHERE space_id=?", (space_id,))
            conn.execute("DELETE FROM semantic_space_versions WHERE space_id=?", (space_id,))
            conn.execute("DELETE FROM semantic_spaces WHERE space_id=?", (space_id,))
            conn.commit()
            return True

    def add_catalog_table_to_space(self, space_id: str, physical_table: str) -> SemanticSpace:
        """Explicitly expand one managed space with a scanned catalog table.

        This is used by pack mounting after an administrator selects a ranked
        outside-scope candidate. Only an existing table from the space's own
        snapshot may be added; every scanned column is seeded as confirmed so
        a subsequent mapping cannot point at an ungoverned free-form field.
        """
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            space_row = conn.execute(
                "SELECT * FROM semantic_spaces WHERE space_id=?", (space_id,)
            ).fetchone()
            if space_row is None:
                raise KeyError(f"Semantic space not found: {space_id}")

            existing = conn.execute(
                "SELECT entity_id FROM semantic_entities "
                "WHERE space_id=? AND lower(physical_table)=lower(?)",
                (space_id, physical_table),
            ).fetchone()
            if existing is None:
                catalog_table = next(
                    (
                        table
                        for table in self._load_catalog_tables(conn, space_row["snapshot_id"])
                        if self._table_match_keys(physical_table)
                        & self._table_match_keys(table.table_name, table.schema_name)
                    ),
                    None,
                )
                if catalog_table is None:
                    raise KeyError(f"Scanned catalog table not found: {physical_table}")

                resolved_table = (
                    f"{catalog_table.schema_name}.{catalog_table.table_name}"
                    if catalog_table.schema_name
                    else catalog_table.table_name
                )
                entity_id = f"ent_{uuid4().hex[:16]}"
                conn.execute(
                    """
                    INSERT INTO semantic_entities
                        (entity_id, space_id, snapshot_id, physical_table,
                         business_name, recommendation)
                    VALUES (?, ?, ?, ?, ?, 'recommended_include')
                    """,
                    (
                        entity_id,
                        space_id,
                        space_row["snapshot_id"],
                        resolved_table,
                        catalog_table.comment or catalog_table.table_name,
                    ),
                )
                for column in catalog_table.columns:
                    self._insert_catalog_column_field(
                        conn,
                        column=column,
                        entity_id=entity_id,
                        physical_table=resolved_table,
                    )
                conn.commit()

        expanded = self.get_space(space_id)
        if expanded is None:  # pragma: no cover - defensive
            raise RuntimeError(f"Failed to expand semantic space: {space_id}")
        return expanded

    def get_space(self, space_id: str) -> SemanticSpace | None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM semantic_spaces WHERE space_id=?", (space_id,)
            ).fetchone()
            if not row:
                return None
            entities = self._load_entities(conn, space_id)
            return self._row_to_space(row, entities)

    def list_managed_spaces(self, data_source_id: str) -> list[SemanticSpace]:
        """List explicitly-managed spaces for a data source (scan candidates excluded)."""
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT s.* FROM semantic_spaces s
                JOIN snapshots sn ON s.snapshot_id = sn.snapshot_id
                WHERE sn.data_source_id=? AND s.version_state IS NOT NULL
                ORDER BY s.rowid
                """,
                (data_source_id,),
            ).fetchall()
            return [self._row_to_space(row, self._load_entities(conn, row["space_id"])) for row in rows]

    def list_recommended_spaces(self, data_source_id: str) -> list[SemanticSpace]:
        """Scan-time LLM-discovered candidate space groupings for the latest
        snapshot — recommendations to seed a managed semantic space from, not
        themselves manageable/publishable (version_state stays None)."""
        snapshot = self.get_latest_snapshot(data_source_id)
        if not snapshot:
            return []
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM semantic_spaces WHERE snapshot_id=? AND version_state IS NULL ORDER BY rowid",
                (snapshot.snapshot_id,),
            ).fetchall()
            return [self._row_to_space(row, self._load_entities(conn, row["space_id"])) for row in rows]

    def _candidate_pool(self, conn: sqlite3.Connection, data_source_id: str) -> list[SemanticField]:
        """Fields from the latest snapshot's scan-candidate clusters (not yet managed)."""
        snap_row = conn.execute(
            "SELECT snapshot_id FROM snapshots WHERE data_source_id=? ORDER BY version DESC LIMIT 1",
            (data_source_id,),
        ).fetchone()
        if not snap_row:
            return []
        space_rows = conn.execute(
            "SELECT space_id FROM semantic_spaces WHERE snapshot_id=? AND version_state IS NULL",
            (snap_row["snapshot_id"],),
        ).fetchall()
        fields: list[SemanticField] = []
        for sr in space_rows:
            for entity in self._load_entities(conn, sr["space_id"]):
                fields.extend(entity.fields)
        return fields

    def _adopted_field_keys(self, conn: sqlite3.Connection, data_source_id: str) -> set[tuple[str, str]]:
        """(physical_table, physical_column) already adopted by any managed space."""
        rows = conn.execute(
            """
            SELECT DISTINCT f.physical_table, f.physical_column
            FROM semantic_fields f
            JOIN semantic_entities e ON f.entity_id = e.entity_id
            JOIN semantic_spaces s ON e.space_id = s.space_id
            JOIN snapshots sn ON s.snapshot_id = sn.snapshot_id
            WHERE sn.data_source_id=? AND s.version_state IS NOT NULL
            """,
            (data_source_id,),
        ).fetchall()
        return {(r["physical_table"], r["physical_column"]) for r in rows}

    def refresh_space(self, space_id: str) -> SemanticSpaceDiff:
        """Compute new/removed/changed fields for a space without mutating it."""
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            space_row = conn.execute(
                "SELECT * FROM semantic_spaces WHERE space_id=?", (space_id,)
            ).fetchone()
            if not space_row:
                raise KeyError(f"Semantic space not found: {space_id}")
            snap_row = conn.execute(
                "SELECT data_source_id FROM snapshots WHERE snapshot_id=?",
                (space_row["snapshot_id"],),
            ).fetchone()
            data_source_id = snap_row["data_source_id"] if snap_row else None

            entities = self._load_entities(conn, space_id)
            scoped_table_keys: set[str] = set()
            adopted_fields: list[SemanticField] = []
            for entity in entities:
                scoped_table_keys.update(self._table_match_keys(entity.physical_table))
                adopted_fields.extend(entity.fields)
            adopted_by_key = {(f.physical_table, f.physical_column): f for f in adopted_fields}

            candidate_fields = self._candidate_pool(conn, data_source_id) if data_source_id else []
            if scoped_table_keys:
                candidate_fields = [
                    f for f in candidate_fields
                    if self._table_match_keys(f.physical_table) & scoped_table_keys
                ]
            adopted_elsewhere = self._adopted_field_keys(conn, data_source_id) if data_source_id else set()
            candidate_by_key = {(f.physical_table, f.physical_column): f for f in candidate_fields}

            new_fields = [
                f
                for f in candidate_fields
                if (f.physical_table, f.physical_column) not in adopted_by_key
                and (f.physical_table, f.physical_column) not in adopted_elsewhere
            ]

            removed_fields: list[SemanticField] = []
            changed_fields: list[ChangedFieldEntry] = []
            invalidated_fields: list[str] = []
            for f in adopted_fields:
                latest = candidate_by_key.get((f.physical_table, f.physical_column))
                if latest is None:
                    removed_fields.append(f)
                    invalidated_fields.append(f.field_id)
                    continue
                before: dict[str, object] = {}
                after: dict[str, object] = {}
                if latest.business_name != f.business_name:
                    before["business_name"] = f.business_name
                    after["business_name"] = latest.business_name
                if latest.data_type != f.data_type:
                    before["data_type"] = f.data_type
                    after["data_type"] = latest.data_type
                if after:
                    changed_fields.append(ChangedFieldEntry(field_id=f.field_id, before=before, after=after))

        return SemanticSpaceDiff(
            space_id=space_id,
            new_fields=new_fields,
            removed_fields=removed_fields,
            changed_fields=changed_fields,
            invalidated_fields=invalidated_fields,
        )

    def publish_space(
        self,
        space_id: str,
        confirmed_field_ids: list[str] | None = None,
        *,
        published_by: str = "system",
    ) -> SemanticSpace:
        """Adopt confirmed diff suggestions and publish a new version.

        Prior versions are frozen into ``semantic_space_versions`` so they
        remain queryable via :meth:`list_space_versions` /
        :meth:`get_space_version`.
        """
        confirmed_field_ids = confirmed_field_ids or []
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            space_row = conn.execute(
                "SELECT * FROM semantic_spaces WHERE space_id=?", (space_id,)
            ).fetchone()
            if not space_row:
                raise KeyError(f"Semantic space not found: {space_id}")
            snap_row = conn.execute(
                "SELECT data_source_id FROM snapshots WHERE snapshot_id=?",
                (space_row["snapshot_id"],),
            ).fetchone()
            data_source_id = snap_row["data_source_id"] if snap_row else None

            if confirmed_field_ids and data_source_id:
                # Adoption re-parents the field row from its scan-candidate entity to
                # a managed entity in this space (preserving field_id/evidence), rather
                # than copying — the field_id primary key must stay unique, and once
                # re-parented the field naturally drops out of _candidate_pool().
                candidate_by_id = {f.field_id: f for f in self._candidate_pool(conn, data_source_id)}
                entity_by_table = {
                    e.physical_table: e.entity_id for e in self._load_entities(conn, space_id)
                }
                for field_id in confirmed_field_ids:
                    cf = candidate_by_id.get(field_id)
                    if cf is None:
                        continue  # not a pending suggestion for this space; ignore
                    entity_id = entity_by_table.get(cf.physical_table)
                    if entity_id is None:
                        entity_id = f"ent_{uuid4().hex[:16]}"
                        conn.execute(
                            """
                            INSERT INTO semantic_entities
                                (entity_id, space_id, snapshot_id, physical_table, business_name, recommendation)
                            VALUES (?, ?, ?, ?, ?, 'recommended_include')
                            """,
                            (entity_id, space_id, space_row["snapshot_id"], cf.physical_table, cf.physical_table),
                        )
                        entity_by_table[cf.physical_table] = entity_id
                    conn.execute(
                        "UPDATE semantic_fields SET entity_id=?, status=?, is_candidate=0 WHERE field_id=?",
                        (entity_id, "confirmed", field_id),
                    )

            current_version = space_row["version"] or 1
            was_published = space_row["version_state"] == SemanticSpaceVersionState.published.value
            new_version = current_version + 1 if was_published else current_version
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE semantic_spaces SET version=?, version_state=?, published_at=? WHERE space_id=?",
                (new_version, SemanticSpaceVersionState.published.value, now, space_id),
            )

            row = conn.execute("SELECT * FROM semantic_spaces WHERE space_id=?", (space_id,)).fetchone()
            entities = self._load_entities(conn, space_id)
            published = self._row_to_space(row, entities)

            conn.execute(
                """
                INSERT INTO semantic_space_versions
                    (version_id, space_id, version, snapshot_json, published_by, published_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"spv_{uuid4().hex[:16]}", space_id, new_version,
                    published.model_dump_json(), published_by, now,
                ),
            )
            conn.commit()
        return published

    def list_space_versions(self, space_id: str) -> list[int]:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            rows = conn.execute(
                "SELECT version FROM semantic_space_versions WHERE space_id=? ORDER BY version",
                (space_id,),
            ).fetchall()
            return [r[0] for r in rows]

    def get_space_version(self, space_id: str, version: int) -> SemanticSpace | None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            row = conn.execute(
                "SELECT snapshot_json FROM semantic_space_versions WHERE space_id=? AND version=?",
                (space_id, version),
            ).fetchone()
            if not row:
                return None
            return SemanticSpace.model_validate_json(row[0])

    def list_unadopted_fields(self, data_source_id: str) -> list[SemanticField]:
        """Fields scanned for this data source but not adopted into any managed space."""
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            candidates = self._candidate_pool(conn, data_source_id)
            adopted = self._adopted_field_keys(conn, data_source_id)
        return [f for f in candidates if (f.physical_table, f.physical_column) not in adopted]

    def lookup_gap_candidates(self, data_source_id: str, query: str) -> list[SemanticGapCandidate]:
        """Match an ask-data question against the unadopted-field ledger."""
        unadopted = self.list_unadopted_fields(data_source_id)
        if not unadopted or not query.strip():
            return []
        from sq_bi_semantic.synonyms import is_partial_match

        results: list[SemanticGapCandidate] = []
        for f in unadopted:
            if is_partial_match(query, f.business_name, list(f.synonyms or [])):
                results.append(
                    SemanticGapCandidate(
                        field_id=f.field_id,
                        physical_table=f.physical_table,
                        physical_column=f.physical_column,
                        business_name=f.business_name,
                        description=f.description,
                        confidence=f.confidence,
                        suggested_reason=(
                            f"用户提问提及了「{f.business_name}」，该物理字段与提问主题相关，"
                            "但尚未纳入本数据源的任何业务语义空间中"
                        ),
                        field_name=f.physical_column,
                        table_name=f.physical_table,
                        connection_id=data_source_id,
                    )
                )
        return results

    # ── Documents ─────────────────────────────────────────────────────

    def create_document(
        self,
        data_source_id: str,
        filename: str,
        content_type: str,
        byte_size: int,
    ) -> DataSourceDocument:
        doc_id = f"doc_{uuid4().hex[:16]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                """
                INSERT INTO ds_documents
                    (document_id, data_source_id, filename, content_type,
                     byte_size, upload_status, uploaded_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (doc_id, data_source_id, filename, content_type, byte_size, now),
            )
            conn.commit()
        return DataSourceDocument(
            document_id=doc_id,
            data_source_id=data_source_id,
            filename=filename,
            content_type=content_type,
            byte_size=byte_size,
            upload_status="pending",
            uploaded_at=now,
        )

    def update_document_status(
        self,
        document_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                "UPDATE ds_documents SET upload_status=?, error=? WHERE document_id=?",
                (status, error, document_id),
            )
            conn.commit()

    def list_documents(self, data_source_id: str) -> list[DataSourceDocument]:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM ds_documents WHERE data_source_id=? ORDER BY uploaded_at DESC",
                (data_source_id,),
            ).fetchall()
            return [self._row_to_document(r) for r in rows]

    def get_document(self, document_id: str) -> DataSourceDocument | None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM ds_documents WHERE document_id=?", (document_id,)
            ).fetchone()
            return self._row_to_document(row) if row else None

    def delete_document(self, document_id: str) -> bool:
        """Delete a document row. Returns False if it didn't exist."""
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            cur = conn.execute("DELETE FROM ds_documents WHERE document_id=?", (document_id,))
            conn.commit()
            return cur.rowcount > 0

    def _row_to_document(self, row: sqlite3.Row) -> DataSourceDocument:
        return DataSourceDocument(
            document_id=row["document_id"],
            data_source_id=row["data_source_id"],
            filename=row["filename"],
            content_type=row["content_type"],
            byte_size=row["byte_size"],
            upload_status=row["upload_status"],  # type: ignore[arg-type]
            uploaded_at=row["uploaded_at"],
            error=row["error"],
        )
