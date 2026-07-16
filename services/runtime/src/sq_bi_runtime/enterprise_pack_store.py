"""SQLite-backed store for enterprise domain packs.

Schema
------
  enterprise_packs — one row per pack identity; draft stored as JSON blob.
  pack_snapshots   — immutable published snapshots (draft_json frozen at publish).

Official packs (PackRegistry) are NEVER written here; this store is read-only
with respect to official pack files.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sq_bi_contracts.enterprise_pack import (
    CreateEnterprisePackRequest,
    EnterprisePack,
    EnterprisePackDraft,
    ExtensionLayerState,
    PackCreateMode,
    PackEnterpriseField,
    PackEnterpriseMetric,
    PackExtensionLayer,
    PackVersionState,
)

logger = logging.getLogger(__name__)

_INITIAL_VERSION = "0.1.0"
_PACK_ID_PREFIX = "ep_"
_EXTENSION_ID_PREFIX = "ext_"


def _bump_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) == 3:
        try:
            return f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"
        except ValueError:
            pass
    return version + ".1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EnterprisePackStore:
    """Persists enterprise domain packs separately from the read-only official registry."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._lock = threading.Lock()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"Cannot create enterprise-pack store directory {self._path.parent}: {exc}"
            ) from exc
        self._init_db()

    def _init_db(self) -> None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS enterprise_packs (
                    pack_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    business_context TEXT,
                    data_source_id TEXT NOT NULL DEFAULT '',
                    version TEXT NOT NULL DEFAULT '0.1.0',
                    version_state TEXT NOT NULL DEFAULT 'draft',
                    base_pack_id TEXT,
                    base_pack_version TEXT,
                    create_mode TEXT NOT NULL DEFAULT 'blank',
                    draft_json TEXT NOT NULL DEFAULT '{}',
                    created_by TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT,
                    updated_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_ep_data_source
                ON enterprise_packs (data_source_id);

                CREATE TABLE IF NOT EXISTS pack_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    pack_id TEXT NOT NULL REFERENCES enterprise_packs(pack_id),
                    version TEXT NOT NULL,
                    draft_json TEXT NOT NULL,
                    published_by TEXT,
                    published_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_snap_pack
                ON pack_snapshots (pack_id, version);

                CREATE TABLE IF NOT EXISTS pack_extension_layers (
                    extension_id TEXT PRIMARY KEY,
                    base_pack_id TEXT NOT NULL UNIQUE,
                    base_pack_version TEXT NOT NULL,
                    base_kind TEXT NOT NULL,
                    version TEXT NOT NULL DEFAULT '0.1.0',
                    version_state TEXT NOT NULL DEFAULT 'draft',
                    state TEXT NOT NULL DEFAULT 'draft',
                    draft_json TEXT NOT NULL DEFAULT '{}',
                    audit_json TEXT NOT NULL DEFAULT '[]',
                    created_by TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT,
                    updated_at TEXT
                );
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(enterprise_packs)")}
            # Keep old columns for a non-destructive migration, but move their
            # values into evidence and never expose them as a pack definition.
            for name, definition in (
                ("legacy_review_required", "INTEGER NOT NULL DEFAULT 0"),
                ("legacy_evidence_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("business_context", "TEXT"),
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE enterprise_packs ADD COLUMN {name} {definition}")
            conn.execute(
                """
                UPDATE enterprise_packs
                SET legacy_review_required=1,
                    legacy_evidence_json=json_object(
                        'data_source_id', data_source_id,
                        'create_mode', create_mode,
                        'draft', draft_json
                    )
                WHERE data_source_id <> '' AND legacy_review_required=0
                """
            )
            # Modes retired by the portable two-mode model (clone_enterprise,
            # ai_from_profile) can no longer be loaded as PackCreateMode. Fold
            # any row using a retired mode into a review-required blank draft,
            # preserving its original mode as evidence rather than dropping it.
            valid_modes = tuple(m.value for m in PackCreateMode)
            placeholders = ", ".join("?" for _ in valid_modes)
            conn.execute(
                f"""
                UPDATE enterprise_packs
                SET legacy_review_required=1,
                    legacy_evidence_json=json_object(
                        'data_source_id', data_source_id,
                        'create_mode', create_mode,
                        'draft', draft_json
                    ),
                    create_mode='blank'
                WHERE create_mode NOT IN ({placeholders})
                """,
                valid_modes,
            )
            # The former `extend_official` rows were top-level enterprise
            # records.  Preserve their authored delta as a base-owned layer,
            # then hide them from new top-level listings.  When historic data
            # contains several such rows we retain all but the earliest as
            # review evidence instead of silently merging ambiguous deltas.
            conn.row_factory = sqlite3.Row
            legacy_extensions = conn.execute(
                """
                SELECT * FROM enterprise_packs
                WHERE create_mode='extend_official' AND base_pack_id IS NOT NULL
                ORDER BY created_at, pack_id
                """
            ).fetchall()
            seen_bases: set[str] = set()
            for row in legacy_extensions:
                base_id = str(row["base_pack_id"])
                evidence = json.dumps({
                    "migrated_from_pack_id": row["pack_id"],
                    "historic_create_mode": "extend_official",
                })
                if base_id not in seen_bases:
                    seen_bases.add(base_id)
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO pack_extension_layers
                            (extension_id, base_pack_id, base_pack_version,
                             base_kind, version, version_state, state,
                             draft_json, audit_json, created_by, created_at, updated_at)
                        VALUES (?, ?, ?, 'official', ?, ?, 'inactive', ?, ?, ?, ?, ?)
                        """,
                        (
                            _EXTENSION_ID_PREFIX + uuid4().hex[:16], base_id,
                            row["base_pack_version"] or "legacy", row["version"],
                            row["version_state"], row["draft_json"], evidence,
                            row["created_by"], row["created_at"], row["updated_at"],
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE enterprise_packs
                        SET legacy_review_required=1,
                            legacy_evidence_json=json_object(
                                'reason', 'multiple_historic_extension_layers',
                                'base_pack_id', base_pack_id,
                                'draft', draft_json
                            )
                        WHERE pack_id=?
                        """,
                        (row["pack_id"],),
                    )
            conn.row_factory = None
        logger.info("enterprise_pack_store.init", extra={"db_path": str(self._path)})

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def create(self, req: CreateEnterprisePackRequest) -> EnterprisePack:
        pack_id = _PACK_ID_PREFIX + uuid4().hex[:16]
        now = _now()
        draft = EnterprisePackDraft()
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                """
                INSERT INTO enterprise_packs
                    (pack_id, name, description, business_context, data_source_id, version,
                     version_state, base_pack_id, base_pack_version,
                     create_mode, draft_json, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pack_id, req.name, req.description, req.business_context, "",
                    _INITIAL_VERSION, PackVersionState.draft.value,
                    req.base_pack_id, req.base_pack_version,
                    req.mode.value,
                    draft.model_dump_json(),
                    req.created_by, now, now,
                ),
            )
        return self._get_or_raise(pack_id)

    def get(self, pack_id: str) -> EnterprisePack | None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM enterprise_packs WHERE pack_id=?", (pack_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_pack(row)

    def list(self) -> list[EnterprisePack]:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM enterprise_packs ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_pack(r) for r in rows]

    def list_base_packs(self) -> list[EnterprisePack]:
        """Return standalone enterprise bases only, never legacy layers."""
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM enterprise_packs
                WHERE base_pack_id IS NULL AND create_mode='blank'
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [self._row_to_pack(row) for row in rows]

    def delete(self, pack_id: str) -> None:
        """Delete one enterprise-owned pack and its immutable snapshots."""
        self._get_or_raise(pack_id)
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute("DELETE FROM pack_snapshots WHERE pack_id=?", (pack_id,))
            cursor = conn.execute("DELETE FROM enterprise_packs WHERE pack_id=?", (pack_id,))
        if cursor.rowcount == 0:
            raise KeyError(f"Enterprise pack not found: {pack_id}")

    # ── Base-owned extension layers ─────────────────────────────────────────

    def get_extension_for_base(self, base_pack_id: str) -> PackExtensionLayer | None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM pack_extension_layers WHERE base_pack_id=?",
                (base_pack_id,),
            ).fetchone()
        return self._row_to_extension(row) if row is not None else None

    def get_extension(self, extension_id: str) -> PackExtensionLayer | None:
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM pack_extension_layers WHERE extension_id=?",
                (extension_id,),
            ).fetchone()
        return self._row_to_extension(row) if row is not None else None

    def list_extensions(self, *, active_only: bool = False) -> list[PackExtensionLayer]:
        query = "SELECT * FROM pack_extension_layers"
        params: tuple[object, ...] = ()
        if active_only:
            query += " WHERE state=?"
            params = (ExtensionLayerState.active.value,)
        query += " ORDER BY created_at"
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_extension(row) for row in rows]

    def get_or_create_extension(
        self,
        *,
        base_pack_id: str,
        base_pack_version: str,
        base_kind: str,
        created_by: str = "system",
    ) -> PackExtensionLayer:
        if base_kind not in {"official", "enterprise"}:
            raise ValueError("base_kind must be 'official' or 'enterprise'.")
        if self.get_extension(base_pack_id) is not None:
            raise ValueError("An extension layer cannot own a child extension layer.")
        existing = self.get_extension_for_base(base_pack_id)
        if existing is not None:
            return existing
        now = _now()
        extension_id = _EXTENSION_ID_PREFIX + uuid4().hex[:16]
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO pack_extension_layers
                        (extension_id, base_pack_id, base_pack_version, base_kind,
                         version, version_state, state, draft_json, audit_json,
                         created_by, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        extension_id, base_pack_id, base_pack_version, base_kind,
                        _INITIAL_VERSION, PackVersionState.draft.value,
                        ExtensionLayerState.draft.value,
                        EnterprisePackDraft().model_dump_json(),
                        json.dumps([{"at": now, "action": "created", "by": created_by}]),
                        created_by, now, now,
                    ),
                )
            except sqlite3.IntegrityError:
                # Another request won the single-layer race; opening it is
                # the specified behaviour, never create a second identity.
                pass
        layer = self.get_extension_for_base(base_pack_id)
        if layer is None:
            raise RuntimeError("Could not create extension layer.")
        return layer

    def update_extension_draft(
        self, extension_id: str, draft: EnterprisePackDraft, *, updated_by: str = "system"
    ) -> PackExtensionLayer:
        layer = self._get_extension_or_raise(extension_id)
        if layer.state == ExtensionLayerState.archived:
            raise ValueError("Archived extension must be restored before editing.")
        self._validate_delta_identifiers(draft)
        self._write_extension(
            extension_id, draft=draft, audit_action="edited", actor=updated_by,
        )
        return self._get_extension_or_raise(extension_id)

    @staticmethod
    def _validate_delta_identifiers(draft: EnterprisePackDraft) -> None:
        """Reject duplicate IDs in an additive layer before base comparison.

        Base-collision checks require the resolved pinned base and are done by
        the API resolver.  Keeping this part in persistence makes malformed
        extension drafts impossible through every API entry point.
        """
        for label, values in (
            ("field", [item.field_id for item in draft.fields]),
            ("metric", [item.metric_code for item in draft.metrics]),
            ("skill", [item.skill_id for item in draft.skills]),
            ("report", [item.report_id for item in draft.reports]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"Extension draft contains duplicate {label} identifiers.")

    def set_extension_state(
        self, extension_id: str, state: ExtensionLayerState, *, actor: str = "system"
    ) -> PackExtensionLayer:
        layer = self._get_extension_or_raise(extension_id)
        if state == ExtensionLayerState.draft:
            raise ValueError("Use update_extension_draft instead of resetting lifecycle to draft.")
        if layer.state == ExtensionLayerState.archived and state not in {ExtensionLayerState.inactive, ExtensionLayerState.active}:
            raise ValueError("Archived extension can only be restored to inactive or active.")
        self._write_extension(extension_id, state=state, audit_action=state.value, actor=actor)
        return self._get_extension_or_raise(extension_id)

    def publish_extension(
        self, extension_id: str, *, version: str | None = None, actor: str = "system"
    ) -> PackExtensionLayer:
        layer = self._get_extension_or_raise(extension_id)
        if layer.state == ExtensionLayerState.archived:
            raise ValueError("Archived extension must be restored before publishing.")
        self._write_extension(
            extension_id,
            version=version or layer.version,
            version_state=PackVersionState.published,
            state=ExtensionLayerState.active,
            audit_action="published",
            actor=actor,
        )
        return self._get_extension_or_raise(extension_id)

    def delete_extension(self, extension_id: str, *, active_deployment_ids: list[str]) -> bool:
        if active_deployment_ids:
            raise ValueError(
                "Cannot delete an extension layer while active deployments use it: "
                + ", ".join(active_deployment_ids)
            )
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            cursor = conn.execute(
                "DELETE FROM pack_extension_layers WHERE extension_id=?", (extension_id,)
            )
        return cursor.rowcount > 0

    def _write_extension(
        self,
        extension_id: str,
        *,
        draft: EnterprisePackDraft | None = None,
        state: ExtensionLayerState | None = None,
        version: str | None = None,
        version_state: PackVersionState | None = None,
        audit_action: str,
        actor: str,
    ) -> None:
        layer = self._get_extension_or_raise(extension_id)
        now = _now()
        audit = [*layer.audit, {"at": now, "action": audit_action, "by": actor}]
        updates: list[tuple[str, object]] = [
            ("audit_json", json.dumps(audit)), ("updated_at", now),
        ]
        if draft is not None:
            updates.append(("draft_json", draft.model_dump_json()))
        if state is not None:
            updates.append(("state", state.value))
        if version is not None:
            updates.append(("version", version))
        if version_state is not None:
            updates.append(("version_state", version_state.value))
        clause = ", ".join(f"{column}=?" for column, _ in updates)
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                f"UPDATE pack_extension_layers SET {clause} WHERE extension_id=?",
                [value for _, value in updates] + [extension_id],
            )

    def _get_extension_or_raise(self, extension_id: str) -> PackExtensionLayer:
        layer = self.get_extension(extension_id)
        if layer is None:
            raise KeyError(f"Extension layer not found: {extension_id}")
        return layer

    def update_draft(
        self,
        pack_id: str,
        draft: EnterprisePackDraft,
        *,
        updated_by: str = "system",
    ) -> EnterprisePack:
        """Replace the draft of a pack. Rejects writes to published snapshots."""
        pack = self._get_or_raise(pack_id)
        if pack.version_state == PackVersionState.published:
            raise ValueError(
                f"Pack {pack_id} is published (v{pack.version}). "
                "Create a new draft via fork_for_edit() before editing."
            )
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                "UPDATE enterprise_packs SET draft_json=?, updated_at=? WHERE pack_id=?",
                (draft.model_dump_json(), _now(), pack_id),
            )
        return self._get_or_raise(pack_id)

    def update_meta(
        self,
        pack_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        business_context: str | None = None,
        base_pack_version: str | None = None,
    ) -> EnterprisePack:
        """Update pack metadata fields without touching the draft."""
        pack = self._get_or_raise(pack_id)
        if pack.version_state == PackVersionState.published:
            raise ValueError(f"Pack {pack_id} is published — fork first to edit.")
        fields: list[tuple[str, object]] = []
        if name is not None:
            fields.append(("name", name))
        if description is not None:
            fields.append(("description", description))
        if business_context is not None:
            fields.append(("business_context", business_context))
        if base_pack_version is not None:
            fields.append(("base_pack_version", base_pack_version))
        if not fields:
            return pack
        set_clause = ", ".join(f"{k}=?" for k, _ in fields) + ", updated_at=?"
        values = [v for _, v in fields] + [_now(), pack_id]
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                f"UPDATE enterprise_packs SET {set_clause} WHERE pack_id=?",
                values,
            )
        return self._get_or_raise(pack_id)

    # ── Versioning & publish ──────────────────────────────────────────────────

    def publish(self, pack_id: str, *, version: str | None = None, published_by: str = "system") -> EnterprisePack:
        """Freeze the draft as an immutable published snapshot.

        If *version* is provided it overrides the current version. Otherwise the
        existing version is used (caller is responsible for bumping before publishing).
        """
        pack = self._get_or_raise(pack_id)
        if pack.version_state == PackVersionState.published:
            raise ValueError(f"Pack {pack_id} is already published at v{pack.version}.")
        target_version = version or pack.version
        snapshot_id = f"snap_{uuid4().hex[:16]}"
        now = _now()
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                """
                INSERT INTO pack_snapshots (snapshot_id, pack_id, version, draft_json, published_by, published_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (snapshot_id, pack_id, target_version, pack.draft.model_dump_json(), published_by, now),
            )
            conn.execute(
                "UPDATE enterprise_packs SET version_state=?, version=?, updated_at=? WHERE pack_id=?",
                (PackVersionState.published.value, target_version, now, pack_id),
            )
        logger.info(
            "enterprise_pack.published",
            extra={"pack_id": pack_id, "version": target_version, "snapshot_id": snapshot_id},
        )
        return self._get_or_raise(pack_id)

    def fork_for_edit(self, pack_id: str, *, forked_by: str = "system") -> EnterprisePack:
        """Create a new draft at the next version. Published snapshot is retained."""
        pack = self._get_or_raise(pack_id)
        if pack.version_state != PackVersionState.published:
            raise ValueError(f"Pack {pack_id} is already a draft — no fork needed.")
        new_version = _bump_version(pack.version)
        now = _now()
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            conn.execute(
                "UPDATE enterprise_packs SET version_state=?, version=?, updated_at=? WHERE pack_id=?",
                (PackVersionState.draft.value, new_version, now, pack_id),
            )
        logger.info(
            "enterprise_pack.forked",
            extra={"pack_id": pack_id, "new_version": new_version},
        )
        return self._get_or_raise(pack_id)

    def get_snapshot(self, pack_id: str, version: str) -> EnterprisePackDraft | None:
        """Load a frozen published snapshot by version."""
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            row = conn.execute(
                "SELECT draft_json FROM pack_snapshots WHERE pack_id=? AND version=?",
                (pack_id, version),
            ).fetchone()
        if row is None:
            return None
        return EnterprisePackDraft.model_validate_json(row[0])

    def list_snapshots(
        self,
        pack_id: str | None = None,
    ) -> list[tuple[EnterprisePack, str, EnterprisePackDraft]]:
        """List immutable published snapshots without projecting them to runtime."""
        with self._lock, sqlite3.connect(str(self._path)) as conn:
            if pack_id is None:
                rows = conn.execute(
                    "select pack_id, version, draft_json from pack_snapshots order by published_at"
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    select pack_id, version, draft_json from pack_snapshots
                    where pack_id = ? order by published_at
                    """,
                    (pack_id,),
                ).fetchall()
        snapshots: list[tuple[EnterprisePack, str, EnterprisePackDraft]] = []
        for snapshot_pack_id, version, draft_json in rows:
            pack = self.get(snapshot_pack_id)
            if pack is not None:
                snapshots.append(
                    (pack, version, EnterprisePackDraft.model_validate_json(draft_json))
                )
        return snapshots

    # ── Internal ─────────────────────────────────────────────────────────────

    def _get_or_raise(self, pack_id: str) -> EnterprisePack:
        pack = self.get(pack_id)
        if pack is None:
            raise KeyError(f"Enterprise pack not found: {pack_id}")
        return pack

    @staticmethod
    def _row_to_pack(row: sqlite3.Row) -> EnterprisePack:
        draft_data = json.loads(row["draft_json"])
        return EnterprisePack(
            pack_id=row["pack_id"],
            name=row["name"],
            description=row["description"],
            business_context=row["business_context"],
            version=row["version"],
            version_state=PackVersionState(row["version_state"]),
            base_pack_id=row["base_pack_id"],
            base_pack_version=row["base_pack_version"],
            legacy_review_required=bool(row["legacy_review_required"]),
            legacy_authoring_evidence=json.loads(row["legacy_evidence_json"]),
            create_mode=PackCreateMode(row["create_mode"]),
            draft=EnterprisePackDraft.model_validate(draft_data),
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_extension(row: sqlite3.Row) -> PackExtensionLayer:
        return PackExtensionLayer(
            extension_id=row["extension_id"],
            base_pack_id=row["base_pack_id"],
            base_pack_version=row["base_pack_version"],
            base_kind=row["base_kind"],
            version=row["version"],
            version_state=PackVersionState(row["version_state"]),
            state=ExtensionLayerState(row["state"]),
            draft=EnterprisePackDraft.model_validate_json(row["draft_json"]),
            audit=json.loads(row["audit_json"]),
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
