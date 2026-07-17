from __future__ import annotations

import json
import os
import re
import sqlite3
from io import BytesIO
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.sax.saxutils import escape as xml_escape
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import BaseModel, Field
from sq_bi_contracts.assets import AssetKey, AssetRef
from sq_bi_contracts.enums import AssetSourceType, AssetType, MetricVisibility, SkillVisibility
from sq_bi_contracts.metrics import MetricDefinition, MetricFormula
from sq_bi_contracts.skills import SkillDefinition, SkillResolveRequest, SkillResolveResult

from .repository import FileBackedSemanticRepository
from .sql_validation import validate_metric_select_sql
from .synonyms import is_partial_match, match_synonyms, normalize_text


DEFAULT_STORE_PATH = Path(".local/sqbi.sqlite3")
DEFAULT_FILE_ROOT = Path(".local/files")


class ReportRecord(BaseModel):
    report_id: str
    name: str
    description: str
    visibility: str = "private"
    owner: str
    outputTypes: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    template: str | None = None
    templateMode: str | None = None
    templateLabel: str | None = None
    flow: str
    sections: list[str] = Field(default_factory=list)
    analysis_chain: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    schedule: dict[str, Any] | None = None
    artifact_url: str | None = None
    publish_url: str | None = None
    version: str = "1.0.0"
    asset_ref: AssetRef | None = None
    dependency_refs: list[AssetRef] = Field(default_factory=list)
    data_source_bindings: list[dict[str, Any]] = Field(default_factory=list)
    execution_contract: dict[str, Any] | None = None
    build_trace: list[dict[str, Any]] = Field(default_factory=list)
    validation_evidence: list[dict[str, Any]] = Field(default_factory=list)


class GeneratedFileRecord(BaseModel):
    file_id: str
    owner_user_id: str
    entity_type: str
    entity_id: str
    filename: str
    content_type: str
    byte_size: int
    download_url: str
    view_url: str | None = None
    render_provider: str = "cloud"
    created_at: str
    derived_from: str | None = None
    converter_version: str | None = None


class ScheduledJobRecord(BaseModel):
    job_id: str
    owner_user_id: str
    entity_type: str
    entity_id: str
    status: str
    schedule_text: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class ChatMessageRecord(BaseModel):
    message_id: str
    session_id: str
    user_id: str
    sender: str = "user"
    text: str
    payload: dict[str, Any] = Field(default_factory=dict)
    archived: bool = False
    created_at: str
    updated_at: str


class ChatSessionRecord(BaseModel):
    session_id: str
    user_id: str
    title: str
    archived: bool = False
    message_count: int = 0
    created_at: str
    updated_at: str


class MetricDependencyRecord(BaseModel):
    source_type: str
    source_id: str
    source_name: str
    relation_type: str = "uses"
    blocking: bool = False


