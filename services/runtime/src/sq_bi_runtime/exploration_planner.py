"""Phase 3 AI Exploration Planner.

Asks the LLM for a structured interpretation (JSON, never SQL) of an
exploration question grounded in the database semantic profile, computes
confidence tier and Join evidence deterministically from Phase-1 evidence,
and prepares the query plan for compilation through the existing ask pipeline.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sq_bi_contracts.exploration import (
    AnswerPath,
    ClarificationOption,
    ClarificationRequest,
    ConfidenceTier,
    FieldAssumption,
    JoinAssumption,
    JoinEvidence,
    QueryAssumption,
)
from sq_bi_contracts.semantic_profile import FieldOrigin

logger = logging.getLogger(__name__)

# Fields that, if found in the profile with the right confidence, indicate
# high vs medium tier. Threshold values from the design.
_HIGH_CONFIDENCE_THRESHOLD = 0.75
_MEDIUM_CONFIDENCE_THRESHOLD = 0.4

_EXPLORATION_SYSTEM_PROMPT = """\
You are a database semantic interpreter. Given a user question and a database semantic context, \
produce a JSON interpretation of how to answer the question using the listed tables and fields.

Return ONLY valid JSON (no markdown fences) with this schema:
{
  "fields": [
    {
      "physical_table": "<TABLE_NAME>",
      "physical_column": "<COLUMN_NAME>",
      "business_name": "<business label>",
      "inferred_meaning": "<brief explanation>",
      "role": "measure|dimension|time|filter"
    }
  ],
  "aggregation": "<SUM|COUNT|COUNT_DISTINCT|AVG|MAX|MIN|RATE|null>",
  "time_field": "<TABLE.COLUMN or null>",
  "time_grain": "<day|week|month|quarter|year or null>",
  "filters": ["<condition string>"],
  "joins": [
    {
      "left_table": "<TABLE>",
      "right_table": "<TABLE>",
      "join_key": "<COLUMN>",
      "evidence": "<foreign_key|declared_relation|document|name_uniqueness_validated|llm_guess>",
      "note": "<optional explanation>"
    }
  ],
  "clarification_needed": false,
  "clarification_question": null,
  "clarification_options": []
}

