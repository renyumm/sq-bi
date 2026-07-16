"""AI Pack Drafter — generate a structured EnterprisePackDraft from profile + documents.

The LLM produces candidate entities, enterprise fields, terms, metric formulas,
analysis steps, and acceptance questions. The output is NEVER SQL; the LLM
stage returns structured JSON. Field proposals are validated against the
data-source semantic profile; metric formulas compile through the deterministic
path and are guardrail-checked before acceptance.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sq_bi_contracts.enterprise_pack import (
    PackAcceptanceQuestion,
    PackDraftResult,
    PackEnterpriseField,
    PackEnterpriseMetric,
    PackEntity,
    PackTerm,
    EnterprisePackDraft,
)
from sq_bi_contracts.metrics import MetricFormula

from .enterprise_pack_store import EnterprisePackStore
from .guardrails import SQLValidationError, validate_sql
from .semantic_profile_store import SemanticProfileStore

logger = logging.getLogger(__name__)

_PACK_DRAFT_SYSTEM_PROMPT = """\
You are a business intelligence architect. Given a database semantic profile and \
optionally one or more business documents, produce a structured enterprise domain pack draft.

Return ONLY valid JSON (no markdown fences) with this schema:
{
  "entities": [
    {"entity_id": "<short_snake_case>", "name": "<Chinese business name>", "physical_table": "<TABLE>", "tags": [], "description": "<optional>"}
  ],
  "fields": [
    {
      "field_id": "<short_snake_case>",
      "business_name": "<Chinese name>",
      "physical_table": "<TABLE>",
      "physical_column": "<COLUMN>",
      "data_type": "<type>",
      "entity_id": "<entity_id or null>",
      "synonyms": ["<synonym>"],
      "description": "<optional>"
    }
  ],
  "terms": [
    {"term_id": "<short_snake_case>", "term": "<Chinese term>", "definition": "<definition>", "synonyms": []}
  ],
  "metrics": [
    {
      "metric_code": "<snake_case>",
      "name": "<Chinese metric name>",
      "definition": "<Chinese business definition>",
      "formula_expression": "<SQL aggregate expression using physical columns, e.g. SUM(table.col)>",
      "filters": [],
      "time_field": "<TABLE.COLUMN or null>",
      "entity_id": "<entity_id or null>",
      "synonyms": []
    }
  ],
  "acceptance_questions": [
    {"question_id": "<short_id>", "question": "<Chinese question>", "expected_metric_code": "<metric_code or null>"}
  ]
}

Rules:
- Only reference physical tables and columns that appear in the provided semantic profile.
- Do NOT return raw SQL statements. formula_expression must be a single SQL aggregate fragment \
  like SUM(table.col) or COUNT(DISTINCT table.col) — not a full SELECT statement.