class SQLiteProductRepository(FileBackedSemanticRepository):
    """SQLite-backed product catalog seeded from the TMS semantic YAML.

    The YAML remains the immutable source for physical catalog metadata. Product
    entities users create or share are persisted under .local so they survive
    frontend refreshes without entering git.
    """

    def __init__(
        self,
        data_file: Path | str,
        *,
        store_path: Path | str = DEFAULT_STORE_PATH,
        file_root: Path | str = DEFAULT_FILE_ROOT,
    ) -> None:
        super().__init__(data_file=data_file, user_metrics_file=None)
        self.store_path = Path(store_path)
        self.file_root = Path(file_root)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_root.mkdir(parents=True, exist_ok=True)
        for child in ("generated", "templates"):
            (self.file_root / child).mkdir(parents=True, exist_ok=True)
        self._seed_default_report_templates()
        self._init_schema()
        self._seed_if_needed()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store_path)
        conn.row_factory = sqlite3.Row
        return conn

    def asset_revision(self) -> str:
        with self._connect() as conn:
            row = conn.execute(
                """
                select
                  (select count(*) from product_metrics) as metric_count,
                  coalesce((select max(updated_at) from product_metrics), '') as metric_updated_at,
                  (select count(*) from product_skills) as skill_count,
                  coalesce((select max(updated_at) from product_skills), '') as skill_updated_at,
                  (select count(*) from product_reports) as report_count,
                  coalesce((select max(updated_at) from product_reports), '') as report_updated_at
                """
            ).fetchone()
        return "|".join(str(row[key]) for key in row.keys())

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists meta (
                  key text primary key,
                  value text not null
                );
                create table if not exists users (
                  user_id text primary key,
                  payload text not null,
                  created_at text not null,
                  updated_at text not null
                );
                create table if not exists product_metrics (
                  asset_id text primary key,
                  source_type text not null,
                  source_id text not null,
                  asset_type text not null check(asset_type = 'metric'),
                  local_code text not null,
                  version text not null,
                  metric_code text not null,
                  visibility text not null,
                  owner_user_id text not null,
                  payload text not null,
                  created_at text not null,
                  updated_at text not null,
                  unique(source_type, source_id, local_code)
                );
                create table if not exists product_skills (
                  asset_id text primary key,
                  source_type text not null,
                  source_id text not null,
                  asset_type text not null check(asset_type = 'skill'),
                  local_code text not null,
                  version text not null,
                  skill_id text not null,
                  visibility text not null,
                  owner_user_id text not null,
                  skill_type text not null,
                  payload text not null,
                  created_at text not null,
                  updated_at text not null,
                  unique(source_type, source_id, local_code)
                );
                create table if not exists product_reports (
                  asset_id text primary key,
                  source_type text not null,
                  source_id text not null,
                  asset_type text not null check(asset_type = 'report'),
                  local_code text not null,
                  version text not null,
                  report_id text not null,
                  visibility text not null,
                  owner_user_id text not null,
                  payload text not null,
                  created_at text not null,
                  updated_at text not null,
                  unique(source_type, source_id, local_code)
                );
                create table if not exists share_records (
                  share_id text primary key,
                  entity_type text not null,
                  entity_id text not null,
                  created_by text not null,
                  payload text not null,
                  created_at text not null
                );
                create table if not exists entity_versions (
                  version_id text primary key,
                  entity_type text not null,
                  entity_id text not null,
                  version text not null,
                  payload text not null,
                  created_by text not null,
                  created_at text not null
                );
                create table if not exists generated_files (
                  file_id text primary key,
                  owner_user_id text not null,
                  entity_type text not null,
                  entity_id text not null,
                  filename text not null,
                  path text not null,
                  content_type text not null,
                  byte_size integer not null,
                  payload text not null,
                  created_at text not null
                );
                create table if not exists scheduled_jobs (
                  job_id text primary key,
                  owner_user_id text not null,
                  entity_type text not null,
                  entity_id text not null,
                  status text not null,
                  schedule_text text not null,
                  payload text not null,
                  created_at text not null,
                  updated_at text not null
                );
                create table if not exists chat_sessions (
                  session_id text primary key,
                  user_id text not null,
                  title text not null,
                  archived integer not null default 0,
                  created_at text not null,
                  updated_at text not null
                );
                create table if not exists chat_messages (
                  message_id text primary key,
                  session_id text not null,
                  user_id text not null,
                  sender text not null default 'user',
                  text text not null,
                  payload text not null default '{}',
                  archived integer not null default 0,
                  created_at text not null,
                  updated_at text not null
                );
                """
            )
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        self._migrate_asset_identity(conn)
        columns = {row["name"] for row in conn.execute("pragma table_info(generated_files)")}
        if "filename" not in columns:
            conn.execute("alter table generated_files add column filename text not null default ''")
        if "byte_size" not in columns:
            conn.execute("alter table generated_files add column byte_size integer not null default 0")
        chat_columns = {row["name"] for row in conn.execute("pragma table_info(chat_messages)")}
        if "session_id" not in chat_columns:
            conn.execute("alter table chat_messages add column session_id text not null default ''")
        if "sender" not in chat_columns:
            conn.execute("alter table chat_messages add column sender text not null default 'user'")
        if "payload" not in chat_columns:
            conn.execute("alter table chat_messages add column payload text not null default '{}'")
        self._migrate_chat_sessions(conn)

    def _migrate_asset_identity(self, conn: sqlite3.Connection) -> None:
        legacy_ids: dict[tuple[str, str], str] = {}
        table_specs = (
            ("product_metrics", "metric_code", AssetType.METRIC),
            ("product_skills", "skill_id", AssetType.SKILL),
            ("product_reports", "report_id", AssetType.REPORT),
        )
        for table, local_column, asset_type in table_specs:
            columns = {row["name"] for row in conn.execute(f"pragma table_info({table})")}
            if "asset_id" not in columns:
                rows = conn.execute(f"select * from {table}").fetchall()
                legacy_table = f"{table}_legacy_asset_identity"
                conn.execute(f"alter table {table} rename to {legacy_table}")
                self._create_product_asset_table(conn, table, local_column, asset_type)
                for row in rows:
                    payload = json.loads(row["payload"])
                    if asset_type == AssetType.METRIC:
                        definition = self._metric_with_asset_ref(
                            MetricDefinition(**payload), row["owner_user_id"]
                        )
                        visibility = definition.visibility.value
                        version = definition.version
                        extra = ()
                    elif asset_type == AssetType.SKILL:
                        definition = self._skill_with_asset_ref(
                            SkillDefinition(**payload), row["owner_user_id"]
                        )
                        visibility = definition.visibility.value
                        version = _skill_version(definition)
                        extra = (row["skill_type"],)
                    else:
                        definition = self._report_with_asset_ref(
                            ReportRecord(**payload), row["owner_user_id"]
                        )
                        visibility = definition.visibility
                        version = definition.version
                        extra = ()
                    ref = definition.asset_ref
                    assert ref is not None
                    values = (
                        ref.asset.asset_id,
                        ref.asset.source_type.value,
                        ref.asset.source_id,
                        ref.asset.asset_type.value,
                        ref.asset.local_code,
                        version,
                        row[local_column],
                        visibility,
                        row["owner_user_id"],
                        *extra,
                        definition.model_dump_json(),
                        row["created_at"],
                        row["updated_at"],
                    )
                    placeholders = ", ".join("?" for _ in values)
                    conn.execute(f"insert into {table} values ({placeholders})", values)
                    legacy_ids[(asset_type.value, row[local_column])] = ref.asset.asset_id
                conn.execute(f"drop table {legacy_table}")
            else:
                for row in conn.execute(f"select asset_id, {local_column} from {table}"):
                    legacy_ids[(asset_type.value, row[local_column])] = row["asset_id"]
            conn.execute(
                f"create index if not exists idx_{table}_{local_column} "
                f"on {table}({local_column})"
            )
        self._migrate_entity_version_ids(conn, legacy_ids)

    @staticmethod
    def _create_product_asset_table(
        conn: sqlite3.Connection,
        table: str,
        local_column: str,
        asset_type: AssetType,
    ) -> None:
        skill_type_column = "skill_type text not null," if asset_type == AssetType.SKILL else ""
        conn.execute(
            f"""
            create table {table} (
              asset_id text primary key,
              source_type text not null,
              source_id text not null,
              asset_type text not null check(asset_type = '{asset_type.value}'),
              local_code text not null,
              version text not null,
              {local_column} text not null,
              visibility text not null,
              owner_user_id text not null,
              {skill_type_column}
              payload text not null,
              created_at text not null,
              updated_at text not null,
              unique(source_type, source_id, local_code)
            )
            """
        )

    @staticmethod
    def _migrate_entity_version_ids(
        conn: sqlite3.Connection,
        legacy_ids: dict[tuple[str, str], str],
    ) -> None:
        rows = conn.execute(
            "select version_id, entity_type, entity_id, version, payload from entity_versions"
        ).fetchall()
        asset_tables = {
            AssetType.METRIC.value: "product_metrics",
            AssetType.SKILL.value: "product_skills",
            AssetType.REPORT.value: "product_reports",
        }
        for row in rows:
            source_table = asset_tables.get(row["entity_type"])
            if source_table is None:
                continue
            asset_id = legacy_ids.get((row["entity_type"], row["entity_id"]))
            if asset_id is None or row["entity_id"] == asset_id:
                continue
            payload = json.loads(row["payload"])
            if not payload.get("asset_ref"):
                source_row = conn.execute(
                    f"select payload from {source_table} where asset_id = ?",
                    (asset_id,),
                ).fetchone()
                if source_row:
                    current_payload = json.loads(source_row["payload"])
                    payload["asset_ref"] = current_payload.get("asset_ref")
                    if payload["asset_ref"]:
                        payload["asset_ref"]["version"] = row["version"]
            conn.execute(
                "update entity_versions set entity_id = ?, payload = ? where version_id = ?",
                (asset_id, _json(payload), row["version_id"]),
            )

    def _metric_with_asset_ref(
        self,
        metric: MetricDefinition,
        owner_user_id: str,
        *,
        force_personal: bool = False,
    ) -> MetricDefinition:
        source_type = AssetSourceType.PERSONAL_WORKSPACE
        source_id = owner_user_id or metric.owner or "anonymous"
        if not force_personal and metric.metric_code in self.official_metrics:
            source_type = AssetSourceType.OFFICIAL_PACK
            source_id = "tms"
        if force_personal:
            _validate_personal_ref_owner(metric.asset_ref, source_id)
        ref = _validated_asset_ref(
            metric.asset_ref,
            source_type=source_type,
            source_id=source_id,
            asset_type=AssetType.METRIC,
            local_code=metric.metric_code,
            version=metric.version,
        )
        return metric.model_copy(update={"asset_ref": ref})

    def _skill_with_asset_ref(
        self,
        skill: SkillDefinition,
        owner_user_id: str,
        *,
        force_personal: bool = False,
    ) -> SkillDefinition:
        source_type = AssetSourceType.PERSONAL_WORKSPACE
        source_id = owner_user_id or skill.owner_user_id or "anonymous"
        if not force_personal and skill.skill_id in self.skills:
            source_type = AssetSourceType.OFFICIAL_PACK
            source_id = "tms"
        if force_personal:
            _validate_personal_ref_owner(skill.asset_ref, source_id)
        ref = _validated_asset_ref(
            skill.asset_ref,
            source_type=source_type,
            source_id=source_id,
            asset_type=AssetType.SKILL,
            local_code=skill.skill_id,
            version=_skill_version(skill),
        )
        return skill.model_copy(update={"asset_ref": ref})

    @staticmethod
    def _report_with_asset_ref(
        report: ReportRecord,
        owner_user_id: str,
        *,
        force_personal: bool = False,
    ) -> ReportRecord:
        is_official = report.visibility == "official" and not force_personal
        personal_source_id = owner_user_id or report.owner or "anonymous"
        if force_personal:
            _validate_personal_ref_owner(report.asset_ref, personal_source_id)
        ref = _validated_asset_ref(
            report.asset_ref,
            source_type=(
                AssetSourceType.OFFICIAL_PACK
                if is_official
                else AssetSourceType.PERSONAL_WORKSPACE
            ),
            source_id="tms" if is_official else personal_source_id,
            asset_type=AssetType.REPORT,
            local_code=report.report_id,
            version=report.version,
        )
        return report.model_copy(update={"asset_ref": ref})

    def _migrate_chat_sessions(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            select user_id,
                   min(created_at) as created_at,
                   max(updated_at) as updated_at
            from chat_messages
            where session_id = ''
            group by user_id
            """
        ).fetchall()
        for row in rows:
            latest = conn.execute(
                """
                select text
                from chat_messages
                where user_id = ? and session_id = ''
                order by created_at desc
                limit 1
                """,
                (row["user_id"],),
            ).fetchone()
            session_id = f"chat_session_{uuid4().hex[:12]}"
            title = _chat_title(latest["text"] if latest else "历史对话")
            conn.execute(
                """
                insert into chat_sessions(session_id, user_id, title, archived, created_at, updated_at)
                values (?, ?, ?, 0, ?, ?)
                """,
                (session_id, row["user_id"], title, row["created_at"], row["updated_at"]),
            )
            conn.execute(
                "update chat_messages set session_id = ? where user_id = ? and session_id = ''",
                (session_id, row["user_id"]),
            )

    def _seed_if_needed(self) -> None:
        with self._connect() as conn:
            seeded = conn.execute("select value from meta where key = ?", ("product_seed_v1",)).fetchone()
            if seeded:
                self._seed_ai_native_reports_if_needed(conn)
                self._seed_rich_assets_if_needed(conn)
                self._seed_metric_sql_contracts_if_needed(conn)
                self._seed_html_report_publish_if_needed(conn)
                self._seed_asset_visibility_mix_if_needed(conn)
                self._seed_skill_sql_contracts_if_needed(conn)
                self._seed_html_only_report_contracts_if_needed(conn)
                return
            now = _now()
            current_user = {
                "user_id": "system-admin",
                "display_name": "System Administrator",
                "org_id": "org-default",
                "org_name": "Default Organization",
                "role_ids": ["role-system-admin", "role-data-analyst"],
                "locale": "zh-CN",
                "timezone": "Asia/Shanghai",
            }
            conn.execute(
                "insert into users(user_id, payload, created_at, updated_at) values (?, ?, ?, ?)",
                (current_user["user_id"], _json(current_user), now, now),
            )

            for metric in self.official_metrics.values():
                visibility, owner = _seed_metric_visibility_owner(metric.metric_code)
                payload = metric.model_copy(update={"visibility": visibility, "owner": owner})
                self._upsert_metric(conn, payload, owner_user_id=owner, now=now)

            for skill in self.skills.values():
                visibility, owner = _seed_skill_visibility_owner(skill.skill_id)
                payload = _skill_with_product_schema(skill.model_copy(update={"visibility": visibility, "owner_user_id": owner}))
                self._upsert_skill(conn, payload, owner_user_id=owner, now=now)

            for report in _seed_reports():
                self._upsert_report(conn, report, owner_user_id=_owner_from_report(report), now=now)
            conn.execute("insert or replace into meta(key, value) values (?, ?)", ("product_seed_v1", now))
            conn.execute("insert or replace into meta(key, value) values (?, ?)", ("product_seed_v2_ai_native_reports", now))
            conn.execute("insert or replace into meta(key, value) values (?, ?)", ("product_seed_v3_rich_assets", now))
            conn.execute("insert or replace into meta(key, value) values (?, ?)", ("product_seed_v4_metric_sql_contracts", now))
            conn.execute("insert or replace into meta(key, value) values (?, ?)", ("product_seed_v5_html_report_publish", now))
            conn.execute("insert or replace into meta(key, value) values (?, ?)", ("product_seed_v6_asset_visibility_mix", now))
            conn.execute("insert or replace into meta(key, value) values (?, ?)", ("product_seed_v9_skill_contracts", now))
            conn.execute("insert or replace into meta(key, value) values (?, ?)", ("product_seed_v10_html_only_reports", now))

    def _seed_ai_native_reports_if_needed(self, conn: sqlite3.Connection) -> None:
        if conn.execute("select value from meta where key = ?", ("product_seed_v2_ai_native_reports",)).fetchone():
            return
        now = _now()
        for report in _seed_reports():
            existing = conn.execute("select payload from product_reports where report_id = ?", (report.report_id,)).fetchone()
            if existing is None:
                self._upsert_report(conn, report, owner_user_id=_owner_from_report(report), now=now)
                continue
            current = ReportRecord(**json.loads(existing["payload"]))
            if current.analysis_chain:
                continue
            updated = current.model_copy(
                update={
                    "description": report.description,
                    "flow": report.flow,
                    "sections": report.sections,
                    "analysis_chain": report.analysis_chain,
                    "tags": list(dict.fromkeys([*current.tags, *report.tags])),
                    "parameters": current.parameters or report.parameters,
                    "template": report.template,
                    "templateMode": report.templateMode,
                    "templateLabel": report.templateLabel,
                    "version": report.version,
                }
            )
            self._upsert_report(conn, updated, owner_user_id=_owner_from_report(updated), now=now)
        conn.execute("insert or replace into meta(key, value) values (?, ?)", ("product_seed_v2_ai_native_reports", now))

    def _seed_rich_assets_if_needed(self, conn: sqlite3.Connection) -> None:
        if conn.execute("select value from meta where key = ?", ("product_seed_v3_rich_assets",)).fetchone():
            return
        now = _now()
        for metric in self.official_metrics.values():
            visibility, owner = _seed_metric_visibility_owner(metric.metric_code)
            payload = metric.model_copy(update={"visibility": visibility, "owner": owner})
            self._upsert_metric(conn, payload, owner_user_id=owner, now=now)

        for skill in self.skills.values():
            visibility, owner = _seed_skill_visibility_owner(skill.skill_id)
            payload = _skill_with_product_schema(skill.model_copy(update={"visibility": visibility, "owner_user_id": owner}))
            self._upsert_skill(conn, payload, owner_user_id=owner, now=now)

        for report in _seed_reports():
            self._upsert_report(conn, report, owner_user_id=_owner_from_report(report), now=now)
        conn.execute("insert or replace into meta(key, value) values (?, ?)", ("product_seed_v3_rich_assets", now))

    def _seed_metric_sql_contracts_if_needed(self, conn: sqlite3.Connection) -> None:
        if conn.execute("select value from meta where key = ?", ("product_seed_v4_metric_sql_contracts",)).fetchone():
            return
        now = _now()
        for metric in self.official_metrics.values():
            visibility, owner = _seed_metric_visibility_owner(metric.metric_code)
            payload = _metric_with_validated_sql(
                metric.model_copy(update={"visibility": visibility, "owner": owner})
            )
            self._upsert_metric(conn, payload, owner_user_id=owner, now=now)
        conn.execute("insert or replace into meta(key, value) values (?, ?)", ("product_seed_v4_metric_sql_contracts", now))

    def _seed_html_report_publish_if_needed(self, conn: sqlite3.Connection) -> None:
        if conn.execute("select value from meta where key = ?", ("product_seed_v5_html_report_publish",)).fetchone():
            return
        now = _now()
        seed_by_id = {report.report_id: report for report in _seed_reports()}
        for report_id in ("official_tms_management_pack", "user_sample_monthly_tms_review"):
            seeded = seed_by_id.get(report_id)
            existing = conn.execute("select payload from product_reports where report_id = ?", (report_id,)).fetchone()
            if not seeded or existing is None:
                continue
            current = ReportRecord(**json.loads(existing["payload"]))
            output_types = list(dict.fromkeys([*current.outputTypes, "html"]))
            updated = current.model_copy(
                update={
                    "description": seeded.description,
                    "outputTypes": output_types,
                    "flow": seeded.flow,
                    "sections": seeded.sections,
                    "analysis_chain": seeded.analysis_chain,
                    "template": seeded.template,
                    "templateMode": seeded.templateMode,
                    "templateLabel": seeded.templateLabel,
                    "tags": list(dict.fromkeys([*current.tags, *seeded.tags, "在线报告"])),
                    "version": seeded.version,
                }
            )
            self._upsert_report(conn, updated, owner_user_id=_owner_from_report(updated), now=now)
        conn.execute("insert or replace into meta(key, value) values (?, ?)", ("product_seed_v5_html_report_publish", now))

    def _seed_asset_visibility_mix_if_needed(self, conn: sqlite3.Connection) -> None:
        if conn.execute("select value from meta where key = ?", ("product_seed_v6_asset_visibility_mix",)).fetchone():
            return
        now = _now()
        for metric in self.official_metrics.values():
            visibility, owner = _seed_metric_visibility_owner(metric.metric_code)
            payload = _metric_with_validated_sql(metric.model_copy(update={"visibility": visibility, "owner": owner}))
            self._upsert_metric(conn, payload, owner_user_id=owner, now=now)
        for skill in self.skills.values():
            visibility, owner = _seed_skill_visibility_owner(skill.skill_id)
            payload = _skill_with_product_schema(skill.model_copy(update={"visibility": visibility, "owner_user_id": owner}))
            self._upsert_skill(conn, payload, owner_user_id=owner, now=now)
        conn.execute("insert or replace into meta(key, value) values (?, ?)", ("product_seed_v6_asset_visibility_mix", now))

    def _seed_skill_sql_contracts_if_needed(self, conn: sqlite3.Connection) -> None:
        if conn.execute("select value from meta where key = ?", ("product_seed_v9_skill_contracts",)).fetchone():
            return
        now = _now()
        seed_by_id = {skill.skill_id: _skill_with_product_schema(skill) for skill in self.skills.values()}
        contract_keys = {
            "sql",
            "time_fields",
            "metrics",
            "dimensions",
            "sections",
            "columns",
            "analysisMethod",
            "outputFormat",
            "steps",
            "chartType",
        }
        for seeded in seed_by_id.values():
            skill_id = seeded.skill_id
            existing = conn.execute("select payload from product_skills where skill_id = ?", (skill_id,)).fetchone()
            if existing is None:
                continue
            current = SkillDefinition(**json.loads(existing["payload"]))
            current_schema = dict(current.output_schema or {})
            nested = current_schema.get("schema")
            nested_schema = dict(nested) if isinstance(nested, dict) else {}
            seeded_schema = dict(seeded.output_schema or {})
            changed = False
            for key in contract_keys:
                if key not in seeded_schema:
                    continue
                seeded_value = seeded_schema.get(key)
                current_value = current_schema.get(key, nested_schema.get(key))
                if current_value == seeded_value:
                    continue
                current_schema[key] = seeded_value
                changed = True
            if nested_schema:
                for key in contract_keys:
                    if key in seeded_schema:
                        nested_schema[key] = seeded_schema.get(key)
                current_schema["schema"] = nested_schema
            if not changed:
                continue
            updated = _skill_with_product_schema(current.model_copy(update={"output_schema": current_schema}))
            _visibility, seeded_owner = _seed_skill_visibility_owner(skill_id)
            self._upsert_skill(conn, updated, owner_user_id=updated.owner_user_id or seeded_owner, now=now)
        conn.execute("insert or replace into meta(key, value) values (?, ?)", ("product_seed_v9_skill_contracts", now))

    def _seed_html_only_report_contracts_if_needed(self, conn: sqlite3.Connection) -> None:
        if conn.execute("select value from meta where key = ?", ("product_seed_v10_html_only_reports",)).fetchone():
            return
        now = _now()
        seed_by_id = {report.report_id: report for report in _seed_reports()}
        for seeded in seed_by_id.values():
            existing = conn.execute("select payload from product_reports where report_id = ?", (seeded.report_id,)).fetchone()
            if existing is None:
                self._upsert_report(conn, seeded, owner_user_id=_owner_from_report(seeded), now=now)
                continue
            current = ReportRecord(**json.loads(existing["payload"]))
            updated = current.model_copy(
                update={
                    "description": seeded.description,
                    "outputTypes": seeded.outputTypes,
                    "channels": seeded.channels,
                    "template": seeded.template,
                    "templateMode": seeded.templateMode,
                    "templateLabel": seeded.templateLabel,
                    "flow": seeded.flow,
                    "sections": seeded.sections,
                    "analysis_chain": seeded.analysis_chain,
                    "tags": seeded.tags,
                    "parameters": seeded.parameters,
                    "version": seeded.version,
                }
            )
            self._upsert_report(conn, updated, owner_user_id=_owner_from_report(updated), now=now)
        conn.execute("insert or replace into meta(key, value) values (?, ?)", ("product_seed_v10_html_only_reports", now))

    def _seed_default_report_templates(self) -> None:
        for template_id, payload in _default_report_templates().items():
            path = self.file_root / "templates" / f"{template_id}.json"
            if not path.exists():
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_metrics(self, visibility: MetricVisibility | None = None) -> list[MetricDefinition]:
        sql = "select payload from product_metrics"
        args: tuple[Any, ...] = ()
        if visibility is not None:
            sql += " where visibility = ?"
            args = (visibility.value,)
        sql += " order by case visibility when 'private' then 1 when 'shared' then 2 else 3 end, metric_code"
        with self._connect() as conn:
            metrics = [MetricDefinition(**json.loads(row["payload"])) for row in conn.execute(sql, args)]
        return [metric for metric in metrics if metric.lifecycle_status != "deleted"]

    def get_metric_by_code(self, metric_code: str) -> MetricDefinition | None:
        with self._connect() as conn:
            rows = conn.execute(
                "select payload from product_metrics where metric_code = ?",
                (metric_code,),
            ).fetchall()
        if len(rows) > 1:
            raise ValueError(f"AMBIGUOUS_ASSET_REF: metric_code '{metric_code}' matches multiple assets.")
        return MetricDefinition(**json.loads(rows[0]["payload"])) if rows else None

    def get_metric_by_ref(self, asset_ref: AssetRef) -> MetricDefinition | None:
        payload = self._get_product_asset_payload(asset_ref, AssetType.METRIC)
        return MetricDefinition(**payload) if payload is not None else None

    def create_user_metric(self, metric: MetricDefinition) -> MetricDefinition:
        metric = _metric_with_validated_sql(metric)
        metric = self._metric_with_asset_ref(metric, metric.owner, force_personal=True)
        self._validate_metric_name(metric)
        with self._connect() as conn:
            self._upsert_metric(conn, metric, owner_user_id=metric.owner, now=_now())
        return metric

    def _validate_metric_name(self, metric: MetricDefinition) -> None:
        normalized_name = normalize_text(metric.name)
        for existing in self.list_metrics():
            if existing.metric_code == metric.metric_code or normalize_text(existing.name) != normalized_name:
                continue
            if existing.visibility == MetricVisibility.OFFICIAL:
                raise ValueError(f"Metric name '{metric.name}' conflicts with official metric '{existing.name}'")
            if existing.visibility == MetricVisibility.PRIVATE and existing.owner == metric.owner:
                raise ValueError(f"You already own a private metric named '{metric.name}'.")

    def update_metric(
        self,
        metric_code: str,
        patch: dict[str, Any],
        user_id: str,
        role_ids: list[str] | None = None,
    ) -> MetricDefinition:
        metric = self._require_metric(metric_code)
        if metric.visibility == MetricVisibility.OFFICIAL and not _is_admin(role_ids):
            raise ValueError("Official metrics are read-only.")
        if metric.visibility != MetricVisibility.OFFICIAL and metric.owner != user_id and not _is_admin(role_ids):
            raise ValueError("Only the metric owner or an administrator can edit this metric.")

        data = metric.model_dump(mode="json")
        for key in (
            "name",
            "definition",
            "update_frequency",
            "synonyms",
            "permission_tags",
            "execution_contract",
            "build_trace",
            "validation_evidence",
        ):
            if key in patch:
                data[key] = patch[key]
        if "formula" in patch:
            current_formula = metric.formula.model_dump(mode="json")
            current_formula.update(patch["formula"])
            if "expression" in current_formula:
                current_formula["expression"] = validate_metric_select_sql(str(current_formula["expression"]))
            data["formula"] = MetricFormula(**current_formula).model_dump(mode="json")

        updated = MetricDefinition(**data)
        updated = _metric_with_validated_sql(updated)
        self._validate_metric_name(updated)
        with self._connect() as conn:
            self._upsert_metric(conn, updated, owner_user_id=updated.owner, now=_now())
        return updated

    def update_metric_visibility(
        self,
        metric_code: str,
        visibility: MetricVisibility,
        user_id: str,
        role_ids: list[str] | None = None,
    ) -> MetricDefinition:
        metric = self._require_metric(metric_code)
        if metric.visibility == MetricVisibility.OFFICIAL:
            raise ValueError("Official metrics are read-only.")
        if metric.owner != user_id and not _is_admin(role_ids):
            raise ValueError("Only the metric owner or an administrator can change metric visibility.")
        if metric.visibility == MetricVisibility.SHARED and visibility == MetricVisibility.PRIVATE:
            blocking = [item for item in self.list_metric_dependencies(metric_code) if item.blocking]
            if blocking:
                first = blocking[0]
                raise ValueError(
                    f"阻断：该指标目前正被【{first.source_name}】{first.source_type}引用，请先解除绑定后再行删除/下架。"
                )
        updated = metric.model_copy(update={"visibility": visibility, "owner": metric.owner or user_id})
        with self._connect() as conn:
            self._upsert_metric(conn, updated, owner_user_id=updated.owner, now=_now())
            if visibility == MetricVisibility.SHARED:
                self._create_share_record(conn, "metric", metric_code, user_id, updated.model_dump(mode="json"))
        return updated

    def copy_metric(self, metric_code: str, user_id: str) -> MetricDefinition:
        metric = self._require_metric(metric_code)
        if metric.visibility == MetricVisibility.OFFICIAL:
            raise ValueError("Official metrics are read-only and cannot be copied from this action.")
        if metric.visibility != MetricVisibility.SHARED and metric.owner != user_id:
            raise ValueError("Only shared metrics can be copied by non-owners.")
        copied = metric.model_copy(
            update={
                "metric_code": f"user_{_slug(user_id)}::{_slug(metric.name)}_copy_{uuid4().hex[:6]}",
                "name": f"{metric.name} 副本",
                "visibility": MetricVisibility.PRIVATE,
                "owner": user_id,
                "version": "1.0.0",
                "lifecycle_status": "published",
                "asset_ref": None,
            }
        )
        copied = self._metric_with_asset_ref(copied, user_id, force_personal=True)
        with self._connect() as conn:
            self._upsert_metric(conn, copied, owner_user_id=user_id, now=_now())
        return copied

    def delete_metric(
        self,
        metric_code: str,
        user_id: str,
        role_ids: list[str] | None = None,
    ) -> MetricDefinition:
        metric = self._require_metric(metric_code)
        if metric.visibility == MetricVisibility.OFFICIAL:
            if not _is_admin(role_ids):
                raise ValueError("Official metrics are read-only.")
            updated_official = metric.model_copy(update={"lifecycle_status": "disabled"})
            with self._connect() as conn:
                self._upsert_metric(conn, updated_official, owner_user_id=updated_official.owner, now=_now())
            return updated_official
        if metric.owner != user_id and not _is_admin(role_ids):
            raise ValueError("Only the metric owner or an administrator can delete this metric.")
        blocking = [item for item in self.list_metric_dependencies(metric_code) if item.blocking]
        if blocking:
            first = blocking[0]
            raise ValueError(
                f"阻断：该指标目前正被【{first.source_name}】{first.source_type}引用，请前往对应资产解除绑定后再行删除/下架。"
            )
        updated = metric.model_copy(update={"lifecycle_status": "deleted"})
        with self._connect() as conn:
            self._upsert_metric(conn, updated, owner_user_id=updated.owner, now=_now())
        return updated

    def list_metric_dependencies(self, metric_code: str) -> list[MetricDependencyRecord]:
        dependencies: list[MetricDependencyRecord] = []
        with self._connect() as conn:
            for row in conn.execute("select payload from product_skills"):
                skill = SkillDefinition(**json.loads(row["payload"]))
                payload = skill.model_dump(mode="json")
                if metric_code in _json(payload):
                    dependencies.append(
                        MetricDependencyRecord(
                            source_type="技能",
                            source_id=skill.skill_id,
                            source_name=skill.name,
                            relation_type="uses",
                            blocking=False,
                        )
                    )
            for row in conn.execute("select payload from product_reports"):
                report = ReportRecord(**json.loads(row["payload"]))
                payload = report.model_dump(mode="json")
                if metric_code in _json(payload):
                    dependencies.append(
                        MetricDependencyRecord(
                            source_type="报表",
                            source_id=report.report_id,
                            source_name=report.name,
                            relation_type="binds",
                            blocking=bool(report.schedule and report.schedule.get("status") == "scheduled"),
                        )
                    )
            for row in conn.execute("select payload from scheduled_jobs where status = 'scheduled'"):
                job = ScheduledJobRecord(**json.loads(row["payload"]))
                if metric_code in _json(job.model_dump(mode="json")):
                    dependencies.append(
                        MetricDependencyRecord(
                            source_type="定时任务",
                            source_id=job.job_id,
                            source_name=str(job.payload.get("title") or job.entity_id or job.job_id),
                            relation_type="schedules",
                            blocking=True,
                        )
                    )
        return dependencies

    def list_skills(self, visibility: SkillVisibility | None = None) -> list[SkillDefinition]:
        sql = "select payload from product_skills"
        args: tuple[Any, ...] = ()
        if visibility is not None:
            sql += " where visibility = ?"
            args = (visibility.value,)
        sql += " order by case visibility when 'private' then 1 when 'shared' then 2 else 3 end, skill_id"
        with self._connect() as conn:
            return [SkillDefinition(**json.loads(row["payload"])) for row in conn.execute(sql, args)]

    def create_skill(self, skill: SkillDefinition, user_id: str) -> SkillDefinition:
        if not skill.skill_id:
            raise ValueError("Skill ID is required.")
        payload = _skill_with_product_schema(skill.model_copy(update={"visibility": SkillVisibility.PRIVATE, "owner_user_id": user_id}))
        payload = self._skill_with_asset_ref(payload, user_id, force_personal=True)
        self._validate_skill_name(payload, user_id)
        with self._connect() as conn:
            self._upsert_skill(conn, payload, owner_user_id=user_id, now=_now())
        return payload

    def _validate_skill_name(self, skill: SkillDefinition, user_id: str, *, ignore_skill_id: str | None = None) -> None:
        normalized_name = normalize_text(skill.name)
        if not normalized_name:
            raise ValueError("Skill name is required.")
        for existing in self.list_skills():
            if existing.skill_id == (ignore_skill_id or skill.skill_id):
                continue
            if normalize_text(existing.name) != normalized_name:
                continue
            if existing.visibility == SkillVisibility.OFFICIAL:
                raise ValueError(f"Skill name '{skill.name}' conflicts with official skill '{existing.name}'.")
            if existing.owner_user_id == user_id:
                raise ValueError(f"You already own a skill named '{skill.name}'.")

    def update_skill(self, skill_id: str, patch: dict[str, Any], user_id: str) -> SkillDefinition:
        current = self._require_skill(skill_id)
        if current.visibility == SkillVisibility.OFFICIAL:
            raise ValueError("Official skills are read-only.")
        data = current.model_dump(mode="json")
        data.update({k: v for k, v in patch.items() if v is not None})
        data["owner_user_id"] = current.owner_user_id or user_id
        updated = _skill_with_product_schema(SkillDefinition(**data))
        updated = self._skill_with_asset_ref(updated, data["owner_user_id"])
        self._validate_skill_name(updated, user_id, ignore_skill_id=skill_id)
        with self._connect() as conn:
            self._upsert_skill(conn, updated, owner_user_id=data["owner_user_id"], now=_now())
        return updated

    def update_skill_visibility(self, skill_id: str, visibility: SkillVisibility, user_id: str) -> SkillDefinition:
        skill = self._require_skill(skill_id)
        if skill.visibility == SkillVisibility.OFFICIAL:
            raise ValueError("Official skills are read-only.")
        updated = _skill_with_product_schema(skill.model_copy(update={"visibility": visibility}))
        with self._connect() as conn:
            self._upsert_skill(conn, updated, owner_user_id=updated.owner_user_id or user_id, now=_now())
            if visibility == SkillVisibility.SHARED:
                self._create_share_record(conn, "skill", skill_id, user_id, updated.model_dump(mode="json"))
        return updated

    def copy_skill(self, skill_id: str, user_id: str) -> SkillDefinition:
        skill = self._require_skill(skill_id)
        if skill.visibility == SkillVisibility.OFFICIAL:
            raise ValueError("Official skills are read-only and cannot be copied from this action.")
        copied = _skill_with_product_schema(
            skill.model_copy(
                update={
                    "skill_id": f"user_{_slug(user_id)}_copy_{uuid4().hex[:8]}",
                    "namespace": "user",
                    "name": f"{skill.name} 副本",
                    "visibility": SkillVisibility.PRIVATE,
                    "owner_user_id": user_id,
                    "asset_ref": None,
                }
            )
        )
        copied = self._skill_with_asset_ref(copied, user_id, force_personal=True)
        with self._connect() as conn:
            self._upsert_skill(conn, copied, owner_user_id=user_id, now=_now())
        return copied

    def delete_skill(self, skill_id: str, user_id: str, role_ids: list[str] | None = None) -> None:
        skill = self._require_skill(skill_id)
        if skill.visibility == SkillVisibility.OFFICIAL:
            raise ValueError("Official skills are read-only.")
        if skill.owner_user_id != user_id and not _is_admin(role_ids):
            raise ValueError("Only the skill owner or an administrator can delete this skill.")
        assert skill.asset_ref is not None
        with self._connect() as conn:
            conn.execute(
                "delete from product_skills where asset_id = ?",
                (skill.asset_ref.asset.asset_id,),
            )
            conn.execute("delete from share_records where entity_type = 'skill' and entity_id = ?", (skill_id,))

    def resolve_skill(self, request: SkillResolveRequest) -> SkillResolveResult:
        exact_matches: list[SkillDefinition] = []
        candidates: list[SkillDefinition] = []
        query_text = request.text or request.trigger
        for skill in self.list_skills():
            if match_synonyms(query_text, skill.name, skill.synonyms):
                exact_matches.append(skill)
            elif is_partial_match(query_text, skill.name, skill.synonyms):
                candidates.append(skill)
        return SkillResolveResult(
            matched_skill=exact_matches[0] if exact_matches else None,
            candidates=exact_matches + candidates,
        )

    def list_reports(self, visibility: str | None = None) -> list[ReportRecord]:
        sql = "select payload from product_reports"
        args: tuple[Any, ...] = ()
        if visibility is not None:
            sql += " where visibility = ?"
            args = (visibility,)
        sql += " order by case visibility when 'private' then 1 when 'shared' then 2 else 3 end, report_id"
        with self._connect() as conn:
            return [ReportRecord(**json.loads(row["payload"])) for row in conn.execute(sql, args)]

    def get_skill_by_ref(self, asset_ref: AssetRef) -> SkillDefinition | None:
        payload = self._get_product_asset_payload(asset_ref, AssetType.SKILL)
        return SkillDefinition(**payload) if payload is not None else None

    def get_report_by_ref(self, asset_ref: AssetRef) -> ReportRecord | None:
        payload = self._get_product_asset_payload(asset_ref, AssetType.REPORT)
        return ReportRecord(**payload) if payload is not None else None

    def upsert_pack_assets(
        self,
        *,
        owner_user_id: str,
        metrics: list[MetricDefinition] | None = None,
        reports: list[ReportRecord] | None = None,
    ) -> None:
        """Project pack product assets into the repository.

        Callers must pre-populate each asset's ``asset_ref`` with its pack
        identity (source_type/source_id); the ref is preserved as-is so
        re-projection stays idempotent.
        """
        now = _now()
        with self._connect() as conn:
            for metric in metrics or []:
                if metric.asset_ref is None:
                    raise ValueError("Pack metric projection requires a pack asset_ref.")
                self._upsert_metric(conn, metric, owner_user_id=owner_user_id, now=now)
            for report in reports or []:
                if report.asset_ref is None:
                    raise ValueError("Pack report projection requires a pack asset_ref.")
                self._upsert_report(conn, report, owner_user_id=owner_user_id, now=now)

    def remove_pack_assets(self, *, source_type: str, source_id: str) -> None:
        """Remove all projected assets belonging to one pack source."""
        with self._connect() as conn:
            conn.execute(
                "delete from product_metrics where source_type=? and source_id=?",
                (source_type, source_id),
            )
            conn.execute(
                "delete from product_reports where source_type=? and source_id=?",
                (source_type, source_id),
            )

    def create_report(self, report: ReportRecord, user_id: str) -> ReportRecord:
        payload = report.model_copy(update={"visibility": "private", "owner": report.owner or user_id})
        payload = self._report_with_asset_ref(payload, user_id, force_personal=True)
        self._validate_report_name(payload, user_id)
        with self._connect() as conn:
            self._upsert_report(conn, payload, owner_user_id=user_id, now=_now())
        return payload

    def _validate_report_name(self, report: ReportRecord, user_id: str, *, ignore_report_id: str | None = None) -> None:
        normalized_name = normalize_text(report.name)
        if not normalized_name:
            raise ValueError("Report name is required.")
        for existing in self.list_reports():
            if existing.report_id == (ignore_report_id or report.report_id):
                continue
            if normalize_text(existing.name) != normalized_name:
                continue
            if existing.visibility == "official":
                raise ValueError(f"Report name '{report.name}' conflicts with official report '{existing.name}'.")
            if _is_report_owner(existing, user_id) or existing.owner == report.owner:
                raise ValueError(f"You already own a report named '{report.name}'.")

    def update_report_visibility(self, report_id: str, visibility: str, user_id: str) -> ReportRecord:
        report = self._require_report(report_id)
        if report.visibility == "official":
            raise ValueError("Official reports are read-only.")
        updated = report.model_copy(update={"visibility": visibility})
        with self._connect() as conn:
            self._upsert_report(conn, updated, owner_user_id=_owner_from_report(updated), now=_now())
            if visibility == "shared":
                self._create_share_record(conn, "report", report_id, user_id, updated.model_dump(mode="json"))
        return updated

    def update_report(
        self,
        report_id: str,
        patch: dict[str, Any],
        user_id: str,
        role_ids: list[str] | None = None,
    ) -> ReportRecord:
        report = self._require_report(report_id)
        if report.visibility == "official" and not _is_admin(role_ids):
            raise ValueError("Official reports are read-only.")
        if report.visibility != "official" and not _is_report_owner(report, user_id) and not _is_admin(role_ids):
            raise ValueError("Only the report owner or an administrator can edit this report.")
        allowed_fields = {
            "name",
            "description",
            "outputTypes",
            "channels",
            "flow",
            "sections",
            "analysis_chain",
            "tags",
            "parameters",
            "schedule",
            "artifact_url",
            "publish_url",
            "version",
            "data_source_bindings",
            "execution_contract",
            "build_trace",
            "validation_evidence",
        }
        sanitized = {key: value for key, value in patch.items() if key in allowed_fields}
        updated = report.model_copy(update=sanitized)
        updated = self._report_with_asset_ref(updated, _owner_from_report(updated))
        self._validate_report_name(updated, user_id, ignore_report_id=report_id)
        with self._connect() as conn:
            self._upsert_report(conn, updated, owner_user_id=_owner_from_report(updated), now=_now())
        return updated

    def copy_report(self, report_id: str, user_id: str) -> ReportRecord:
        report = self._require_report(report_id)
        if report.visibility == "official":
            raise ValueError("Official reports are read-only and cannot be copied from this action.")
        copied = report.model_copy(
            update={
                "report_id": f"user_{_slug(user_id)}_report_copy_{uuid4().hex[:8]}",
                "name": f"{report.name} 副本",
                "visibility": "private",
                "owner": user_id,
                "version": "1.0.0",
                "asset_ref": None,
            }
        )
        copied = self._report_with_asset_ref(copied, user_id, force_personal=True)
        with self._connect() as conn:
            self._upsert_report(conn, copied, owner_user_id=user_id, now=_now())
        return copied

    def delete_report(self, report_id: str, user_id: str, role_ids: list[str] | None = None) -> None:
        report = self._require_report(report_id)
        if report.visibility == "official":
            raise ValueError("Official reports are read-only.")
        if not _is_report_owner(report, user_id) and not _is_admin(role_ids):
            raise ValueError("Only the report owner or an administrator can delete this report.")
        assert report.asset_ref is not None
        with self._connect() as conn:
            conn.execute(
                "delete from product_reports where asset_id = ?",
                (report.asset_ref.asset.asset_id,),
            )
            conn.execute("delete from share_records where entity_type = 'report' and entity_id = ?", (report_id,))

    def generate_report_file(
        self,
        report_id: str,
        *,
        user_id: str,
        output_type: str,
        title: str | None = None,
        content: str | None = None,
        bound_metric_codes: list[str] | None = None,
        bound_skill_ids: list[str] | None = None,
    ) -> GeneratedFileRecord:
        report = self._require_report(report_id)
        normalized_type = output_type.lower()
        if normalized_type not in {"html", "pdf", "pptx", "docx"}:
            raise ValueError("Unsupported report output type.")
        file_id = f"file_{uuid4().hex[:12]}"
        filename = f"{report_id}_{file_id}.{normalized_type}"
        path = self.file_root / "generated" / filename
        resolved_title = title or report.name
        derived_from: str | None = None
        converter_version: str | None = None
        if normalized_type == "html":
            raw_content = (content or "").strip()
            if not _looks_like_full_html(raw_content):
                raise ValueError("REPORT_HTML_CONTENT_INVALID")
            data = raw_content.encode("utf-8")
            content_type = "text/html; charset=utf-8"
            render_provider = "llm_html"
        else:
            with self._connect() as conn:
                source_row = conn.execute(
                    """
                    select file_id, path from generated_files
                    where entity_type = 'report' and entity_id = ? and content_type like 'text/html%'
                    order by created_at desc limit 1
                    """,
                    (report_id,),
                ).fetchone()
            if not source_row:
                raise ValueError("REPORT_HTML_SOURCE_REQUIRED")
            source_path = Path(source_row["path"])
            if not source_path.exists():
                raise ValueError("REPORT_HTML_SOURCE_REQUIRED")
            derived_from = str(source_row["file_id"])
            converter_version = "sqbi-html-derived-v1"
            data, content_type = self._derive_html_artifact(source_path.read_text(encoding="utf-8"), normalized_type, resolved_title)
            render_provider = "html_derivative"
        path.write_bytes(data)
        record = GeneratedFileRecord(
            file_id=file_id,
            owner_user_id=user_id,
            entity_type="report",
            entity_id=report_id,
            filename=filename,
            content_type=content_type,
            byte_size=len(data),
            download_url=f"/api/v1/files/{file_id}/download",
            view_url=f"/api/v1/files/{file_id}/view" if normalized_type == "html" else None,
            render_provider=render_provider,
            created_at=_now(),
            derived_from=derived_from,
            converter_version=converter_version,
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into generated_files(file_id, owner_user_id, entity_type, entity_id, filename, path, content_type, byte_size, payload, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.file_id,
                    user_id,
                    "report",
                    report_id,
                    filename,
                    str(path),
                    content_type,
                    len(data),
                    record.model_dump_json(),
                    record.created_at,
                ),
            )
            absolute_download = record.download_url
            absolute_view = record.view_url
            updated_report = report.model_copy(
                update={
                    "artifact_url": absolute_download,
                    "publish_url": absolute_view if normalized_type == "html" else report.publish_url,
                }
            )
            self._upsert_report(conn, updated_report, owner_user_id=_owner_from_report(updated_report), now=_now())
        return record

    def get_generated_file(self, file_id: str) -> tuple[GeneratedFileRecord, Path]:
        with self._connect() as conn:
            row = conn.execute("select payload, path from generated_files where file_id = ?", (file_id,)).fetchone()
        if not row:
            raise KeyError("Generated file not found.")
        path = Path(row["path"])
        if not path.exists():
            raise KeyError("Generated file content not found.")
        return GeneratedFileRecord(**json.loads(row["payload"])), path


    @staticmethod
    def _derive_html_artifact(html: str, output_type: str, title: str) -> tuple[bytes, str]:
        plain_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
        if output_type == "pdf":
            return SQLiteProductRepository._render_text_pdf([title, plain_text]), "application/pdf"
        if output_type == "docx":
            return SQLiteProductRepository._render_docx(title, plain_text), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if output_type == "pptx":
            return SQLiteProductRepository._render_pptx(title, plain_text), "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        raise ValueError("Unsupported report output type.")


    @staticmethod
    def _render_text_pdf(lines: list[str]) -> bytes:
        text = "\\n".join(line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines)
        stream = f"BT /F1 11 Tf 54 740 Td 13 TL ({text[:3000]}) Tj ET"
        objects = [
            "<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            f"<< /Length {len(stream.encode('utf-8'))} >>\nstream\n{stream}\nendstream",
        ]
        chunks = [b"%PDF-1.4\n"]
        offsets: list[int] = []
        for index, obj in enumerate(objects, start=1):
            offsets.append(sum(len(chunk) for chunk in chunks))
            chunks.append(f"{index} 0 obj\n{obj}\nendobj\n".encode("utf-8"))
        xref_offset = sum(len(chunk) for chunk in chunks)
        xref = ["xref", f"0 {len(objects) + 1}", "0000000000 65535 f "]
        xref.extend(f"{offset:010d} 00000 n " for offset in offsets)
        chunks.append(("\n".join(xref) + "\n").encode("utf-8"))
        chunks.append(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("utf-8"))
        return b"".join(chunks)


    @staticmethod
    def _render_docx(title: str, text: str) -> bytes:
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
            archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
            archive.writestr("word/document.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{xml_escape(title)}</w:t></w:r></w:p><w:p><w:r><w:t>{xml_escape(text[:12000])}</w:t></w:r></w:p><w:sectPr/></w:body></w:document>')
        return buffer.getvalue()


    @staticmethod
    def _render_pptx(title: str, text: str) -> bytes:
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/><Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/></Types>')
            archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>')
            archive.writestr("ppt/presentation.xml", '<?xml version="1.0"?><p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
            archive.writestr("ppt/_rels/presentation.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/></Relationships>')
            archive.writestr("ppt/slides/slide1.xml", f'<?xml version="1.0" encoding="UTF-8"?><p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvPr id="2" name="Content"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{xml_escape(title)}\n{xml_escape(text[:4000])}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')
        return buffer.getvalue()

    def create_scheduled_job(
        self,
        *,
        user_id: str,
        entity_type: str,
        entity_id: str,
        schedule_text: str,
        payload: dict[str, Any] | None = None,
    ) -> ScheduledJobRecord:
        now = _now()
        record = ScheduledJobRecord(
            job_id=f"job_{uuid4().hex[:12]}",
            owner_user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            status="scheduled",
            schedule_text=schedule_text,
            payload=payload or {},
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into scheduled_jobs(job_id, owner_user_id, entity_type, entity_id, status, schedule_text, payload, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.job_id,
                    user_id,
                    entity_type,
                    entity_id,
                    record.status,
                    schedule_text,
                    record.model_dump_json(),
                    now,
                    now,
                ),
            )
        return record

    def stop_scheduled_job(self, job_id: str, user_id: str) -> ScheduledJobRecord:
        with self._connect() as conn:
            row = conn.execute("select payload from scheduled_jobs where job_id = ? and owner_user_id = ?", (job_id, user_id)).fetchone()
            if not row:
                raise KeyError("Scheduled job not found.")
            current = ScheduledJobRecord(**json.loads(row["payload"]))
            updated = current.model_copy(update={"status": "stopped", "updated_at": _now()})
            conn.execute(
                "update scheduled_jobs set status = ?, payload = ?, updated_at = ? where job_id = ?",
                (updated.status, updated.model_dump_json(), updated.updated_at, job_id),
            )
        return updated

    def list_chat_sessions(self, user_id: str, include_archived: bool = False) -> list[ChatSessionRecord]:
        sql = """
            select s.session_id,
                   s.user_id,
                   s.title,
                   s.archived,
                   s.created_at,
                   s.updated_at,
                   count(m.message_id) as message_count
            from chat_sessions s
            left join chat_messages m
              on m.session_id = s.session_id and m.archived = 0
            where s.user_id = ?
        """
        args: list[Any] = [user_id]
        if not include_archived:
            sql += " and s.archived = 0"
        sql += " group by s.session_id order by s.updated_at desc limit 100"
        with self._connect() as conn:
            return [
                ChatSessionRecord(
                    session_id=row["session_id"],
                    user_id=row["user_id"],
                    title=row["title"],
                    archived=bool(row["archived"]),
                    message_count=int(row["message_count"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in conn.execute(sql, args)
            ]

    def create_chat_session(self, user_id: str, title: str | None = None) -> ChatSessionRecord:
        now = _now()
        record = ChatSessionRecord(
            session_id=f"chat_session_{uuid4().hex[:12]}",
            user_id=user_id,
            title=_chat_title(title or "新对话"),
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into chat_sessions(session_id, user_id, title, archived, created_at, updated_at)
                values (?, ?, ?, 0, ?, ?)
                """,
                (record.session_id, user_id, record.title, now, now),
            )
        return record

    def list_chat_messages(
        self,
        user_id: str,
        include_archived: bool = False,
        session_id: str | None = None,
    ) -> list[ChatMessageRecord]:
        sql = "select message_id, session_id, user_id, sender, text, payload, archived, created_at, updated_at from chat_messages where user_id = ?"
        args: list[Any] = [user_id]
        if session_id:
            sql += " and session_id = ?"
            args.append(session_id)
        if not include_archived:
            sql += " and archived = 0"
        sql += " order by created_at asc limit 200"
        with self._connect() as conn:
            return [
                ChatMessageRecord(
                    message_id=row["message_id"],
                    session_id=row["session_id"],
                    user_id=row["user_id"],
                    sender=row["sender"],
                    text=row["text"],
                    payload=json.loads(row["payload"] or "{}"),
                    archived=bool(row["archived"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in conn.execute(sql, args)
            ]

    def create_chat_message(
        self,
        user_id: str,
        text: str,
        session_id: str | None = None,
        sender: str = "user",
        payload: dict[str, Any] | None = None,
    ) -> ChatMessageRecord:
        now = _now()
        normalized_sender = sender if sender in {"user", "assistant", "system"} else "user"
        message_payload = payload or {}
        with self._connect() as conn:
            session = None
            if session_id:
                session = conn.execute(
                    "select * from chat_sessions where session_id = ? and user_id = ? and archived = 0",
                    (session_id, user_id),
                ).fetchone()
            if session is None:
                session_id = f"chat_session_{uuid4().hex[:12]}"
                conn.execute(
                    """
                    insert into chat_sessions(session_id, user_id, title, archived, created_at, updated_at)
                    values (?, ?, ?, 0, ?, ?)
                    """,
                    (session_id, user_id, _chat_title(text if normalized_sender == "user" else "新对话"), now, now),
                )
            else:
                title = session["title"]
                next_title = _chat_title(text) if title == "新对话" and normalized_sender == "user" else title
                conn.execute(
                    "update chat_sessions set title = ?, updated_at = ? where session_id = ?",
                    (next_title, now, session_id),
                )
            assert session_id is not None
            record = ChatMessageRecord(
                message_id=f"chat_{uuid4().hex[:12]}",
                session_id=session_id,
                user_id=user_id,
                sender=normalized_sender,
                text=text,
                payload=message_payload,
                created_at=now,
                updated_at=now,
            )
            conn.execute(
                """
                insert into chat_messages(message_id, session_id, user_id, sender, text, payload, archived, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (record.message_id, session_id, user_id, normalized_sender, text, _json(message_payload), now, now),
            )
        return record

    def archive_chat_session(self, session_id: str, user_id: str) -> ChatSessionRecord:
        with self._connect() as conn:
            row = conn.execute("select * from chat_sessions where session_id = ? and user_id = ?", (session_id, user_id)).fetchone()
            if not row:
                raise KeyError("Chat session not found.")
            now = _now()
            conn.execute("update chat_sessions set archived = 1, updated_at = ? where session_id = ?", (now, session_id))
            conn.execute("update chat_messages set archived = 1, updated_at = ? where session_id = ?", (now, session_id))
            count = conn.execute(
                "select count(*) as message_count from chat_messages where session_id = ?",
                (session_id,),
            ).fetchone()
        return ChatSessionRecord(
            session_id=row["session_id"],
            user_id=row["user_id"],
            title=row["title"],
            archived=True,
            message_count=int(count["message_count"] if count else 0),
            created_at=row["created_at"],
            updated_at=now,
        )

    def create_legacy_chat_message(self, user_id: str, text: str) -> ChatMessageRecord:
        return self.create_chat_message(user_id, text)

    def archive_chat_message(self, message_id: str, user_id: str) -> ChatMessageRecord:
        with self._connect() as conn:
            row = conn.execute("select * from chat_messages where message_id = ? and user_id = ?", (message_id, user_id)).fetchone()
            if not row:
                raise KeyError("Chat message not found.")
            now = _now()
            conn.execute("update chat_messages set archived = 1, updated_at = ? where message_id = ?", (now, message_id))
        return ChatMessageRecord(
            message_id=row["message_id"],
            session_id=row["session_id"],
            user_id=row["user_id"],
            sender=row["sender"],
            text=row["text"],
            payload=json.loads(row["payload"] or "{}"),
            archived=True,
            created_at=row["created_at"],
            updated_at=now,
        )

    def get_current_user(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("select payload from users where user_id = ?", ("system-admin",)).fetchone()
        return json.loads(row["payload"]) if row else {}

    def _require_metric(self, metric_code: str) -> MetricDefinition:
        metric = self.get_metric_by_code(metric_code)
        if metric is None:
            raise KeyError("Metric not found.")
        return metric

    def _require_skill(self, skill_id: str) -> SkillDefinition:
        with self._connect() as conn:
            rows = conn.execute(
                "select payload from product_skills where skill_id = ?", (skill_id,)
            ).fetchall()
        if len(rows) > 1:
            raise ValueError(f"AMBIGUOUS_ASSET_REF: skill_id '{skill_id}' matches multiple assets.")
        if not rows:
            raise KeyError("Skill not found.")
        return SkillDefinition(**json.loads(rows[0]["payload"]))

    def _require_report(self, report_id: str) -> ReportRecord:
        with self._connect() as conn:
            rows = conn.execute(
                "select payload from product_reports where report_id = ?", (report_id,)
            ).fetchall()
        if len(rows) > 1:
            raise ValueError(f"AMBIGUOUS_ASSET_REF: report_id '{report_id}' matches multiple assets.")
        if not rows:
            raise KeyError("Report not found.")
        return ReportRecord(**json.loads(rows[0]["payload"]))

    def _get_product_asset_payload(
        self,
        asset_ref: AssetRef,
        expected_type: AssetType,
    ) -> dict[str, Any] | None:
        if asset_ref.asset.asset_type != expected_type:
            return None
        table = f"product_{expected_type.value}s"
        with self._connect() as conn:
            current = conn.execute(
                f"select version, payload from {table} where asset_id = ?",
                (asset_ref.asset.asset_id,),
            ).fetchone()
            if current and current["version"] == asset_ref.version:
                return json.loads(current["payload"])
            historical = conn.execute(
                """
                select payload from entity_versions
                where entity_type = ? and entity_id = ? and version = ?
                order by created_at desc limit 1
                """,
                (expected_type.value, asset_ref.asset.asset_id, asset_ref.version),
            ).fetchone()
        if not historical:
            return None
        payload = json.loads(historical["payload"])
        stored_ref = payload.get("asset_ref")
        return payload if stored_ref and AssetRef(**stored_ref) == asset_ref else None

    def _upsert_metric(self, conn: sqlite3.Connection, metric: MetricDefinition, *, owner_user_id: str, now: str) -> None:
        metric = self._metric_with_asset_ref(metric, owner_user_id)
        ref = metric.asset_ref
        assert ref is not None
        conn.execute(
            """
            insert into product_metrics(asset_id, source_type, source_id, asset_type, local_code, version, metric_code, visibility, owner_user_id, payload, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(asset_id) do update set
              version = excluded.version,
              metric_code = excluded.metric_code,
              visibility = excluded.visibility,
              owner_user_id = excluded.owner_user_id,
              payload = excluded.payload,
              updated_at = excluded.updated_at
            """,
            (
                ref.asset.asset_id,
                ref.asset.source_type.value,
                ref.asset.source_id,
                ref.asset.asset_type.value,
                ref.asset.local_code,
                ref.version,
                metric.metric_code,
                metric.visibility.value,
                owner_user_id,
                metric.model_dump_json(),
                now,
                now,
            ),
        )
        self._record_version(conn, "metric", ref.asset.asset_id, metric.version, metric.model_dump(mode="json"), owner_user_id, now)

    def _upsert_skill(self, conn: sqlite3.Connection, skill: SkillDefinition, *, owner_user_id: str, now: str) -> None:
        skill = self._skill_with_asset_ref(skill, owner_user_id)
        ref = skill.asset_ref
        assert ref is not None
        conn.execute(
            """
            insert into product_skills(asset_id, source_type, source_id, asset_type, local_code, version, skill_id, visibility, owner_user_id, skill_type, payload, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(asset_id) do update set
              version = excluded.version,
              skill_id = excluded.skill_id,
              visibility = excluded.visibility,
              owner_user_id = excluded.owner_user_id,
              skill_type = excluded.skill_type,
              payload = excluded.payload,
              updated_at = excluded.updated_at
            """,
            (
                ref.asset.asset_id,
                ref.asset.source_type.value,
                ref.asset.source_id,
                ref.asset.asset_type.value,
                ref.asset.local_code,
                ref.version,
                skill.skill_id,
                skill.visibility.value,
                owner_user_id,
                skill.skill_type.value,
                skill.model_dump_json(),
                now,
                now,
            ),
        )
        self._record_version(conn, "skill", ref.asset.asset_id, ref.version, skill.model_dump(mode="json"), owner_user_id, now)

    def _upsert_report(self, conn: sqlite3.Connection, report: ReportRecord, *, owner_user_id: str, now: str) -> None:
        report = self._report_with_asset_ref(report, owner_user_id)
        ref = report.asset_ref
        assert ref is not None
        conn.execute(
            """
            insert into product_reports(asset_id, source_type, source_id, asset_type, local_code, version, report_id, visibility, owner_user_id, payload, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(asset_id) do update set
              version = excluded.version,
              report_id = excluded.report_id,
              visibility = excluded.visibility,
              owner_user_id = excluded.owner_user_id,
              payload = excluded.payload,
              updated_at = excluded.updated_at
            """,
            (
                ref.asset.asset_id,
                ref.asset.source_type.value,
                ref.asset.source_id,
                ref.asset.asset_type.value,
                ref.asset.local_code,
                ref.version,
                report.report_id,
                report.visibility,
                owner_user_id,
                report.model_dump_json(),
                now,
                now,
            ),
        )
        self._record_version(conn, "report", ref.asset.asset_id, report.version, report.model_dump(mode="json"), owner_user_id, now)

    def _record_version(
        self,
        conn: sqlite3.Connection,
        entity_type: str,
        entity_id: str,
        version: str,
        payload: dict[str, Any],
        created_by: str,
        now: str,
    ) -> None:
        conn.execute(
            """
            insert into entity_versions(version_id, entity_type, entity_id, version, payload, created_by, created_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (f"ver_{uuid4().hex[:12]}", entity_type, entity_id, version, _json(payload), created_by, now),
        )

    def _create_share_record(
        self,
        conn: sqlite3.Connection,
        entity_type: str,
        entity_id: str,
        user_id: str,
        payload: dict[str, Any],
    ) -> None:
        conn.execute(
            "insert into share_records(share_id, entity_type, entity_id, created_by, payload, created_at) values (?, ?, ?, ?, ?, ?)",
            (f"share_{uuid4().hex[:10]}", entity_type, entity_id, user_id, _json(payload), _now()),
        )


def _looks_like_full_html(content: str) -> bool:
    normalized = content.lstrip().lower()
    return normalized.startswith("<!doctype html") or normalized.startswith("<html")


def _default_report_templates() -> dict[str, dict[str, Any]]:
    return {
        "management_review": {
            "template_id": "management_review",
            "format": "html",
            "name": "管理层在线经营报告模板",
            "content_examples": ["首屏摘要", "经营指标", "异常归因", "管理动作", "血缘附录"],
            "style": {"tone": "management", "chart_density": "medium", "snapshot_required": True},
        },
        "interactive_dashboard": {
            "template_id": "interactive_dashboard",
            "format": "html",
            "name": "交互分析页面模板",
            "content_examples": ["筛选条件", "KPI 看板", "趋势图", "明细表", "AI 结论"],
            "style": {"tone": "dashboard", "chart_density": "high"},
        },
        "executive_portal": {
            "template_id": "executive_portal",
            "format": "html",
            "name": "管理层在线汇报模板",
            "content_examples": ["首屏结论", "关键指标", "风险归因", "行动建议"],
            "style": {"tone": "executive", "chart_density": "medium"},
        },
        "mobile_digest": {
            "template_id": "mobile_digest",
            "format": "html",
            "name": "移动端摘要页面模板",
            "content_examples": ["摘要", "异常", "建议", "明细链接"],
            "style": {"tone": "concise", "chart_density": "low"},
        },
        "push_default": {
            "template_id": "push_default",
            "format": "push",
            "name": "默认推送模板",
            "content_examples": ["标题", "一句话结论", "异常提醒", "行动建议", "跳转链接"],
            "style": {"tone": "concise", "max_length": 500},
        },
    }


def _seed_reports() -> list[ReportRecord]:
    return [
        ReportRecord(
            report_id="official_tms_management_pack",
            name="TMS 经营管理汇报包",
            description="官方高阶 Skill：围绕时间范围、厂区和备注风格，编排 TMS 问数、物流风险、承运商履约和项目延期分析，输出可在线分享的 HTML 经营报告。",
            visibility="official",
            owner="tms-semantic-catalog",
            outputTypes=["html"],
            channels=[],
            template="management_review",
            templateMode="built_in",
            templateLabel="管理层在线经营报告模板",
            flow=(
                "解析动态参数与上下文 -> 采集 TMS 核心经营指标 -> 扫描时效/签收/在途风险 -> "
                "拆解承运商履约与项目延期 -> 生成经营叙事和行动建议 -> "
                "参考管理层在线报告风格生成 HTML 页面，返回预览链接、下载链接和血缘"
            ),
            sections=[
                "封面与参数摘要",
                "经营摘要",
                "核心指标水位",
                "履约风险扫描",
                "承运商表现归因",
                "项目延期与大区拆解",
                "管理层行动建议",
                "口径、血缘和审计附录",
            ],
            analysis_chain=[
                {
                    "name": "参数解析与上下文压缩",
                    "type": "llm_context",
                    "inputs": ["time_range", "factory", "remark_style"],
                    "output": "生成报表运行上下文，不满足时由模型软提示并继续尝试。",
                },
                {
                    "name": "核心经营指标采集",
                    "type": "skill",
                    "skill_id": "tms_system_askdata",
                    "inputs": ["apply_count", "form_count", "execution_count", "ontime_rate", "signed_rate", "unsigned_rate"],
                    "output": "经营摘要页、核心指标水位页和环比变化说明。",
                },
                {
                    "name": "签收闭环诊断",
                    "type": "skill",
                    "skill_id": "tms_fulfillment_exception",
                    "inputs": ["signed_rate", "unsigned_count", "unsigned_rate", "in_transit_count"],
                    "output": "签收积压、在途积压和履约闭环异常页。",
                },
                {
                    "name": "物流风险扫描",
                    "type": "skill",
                    "skill_id": "tms_logistics_risk_scan",
                    "inputs": ["ontime_rate", "delayed_rate", "in_transit_count", "unsigned_count", "project_shipment_count"],
                    "output": "风险信号、异常项目和优先级建议。",
                },
                {
                    "name": "承运商履约归因",
                    "type": "skill",
                    "skill_id": "tms_carrier_performance",
                    "inputs": ["carrier_shipment_count", "carrier_ontime_rate", "carrier_delay_count", "avg_delay_hours"],
                    "output": "承运商排行、准时率/延期双轴对比和低效承运商解释。",
                },
                {
                    "name": "项目延期拆解",
                    "type": "skill",
                    "skill_id": "tms_project_delay_analysis",
                    "inputs": ["project_shipment_count", "delayed_count", "delayed_rate", "avg_delay_hours"],
                    "output": "按项目、厂区和大区拆解延期来源。",
                },
                {
                    "name": "RFQ 供给侧补充",
                    "type": "skill",
                    "skill_id": "tms_rfq_analysis",
                    "inputs": ["enquiry_count", "supplier_quotation_count", "rfq_response_rate"],
                    "output": "询比价响应不足对运输供给风险的补充说明。",
                },
                {
                    "name": "经营叙事与制品渲染",
                    "type": "report_renderer",
                    "inputs": ["management_review", "analysis_results", "remark_style"],
                    "output": "补齐首屏摘要、经营指标、风险归因、行动建议和血缘附录，返回 HTML 在线报告链接和血缘审计信息。",
                },
            ],
            tags=["官方模板", "管理层", "在线报告", "高阶Skill", "HTML优先"],
            parameters=[
                {"name": "time_range", "label": "时间范围", "data_type": "TimeRange", "required": True},
                {"name": "factory", "label": "覆盖厂区", "data_type": "Factory", "required": True},
                {"name": "remark_style", "label": "AI备注风格", "data_type": "String", "required": False},
            ],
            version="2.0.0",
        ),
        ReportRecord(
            report_id="shared_carrier_weekly_digest",
            name="承运商履约周报",
            description="共享报表：按周汇总承运商接单、到货、签收和超时风险。",
            visibility="shared",
            owner="logistics-shared",
            outputTypes=["html", "push"],
            channels=["email"],
            template="interactive_dashboard",
            templateMode="built_in",
            templateLabel="交互分析页面模板",
            flow=(
                "解析周度范围和厂区 -> 执行承运商履约 Skill -> 执行物流风险扫描 Skill -> "
                "拆解签收和延期异常 -> 生成周报摘要与处理动作 -> 按交互分析页面模板输出 HTML 看板或 PUSH 摘要"
            ),
            sections=["履约概览", "承运商排行", "异常承运商", "待处理项目", "推送摘要", "血缘附录"],
            analysis_chain=[
                {
                    "name": "周度承运商履约",
                    "type": "skill",
                    "skill_id": "tms_carrier_performance",
                    "inputs": ["time_range", "factory", "carrier_shipment_count", "carrier_ontime_rate", "carrier_delay_count"],
                    "output": "承运商承运量、准时率、延期单量和重点关注名单。",
                },
                {
                    "name": "风险补充扫描",
                    "type": "skill",
                    "skill_id": "tms_logistics_risk_scan",
                    "inputs": ["unsigned_count", "unsigned_rate", "in_transit_count", "ontime_rate", "delayed_rate"],
                    "output": "周度异常风险和待处理项目。",
                },
                {
                    "name": "签收闭环补充",
                    "type": "skill",
                    "skill_id": "tms_fulfillment_exception",
                    "inputs": ["signed_rate", "unsigned_count", "project_shipment_count"],
                    "output": "签收积压责任线索和处理优先级。",
                },
                {
                    "name": "渠道制品生成",
                    "type": "report_renderer",
                    "inputs": ["interactive_dashboard", "analysis_results", "recipient"],
                    "output": "填充 KPI 看板、趋势图、异常明细和 AI 结论，生成 HTML 页面或 PUSH 文本摘要。",
                },
            ],
            tags=["周报", "承运商", "推送", "高阶Skill"],
            parameters=[
                {"name": "time_range", "label": "时间范围", "data_type": "TimeRange", "required": True},
                {"name": "factory", "label": "覆盖厂区", "data_type": "Factory", "required": True},
                {"name": "recipient", "label": "推送对象", "data_type": "Recipient", "required": True},
            ],
            version="1.2.0",
        ),
        ReportRecord(
            report_id="user_sample_monthly_tms_review",
            name="月度 TMS 运营复盘",
            description="示例报表：面向物流运营例会的月度成本、时效和异常复盘材料。",
            visibility="private",
            owner="system-admin",
            outputTypes=["html"],
            channels=[],
            template="management_review",
            templateMode="built_in",
            templateLabel="管理层在线经营报告模板",
            flow=(
                "承接用户输入参数 -> 运行 TMS 核心问数 -> 诊断签收闭环和风险水位 -> "
                "运行承运商、项目延期和 RFQ 补充分析 -> LLM 生成正式/简洁/详细等备注风格 -> "
                "按管理层在线报告模板渲染 HTML"
            ),
            sections=["关键结论", "核心指标趋势", "签收与在途风险", "承运商排行", "项目/大区拆解", "RFQ 供给侧补充", "下一步动作"],
            analysis_chain=[
                {
                    "name": "月度核心问数",
                    "type": "skill",
                    "skill_id": "tms_system_askdata",
                    "inputs": ["apply_count", "form_count", "execution_count", "signed_count", "ontime_rate", "delayed_rate"],
                    "output": "月度 TMS 运营水位和趋势摘要。",
                },
                {
                    "name": "签收与在途风险",
                    "type": "skill",
                    "skill_id": "tms_fulfillment_exception",
                    "inputs": ["signed_rate", "unsigned_count", "unsigned_rate", "in_transit_count"],
                    "output": "未签收积压、在途积压和闭环异常责任线索。",
                },
                {
                    "name": "承运商表现拆解",
                    "type": "skill",
                    "skill_id": "tms_carrier_performance",
                    "inputs": ["carrier_shipment_count", "carrier_ontime_rate", "carrier_delay_count"],
                    "output": "承运商排行与履约波动解释。",
                },
                {
                    "name": "延期项目定位",
                    "type": "skill",
                    "skill_id": "tms_project_delay_analysis",
                    "inputs": ["project_shipment_count", "delayed_count", "delayed_rate", "avg_delay_hours"],
                    "output": "延期项目、大区和厂区维度拆解。",
                },
                {
                    "name": "RFQ 供给侧补充",
                    "type": "skill",
                    "skill_id": "tms_rfq_analysis",
                    "inputs": ["enquiry_count", "supplier_quotation_count", "rfq_response_rate"],
                    "output": "供应商报价响应与运输供给风险补充。",
                },
                {
                    "name": "复盘材料生成",
                    "type": "report_renderer",
                    "inputs": ["management_review", "analysis_results", "remark_style"],
                    "output": "填充经营摘要、核心指标、风险归因、行动建议和血缘信息，输出 HTML 复盘页面和预览链接。",
                },
            ],
            tags=["tms", "月报", "经营复盘", "高阶Skill"],
            parameters=[
                {"name": "time_range", "label": "时间范围", "data_type": "TimeRange", "required": True},
                {"name": "factory", "label": "覆盖厂区", "data_type": "Factory", "required": True},
                {"name": "remark_style", "label": "AI备注风格", "data_type": "String", "required": False},
            ],
            version="1.0.0",
        ),
    ]


def _skill_with_product_schema(skill: SkillDefinition) -> SkillDefinition:
    output_schema = dict(skill.output_schema or {})
    if "schema" not in output_schema:
        output_schema["schema"] = {
            "parameters": [
                {
                    "name": param.name,
                    "label": param.description or param.name,
                    "dataType": param.data_type,
                    "required": param.required,
                }
                for param in skill.parameters
            ],
            "metrics": output_schema.get("metrics") or [],
            "analysisMethod": output_schema.get("analysisMethod") or skill.description,
            "outputFormat": output_schema.get("outputFormat") or "mixed_report",
            "steps": output_schema.get("steps") or [skill.description],
            "sql": output_schema.get("sql") or "由 AI-native Skill 运行时结合语义目录生成受控查询。",
            "time_fields": output_schema.get("time_fields") or {},
            "chartType": output_schema.get("chart") or output_schema.get("chartType") or "指标趋势图",
        }
    output_schema.setdefault("lifecycle", "published" if skill.visibility == SkillVisibility.SHARED else "solidified")
    output_schema.setdefault("creator", skill.owner_user_id or "tms-semantic-catalog")
    output_schema.setdefault("department", "物流部")
    output_schema.setdefault("version", "1.0.0")
    return skill.model_copy(update={"output_schema": output_schema})


def _skill_version(skill: SkillDefinition) -> str:
    return str(skill.output_schema.get("version") or "1.0.0")


def _validated_asset_ref(
    current: AssetRef | None,
    *,
    source_type: AssetSourceType,
    source_id: str,
    asset_type: AssetType,
    local_code: str,
    version: str,
) -> AssetRef:
    if current is not None:
        if current.asset.asset_type != asset_type or current.asset.local_code != local_code:
            raise ValueError("Asset identity cannot change its asset type or local code.")
        return AssetRef(asset=current.asset, version=version)
    return AssetRef(
        asset=AssetKey(
            source_type=source_type,
            source_id=source_id,
            asset_type=asset_type,
            local_code=local_code,
        ),
        version=version,
    )


def _validate_personal_ref_owner(current: AssetRef | None, owner_user_id: str) -> None:
    if current is None:
        return
    if (
        current.asset.source_type != AssetSourceType.PERSONAL_WORKSPACE
        or current.asset.source_id != owner_user_id
    ):
        raise ValueError("Personal asset identity must belong to the creating workspace.")


def _seed_metric_visibility_owner(metric_code: str) -> tuple[MetricVisibility, str]:
    custom_metric_codes = {
        "ontime_rate",
        "unsigned_count",
        "delayed_rate",
        "carrier_ontime_rate",
    }
    shared_metric_codes = {
        "carrier_shipment_count",
        "project_shipment_count",
        "delayed_count",
        "avg_delay_hours",
        "signed_rate",
        "unsigned_rate",
    }
    if metric_code in custom_metric_codes:
        return MetricVisibility.PRIVATE, "system-admin"
    if metric_code in shared_metric_codes:
        return MetricVisibility.SHARED, "logistics-shared"
    return MetricVisibility.OFFICIAL, "tms-semantic-catalog"


def _seed_skill_visibility_owner(skill_id: str) -> tuple[SkillVisibility, str]:
    custom_skill_ids = {
        "tms_carrier_performance",
    }
    shared_skill_ids = {
        "tms_transport_mode_distribution",
        "tms_logistics_risk_scan",
        "tms_fulfillment_exception",
        "tms_project_delay_analysis",
    }
    if skill_id in custom_skill_ids:
        return SkillVisibility.PRIVATE, "system-admin"
    if skill_id in shared_skill_ids:
        return SkillVisibility.SHARED, "logistics-shared"
    return SkillVisibility.OFFICIAL, "tms-semantic-catalog"


def _metric_with_validated_sql(metric: MetricDefinition) -> MetricDefinition:
    return metric.model_copy(
        update={
            "formula": metric.formula.model_copy(
                update={"expression": validate_metric_select_sql(metric.formula.expression)}
            )
        }
    )


def _owner_from_report(report: ReportRecord) -> str:
    if report.visibility == "official":
        return "tms-semantic-catalog"
    if report.visibility == "shared":
        return report.owner or "logistics-shared"
    return report.owner or "system-admin"


def _is_report_owner(report: ReportRecord, user_id: str) -> bool:
    owner = (report.owner or "").strip()
    return owner == user_id or owner == f"user_{_slug(user_id)}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _is_admin(role_ids: list[str] | None = None) -> bool:
    return bool({"admin", "role-admin", "role-system-admin"} & set(role_ids or []))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _chat_title(text: str, limit: int = 28) -> str:
    normalized = re.sub(r"\s+", " ", text).strip() or "新对话"
    return normalized if len(normalized) <= limit else f"{normalized[:limit]}..."


def _slug(value: str) -> str:
    return re.sub(r"[^\w-]", "_", value).strip("_").lower() or "anonymous"
