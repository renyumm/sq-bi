from __future__ import annotations

import difflib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sq_bi_contracts.domain_pack import PackStandardField
from sq_bi_contracts.field_mount import (
    CandidateMapping,
    ConfirmationRequest,
    FieldMapping,
    LogicalMetricDefinition,
    MappingEvidence,
    MountStatus,
    MountTriggerRequest,
    MountTriggerResponse,
    PendingMapping,
    SmokeTestMetric,
    SmokeTestResult,
)

from .dsl_compiler import compile_oracle
from .field_mapping_store import FieldMappingStore

logger = logging.getLogger(__name__)

# ── Tuning constants (not magic numbers) ────────────────────────────

# Name-similarity thresholds for deterministic matching
_SIM_HIGH: float = 0.8
_SIM_MED: float = 0.5

# Per-signal score contributions (sum across active signals ≤ 1.05, clamped to 1.0)
_SCORE_SIM_HIGH: float = 0.4
_SCORE_SIM_MED: float = 0.2
_SCORE_NORM_MATCH: float = 0.3
_SCORE_COMMENT: float = 0.15
_SCORE_ENUM: float = 0.2

# Confidence thresholds
CONFIDENCE_AUTO_APPLY: float = 0.85
_CONFIDENCE_CANDIDATE_MIN: float = 0.2

# Misc
_LLM_SAMPLE_VALUES_MAX: int = 3
_PENDING_EXTRA_CANDIDATES: int = 2
_MAPPING_ID_HEX_CHARS: int = 12

# Table-name prefix patterns to strip during normalisation
_TABLE_PREFIX_PATTERN = re.compile(r"^(dim_|fact_|t_|v_)", re.IGNORECASE)


# ── Physical schema column info ──────────────────────────────────────

class PhysicalColumn:
    """Scanned metadata about one physical column."""

    __slots__ = ("table", "column", "data_type", "comment", "sample_values")

    def __init__(
        self,
        table: str,
        column: str,
        data_type: str = "",
        comment: str = "",
        sample_values: list[str] | None = None,
    ) -> None:
        self.table = table
        self.column = column
        self.data_type = data_type
        self.comment = comment
        self.sample_values: list[str] = sample_values or []

    def __repr__(self) -> str:
        return f"{self.table}.{self.column} ({self.data_type})"


# ── 4.1: Schema scanning ────────────────────────────────────────────

def scan_physical_schema(
    live_catalog: dict[str, set[str]],
    semantic_catalog: dict[str, set[str]],
) -> dict[str, list[PhysicalColumn]]:
    """Merge live + semantic catalogs into {TABLE: [PhysicalColumn, ...]}."""
    merged: dict[str, set[str]] = {}
    for catalog in (live_catalog, semantic_catalog):
        for table, columns in catalog.items():
            merged.setdefault(table.upper(), set()).update(
                c.upper() for c in columns
            )
    return {
        table: [PhysicalColumn(table=table, column=col) for col in sorted(cols)]
        for table, cols in sorted(merged.items())
    }


# ── 4.2: Deterministic matching ─────────────────────────────────────

def _normalize_name(name: str) -> str:
    n = name.lower().strip()
    n = _TABLE_PREFIX_PATTERN.sub("", n)
    return n.replace("_", "")


def _name_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalize_name(a), _normalize_name(b)).ratio()


def _type_compatible(std_type: str, phys_type: str) -> bool:
    type_map: dict[str, set[str]] = {
        "text": {"varchar", "char", "text", "clob", "nvarchar", "nchar"},
        "integer": {"integer", "int", "number", "numeric", "smallint", "bigint"},
        "number": {"number", "numeric", "decimal", "float", "double", "real"},
        "decimal": {"number", "numeric", "decimal", "float", "double"},
        "date": {"date"},
        "datetime": {"date", "timestamp", "datetime"},
        "boolean": {"boolean", "char", "varchar", "number", "int"},
        "enum": {"varchar", "char", "text", "number", "int"},
        "percentage": {"number", "numeric", "decimal", "float"},
        "ratio": {"number", "numeric", "decimal", "float"},
    }
    compatible = type_map.get(std_type.lower(), {std_type.lower()})
    phys_lower = phys_type.lower()
    return any(ct in phys_lower for ct in compatible)


