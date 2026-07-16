"""Semantic discovery engine.

LLM stage: clusters tables into SemanticSpaces and proposes entities/fields.
Parses LLM output into typed contract models.
Assigns origin=inferred, computes confidence, attaches evidence.
Retains conflicting candidates rather than collapsing them.
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from sq_bi_contracts.semantic_profile import (
    EvidenceItem,
    EvidenceSource,
    FieldOrigin,
    SemanticEntity,
    SemanticField,
    SemanticSpace,
    TableRecommendation,
)

from .llm_client import OpenAICompatClient, parse_json_payload
from .schema_profiler import TableProfile
from .schema_scanner import SchemaScanner, ScanMetadata, TableMeta

logger = logging.getLogger(__name__)

_DISCOVERY_SYSTEM_PROMPT = """\
You are a database semantics expert. Given table metadata and optional profiling data,
cluster the tables into business semantic spaces and propose business names, entity
descriptions, and field interpretations.

Respond in JSON with the following shape:
{
  "spaces": [
    {
      "name": "<business domain name in Chinese>",
      "description": "<one-sentence description>",
      "entities": [
        {
          "physical_table": "<TABLE_NAME>",
          "business_name": "<Chinese business name>",
          "description": "<description>",
          "recommendation": "recommended_include|possibly_relevant|not_relevant",
          "fields": [
            {
              "physical_column": "<COLUMN_NAME>",
              "business_name": "<Chinese field name>",
              "description": "<description>",
              "semantic_role": "identifier|measure|dimension|time|attribute|flag|other",
              "default_aggregation": "sum|count|avg|max|min|none",
              "synonyms": ["<synonym>"],
              "confidence": 0.0..1.0,
              "evidence_sources": ["comment","name","sample","document","ai_inference"]
            }
          ]
        }
      ]
    }
  ]
}

