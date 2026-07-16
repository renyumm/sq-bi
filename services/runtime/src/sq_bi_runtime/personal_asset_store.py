from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from sq_bi_contracts.assets import AssetRef
from sq_bi_contracts.personal_assets import (
    PersonalAssetRecord,
    PersonalAssetScope,
    PersonalWorkspace,
    PromotionRecord,
)
from sq_bi_contracts.enums import AssetSourceType, MetricVisibility, SkillVisibility


class PersonalAssetStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                create table if not exists personal_workspaces (
                    workspace_id text primary key,
                    owner_user_id text not null,
                    org_id text not null,
                    payload text not null
                );
                create table if not exists personal_asset_records (
                    asset_id text not null,
                    version text not null,
                    workspace_id text not null,
                    owner_user_id text not null,
                    payload text not null,
                    primary key(asset_id, version)
                );
                create index if not exists idx_personal_assets_workspace
                    on personal_asset_records(workspace_id);
                create table if not exists personal_promotions (
                    promotion_id text primary key,
                    workspace_id text not null,
                    target_pack_id text not null,
                    payload text not null
                );
                """
            )
            conn.commit()

    @staticmethod
    def workspace_id_for(owner_user_id: str, org_id: str = "default") -> str:
        # P2 legacy personal AssetKey.source_id is the owner. Keeping the same
        # stable id avoids a second identity migration while making ownership explicit.
        return owner_user_id.strip() or "anonymous"

    def ensure_workspace(self, owner_user_id: str, org_id: str = "default") -> PersonalWorkspace:
        workspace = PersonalWorkspace(
            workspace_id=self.workspace_id_for(owner_user_id, org_id),
            owner_user_id=owner_user_id,
            org_id=org_id,
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                "insert or ignore into personal_workspaces(workspace_id, owner_user_id, org_id, payload) values(?,?,?,?)",
                (
                    workspace.workspace_id,
                    owner_user_id,
                    org_id,
                    workspace.model_dump_json(),
                ),
            )
            conn.commit()
        return workspace

    def save_asset(self, record: PersonalAssetRecord) -> PersonalAssetRecord:
        self.ensure_workspace(record.owner_user_id)
        self._validate_dependencies(record)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert into personal_asset_records(asset_id, version, workspace_id, owner_user_id, payload)
                values(?,?,?,?,?)
                on conflict(asset_id, version) do update set
                    workspace_id=excluded.workspace_id,
                    owner_user_id=excluded.owner_user_id,
                    payload=excluded.payload
                """,
                (
                    record.asset_ref.asset.asset_id,
                    record.asset_ref.version,
                    record.workspace_id,
                    record.owner_user_id,
                    record.model_dump_json(),
                ),
            )
            conn.commit()
        return record

    def get_asset(
        self, asset_ref: AssetRef, *, workspace_id: str | None = None
    ) -> PersonalAssetRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "select payload from personal_asset_records where asset_id=? and version=?",
                (asset_ref.asset.asset_id, asset_ref.version),
            ).fetchone()
        if row is None:
            return None
        record = PersonalAssetRecord.model_validate_json(row["payload"])
        if workspace_id is not None and record.workspace_id != workspace_id:
            return None
        return record

    def list_assets(self, workspace_id: str) -> list[PersonalAssetRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "select payload from personal_asset_records where workspace_id=? order by asset_id, version",
                (workspace_id,),
            ).fetchall()
        return [PersonalAssetRecord.model_validate_json(row["payload"]) for row in rows]

    def effective_scope(self, refs: list[AssetRef], workspace_id: str) -> PersonalAssetScope:
        records = [self.get_asset(ref, workspace_id=workspace_id) for ref in refs]
        if any(record is None for record in records):
            raise ValueError("DEPENDENCY_NOT_FOUND")
        scopes = [record.scope for record in records if record is not None]
        data_sources = {scope.data_source_id for scope in scopes}
        environments = {scope.environment for scope in scopes}
        if len(data_sources) != 1 or len(environments) != 1:
            raise ValueError("INCOMPATIBLE_DEPENDENCY_SCOPE")
        semantic_sets = [set(scope.semantic_space_ids) for scope in scopes if scope.semantic_space_ids]
        semantic_spaces = set.intersection(*semantic_sets) if semantic_sets else set()
        if semantic_sets and not semantic_spaces:
            raise ValueError("INCOMPATIBLE_DEPENDENCY_SCOPE")
        return PersonalAssetScope(
            workspace_id=workspace_id,
            data_source_id=next(iter(data_sources)),
            environment=next(iter(environments)),
            semantic_space_ids=sorted(semantic_spaces),
            physical_tables=sorted({item for scope in scopes for item in scope.physical_tables}),
            physical_fields=sorted({item for scope in scopes for item in scope.physical_fields}),
        )

    def save_promotion(self, record: PromotionRecord) -> PromotionRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                "insert into personal_promotions(promotion_id, workspace_id, target_pack_id, payload) values(?,?,?,?)",
                (
                    record.promotion_id,
                    record.workspace_id,
                    record.target_pack_id,
                    record.model_dump_json(),
                ),
            )
            conn.commit()
        return record

    def backfill_from_repository(self, repository: object) -> int:
        """Add scope rows for legacy personal assets without rewriting product payloads."""
        inserted = 0
        list_metrics = getattr(repository, "list_metrics", None)
        if callable(list_metrics):
            try:
                metrics = list_metrics()
            except Exception:  # noqa: BLE001 - legacy store may not be initialized yet
                metrics = []
            for metric in metrics:
                ref = getattr(metric, "asset_ref", None)
                if (
                    ref is None
                    or ref.asset.source_type != AssetSourceType.PERSONAL_WORKSPACE
                    or metric.visibility == MetricVisibility.OFFICIAL
                    or self.get_asset(ref) is not None
                ):
                    continue
                scope = PersonalAssetScope(
                    workspace_id=ref.asset.source_id,
                    data_source_id=metric.data_source_id,
                )
                self.save_asset(
                    new_personal_record(
                        asset_ref=ref,
                        name=metric.name,
                        owner_user_id=metric.owner,
                        scope=scope,
                    )
                )
                inserted += 1
        list_skills = getattr(repository, "list_skills", None)
        if callable(list_skills):
            try:
                skills = list_skills()
            except Exception:  # noqa: BLE001 - legacy store may not be initialized yet
                skills = []
            for skill in skills:
                ref = getattr(skill, "asset_ref", None)
                if (
                    ref is None
                    or ref.asset.source_type != AssetSourceType.PERSONAL_WORKSPACE
                    or skill.visibility == SkillVisibility.OFFICIAL
                    or self.get_asset(ref) is not None
                ):
                    continue
                try:
                    scope = self.effective_scope(list(skill.dependency_refs), ref.asset.source_id)
                except ValueError:
                    scope = PersonalAssetScope(
                        workspace_id=ref.asset.source_id,
                        data_source_id="unbound",
                    )
                self.save_asset(
                    new_personal_record(
                        asset_ref=ref,
                        name=skill.name,
                        owner_user_id=skill.owner_user_id or ref.asset.source_id,
                        scope=scope,
                        dependency_refs=list(skill.dependency_refs),
                    )
                )
                inserted += 1
        return inserted

    def get_promotion(self, promotion_id: str) -> PromotionRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "select payload from personal_promotions where promotion_id=?", (promotion_id,)
            ).fetchone()
        return PromotionRecord.model_validate_json(row["payload"]) if row else None

    def _validate_dependencies(self, record: PersonalAssetRecord) -> None:
        if record.asset_ref in record.dependency_refs:
            raise ValueError("DEPENDENCY_CYCLE")
        personal_refs = [
            ref for ref in record.dependency_refs
            if ref.asset.source_type == AssetSourceType.PERSONAL_WORKSPACE
        ]
        if self._dependency_path_reaches(
            personal_refs,
            record.asset_ref,
            record.workspace_id,
            set(),
        ):
            raise ValueError("DEPENDENCY_CYCLE")
        # Official/enterprise references are immutable catalog leaves. Their
        # runtime eligibility is established by the resolver before creation;
        # only personal-workspace dependencies participate in local cycle and
        # scope validation.
        if personal_refs and record.scope.data_source_id != "unbound":
            derived = self.effective_scope(personal_refs, record.workspace_id)
            if (
                derived.data_source_id != record.scope.data_source_id
                or derived.environment != record.scope.environment
            ):
                raise ValueError("INCOMPATIBLE_DEPENDENCY_SCOPE")

    def _dependency_path_reaches(
        self,
        refs: list[AssetRef],
        target: AssetRef,
        workspace_id: str,
        visited: set[tuple[str, str]],
    ) -> bool:
        for ref in refs:
            if ref == target:
                return True
            key = (ref.asset.asset_id, ref.version)
            if key in visited:
                continue
            visited.add(key)
            existing = self.get_asset(ref, workspace_id=workspace_id)
            if existing and self._dependency_path_reaches(
                existing.dependency_refs, target, workspace_id, visited
            ):
                return True
        return False


def new_personal_record(
    *,
    asset_ref: AssetRef,
    name: str,
    owner_user_id: str,
    scope: PersonalAssetScope,
    dependency_refs: list[AssetRef] | None = None,
    template_asset_ref: AssetRef | None = None,
) -> PersonalAssetRecord:
    return PersonalAssetRecord(
        asset_ref=asset_ref,
        name=name,
        workspace_id=scope.workspace_id,
        owner_user_id=owner_user_id,
        scope=scope,
        dependency_refs=dependency_refs or [],
        template_asset_ref=template_asset_ref,
        created_at=datetime.now(UTC),
    )