- Field entity_id must reference an entity declared in the same response.
- Metric formula_expression references ONLY columns visible in the profile.
- Write all Chinese-language business names, definitions, terms, and questions in Simplified Chinese.
- Be concrete and grounded in the profile; do not invent table or column names.
"""


class PackDrafter:
    """Generates a validated EnterprisePackDraft from profile + documents."""

    def __init__(
        self,
        llm_client: Any,
        profile_store_path: str | Path | None = None,
    ) -> None:
        self._llm = llm_client
        self._profile_store_path = Path(profile_store_path) if profile_store_path else None

    def draft(
        self,
        data_source_id: str,
        document_texts: list[str] | None = None,
    ) -> PackDraftResult:
        """Generate a structured pack draft.

        Returns:
            PackDraftResult with the validated draft, dropped fields, and rejected metrics.
        """
        profile_columns = self._load_profile_columns(data_source_id)
        semantic_context = self._build_semantic_context(data_source_id, profile_columns)
        doc_context = _format_documents(document_texts or [])

        user_prompt = f"数据源: {data_source_id}\n\n{semantic_context}"
        if doc_context:
            user_prompt += f"\n\n业务文档:\n{doc_context}"

        try:
            raw = self._llm.chat(system=_PACK_DRAFT_SYSTEM_PROMPT, user=user_prompt)
            payload = json.loads(raw)
        except Exception as exc:
            logger.warning("pack_drafter.llm_failure", exc_info=True)
            return PackDraftResult(
                draft=EnterprisePackDraft(),
                rejection_reasons={"__llm__": str(exc)},
            )

        return self._validate_and_assemble(payload, profile_columns)

    # ── Validation & assembly ─────────────────────────────────────────────────

    def _validate_and_assemble(
        self,
        payload: dict[str, Any],
        profile_columns: set[tuple[str, str]],
    ) -> PackDraftResult:
        entities = _parse_entities(payload.get("entities") or [])
        raw_fields = payload.get("fields") or []
        raw_metrics = payload.get("metrics") or []
        terms = _parse_terms(payload.get("terms") or [])
        acceptance_questions = _parse_acceptance_questions(payload.get("acceptance_questions") or [])

        # Validate fields against profile
        kept_fields: list[PackEnterpriseField] = []
        dropped_fields: list[str] = []
        for rf in raw_fields:
            table = str(rf.get("physical_table") or "")
            col = str(rf.get("physical_column") or "")
            key = (table.upper(), col.upper())
            normalized = {(t.upper(), c.upper()) for t, c in profile_columns}
            if not profile_columns or key in normalized:
                kept_fields.append(PackEnterpriseField(
                    field_id=str(rf.get("field_id") or f"ef_{table}_{col}").lower(),
                    business_name=str(rf.get("business_name") or col),
                    data_type=str(rf.get("data_type") or "TEXT"),
                    entity_id=rf.get("entity_id") or None,
                    synonyms=list(rf.get("synonyms") or []),
                    description=rf.get("description") or None,
                    source="ai_draft",
                ))
            else:
                dropped_fields.append(rf.get("field_id") or f"{table}.{col}")
                logger.warning(
                    "pack_drafter.field_not_in_profile",
                    extra={"field": f"{table}.{col}"},
                )

        # Validate and compile metric formulas
        kept_metrics: list[PackEnterpriseMetric] = []
        rejected_metrics: list[str] = []
        rejection_reasons: dict[str, str] = {}
        for rm in raw_metrics:
            code = str(rm.get("metric_code") or "unknown")
            expr = str(rm.get("formula_expression") or "")
            sql_for_check = f"SELECT {expr} FROM DUAL"
            try:
                validate_sql(sql_for_check)
            except (SQLValidationError, Exception) as exc:
                reason = str(exc)
                rejected_metrics.append(code)
                rejection_reasons[code] = reason
                logger.warning("pack_drafter.metric_rejected", extra={"metric_code": code, "reason": reason})
                continue

            if _contains_raw_sql(expr):
                rejected_metrics.append(code)
                rejection_reasons[code] = "formula_expression contains a full SQL statement; only aggregate fragments are allowed"
                continue

            kept_metrics.append(PackEnterpriseMetric(
                metric_code=code,
                name=str(rm.get("name") or code),
                definition=str(rm.get("definition") or ""),
                formula=MetricFormula(
                    expression=expr,
                    filters=list(rm.get("filters") or []),
                    time_field=rm.get("time_field") or None,
                ),
                entity_id=rm.get("entity_id") or None,
                synonyms=list(rm.get("synonyms") or []),
                source="ai_draft",
            ))

        draft = EnterprisePackDraft(
            entities=entities,
            fields=kept_fields,
            metrics=kept_metrics,
            terms=terms,
            acceptance_questions=acceptance_questions,
        )
        return PackDraftResult(
            draft=draft,
            dropped_fields=dropped_fields,
            rejected_metrics=rejected_metrics,
            rejection_reasons=rejection_reasons,
        )

    def _load_profile_columns(self, data_source_id: str) -> set[tuple[str, str]]:
        if not self._profile_store_path or not self._profile_store_path.exists():
            return set()
        try:
            store = SemanticProfileStore(self._profile_store_path)
            profile = store.load_profile(data_source_id)
            if not profile:
                return set()
            cols: set[tuple[str, str]] = set()
            for space in profile.spaces:
                for entity in space.entities:
                    for field in entity.fields:
                        cols.add((field.physical_table.upper(), field.physical_column.upper()))
            return cols
        except Exception:
            logger.warning("pack_drafter.profile_load_failed", exc_info=True)
            return set()

    def _build_semantic_context(
        self,
        data_source_id: str,
        profile_columns: set[tuple[str, str]],
    ) -> str:
        if not profile_columns:
            return f"数据源 {data_source_id} 的语义档案暂不可用。"
        tables: dict[str, list[str]] = {}
        for table, col in sorted(profile_columns):
            tables.setdefault(table, []).append(col)
        lines = [f"数据源: {data_source_id}", "可用物理字段:"]
        for table, cols in sorted(tables.items()):
            lines.append(f"  {table}: {', '.join(sorted(cols))}")
        return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_documents(texts: list[str]) -> str:
    return "\n\n---\n\n".join(t.strip() for t in texts if t.strip())


def _contains_raw_sql(expr: str) -> bool:
    """Return True if the expression looks like a full SELECT statement."""
    upper = expr.strip().upper()
    return upper.startswith("SELECT") or "FROM " in upper or "\nFROM" in upper.upper()


def _parse_entities(raw: list[dict[str, Any]]) -> list[PackEntity]:
    result: list[PackEntity] = []
    for r in raw:
        try:
            result.append(PackEntity(
                entity_id=str(r.get("entity_id") or ""),
                name=str(r.get("name") or ""),
                description=r.get("description") or None,
                tags=list(r.get("tags") or []),
                source="ai_draft",
            ))
        except Exception:
            pass
    return result


def _parse_terms(raw: list[dict[str, Any]]) -> list[PackTerm]:
    result: list[PackTerm] = []
    for r in raw:
        try:
            result.append(PackTerm(
                term_id=str(r.get("term_id") or ""),
                term=str(r.get("term") or ""),
                definition=str(r.get("definition") or ""),
                synonyms=list(r.get("synonyms") or []),
            ))
        except Exception:
            pass
    return result


def _parse_acceptance_questions(raw: list[dict[str, Any]]) -> list[PackAcceptanceQuestion]:
    result: list[PackAcceptanceQuestion] = []
    for r in raw:
        try:
            result.append(PackAcceptanceQuestion(
                question_id=str(r.get("question_id") or ""),
                question=str(r.get("question") or ""),
                expected_metric_code=r.get("expected_metric_code") or None,
            ))
        except Exception:
            pass
    return result