Rules:
- Only reference tables and columns that appear in the provided semantic context.
- Do NOT emit SQL.
- If the question is too ambiguous to interpret confidently, set clarification_needed to true \
and provide 2-4 clarification_options.
- For joins, honestly assess the evidence level: prefer foreign_key or declared_relation; \
use llm_guess only when guessing.
"""


@dataclass
class ExplorationPlan:
    """Result of the exploration planning stage."""

    question: str
    data_source_id: str
    assumption: QueryAssumption
    confidence_tier: ConfidenceTier
    clarification: ClarificationRequest | None = None
    # Compact text to pass as extra_context to the ask pipeline
    follow_up_context: str = ""
    # Whether the plan is safe to execute (tier not low, joins safe)
    executable: bool = True


class ExplorationPlanner:
    """Structured LLM planning stage for the exploration path."""

    def __init__(
        self,
        llm_client: Any,
        profile_store_path: Path | str | None = None,
    ) -> None:
        self._llm = llm_client
        self._profile_store_path = profile_store_path

    def plan(
        self,
        question: str,
        data_source_id: str,
        semantic_context: str = "",
    ) -> ExplorationPlan:
        """Produce an ExplorationPlan for the given question.

        semantic_context is the output of SemanticRetriever (already retrieved
        by the ask endpoint); if empty the planner fetches its own context.
        """
        profile_fields = self._load_profile_fields(data_source_id)

        ctx = semantic_context or self._build_fallback_context(data_source_id)

        user_prompt = (
            f"Database semantic context:\n{ctx}\n\n"
            f"User question: {question}\n\n"
            "Provide the structured JSON interpretation."
        )

        try:
            raw = self._llm.chat(_EXPLORATION_SYSTEM_PROMPT, user_prompt)
            interp = _parse_json(raw)
        except Exception as exc:
            logger.warning("exploration_planner.llm_failed", extra={"error": str(exc)})
            interp = {}

        return self._build_plan(question, data_source_id, interp, profile_fields)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_profile_fields(self, data_source_id: str) -> dict[str, Any]:
        """Load {table.column -> SemanticField} from the profile store."""
        if not self._profile_store_path:
            return {}
        try:
            from .semantic_profile_store import SemanticProfileStore
            store = SemanticProfileStore(self._profile_store_path)
            profile = store.load_profile(data_source_id)
            if not profile:
                return {}
            result: dict[str, Any] = {}
            for space in profile.spaces:
                for entity in space.entities:
                    for f in entity.fields:
                        key = f"{entity.physical_table}.{f.physical_column}".upper()
                        result[key] = f
            return result
        except Exception as exc:
            logger.debug("exploration_planner.profile_load_failed", extra={"error": str(exc)})
            return {}

    def _build_fallback_context(self, data_source_id: str) -> str:
        if not self._profile_store_path:
            return ""
        try:
            from .semantic_retriever import SemanticRetriever
            from .semantic_profile_store import SemanticProfileStore
            store = SemanticProfileStore(self._profile_store_path)
            retriever = SemanticRetriever(store)
            return retriever.get_context_for_question("", data_source_id)
        except Exception:
            return ""

    def _build_plan(
        self,
        question: str,
        data_source_id: str,
        interp: dict[str, Any],
        profile_fields: dict[str, Any],
    ) -> ExplorationPlan:
        # Clarification short-circuit
        if interp.get("clarification_needed"):
            clarification = _build_clarification(interp)
            assumption = QueryAssumption()
            return ExplorationPlan(
                question=question,
                data_source_id=data_source_id,
                assumption=assumption,
                confidence_tier=ConfidenceTier.low,
                clarification=clarification,
                executable=False,
            )

        # Build FieldAssumptions — drop fields not in profile
        field_assumptions = _build_field_assumptions(interp.get("fields", []), profile_fields)

        # Build JoinAssumptions
        join_assumptions = _build_join_assumptions(interp.get("joins", []))

        assumption = QueryAssumption(
            fields_used=field_assumptions,
            aggregation=interp.get("aggregation") or None,
            time_field=interp.get("time_field") or None,
            time_grain=interp.get("time_grain") or None,
            filters=list(interp.get("filters") or []),
            joins=join_assumptions,
            best_join_evidence=_best_join_evidence(join_assumptions),
        )

        # Confidence tier from profile evidence
        tier = _compute_tier(field_assumptions, join_assumptions, profile_fields)

        # Join gate: downgrade if aggregating join relies on llm_guess
        has_aggregation = bool(assumption.aggregation)
        join_unsafe = join_assumptions and not assumption.join_safe_for_aggregation()
        executable = tier != ConfidenceTier.low and not (has_aggregation and join_unsafe)

        clarification: ClarificationRequest | None = None
        if not executable and join_unsafe:
            clarification = ClarificationRequest(
                question="Join 关系证据不足，请选择分析范围：",
                options=[
                    ClarificationOption(
                        label="仅分析主表",
                        description="回退到单表明细，不跨表聚合",
                        interpretation="single_table_detail",
                    ),
                ],
            )

        follow_up_context = _render_follow_up(assumption, tier) if executable else ""

        return ExplorationPlan(
            question=question,
            data_source_id=data_source_id,
            assumption=assumption,
            confidence_tier=tier,
            clarification=clarification,
            follow_up_context=follow_up_context,
            executable=executable,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    # Strip optional markdown fences
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(raw)  # type: ignore[no-any-return]


def _build_field_assumptions(
    raw_fields: list[dict[str, Any]],
    profile_fields: dict[str, Any],
) -> list[FieldAssumption]:
    result: list[FieldAssumption] = []
    for rf in raw_fields:
        table = str(rf.get("physical_table") or "").upper()
        col = str(rf.get("physical_column") or "").upper()
        key = f"{table}.{col}"
        # Drop fields not in profile (profile_fields may be empty if no profile loaded)
        if profile_fields and key not in profile_fields:
            logger.debug("exploration_planner.field_not_in_profile", extra={"key": key})
            continue
        pf = profile_fields.get(key)
        origin = pf.origin.value if pf else "inferred"
        result.append(FieldAssumption(
            physical_table=table,
            physical_column=col,
            business_name=str(rf.get("business_name") or col),
            inferred_meaning=rf.get("inferred_meaning") or None,
            origin=origin,
        ))
    return result


def _build_join_assumptions(raw_joins: list[dict[str, Any]]) -> list[JoinAssumption]:
    result: list[JoinAssumption] = []
    for rj in raw_joins:
        ev_str = str(rj.get("evidence") or "llm_guess").lower()
        try:
            ev = JoinEvidence(ev_str)
        except ValueError:
            ev = JoinEvidence.llm_guess
        result.append(JoinAssumption(
            left_table=str(rj.get("left_table") or "").upper(),
            right_table=str(rj.get("right_table") or "").upper(),
            join_key=str(rj.get("join_key") or "").upper(),
            evidence=ev,
            note=rj.get("note") or None,
        ))
    return result


def _best_join_evidence(joins: list[JoinAssumption]) -> JoinEvidence | None:
    if not joins:
        return None
    return min(joins, key=lambda j: j.evidence.rank()).evidence


def _compute_tier(
    field_assumptions: list[FieldAssumption],
    join_assumptions: list[JoinAssumption],
    profile_fields: dict[str, Any],
) -> ConfidenceTier:
    """Deterministic tier from Phase-1 evidence — no LLM self-rating.

    When no profile is available (empty profile_fields), we have no evidence
    either way and default to medium confidence. Only downgrade to low when
    a profile is available but fields are missing from it.
    """
    if not field_assumptions:
        return ConfidenceTier.low

    profile_available = bool(profile_fields)
    confidences: list[float] = []
    for fa in field_assumptions:
        key = f"{fa.physical_table}.{fa.physical_column}"
        pf = profile_fields.get(key)
        if pf is not None:
            # standard/enterprise fields are always high confidence
            if fa.origin in ("standard", "enterprise"):
                confidences.append(1.0)
            else:
                confidences.append(float(getattr(pf, "confidence", 0.5)))
        elif profile_available:
            # Profile loaded but field not found — genuinely low evidence
            confidences.append(0.2)
        else:
            # No profile at all — treat as medium (unknown, not bad)
            confidences.append(0.5)

    avg_confidence = sum(confidences) / len(confidences)

    # Join evidence penalty
    if join_assumptions:
        worst = max(join_assumptions, key=lambda j: j.evidence.rank())
        if worst.evidence == JoinEvidence.llm_guess:
            # Pure-guess joins drag confidence down
            avg_confidence = min(avg_confidence, _MEDIUM_CONFIDENCE_THRESHOLD - 0.01)

    if avg_confidence >= _HIGH_CONFIDENCE_THRESHOLD:
        return ConfidenceTier.high
    if avg_confidence >= _MEDIUM_CONFIDENCE_THRESHOLD:
        return ConfidenceTier.medium
    return ConfidenceTier.low


def _build_clarification(interp: dict[str, Any]) -> ClarificationRequest:
    raw_opts = interp.get("clarification_options") or []
    options: list[ClarificationOption] = []
    for opt in raw_opts:
        if isinstance(opt, dict):
            label = str(opt.get("label") or "")
            description = str(opt.get("description") or "")
            interpretation = str(opt.get("interpretation") or opt.get("label") or "")
        else:
            label = str(opt)
            description = ""
            interpretation = label
        options.append(
            ClarificationOption(
                label=label,
                description=description,
                interpretation=interpretation,
            )
        )
    return ClarificationRequest(
        question=str(interp.get("clarification_question") or "请选择您想分析的内容："),
        options=options,
    )


def _render_follow_up(assumption: QueryAssumption, tier: ConfidenceTier) -> str:
    """Render the assumption as structured extra_context for the ask pipeline."""
    lines = ["# AI 探索解读"]
    if assumption.fields_used:
        lines.append("## 使用字段")
        for f in assumption.fields_used:
            lines.append(f"- {f.physical_table}.{f.physical_column} ({f.business_name})")
    if assumption.aggregation:
        lines.append(f"## 聚合方式: {assumption.aggregation}")
    if assumption.time_field:
        lines.append(f"## 时间字段: {assumption.time_field}")
        if assumption.time_grain:
            lines.append(f"## 时间粒度: {assumption.time_grain}")
    if assumption.filters:
        lines.append("## 过滤条件")
        for f in assumption.filters:
            lines.append(f"- {f}")
    if assumption.joins:
        lines.append("## Join 关系")
        for j in assumption.joins:
            lines.append(f"- {j.left_table} JOIN {j.right_table} ON {j.join_key} [{j.evidence.value}]")
    tier_labels = {
        ConfidenceTier.high: "企业数据库字段，非官方标准口径",
        ConfidenceTier.medium: "AI 推断字段，已列出聚合假设",
        ConfidenceTier.low: "低可信度，请参考返回的澄清选项",
    }
    lines.append(f"\n## 口径说明: {tier_labels[tier]}")
    lines.append("\n请严格按照以上字段和聚合方式生成SQL，不得使用上下文之外的字段。")
    return "\n".join(lines)