Rules:
- Every field must have at least ["ai_inference"] in evidence_sources.
- confidence is 0.0-1.0; use 0.9+ only when DB comment explicitly states the meaning.
- Return ONLY valid JSON. No markdown.
"""


def _table_chunk_to_prompt(
    chunk: list[TableMeta],
    profiles: dict[str, TableProfile],
    business_description: str | None,
) -> str:
    lines: list[str] = []
    if business_description:
        lines.append(f"Business context: {business_description}\n")
    lines.append("## Table Metadata\n")
    lines.append(SchemaScanner.render_chunk_for_llm(chunk))

    profile_data = [profiles[t.name] for t in chunk if t.name in profiles]
    if profile_data:
        lines.append("\n## Column Profiles")
        for tp in profile_data:
            lines.append(f"\n### {tp.table_name}")
            for cp in tp.columns:
                if cp.is_sensitive:
                    continue
                parts: list[str] = [f"  {cp.name}"]
                if cp.null_rate is not None:
                    parts.append(f"null_rate={cp.null_rate:.2f}")
                if cp.unique_rate is not None:
                    parts.append(f"unique_rate={cp.unique_rate:.2f}")
                if cp.enum_distribution:
                    top = list(cp.enum_distribution.items())[:5]
                    parts.append(f"enum={top}")
                if cp.sample_values:
                    parts.append(f"samples={cp.sample_values[:3]}")
                lines.append(" ".join(parts))

    return "\n".join(lines)


def _normalize_name(value: str | None) -> str:
    return str(value or "").strip().upper()


def _table_lookup(chunks: list[list[TableMeta]]) -> dict[str, TableMeta]:
    return {
        _normalize_name(table.name): table
        for chunk in chunks
        for table in chunk
    }


def _profile_lookup(profiles: dict[str, TableProfile]) -> dict[str, TableProfile]:
    lookup: dict[str, TableProfile] = {}
    for key, profile in profiles.items():
        lookup[_normalize_name(key)] = profile
        lookup[_normalize_name(profile.table_name)] = profile
    return lookup


def _column_lookup(table: TableMeta | None) -> dict[str, object]:
    if table is None:
        return {}
    return {_normalize_name(col.name): col for col in table.columns}


def _profile_column_lookup(profile: TableProfile | None) -> dict[str, object]:
    if profile is None:
        return {}
    return {_normalize_name(col.name): col for col in profile.columns}


def _dedupe_evidence(items: list[EvidenceItem]) -> list[EvidenceItem]:
    seen: set[tuple[EvidenceSource, str | None]] = set()
    result: list[EvidenceItem] = []
    for item in items:
        key = (item.source, item.detail)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _safe_preview(values: list[str], limit: int = 3) -> str:
    return "、".join(str(v) for v in values[:limit])


def _real_evidence_for_field(
    *,
    table: TableMeta,
    column_name: str,
    field_data: dict,
    profile: TableProfile | None,
) -> list[EvidenceItem]:
    columns = _column_lookup(table)
    col = columns.get(_normalize_name(column_name))
    profile_col = _profile_column_lookup(profile).get(_normalize_name(column_name))
    evidence: list[EvidenceItem] = []

    if col is not None and getattr(col, "comment", None):
        evidence.append(
            EvidenceItem(
                source=EvidenceSource.comment,
                detail=f"列注释: {getattr(col, 'comment')}",
            )
        )
    elif table.comment:
        evidence.append(
            EvidenceItem(source=EvidenceSource.comment, detail=f"表注释: {table.comment}")
        )

    if col is not None:
        type_suffix = f"，类型 {getattr(col, 'data_type')}" if getattr(col, "data_type", None) else ""
        evidence.append(
            EvidenceItem(
                source=EvidenceSource.name,
                detail=f"扫描到物理列 {table.name}.{getattr(col, 'name')}{type_suffix}",
            )
        )

    if profile_col is not None and not getattr(profile_col, "is_sensitive", False):
        enum_distribution = getattr(profile_col, "enum_distribution", {}) or {}
        sample_values = getattr(profile_col, "sample_values", []) or []
        if enum_distribution:
            preview = "、".join(
                f"{value}({count})"
                for value, count in list(enum_distribution.items())[:3]
            )
            evidence.append(EvidenceItem(source=EvidenceSource.sample, detail=f"真实枚举分布: {preview}"))
        elif sample_values:
            evidence.append(
                EvidenceItem(source=EvidenceSource.sample, detail=f"真实样本值: {_safe_preview(sample_values)}")
            )

    role = str(field_data.get("semantic_role") or "未指定角色")
    evidence.append(
        EvidenceItem(
            source=EvidenceSource.ai_inference,
            detail=f"系统基于扫描元数据、业务背景和字段画像推断业务名/语义角色: {role}",
        )
    )
    return _dedupe_evidence(evidence)


def _llm_declared_evidence(field_data: dict) -> list[EvidenceItem]:
    ev_sources: list[str] = field_data.get("evidence_sources", ["ai_inference"])
    evidence: list[EvidenceItem] = []
    for src in ev_sources:
        try:
            evidence.append(EvidenceItem(source=EvidenceSource(src)))
        except ValueError:
            evidence.append(EvidenceItem(source=EvidenceSource.ai_inference))
    return _dedupe_evidence(evidence)


def _parse_llm_spaces(
    raw_json: dict,
    snapshot_id: str,
    source_tables: set[str],
    table_metas: dict[str, TableMeta] | None = None,
    profiles: dict[str, TableProfile] | None = None,
) -> list[SemanticSpace]:
    spaces: list[SemanticSpace] = []
    source_table_names = {_normalize_name(t) for t in source_tables}
    table_metas = table_metas or {}
    profiles = profiles or {}
    for space_data in raw_json.get("spaces", []):
        space_id = f"sp_{uuid4().hex[:12]}"
        entities: list[SemanticEntity] = []

        for entity_data in space_data.get("entities", []):
            physical_table = _normalize_name(entity_data.get("physical_table", ""))
            if physical_table not in source_table_names:
                continue
            table_meta = table_metas.get(physical_table)
            table_columns = _column_lookup(table_meta)
            table_profile = profiles.get(physical_table)

            entity_id = f"ent_{uuid4().hex[:12]}"
            rec_str = entity_data.get("recommendation", "recommended_include")
            try:
                recommendation = TableRecommendation(rec_str)
            except ValueError:
                recommendation = TableRecommendation.possibly_relevant

            fields: list[SemanticField] = []
            for field_data in entity_data.get("fields", []):
                physical_column = _normalize_name(field_data.get("physical_column", ""))
                if not physical_column:
                    continue
                column_meta = table_columns.get(physical_column) if table_meta else None
                if table_meta is not None and column_meta is None:
                    continue

                confidence = float(field_data.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))

                if table_meta is not None:
                    evidence = _real_evidence_for_field(
                        table=table_meta,
                        column_name=physical_column,
                        field_data=field_data,
                        profile=table_profile,
                    )
                    data_type = getattr(column_meta, "data_type", None)
                    physical_reference = (
                        f"{table_meta.schema}.{table_meta.name}.{physical_column}"
                        if table_meta.schema
                        else f"{table_meta.name}.{physical_column}"
                    )
                else:
                    evidence = _llm_declared_evidence(field_data)
                    data_type = None
                    physical_reference = None

                synonyms = [str(s) for s in field_data.get("synonyms", [])]

                fields.append(
                    SemanticField(
                        field_id=f"fld_{uuid4().hex[:12]}",
                        entity_id=entity_id,
                        physical_table=physical_table,
                        physical_column=physical_column,
                        business_name=str(field_data.get("business_name", physical_column)),
                        description=field_data.get("description"),
                        data_type=data_type,
                        origin=FieldOrigin.inferred,
                        semantic_role=field_data.get("semantic_role"),
                        default_aggregation=field_data.get("default_aggregation"),
                        synonyms=synonyms,
                        confidence=confidence,
                        evidence=evidence,
                        physical_reference=physical_reference,
                    )
                )

            entities.append(
                SemanticEntity(
                    entity_id=entity_id,
                    space_id=space_id,
                    physical_table=physical_table,
                    business_name=str(entity_data.get("business_name", physical_table)),
                    description=entity_data.get("description"),
                    recommendation=recommendation,
                    fields=fields,
                )
            )

        spaces.append(
            SemanticSpace(
                space_id=space_id,
                snapshot_id=snapshot_id,
                name=str(space_data.get("name", "未命名空间")),
                description=space_data.get("description"),
                entities=entities,
                accepted=False,
            )
        )
    return spaces


class SemanticDiscovery:
    """Orchestrates LLM-based semantic clustering."""

    def __init__(self, llm: OpenAICompatClient) -> None:
        self._llm = llm

    def discover(
        self,
        snapshot_id: str,
        chunks: list[list[TableMeta]],
        profiles: dict[str, TableProfile],
        *,
        business_description: str | None = None,
    ) -> tuple[list[SemanticSpace], dict[str, int]]:
        """Run discovery over all chunks, merge results.

        Returns (spaces, recommendation_counts).
        """
        all_spaces: list[SemanticSpace] = []
        source_tables = {
            t.name
            for chunk in chunks
            for t in chunk
        }
        tables_by_name = _table_lookup(chunks)
        profiles_by_name = _profile_lookup(profiles)

        for i, chunk in enumerate(chunks):
            logger.info(
                "semantic_discovery.chunk",
                extra={"chunk": i + 1, "total": len(chunks), "tables": len(chunk)},
            )
            prompt = _table_chunk_to_prompt(chunk, profiles, business_description)
            raw_json: dict[str, object] | None = None
            last_error: Exception | None = None
            for attempt in range(1, 4):
                try:
                    raw_text = self._llm.chat(
                        _DISCOVERY_SYSTEM_PROMPT,
                        prompt,
                        response_format={"type": "json_object"},
                    )
                    raw_json = parse_json_payload(raw_text)
                    if not raw_json.get("spaces"):
                        raise ValueError("LLM returned no semantic spaces.")
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "semantic_discovery.llm.failed",
                        extra={
                            "chunk": i + 1,
                            "attempt": attempt,
                            "error": str(exc),
                        },
                    )
            if raw_json is None:
                raise RuntimeError(
                    f"语义空间推荐生成失败（第 {i + 1}/{len(chunks)} 批，模型调用已重试 3 次）："
                    f"{last_error}"
                ) from last_error

            spaces = _parse_llm_spaces(
                raw_json,
                snapshot_id,
                source_tables,
                table_metas=tables_by_name,
                profiles=profiles_by_name,
            )
            all_spaces.extend(spaces)

        recommendation_counts = _count_recommendations(all_spaces)
        return all_spaces, recommendation_counts

    def recommend_tables(
        self,
        snapshot_id: str,
        metadata: ScanMetadata,
        *,
        business_description: str | None = None,
    ) -> tuple[list[SemanticSpace], dict[str, int]]:
        """Lightweight recommendation pass (no profiling data)."""
        from .schema_scanner import SchemaScanner

        scanner = SchemaScanner.__new__(SchemaScanner)
        scanner._chunk_size = 30
        chunks = [
            metadata.included[i : i + 30]
            for i in range(0, len(metadata.included), 30)
        ]
        return self.discover(
            snapshot_id,
            chunks,
            profiles={},
            business_description=business_description,
        )


def _count_recommendations(spaces: list[SemanticSpace]) -> dict[str, int]:
    counts: dict[str, int] = {
        TableRecommendation.recommended_include.value: 0,
        TableRecommendation.possibly_relevant.value: 0,
        TableRecommendation.not_relevant.value: 0,
    }
    for space in spaces:
        for entity in space.entities:
            key = entity.recommendation.value
            counts[key] = counts.get(key, 0) + 1
    return counts