def deterministic_match(
    std_field: PackStandardField,
    candidates: list[PhysicalColumn],
) -> list[CandidateMapping]:
    """Return scored, sorted CandidateMappings using deterministic rules only."""
    # Pre-compute std_field enum set once (not inside the col loop)
    std_enum_set = (
        {v.lower() for v in std_field.enum_values} if std_field.enum_values else set()
    )
    scored: list[CandidateMapping] = []

    for col in candidates:
        score = 0.0
        reasons: list[str] = []

        sim = _name_similarity(std_field.business_name, col.column)
        biz_sim = _name_similarity(std_field.field_id, col.column)
        type_ok = _type_compatible(str(std_field.data_type), col.data_type) if col.data_type else None
        comment_matched = False

        if sim >= _SIM_HIGH:
            score += _SCORE_SIM_HIGH
            reasons.append(f"name_similarity={sim:.2f}")
        elif sim >= _SIM_MED:
            score += _SCORE_SIM_MED

        if _normalize_name(std_field.field_id) == _normalize_name(col.column):
            score += _SCORE_NORM_MATCH
            reasons.append("normalized_match")

        if col.comment and any(
            kw in col.comment.lower()
            for kw in std_field.business_name.lower().split()
        ):
            score += _SCORE_COMMENT
            reasons.append("comment_match")
            comment_matched = True

        enum_overlap = False
        if std_enum_set and col.sample_values:
            phys_set = {v.lower() for v in col.sample_values}
            if std_enum_set & phys_set:
                score += _SCORE_ENUM
                reasons.append("enum_overlap")
                enum_overlap = True

        if score > 0:
            evidence = MappingEvidence(
                name_similarity=round(sim, 4),
                business_name_similarity=round(biz_sim, 4),
                type_compatible=type_ok,
                comment_evidence=col.comment if comment_matched else None,
                sample_values=col.sample_values[:_LLM_SAMPLE_VALUES_MAX],
                data_quality_flags=(
                    ["enum_overlap"] if enum_overlap else []
                ),
            )
            scored.append(CandidateMapping(
                physical_table=col.table,
                physical_column=col.column,
                confidence=round(min(score, 1.0), 2),
                reason="; ".join(reasons) if reasons else "deterministic",
                evidence=evidence,
            ))

    scored.sort(key=lambda c: c.confidence, reverse=True)
    return scored


# ── 4.4: LLM semantic matching ─────────────────────────────────────

_LLM_SYSTEM_PROMPT = "You are a database schema matching assistant. Output only valid JSON."


def llm_semantic_match(
    std_field: PackStandardField,
    candidates: list[PhysicalColumn],
    llm_client: Any,
) -> CandidateMapping | None:
    """Use LLM to match a standard field to its best physical column."""
    prompt_lines = [
        f"Standard field: {std_field.field_id} ({std_field.business_name})",
        f"Data type: {std_field.data_type}",
        f"Description: {std_field.description or ''}",
    ]
    if std_field.enum_values:
        prompt_lines.append(f"Enum values: {', '.join(std_field.enum_values)}")

    prompt_lines.append("\nCandidate physical columns:")
    for i, col in enumerate(candidates):
        samples = col.sample_values[:_LLM_SAMPLE_VALUES_MAX] if col.sample_values else None
        prompt_lines.append(
            f"{i}. {col.table}.{col.column} (type: {col.data_type}, "
            f"comment: {col.comment or 'N/A'}, samples: {samples or 'N/A'})"
        )
    prompt_lines += [
        "",
        'Respond with JSON only: {"candidate_index": <int>, "confidence": <0.0-1.0>, "reason": "<string>"}',
        "If no candidate matches, set candidate_index to -1.",
    ]
    prompt = "\n".join(prompt_lines)

    try:
        raw = llm_client.chat(_LLM_SYSTEM_PROMPT, prompt)
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "mounting_pipeline.llm_parse_error",
            extra={"field_id": std_field.field_id, "error": str(exc), "raw": raw[:200]},
        )
        return None
    except Exception as exc:
        logger.warning(
            "mounting_pipeline.llm_error",
            extra={"field_id": std_field.field_id, "error": str(exc)},
        )
        return None

    idx = payload.get("candidate_index", -1)
    # Guard: JSON numbers can be float (e.g. 0.0); treat whole-value floats as int
    if isinstance(idx, float) and idx == int(idx):
        idx = int(idx)
    if not isinstance(idx, int) or idx < 0 or idx >= len(candidates):
        logger.warning(
            "mounting_pipeline.llm_invalid_index",
            extra={"field_id": std_field.field_id, "index": idx, "candidates": len(candidates)},
        )
        return None

    confidence = float(payload.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))  # clamp to [0,1]

    col = candidates[idx]
    evidence = MappingEvidence(
        name_similarity=round(_name_similarity(std_field.business_name, col.column), 4),
        business_name_similarity=round(_name_similarity(std_field.field_id, col.column), 4),
        type_compatible=_type_compatible(str(std_field.data_type), col.data_type) if col.data_type else None,
        comment_evidence=col.comment or None,
        sample_values=col.sample_values[:_LLM_SAMPLE_VALUES_MAX],
    )
    return CandidateMapping(
        physical_table=col.table,
        physical_column=col.column,
        confidence=round(confidence, 2),
        reason=str(payload.get("reason", "LLM suggested")),
        evidence=evidence,
    )


