from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
import yaml

from sq_bi_contracts.catalog import DataSource, SemanticTable, SemanticField
from sq_bi_contracts.metrics import (
    MetricDefinition,
)
from sq_bi_contracts.skills import (
    SkillDefinition,
    SkillResolveRequest,
    SkillResolveResult,
    SkillParameter,
)
from sq_bi_contracts.enums import (
    MetricVisibility,
    SkillVisibility,
    DatabaseType,
    SkillType,
)

from .interfaces import CatalogRepository, MetricRepository, SkillRepository
from .sql_validation import validate_metric_select_sql
from .synonyms import match_synonyms, is_partial_match, normalize_text


class FileBackedSemanticRepository(CatalogRepository, MetricRepository, SkillRepository):
    def __init__(self, data_file: Path | str, user_metrics_file: Path | str | None = None) -> None:
        self.data_file = Path(data_file)
        if user_metrics_file:
            self.user_metrics_file = Path(user_metrics_file)
        else:
            self.user_metrics_file = self.data_file.parent / "user_metrics.json"

        self.data_sources: dict[str, DataSource] = {}
        self.tables: dict[str, SemanticTable] = {}
        self.fields: dict[str, SemanticField] = {}
        self.official_metrics: dict[str, MetricDefinition] = {}
        self.user_metrics: dict[str, MetricDefinition] = {}
        self.skills: dict[str, SkillDefinition] = {}

        self._load_data()
        self._load_user_metrics()

    def _load_data(self) -> None:
        if not self.data_file.exists():
            raise FileNotFoundError(f"Semantic data file not found: {self.data_file}")

        with open(self.data_file, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        # 1. Load Data Sources
        for ds_raw in raw.get("data_sources", []):
            ds = DataSource(**ds_raw)
            self.data_sources[ds.data_source_id] = ds

        # 2. Load Tables
        for table_raw in raw.get("tables", []):
            table = SemanticTable(**table_raw)
            self.tables[table.table_id] = table

        # 3. Load Fields
        for field_raw in raw.get("fields", []):
            field = SemanticField(**field_raw)
            self.fields[field.field_id] = field

        # 4. Load Official Metrics
        for metric_raw in raw.get("metrics", []):
            metric = MetricDefinition(**metric_raw)
            self.official_metrics[metric.metric_code] = metric

        # 5. Load Skills
        for skill_raw in raw.get("skills", []):
            skill = SkillDefinition(**skill_raw)
            self.skills[skill.skill_id] = skill

    def _load_user_metrics(self) -> None:
        if not self.user_metrics_file.exists():
            return
        try:
            with open(self.user_metrics_file, "r", encoding="utf-8") as f:
                data = json.load(f) or []
            for metric_raw in data:
                metric = MetricDefinition(**metric_raw)
                self.user_metrics[metric.metric_code] = metric
        except Exception:
            # Fallback if file is corrupted
            self.user_metrics = {}

    def _save_user_metrics(self) -> None:
        raw_list = [json.loads(m.model_dump_json()) for m in self.user_metrics.values()]
        with open(self.user_metrics_file, "w", encoding="utf-8") as f:
            json.dump(raw_list, f, ensure_ascii=False, indent=2)

    # --- CatalogRepository Implementation ---

    def get_data_source(self, data_source_id: str) -> DataSource | None:
        return self.data_sources.get(data_source_id)

    def list_data_sources(self) -> list[DataSource]:
        return list(self.data_sources.values())

    def get_table(self, table_id: str) -> SemanticTable | None:
        return self.tables.get(table_id)

    def list_tables(self, data_source_id: str | None = None) -> list[SemanticTable]:
        tables = list(self.tables.values())
        if data_source_id:
            tables = [t for t in tables if t.data_source_id == data_source_id]
        return tables

    def get_field(self, field_id: str) -> SemanticField | None:
        return self.fields.get(field_id)

    def list_fields(self, table_id: str | None = None) -> list[SemanticField]:
        fields = list(self.fields.values())
        if table_id:
            fields = [f for f in fields if f.table_id == table_id]
        return fields

    # --- MetricRepository Implementation ---

    def list_metrics(self, visibility: MetricVisibility | None = None) -> list[MetricDefinition]:
        all_metrics = list(self.official_metrics.values()) + list(self.user_metrics.values())
        if visibility:
            all_metrics = [m for m in all_metrics if m.visibility == visibility]
        return all_metrics

    def get_metric_by_code(self, metric_code: str) -> MetricDefinition | None:
        return self.official_metrics.get(metric_code) or self.user_metrics.get(metric_code)

    def create_user_metric(self, metric: MetricDefinition) -> MetricDefinition:
        metric = metric.model_copy(
            update={
                "formula": metric.formula.model_copy(
                    update={"expression": validate_metric_select_sql(metric.formula.expression)}
                )
            }
        )
        # Check name conflict with official metrics
        normalized_name = normalize_text(metric.name)
        for off_metric in self.official_metrics.values():
            if normalize_text(off_metric.name) == normalized_name:
                raise ValueError(f"Metric name '{metric.name}' conflicts with official metric '{off_metric.name}'")

        # Persist
        self.user_metrics[metric.metric_code] = metric
        self._save_user_metrics()
        return metric

    # --- SkillRepository Implementation ---

    def list_skills(self, visibility: SkillVisibility | None = None) -> list[SkillDefinition]:
        all_skills = list(self.skills.values())
        if visibility:
            all_skills = [s for s in all_skills if s.visibility == visibility]
        return all_skills

    def resolve_skill(self, request: SkillResolveRequest) -> SkillResolveResult:
        # Check synonyms or name matching
        exact_matches = []
        candidates = []

        query_text = request.text or request.trigger

        for skill in self.skills.values():
            if match_synonyms(query_text, skill.name, skill.synonyms):
                exact_matches.append(skill)
            elif is_partial_match(query_text, skill.name, skill.synonyms):
                candidates.append(skill)

        matched_skill = exact_matches[0] if exact_matches else None
        # If we have an exact match, it is the matched_skill. Candidates can include all partial matches.
        return SkillResolveResult(
            matched_skill=matched_skill,
            candidates=exact_matches + candidates,
        )
