from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sq_bi_contracts.field_mount import (
    DeploymentInstance,
    FieldMapping,
    MappingStatus,
    PendingMapping,
    ValidationStatus,
)
from sq_bi_contracts.semantic_profile import FieldStatus, SemanticSpace

logger = logging.getLogger(__name__)

_MAPPING_STATUS_ACTIVE: MappingStatus = "active"
_DEPLOY_ID_HEX_CHARS: int = 12


def _normalize_semantic_space_key(semantic_space_ids: list[str]) -> str:
    """Order-independent identity key for a semantic-space binding set.

    Used only for deployment-identity comparison/uniqueness; the raw
    ``semantic_space_ids`` (original order) is still persisted separately.
    """
    return ",".join(sorted({sid for sid in semantic_space_ids if sid}))


class FieldMappingStore:
    """SQLite-backed persistent store for standard-field-to-physical-field mappings
    and deployment instances.

    Schema:
      - ``deployments``: pack × data_source, owns mappings.
      - ``field_mappings``: per-standard-field mapping, scoped by deployment_id.

    Backward-compat: rows without deployment_id are queries without the
    ``deployment_id`` filter; existing callers continue to work.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._lock = threading.Lock()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"Cannot create field-mapping store directory {self._path.parent}: {exc}"
            ) from exc
        self._init_db()

    def _init_db(self) -> None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS deployments (
                    deployment_id TEXT PRIMARY KEY,
                    pack_id TEXT NOT NULL,
                    pack_version TEXT NOT NULL DEFAULT '1.0.0',
                    data_source_id TEXT NOT NULL,
                    license_ref TEXT,
                    last_smoke_passed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT,
                    semantic_space_ids TEXT NOT NULL DEFAULT '[]',
                    UNIQUE (pack_id, data_source_id)
                )
            """)
            try:
                conn.execute(
                    "ALTER TABLE deployments ADD COLUMN semantic_space_ids TEXT NOT NULL DEFAULT '[]'"
                )
            except sqlite3.OperationalError:
                pass  # column already present

            # Migrate legacy schema that still has a per-row `environment` column
            # (the test/production environment concept was removed; deployments
            # are now keyed by pack_id + data_source_id only).
            existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(deployments)")}
            # Only the short-lived legacy environment schema lacks the later
            # binding identity column. The current schema also has an
            # `environment` column, so checking that column alone rebuilt the
            # table on every process restart and silently reset activation.
            if "environment" in existing_cols and "semantic_space_key" not in existing_cols:
                conn.execute("ALTER TABLE deployments RENAME TO deployments_legacy_env")
                conn.execute("""
                    CREATE TABLE deployments (
                        deployment_id TEXT PRIMARY KEY,
                        pack_id TEXT NOT NULL,
                        pack_version TEXT NOT NULL DEFAULT '1.0.0',
                        data_source_id TEXT NOT NULL,
                        license_ref TEXT,
                        last_smoke_passed INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT,
                        updated_at TEXT,
                        semantic_space_ids TEXT NOT NULL DEFAULT '[]',
                        UNIQUE (pack_id, data_source_id)
                    )
                """)
                conn.execute("""
                    INSERT OR IGNORE INTO deployments
                        (deployment_id, pack_id, pack_version, data_source_id,
                         license_ref, last_smoke_passed, created_at, updated_at, semantic_space_ids)
                    SELECT deployment_id, pack_id, pack_version, data_source_id,
                           license_ref, last_smoke_passed, created_at, updated_at, semantic_space_ids
                    FROM deployments_legacy_env
                    ORDER BY (environment = 'production') DESC
                """)
                conn.execute("DROP TABLE deployments_legacy_env")

            # Activation is an independent state from validation_status (P0:
            # split validate/activate — see
            # .design/asset_semantic_space_harness_operating_model.md §9/§11).
            # Runs after the legacy `environment` migration above so it
            # applies to whichever version of `deployments` currently exists.
            for ddl in (
                "ALTER TABLE deployments ADD COLUMN is_active INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE deployments ADD COLUMN activated_at TEXT",
                "ALTER TABLE deployments ADD COLUMN activated_by TEXT",
            ):
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError:
                    pass  # column already present

            # Binding-aware deployment identity (P3 runtime-asset-projection
            # task 2.1). The uniqueness key widens from (pack_id,
            # data_source_id) to (pack_id, pack_version, data_source_id,
            # environment, normalized semantic-space set) so the same
            # pack/data source can have independent deployments per
            # environment or space binding (task 2.2), while an identical
            # effective binding — even reordered — stays idempotent. SQLite
            # cannot alter an existing UNIQUE constraint in place, so rebuild
            # the table the same way the legacy `environment` column above
            # was migrated, this time preserving every row and column,
            # including any already-added is_active/activated_at/activated_by.
            existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(deployments)")}
            if "environment" not in existing_cols or "semantic_space_key" not in existing_cols:
                conn.execute("ALTER TABLE deployments RENAME TO deployments_pre_binding_identity")
                conn.execute("""
                    CREATE TABLE deployments (
                        deployment_id TEXT PRIMARY KEY,
                        pack_id TEXT NOT NULL,
                        pack_version TEXT NOT NULL DEFAULT '1.0.0',
                        data_source_id TEXT NOT NULL,
                        environment TEXT NOT NULL DEFAULT 'default',
                        license_ref TEXT,
                        last_smoke_passed INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT,
                        updated_at TEXT,
                        semantic_space_ids TEXT NOT NULL DEFAULT '[]',
                        semantic_space_key TEXT NOT NULL DEFAULT '',
                        is_active INTEGER NOT NULL DEFAULT 0,
                        activated_at TEXT,
                        activated_by TEXT,
                        UNIQUE (pack_id, pack_version, data_source_id, environment, semantic_space_key)
                    )
                """)
                conn.row_factory = sqlite3.Row
                legacy_rows = conn.execute(
                    "SELECT * FROM deployments_pre_binding_identity"
                ).fetchall()
                for legacy in legacy_rows:
                    legacy_cols = legacy.keys()
                    raw_space_ids = (
                        legacy["semantic_space_ids"]
                        if "semantic_space_ids" in legacy_cols
                        else None
                    )
                    try:
                        space_ids = json.loads(raw_space_ids) if raw_space_ids else []
                    except (TypeError, ValueError):
                        space_ids = []
                    conn.execute(
                        """
                        INSERT INTO deployments
                            (deployment_id, pack_id, pack_version, data_source_id,
                             environment, license_ref, last_smoke_passed,
                             created_at, updated_at, semantic_space_ids,
                             semantic_space_key, is_active, activated_at, activated_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            legacy["deployment_id"],
                            legacy["pack_id"],
                            legacy["pack_version"],
                            legacy["data_source_id"],
                            "default",
                            legacy["license_ref"],
                            legacy["last_smoke_passed"],
                            legacy["created_at"],
                            legacy["updated_at"],
                            raw_space_ids or "[]",
                            _normalize_semantic_space_key(space_ids),
                            legacy["is_active"] if "is_active" in legacy_cols else 0,
                            legacy["activated_at"] if "activated_at" in legacy_cols else None,
                            legacy["activated_by"] if "activated_by" in legacy_cols else None,
                        ),
                    )
                conn.execute("DROP TABLE deployments_pre_binding_identity")
                conn.row_factory = None

            try:
                conn.execute("ALTER TABLE deployments ADD COLUMN smoke_result_json TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE deployments ADD COLUMN extension_layer_id TEXT")
            except sqlite3.OperationalError:
                pass

            conn.execute("""
                CREATE TABLE IF NOT EXISTS field_mappings (
                    mapping_id TEXT PRIMARY KEY,
                    pack_id TEXT NOT NULL,
                    standard_field_id TEXT NOT NULL,
                    data_source_id TEXT NOT NULL,
                    physical_table TEXT NOT NULL,
                    physical_column TEXT NOT NULL,
                    transform TEXT,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source TEXT NOT NULL DEFAULT 'manual',
                    status TEXT NOT NULL DEFAULT 'active',
                    version TEXT NOT NULL DEFAULT '1',
                    deployment_id TEXT REFERENCES deployments(deployment_id),
                    created_at TEXT,
                    updated_at TEXT,
                    created_by TEXT,
                    confirmed_by TEXT,
                    confirmed_at TEXT,
                    CHECK (confidence >= 0.0 AND confidence <= 1.0)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_mappings_lookup
                ON field_mappings (pack_id, data_source_id, standard_field_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_mappings_deployment
                ON field_mappings (deployment_id, status)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_mapping_requests (
                    mapping_request_id TEXT PRIMARY KEY,
                    deployment_id TEXT NOT NULL REFERENCES deployments(deployment_id),
                    standard_field_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pending_mapping_deployment
                ON pending_mapping_requests (deployment_id, standard_field_id)
            """)
            conn.commit()
        logger.info(
            "field_mapping_store.init",
            extra={"db_path": str(self._path)},
        )

    # ── Deployment CRUD ──────────────────────────────────────────────

    def get_or_create_deployment(
        self,
        pack_id: str,
        pack_version: str,
        data_source_id: str,
        license_ref: str | None = None,
        semantic_space_ids: list[str] | None = None,
        environment: str = "default",
        extension_layer_id: str | None = None,
    ) -> DeploymentInstance:
        """Return existing deployment or create a new one.  Idempotent.

        Deployment identity is (pack_id, pack_version, data_source_id,
        environment, normalized semantic_space_ids): repeating the same
        effective binding — even with ``semantic_space_ids`` supplied in a
        different order — resolves the existing deployment, while a
        different environment, pack version, or space set creates an
        independent deployment (P3 runtime-asset-projection task 2.2).
        """
        now = datetime.now(timezone.utc).isoformat()
        space_key = _normalize_semantic_space_key(semantic_space_ids or [])
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM deployments
                WHERE pack_id=? AND pack_version=? AND data_source_id=?
                  AND environment=? AND semantic_space_key=?
                """,
                (pack_id, pack_version, data_source_id, environment, space_key),
            ).fetchone()
            if row:
                dep = self._row_to_deployment(row, conn, pack_id, data_source_id)
                logger.debug(
                    "field_mapping_store.deployment.reused",
                    extra={"deployment_id": dep.deployment_id},
                )
                return dep

            deployment_id = f"dep_{uuid4().hex[:_DEPLOY_ID_HEX_CHARS]}"
            conn.execute(
                """
                INSERT INTO deployments
                    (deployment_id, pack_id, pack_version, data_source_id, environment,
                     license_ref, created_at, updated_at, semantic_space_ids, semantic_space_key,
                     extension_layer_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (deployment_id, pack_id, pack_version, data_source_id, environment,
                 license_ref, now, now, json.dumps(semantic_space_ids or []), space_key,
                 extension_layer_id),
            )
            conn.commit()
            logger.info(
                "field_mapping_store.deployment.created",
                extra={"deployment_id": deployment_id, "pack_id": pack_id,
                       "data_source_id": data_source_id, "environment": environment},
            )
            row = conn.execute(
                "SELECT * FROM deployments WHERE deployment_id=?", (deployment_id,)
            ).fetchone()
            return self._row_to_deployment(row, conn, pack_id, data_source_id)

    def get_deployment(self, deployment_id: str) -> DeploymentInstance | None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM deployments WHERE deployment_id=?", (deployment_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_deployment(row, conn, row["pack_id"], row["data_source_id"])

    def list_deployments(self, pack_id: str | None = None) -> list[DeploymentInstance]:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            if pack_id:
                rows = conn.execute(
                    "SELECT * FROM deployments WHERE pack_id=? ORDER BY created_at DESC",
                    (pack_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM deployments ORDER BY created_at DESC"
                ).fetchall()
            return [
                self._row_to_deployment(r, conn, r["pack_id"], r["data_source_id"])
                for r in rows
            ]

    def mark_smoke_result(
        self,
        deployment_id: str,
        *,
        passed: bool,
        result: dict[str, object] | None = None,
    ) -> None:
        """Persist whether the last smoke test passed. Used for validation_status."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                "UPDATE deployments SET last_smoke_passed=?, smoke_result_json=?, updated_at=? WHERE deployment_id=?",
                (
                    1 if passed else 0,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    now,
                    deployment_id,
                ),
            )
            conn.commit()

    def get_smoke_result(self, deployment_id: str) -> dict[str, object] | None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            row = conn.execute(
                "SELECT smoke_result_json FROM deployments WHERE deployment_id=?",
                (deployment_id,),
            ).fetchone()
        if row is None or not row[0]:
            return None
        try:
            value = json.loads(row[0])
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    # ── Activation (independent from validation_status) ──────────────

    def activate_deployment(
        self, deployment_id: str, activated_by: str | None
    ) -> DeploymentInstance | None:
        """Mark a deployment active. Callers must have already verified
        validation_status == 'ready' — this store has no knowledge of the
        pack manifest needed to compute that, so the readiness gate lives in
        the API layer (see api.py's admin_activate_deployment)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            exists = conn.execute(
                "SELECT 1 FROM deployments WHERE deployment_id=?", (deployment_id,)
            ).fetchone()
            if not exists:
                return None
            conn.execute(
                """
                UPDATE deployments
                SET is_active=1, activated_at=?, activated_by=?, updated_at=?
                WHERE deployment_id=?
                """,
                (now, activated_by, now, deployment_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM deployments WHERE deployment_id=?", (deployment_id,)
            ).fetchone()
            return self._row_to_deployment(row, conn, row["pack_id"], row["data_source_id"])

    def deactivate_deployment(self, deployment_id: str) -> DeploymentInstance | None:
        """Turn a deployment off. Always allowed — an admin may need to pull
        a pack offline even if its validation state has since degraded.
        Keeps activated_at/activated_by as the historical last-activation
        record rather than clearing them; only is_active flips."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            exists = conn.execute(
                "SELECT 1 FROM deployments WHERE deployment_id=?", (deployment_id,)
            ).fetchone()
            if not exists:
                return None
            conn.execute(
                "UPDATE deployments SET is_active=0, updated_at=? WHERE deployment_id=?",
                (now, deployment_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM deployments WHERE deployment_id=?", (deployment_id,)
            ).fetchone()
            return self._row_to_deployment(row, conn, row["pack_id"], row["data_source_id"])

    # ── Coverage & validation_status derivation ──────────────────────

    def _get_last_smoke_passed(self, deployment_id: str) -> bool:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            row = conn.execute(
                "SELECT last_smoke_passed FROM deployments WHERE deployment_id=?",
                (deployment_id,),
            ).fetchone()
            return bool(row[0]) if row else False

    def compute_coverage(
        self,
        deployment_id: str,
        required_standard_field_ids: list[str],
    ) -> tuple[float, ValidationStatus, list[str]]:
        """Return (coverage 0–1, validation_status, blocking_reasons).

        Legacy path: coverage against the pack's full required-field manifest
        and this store's own field_mappings rows. Used only for deployments
        with no bound semantic space — see compute_coverage_from_spaces() for
        the current model.

        Logic:
          - coverage = required fields mapped / total required fields
          - status = 'ready'       if coverage == 1.0 and last smoke passed
          - status = 'incomplete'  if 0 < coverage < 1.0
          - status = 'unvalidated' if no mappings at all
          - status = 'failed'      if coverage == 1.0 but smoke failed
        """
        if not required_standard_field_ids:
            return 1.0, "ready", []

        smoke_passed = self._get_last_smoke_passed(deployment_id)
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            mapped_rows = conn.execute(
                """
                SELECT standard_field_id FROM field_mappings
                WHERE deployment_id=? AND status=?
                """,
                (deployment_id, _MAPPING_STATUS_ACTIVE),
            ).fetchall()

        mapped_ids = {r["standard_field_id"] for r in mapped_rows}
        required_set = set(required_standard_field_ids)
        unmapped = required_set - mapped_ids
        coverage = (len(required_set) - len(unmapped)) / len(required_set)

        blocking_reasons: list[str] = []
        if unmapped:
            blocking_reasons.append(
                f"Required fields not yet mapped: {', '.join(sorted(unmapped))}"
            )

        if coverage == 0.0:
            status: ValidationStatus = "unvalidated"
        elif unmapped:
            status = "incomplete"
        elif not smoke_passed:
            status = "failed"
            blocking_reasons.append("Last smoke test did not pass.")
        else:
            status = "ready"

        return round(coverage, 4), status, blocking_reasons

    def compute_coverage_from_spaces(
        self,
        deployment_id: str,
        required_standard_field_ids: list[str],
        spaces: list[SemanticSpace],
    ) -> tuple[float, ValidationStatus, list[str]]:
        """Return (coverage 0–1, validation_status, blocking_reasons) for a
        deployment bound to semantic space(s).

        Coverage measures whether the PACK's required standard fields are
        actually mapped — not how curated the bound space is. A required
        standard field counts as covered only when ALL of:
          - an active FieldMapping exists for it on this deployment
          - the mapping's (physical_table, physical_column) belongs to one
            of the bound spaces
          - that target field's status is 'confirmed' in the space

        Semantic-space confirmation constrains a mapping (the target must be
        a vetted, in-scope field); it does not replace the mapping itself —
        see .design/asset_semantic_space_harness_operating_model.md §9.

        Logic mirrors compute_coverage():
          - coverage = required fields covered / total required fields
          - status = 'ready'       if coverage == 1.0 and last smoke passed
          - status = 'incomplete'  if 0 < coverage < 1.0
          - status = 'unvalidated' if no mappings at all
          - status = 'failed'      if coverage == 1.0 but smoke failed
        """
        if not required_standard_field_ids:
            return 1.0, "ready", []

        confirmed_keys = {
            (f.physical_table, f.physical_column)
            for space in spaces
            for entity in space.entities
            for f in entity.fields
            if f.status == FieldStatus.confirmed
        }

        active_mappings = self.get_mappings_dict_by_deployment(deployment_id)

        required_set = set(required_standard_field_ids)
        covered = {
            sf_id for sf_id in required_set
            if (mapping := active_mappings.get(sf_id)) is not None
            and (mapping.physical_table, mapping.physical_column) in confirmed_keys
        }
        uncovered = required_set - covered
        coverage = (len(required_set) - len(uncovered)) / len(required_set)

        blocking_reasons: list[str] = []
        if uncovered:
            blocking_reasons.append(
                f"Required fields not yet mapped to a confirmed in-space target: {', '.join(sorted(uncovered))}"
            )

        if coverage == 0.0:
            status: ValidationStatus = "unvalidated"
        elif uncovered:
            status = "incomplete"
        elif not self._get_last_smoke_passed(deployment_id):
            status = "failed"
            blocking_reasons.append("Last smoke test did not pass.")
        else:
            status = "ready"

        return round(coverage, 4), status, blocking_reasons

    def _row_to_deployment(
        self,
        row: sqlite3.Row,
        conn: sqlite3.Connection,
        pack_id: str,
        data_source_id: str,
    ) -> DeploymentInstance:
        """Build a DeploymentInstance with derived coverage/status."""
        deployment_id: str = str(row["deployment_id"])
        # Derive coverage from active mappings (cheap count — no full pack manifest here)
        count_row = conn.execute(
            "SELECT COUNT(DISTINCT standard_field_id) FROM field_mappings WHERE deployment_id=? AND status=?",
            (deployment_id, _MAPPING_STATUS_ACTIVE),
        ).fetchone()
        mapped_count: int = count_row[0] if count_row else 0
        smoke_passed: bool = bool(row["last_smoke_passed"])
        # Without the full required-field manifest we cannot compute exact coverage here;
        # callers who need accurate coverage should call compute_coverage() with the manifest.
        # Return raw mapped_count / 1 placeholder; API layer will call compute_coverage().
        coverage = 0.0 if mapped_count == 0 else min(float(mapped_count) / max(mapped_count, 1), 1.0)
        status: ValidationStatus = (
            "unvalidated" if mapped_count == 0
            else ("ready" if smoke_passed else "incomplete")
        )

        def _dt(val: object) -> datetime | None:
            if not val:
                return None
            try:
                return datetime.fromisoformat(str(val))
            except (ValueError, TypeError):
                return None

        raw_space_ids = row["semantic_space_ids"] if "semantic_space_ids" in row.keys() else None
        try:
            semantic_space_ids: list[str] = json.loads(raw_space_ids) if raw_space_ids else []
        except (TypeError, ValueError):
            semantic_space_ids = []

        row_keys = row.keys()
        is_active = bool(row["is_active"]) if "is_active" in row_keys else False
        activated_at = _dt(row["activated_at"]) if "activated_at" in row_keys else None
        activated_by = row["activated_by"] if "activated_by" in row_keys else None
        environment = str(row["environment"]) if "environment" in row_keys else "default"

        return DeploymentInstance(
            deployment_id=deployment_id,
            pack_id=str(row["pack_id"]),
            pack_version=str(row["pack_version"]),
            data_source_id=str(row["data_source_id"]),
            license_ref=row["license_ref"],
            validation_status=status,
            coverage=coverage,
            blocking_reasons=[],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
            semantic_space_ids=semantic_space_ids,
            environment=environment,
            is_active=is_active,
            activated_at=activated_at,
            activated_by=activated_by,
            extension_layer_id=(
                str(row["extension_layer_id"])
                if "extension_layer_id" in row_keys and row["extension_layer_id"]
                else None
            ),
        )

    # ── Mapping CRUD (extended with deployment_id and confirmation metadata) ─

    def upsert(self, mapping: FieldMapping) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO field_mappings
                    (mapping_id, pack_id, standard_field_id, data_source_id,
                     physical_table, physical_column, transform,
                     confidence, source, status, version, deployment_id,
                     created_at, updated_at, created_by, confirmed_by, confirmed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mapping.mapping_id, mapping.pack_id, mapping.standard_field_id,
                    mapping.data_source_id, mapping.physical_table, mapping.physical_column,
                    mapping.transform,
                    round(max(0.0, min(1.0, mapping.confidence)), 6),
                    mapping.source, mapping.status, mapping.version,
                    mapping.deployment_id,
                    mapping.created_at.isoformat() if mapping.created_at else now,
                    now,
                    mapping.created_by,
                    mapping.confirmed_by,
                    mapping.confirmed_at.isoformat() if mapping.confirmed_at else None,
                ),
            )
            conn.commit()
        logger.info(
            "field_mapping_store.upsert",
            extra={
                "mapping_id": mapping.mapping_id,
                "pack_id": mapping.pack_id,
                "data_source_id": mapping.data_source_id,
                "standard_field_id": mapping.standard_field_id,
                "source": mapping.source,
                "status": mapping.status,
                "confidence": mapping.confidence,
                "deployment_id": mapping.deployment_id,
            },
        )

    def get(self, pack_id: str, data_source_id: str, standard_field_id: str) -> FieldMapping | None:
        """Return the most-recently updated mapping for the given scope, or None."""
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM field_mappings
                WHERE pack_id=? AND data_source_id=? AND standard_field_id=?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (pack_id, data_source_id, standard_field_id),
            ).fetchone()
        return self._row_to_mapping(row) if row else None

    def get_pending_by_deployment(self, deployment_id: str) -> list[FieldMapping]:
        """Return all pending mappings for a deployment."""
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM field_mappings
                WHERE deployment_id=? AND status='pending'
                ORDER BY standard_field_id
                """,
                (deployment_id,),
            ).fetchall()
        return [self._row_to_mapping(r) for r in rows]

    def replace_pending_requests(
        self, deployment_id: str, pending: list[PendingMapping]
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                "DELETE FROM pending_mapping_requests WHERE deployment_id=?",
                (deployment_id,),
            )
            conn.executemany(
                """
                INSERT INTO pending_mapping_requests
                    (mapping_request_id, deployment_id, standard_field_id,
                     payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.mapping_request_id,
                        deployment_id,
                        item.standard_field_id,
                        item.model_dump_json(),
                        now,
                    )
                    for item in pending
                ],
            )
            conn.commit()

    def upsert_pending_request(self, deployment_id: str, pending: PendingMapping) -> None:
        """Replace the pending choice for one standard field without
        discarding other unresolved fields on the deployment."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                "DELETE FROM pending_mapping_requests WHERE deployment_id=? AND standard_field_id=?",
                (deployment_id, pending.standard_field_id),
            )
            conn.execute(
                """
                INSERT INTO pending_mapping_requests
                    (mapping_request_id, deployment_id, standard_field_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    pending.mapping_request_id,
                    deployment_id,
                    pending.standard_field_id,
                    pending.model_dump_json(),
                    now,
                ),
            )
            conn.commit()

    def list_pending_requests(self, deployment_id: str) -> list[PendingMapping]:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            rows = conn.execute(
                """
                SELECT payload_json FROM pending_mapping_requests
                WHERE deployment_id=? ORDER BY standard_field_id
                """,
                (deployment_id,),
            ).fetchall()
        return [PendingMapping.model_validate_json(row[0]) for row in rows]

    def get_pending_request(
        self, deployment_id: str, mapping_request_id: str
    ) -> PendingMapping | None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM pending_mapping_requests
                WHERE deployment_id=? AND mapping_request_id=?
                """,
                (deployment_id, mapping_request_id),
            ).fetchone()
        return PendingMapping.model_validate_json(row[0]) if row else None

    def delete_pending_request(self, deployment_id: str, mapping_request_id: str) -> None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                """
                DELETE FROM pending_mapping_requests
                WHERE deployment_id=? AND mapping_request_id=?
                """,
                (deployment_id, mapping_request_id),
            )
            conn.commit()

    def list_for_data_source(self, pack_id: str, data_source_id: str) -> list[FieldMapping]:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM field_mappings
                WHERE pack_id=? AND data_source_id=?
                ORDER BY standard_field_id, updated_at DESC
                """,
                (pack_id, data_source_id),
            ).fetchall()
        return [self._row_to_mapping(r) for r in rows]

    def get_mappings_dict(self, pack_id: str, data_source_id: str) -> dict[str, FieldMapping]:
        """Return {standard_field_id: FieldMapping} for active mappings only."""
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM field_mappings
                WHERE pack_id=? AND data_source_id=? AND status=?
                ORDER BY standard_field_id, updated_at DESC
                """,
                (pack_id, data_source_id, _MAPPING_STATUS_ACTIVE),
            ).fetchall()
        return {str(r["standard_field_id"]): self._row_to_mapping(r) for r in rows}

    def get_mappings_dict_by_deployment(
        self, deployment_id: str
    ) -> dict[str, FieldMapping]:
        """Return {standard_field_id: FieldMapping} for active mappings scoped to a deployment."""
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM field_mappings
                WHERE deployment_id=? AND status=?
                ORDER BY standard_field_id, updated_at DESC
                """,
                (deployment_id, _MAPPING_STATUS_ACTIVE),
            ).fetchall()
        return {str(r["standard_field_id"]): self._row_to_mapping(r) for r in rows}

    def reuse_deployment_mappings(
        self,
        source_deployment_id: str,
        target_deployment_id: str,
        target_pack_id: str,
    ) -> int:
        """Copy active base mappings into an extension deployment.

        The physical targets remain read-only facts from the active base; the
        copied rows are scoped to the extension so its validation and runtime
        projection are self-contained.
        """
        source = self.get_mappings_dict_by_deployment(source_deployment_id)
        target = self.get_mappings_dict_by_deployment(target_deployment_id)
        count = 0
        for field_id, mapping in source.items():
            if field_id in target:
                continue
            self.upsert(FieldMapping(
                mapping_id=f"map_{uuid4().hex[:16]}",
                pack_id=target_pack_id,
                standard_field_id=field_id,
                data_source_id=mapping.data_source_id,
                physical_table=mapping.physical_table,
                physical_column=mapping.physical_column,
                transform=mapping.transform,
                confidence=mapping.confidence,
                source="manual",
                status="active",
                deployment_id=target_deployment_id,
                created_by="base_deployment_reuse",
                confirmed_by=mapping.confirmed_by,
                confirmed_at=mapping.confirmed_at,
            ))
            count += 1
        return count

    def delete(self, pack_id: str, data_source_id: str, standard_field_id: str) -> bool:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            cursor = conn.execute(
                "DELETE FROM field_mappings WHERE pack_id=? AND data_source_id=? AND standard_field_id=?",
                (pack_id, data_source_id, standard_field_id),
            )
            conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info(
                "field_mapping_store.delete",
                extra={
                    "pack_id": pack_id,
                    "data_source_id": data_source_id,
                    "standard_field_id": standard_field_id,
                    "rows_deleted": cursor.rowcount,
                },
            )
        return deleted

    def count_mapped(self, pack_id: str, data_source_id: str) -> int:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT standard_field_id) FROM field_mappings WHERE pack_id=? AND data_source_id=? AND status=?",
                (pack_id, data_source_id, _MAPPING_STATUS_ACTIVE),
            ).fetchone()
        return row[0] if row else 0

    @staticmethod
    def _row_to_mapping(row: sqlite3.Row) -> FieldMapping:
        def _parse_dt(val: object) -> datetime | None:
            if not val:
                return None
            try:
                return datetime.fromisoformat(str(val))
            except (ValueError, TypeError):
                logger.warning(
                    "field_mapping_store.invalid_datetime",
                    extra={"value": str(val)},
                )
                return None

        return FieldMapping(
            mapping_id=str(row["mapping_id"]),
            pack_id=str(row["pack_id"]),
            standard_field_id=str(row["standard_field_id"]),
            data_source_id=str(row["data_source_id"]),
            physical_table=str(row["physical_table"]),
            physical_column=str(row["physical_column"]),
            transform=row["transform"],
            confidence=float(row["confidence"]),
            source=str(row["source"]),  # type: ignore[arg-type]
            status=str(row["status"]),  # type: ignore[arg-type]
            version=str(row["version"]),
            deployment_id=row["deployment_id"] if "deployment_id" in row.keys() else None,
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
            created_by=row["created_by"],
            confirmed_by=row["confirmed_by"] if "confirmed_by" in row.keys() else None,
            confirmed_at=_parse_dt(row["confirmed_at"]) if "confirmed_at" in row.keys() else None,
        )