# ── 4.5: Validate LLM output ───────────────────────────────────────

def validate_llm_candidate(
    candidate: CandidateMapping,
    available_columns: dict[str, list[PhysicalColumn]],
) -> bool:
    """Ensure the LLM-proposed column actually exists in the scanned schema."""
    if not candidate.physical_table or not candidate.physical_column:
        return False
    table_cols = available_columns.get(candidate.physical_table.upper())
    if table_cols is None:
        return False
    return any(
        col.column.upper() == candidate.physical_column.upper()
        for col in table_cols
    )


# ── Mounting pipeline orchestration ────────────────────────────────

class MountingPipeline:
    """Orchestrates the full mounting flow for a pack on a data source."""

    def __init__(
        self,
        store: FieldMappingStore,
        llm_client: Any = None,
    ) -> None:
        self._store = store
        self._llm_client = llm_client

    def trigger(
        self,
        request: MountTriggerRequest,
        standard_fields: dict[str, PackStandardField],
        live_catalog: dict[str, set[str]],
        semantic_catalog: dict[str, set[str]],
        logical_metrics: list[LogicalMetricDefinition] | None = None,
        allowed_tables: set[str] | None = None,
        preferred_candidates: dict[str, CandidateMapping] | None = None,
        force_pending_fields: set[str] | None = None,
    ) -> MountTriggerResponse:
        """Run the full mounting pipeline for a pack on a data source.

        ``allowed_tables`` scopes matching to a bound semantic space's adopted
        tables (case-insensitive). When ``None`` every scanned table is a
        candidate, preserving pre-existing whole-connection behavior.
        """
        if not standard_fields:
            logger.warning(
                "mounting_pipeline.trigger.empty_fields",
                extra={"pack_id": request.pack_id, "data_source_id": request.data_source_id},
            )

        # Pre-compute affected metric count per standard field (static, from pack manifest)
        field_metric_count: dict[str, int] = {}
        if logical_metrics:
            for metric in logical_metrics:
                for sf_ref in (metric.logical_formula.referenced_standard_fields or []):
                    field_metric_count[sf_ref] = field_metric_count.get(sf_ref, 0) + 1

        scanned = scan_physical_schema(live_catalog, semantic_catalog)
        all_scanned_columns: dict[str, list[PhysicalColumn]] = {
            t.upper(): cols for t, cols in scanned.items()
        }
        available_columns: dict[str, list[PhysicalColumn]] = {
            t.upper(): cols for t, cols in scanned.items()
        }
        if allowed_tables is not None:
            allowed_upper = {t.upper() for t in allowed_tables}
            available_columns = {
                t: cols for t, cols in available_columns.items() if t in allowed_upper
            }

        # Pre-build flat candidate list once — not per standard field
        all_candidates: list[PhysicalColumn] = [
            col for cols in available_columns.values() for col in cols
        ]
        outside_scope_columns: list[PhysicalColumn] = []
        if allowed_tables is not None:
            allowed_upper = {t.upper() for t in allowed_tables}
            outside_scope_columns = [
                col
                for table, cols in all_scanned_columns.items()
                if table not in allowed_upper
                for col in cols
            ]

        auto_mapped: list[FieldMapping] = []
        pending: list[PendingMapping] = []
        errors: list[str] = []
        existing_mappings = (
            self._store.get_mappings_dict_by_deployment(request.deployment_id)
            if request.deployment_id
            else self._store.get_mappings_dict(request.pack_id, request.data_source_id)
        )

        logger.info(
            "mounting_pipeline.trigger.start",
            extra={
                "pack_id": request.pack_id,
                "data_source_id": request.data_source_id,
                "standard_fields": len(standard_fields),
                "physical_columns": len(all_candidates),
            },
        )

        forced_pending = force_pending_fields or set()
        for sf_id, sf in standard_fields.items():
            if sf_id in existing_mappings and sf_id not in forced_pending:
                continue
            det_results = deterministic_match(sf, all_candidates)
            best = det_results[0] if det_results else None
            metric_count = field_metric_count.get(sf_id, 0)
            outside_results: list[CandidateMapping] = []
            preferred = (preferred_candidates or {}).get(sf_id)
            if preferred is not None:
                preferred_table = preferred.physical_table.upper()
                preferred_exists = validate_llm_candidate(preferred, all_scanned_columns)
                if preferred_exists and preferred_table not in available_columns:
                    outside_results.append(preferred)
            for candidate in deterministic_match(sf, outside_scope_columns):
                key = (candidate.physical_table.upper(), candidate.physical_column.upper())
                if any(
                    (item.physical_table.upper(), item.physical_column.upper()) == key
                    for item in outside_results
                ):
                    continue
                if candidate.confidence <= _CONFIDENCE_CANDIDATE_MIN:
                    continue
                outside_results.append(candidate)
                if len(outside_results) >= _PENDING_EXTRA_CANDIDATES + 1:
                    break

            # High-confidence unambiguous deterministic hit → auto-apply
            if sf_id not in forced_pending and best and best.confidence >= CONFIDENCE_AUTO_APPLY and len(det_results) == 1:
                mapping = self._make_mapping(request, sf_id, best, source="auto")
                self._store.upsert(mapping)  # persist immediately
                auto_mapped.append(mapping)
                logger.debug(
                    "mounting_pipeline.auto_mapped",
                    extra={"sf_id": sf_id, "physical": f"{best.physical_table}.{best.physical_column}", "confidence": best.confidence},
                )
                continue

            # LLM fallback when no deterministic candidate
            if not best and self._llm_client and not outside_results:
                llm_result = llm_semantic_match(sf, all_candidates, self._llm_client)
                if llm_result and validate_llm_candidate(llm_result, available_columns):
                    if sf_id not in forced_pending and llm_result.confidence >= CONFIDENCE_AUTO_APPLY:
                        mapping = self._make_mapping(request, sf_id, llm_result, source="llm")
                        self._store.upsert(mapping)  # persist immediately
                        auto_mapped.append(mapping)
                        logger.debug(
                            "mounting_pipeline.llm_auto_mapped",
                            extra={"sf_id": sf_id, "confidence": llm_result.confidence},
                        )
                        continue
                    best = llm_result
                else:
                    errors.append(f"LLM proposed invalid column for '{sf_id}'")
                    logger.warning(
                        "mounting_pipeline.llm_invalid_candidate",
                        extra={"sf_id": sf_id},
                    )

            # High-confidence even with ambiguity → still auto-apply
            if sf_id not in forced_pending and best and best.confidence >= CONFIDENCE_AUTO_APPLY:
                mapping = self._make_mapping(request, sf_id, best, source="auto")
                self._store.upsert(mapping)
                auto_mapped.append(mapping)
                continue

            # Build pending item for admin confirmation
            candidates_for_pending: list[CandidateMapping] = []
            if best:
                candidates_for_pending.append(best)
            for c in det_results[1: 1 + _PENDING_EXTRA_CANDIDATES]:
                if c.confidence > _CONFIDENCE_CANDIDATE_MIN:
                    candidates_for_pending.append(c)

            # Enrich evidence: affected_metric_count + conflicting_candidates per candidate
            conflicting_labels = [
                f"{c.physical_table}.{c.physical_column}"
                for c in candidates_for_pending
            ]
            enriched: list[CandidateMapping] = []
            for i, c in enumerate(candidates_for_pending):
                conflicts = [lbl for j, lbl in enumerate(conflicting_labels) if j != i]
                enriched.append(c.model_copy(update={
                    "evidence": c.evidence.model_copy(update={
                        "affected_metric_count": metric_count,
                        "conflicting_candidates": conflicts,
                    })
                }))

            pending.append(PendingMapping(
                mapping_request_id=f"mreq_{uuid4().hex[:_MAPPING_ID_HEX_CHARS]}",
                standard_field_id=sf_id,
                business_name=sf.business_name,
                candidates=enriched,
                outside_scope_candidates=outside_results,
            ))
            logger.debug(
                "mounting_pipeline.pending",
                extra={"sf_id": sf_id, "candidates": len(candidates_for_pending)},
            )

        status: str = "failed" if (errors and not auto_mapped) else "completed"
        logger.info(
            "mounting_pipeline.trigger.done",
            extra={
                "pack_id": request.pack_id,
                "auto_mapped": len(auto_mapped),
                "pending": len(pending),
                "errors": len(errors),
                "status": status,
            },
        )
        return MountTriggerResponse(
            auto_mapped=auto_mapped,
            pending=pending,
            errors=errors,
            status=status,  # type: ignore[arg-type]
        )

    def confirm(self, request: ConfirmationRequest, pending_item: PendingMapping) -> FieldMapping:
        """Apply a confirmed mapping from admin choice.

        Caller must supply the matching PendingMapping (identified by
        mapping_request_id) so index resolution is unambiguous.
        """
        if request.mapping_request_id != pending_item.mapping_request_id:
            raise ValueError(
                f"mapping_request_id mismatch: request={request.mapping_request_id!r} "
                f"!= pending={pending_item.mapping_request_id!r}"
            )
        idx = request.chosen_candidate_index
        if idx is None:
            raise ValueError("chosen_candidate_index is required for a proposed candidate.")
        candidate_pool = (
            pending_item.outside_scope_candidates
            if request.candidate_scope == "scanned_catalog"
            else pending_item.candidates
        )
        if idx >= len(candidate_pool):
            raise IndexError(
                f"chosen_candidate_index {idx} out of range "
                f"for {len(candidate_pool)} {request.candidate_scope} candidates"
            )
        candidate = candidate_pool[idx]
        return self.confirm_mapping(
            pack_id=request.pack_id,
            data_source_id=request.data_source_id,
            standard_field_id=request.standard_field_id,
            physical_table=candidate.physical_table,
            physical_column=candidate.physical_column,
            confidence=candidate.confidence,
            deployment_id=request.deployment_id,
            confirmed_by=request.confirmed_by,
        )

    def confirm_mapping(
        self,
        pack_id: str,
        data_source_id: str,
        standard_field_id: str,
        physical_table: str,
        physical_column: str,
        confidence: float = 1.0,
        deployment_id: str | None = None,
        confirmed_by: str | None = None,
    ) -> FieldMapping:
        """Record a manually confirmed mapping and persist it."""
        mapping = FieldMapping(
            mapping_id=f"map_{uuid4().hex[:_MAPPING_ID_HEX_CHARS]}",
            pack_id=pack_id,
            standard_field_id=standard_field_id,
            data_source_id=data_source_id,
            physical_table=physical_table,
            physical_column=physical_column,
            confidence=round(max(0.0, min(1.0, confidence)), 2),
            source="manual",
            status="active",
            deployment_id=deployment_id,
            created_at=datetime.now(timezone.utc),
            confirmed_by=confirmed_by,
            confirmed_at=datetime.now(timezone.utc),
        )
        self._store.upsert(mapping)
        logger.info(
            "mounting_pipeline.confirm_mapping",
            extra={
                "pack_id": pack_id,
                "data_source_id": data_source_id,
                "standard_field_id": standard_field_id,
                "physical": f"{physical_table}.{physical_column}",
            },
        )
        return mapping

    def run_smoke_test(
        self,
        pack_id: str,
        data_source_id: str,
        standard_fields: dict[str, PackStandardField],
        test_metrics: list[LogicalMetricDefinition],
        executor: Any = None,
        deployment_id: str | None = None,
    ) -> SmokeTestResult:
        """Compile and optionally execute smoke-test queries.

        If `executor` is provided it must support `.execute(sql) -> list[Any]`.
        Without an executor only compilation is verified.
        """
        mappings = (
            self._store.get_mappings_dict_by_deployment(deployment_id)
            if deployment_id
            else self._store.get_mappings_dict(pack_id, data_source_id)
        )
        metrics_results: list[SmokeTestMetric] = []

        for metric in test_metrics:
            result = SmokeTestMetric(metric_code=metric.metric_code, name=metric.name)
            try:
                sql = compile_oracle(
                    metric.logical_formula.expression,
                    mappings,
                    standard_fields,
                )
                result.compiled = True
                logger.debug(
                    "mounting_pipeline.smoke_test.compiled",
                    extra={"metric_code": metric.metric_code},
                )

                if executor is not None:
                    try:
                        rows = executor.execute(sql)
                        result.executed = True
                        result.row_count = len(rows) if rows is not None else 0
                        logger.debug(
                            "mounting_pipeline.smoke_test.executed",
                            extra={"metric_code": metric.metric_code, "row_count": result.row_count},
                        )
                    except Exception as exec_exc:
                        result.error = f"Execution failed: {exec_exc}"
                        logger.warning(
                            "mounting_pipeline.smoke_test.exec_error",
                            extra={"metric_code": metric.metric_code, "error": str(exec_exc)},
                        )
            except ValueError as exc:
                result.error = str(exc)
                logger.warning(
                    "mounting_pipeline.smoke_test.compile_error",
                    extra={"metric_code": metric.metric_code, "error": str(exc)},
                )

            metrics_results.append(result)

        all_passed = bool(metrics_results) and all(
            m.compiled and not m.error for m in metrics_results
        )
        tested_at = datetime.now(timezone.utc)
        logger.info(
            "mounting_pipeline.smoke_test.done",
            extra={
                "pack_id": pack_id,
                "data_source_id": data_source_id,
                "total": len(metrics_results),
                "passed": sum(1 for m in metrics_results if m.compiled and not m.error),
                "all_passed": all_passed,
            },
        )
        return SmokeTestResult(
            pack_id=pack_id,
            data_source_id=data_source_id,
            deployment_id=deployment_id,
            metrics=metrics_results,
            all_passed=all_passed,
            tested_at=tested_at,
        )

    def get_mount_status(
        self,
        pack_id: str,
        data_source_id: str,
        standard_fields: dict[str, PackStandardField],
        test_metrics: list[LogicalMetricDefinition] | None = None,
        executor: Any = None,
    ) -> MountStatus:
        """Get overall mount status for a pack on a data source."""
        total = len(standard_fields)
        mapped = self._store.count_mapped(pack_id, data_source_id)
        pending_count = max(0, total - mapped)

        smoke = None
        if mapped > 0 and test_metrics:
            smoke = self.run_smoke_test(
                pack_id, data_source_id, standard_fields, test_metrics, executor=executor
            )

        is_ready = (
            total > 0
            and mapped >= total
            and (smoke is None or smoke.all_passed)
        )
        return MountStatus(
            pack_id=pack_id,
            data_source_id=data_source_id,
            total_standard_fields=total,
            mapped_fields=mapped,
            pending_fields=pending_count,
            is_ready=is_ready,
            smoke_test=smoke,
        )

    @staticmethod
    def _make_mapping(
        request: MountTriggerRequest,
        sf_id: str,
        candidate: CandidateMapping,
        source: str = "auto",
    ) -> FieldMapping:
        return FieldMapping(
            mapping_id=f"map_{uuid4().hex[:_MAPPING_ID_HEX_CHARS]}",
            pack_id=request.pack_id,
            standard_field_id=sf_id,
            data_source_id=request.data_source_id,
            physical_table=candidate.physical_table,
            physical_column=candidate.physical_column,
            confidence=round(max(0.0, min(1.0, candidate.confidence)), 2),
            source=source,  # type: ignore[arg-type]
            status="active",
            deployment_id=request.deployment_id,
            created_at=datetime.now(timezone.utc),
        )
