"""AI-assisted authoring for portable domain-pack definitions."""

from __future__ import annotations

import json
import re
from typing import Any

from sq_bi_contracts.enterprise_pack import (
    EnterprisePackDraft,
    PackAcceptanceQuestion,
    PackEnterpriseField,
    PackEnterpriseMetric,
    PackReport,
    PackSkill,
)

from .llm_client import parse_json_payload


_AUTHORING_SYSTEM_PROMPT = """\
You are an enterprise BI domain-pack architect. Generate portable logical definitions,
never database bindings and never complete SQL statements. Return only one JSON object.

The result schema is:
{
  "input_assessment": {"reasonable": true, "feedback": "Chinese assessment of whether the business context is specific enough"},
  "summary": "Chinese summary",
  "suggestions": ["Chinese suggestion"],
  "draft": {
    "entities": [],
    "fields": [{"field_id":"snake_case","business_name":"中文名","data_type":"TEXT|NUMBER|DATE|BOOLEAN","description":"中文说明","entity_id":null,"synonyms":[],"source":"ai_draft"}],
    "metrics": [{"metric_code":"snake_case","name":"中文名","definition":"明确口径","formula":{"expression":"logical aggregate expression using field_id","filters":[],"time_field":null},"entity_id":null,"synonyms":[],"source":"ai_draft"}],
    "skills": [{"skill_id":"snake_case","name":"中文名","description":"分析目标和输出","steps":[{"step_id":"step_1","description":"步骤说明","metric_codes":[],"dimension_field_ids":[]}]}],
    "reports": [{"report_id":"snake_case","name":"中文名","description":"报告说明和章节结构","metric_codes":[],"skill_ids":[]}],
    "terms": [],
    "acceptance_questions": [{"question_id":"snake_case","question":"可验证问题","expected_metric_code":null,"expected_answer_hint":"预期检查点"}]
  }
}

Rules:
- Use Simplified Chinese for user-facing text and stable snake_case IDs.
- Fields are logical standard fields. Do not invent physical tables or columns.
- Metric expressions may reference only field_id values present in the supplied current/candidate draft.
- Skills may reference only declared metric codes and field IDs.
- Reports may reference only declared metrics and skills.
- For a requested single scope, return candidates only for that scope; keep other arrays empty.
- For scope "all", return a coherent full candidate set in dependency order.
- For scope "all", first judge whether name, description, and business context are sufficient to design a coherent pack. If they are too vague, set input_assessment.reasonable=false, explain what is missing, and return an empty draft.
- Never return SELECT, FROM, JOIN, INSERT, UPDATE, DELETE, DDL, or database connection details.
"""


class DomainPackAuthoringService:
    """Generate candidate definitions and deterministic review evidence."""

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def suggest(
        self,
        *,
        scope: str,
        name: str,
        description: str,
        business_context: str,
        draft: EnterprisePackDraft,
        instruction: str = "",
    ) -> dict[str, Any]:
        if scope == "self_check":
            return self._self_check(name=name, description=description, draft=draft, instruction=instruction)

        user_prompt = json.dumps(
            {
                "requested_scope": scope,
                "pack": {
                    "name": name,
                    "description": description,
                    "business_context": business_context,
                },
                "current_draft": draft.model_dump(mode="json"),
                "additional_instruction": instruction,
            },
            ensure_ascii=False,
        )
        raw = self._llm.chat(_AUTHORING_SYSTEM_PROMPT, user_prompt)
        payload = parse_json_payload(raw)
        assessment = payload.get("input_assessment") if isinstance(payload.get("input_assessment"), dict) else {}
        input_reasonable = bool(assessment.get("reasonable", True))
        candidate_payload = _normalize_candidate_payload(payload.get("draft"))
        candidate, normalization_issues = _assemble_candidate(candidate_payload) if input_reasonable else (EnterprisePackDraft(), [])
        candidate.entities = []
        candidate.terms = []
        for field in candidate.fields:
            field.entity_id = None
        for metric in candidate.metrics:
            metric.entity_id = None
        normalization_issues.extend(_drop_physical_sql_metrics(candidate))
        review_draft = EnterprisePackDraft(
            fields=_overlay(draft.fields, candidate.fields, "field_id"),
            metrics=_overlay(draft.metrics, candidate.metrics, "metric_code"),
            skills=_overlay(draft.skills, candidate.skills, "skill_id"),
            reports=_overlay(draft.reports, candidate.reports, "report_id"),
            acceptance_questions=_overlay(
                draft.acceptance_questions, candidate.acceptance_questions, "question_id"
            ),
        )
        issues = [*normalization_issues, *validate_domain_pack(review_draft, include_empty=False)]
        return {
            "scope": scope,
            "input_assessment": {
                "reasonable": input_reasonable,
                "feedback": str(assessment.get("feedback") or ("输入信息足以生成领域包建议。" if input_reasonable else "请补充更具体的业务背景。")),
            },
            "summary": str(payload.get("summary") or "AI 已生成候选配置，请逐项确认。"),
            "suggestions": [str(item) for item in payload.get("suggestions") or []],
            "issues": issues,
            "draft": candidate.model_dump(mode="json"),
        }

    def _self_check(
        self,
        *,
        name: str,
        description: str,
        draft: EnterprisePackDraft,
        instruction: str,
    ) -> dict[str, Any]:
        issues = validate_domain_pack(draft, include_empty=True)
        prompt = json.dumps(
            {
                "task": "Review this portable domain pack and give concise, actionable Chinese advice. Do not generate SQL.",
                "pack": {"name": name, "description": description},
                "deterministic_issues": issues,
                "draft": draft.model_dump(mode="json"),
                "additional_instruction": instruction,
                "response_schema": {"summary": "string", "suggestions": ["string"]},
            },
            ensure_ascii=False,
        )
        raw = self._llm.chat(
            "You review portable BI domain-pack logic. Return JSON only and never output SQL or physical database mappings.",
            prompt,
        )
        payload = parse_json_payload(raw)
        return {
            "scope": "self_check",
            "input_assessment": {"reasonable": True, "feedback": "已进入领域包自检。"},
            "summary": str(payload.get("summary") or ("自检通过。" if not issues else "自检发现待确认项。")),
            "suggestions": [str(item) for item in payload.get("suggestions") or []],
            "issues": issues,
            "draft": EnterprisePackDraft().model_dump(mode="json"),
        }


def validate_domain_pack(draft: EnterprisePackDraft, *, include_empty: bool) -> list[str]:
    issues: list[str] = []
    field_ids = {item.field_id for item in draft.fields}
    metric_codes = {item.metric_code for item in draft.metrics}
    skill_ids = {item.skill_id for item in draft.skills}

    if include_empty and not draft.fields:
        issues.append("尚未定义标准字段。")
    if include_empty and not draft.metrics:
        issues.append("尚未定义指标。")
    if include_empty and not draft.skills:
        issues.append("尚未定义技能。")
    if include_empty and not draft.reports:
        issues.append("尚未定义报表。")

    _append_duplicate_issues(issues, "标准字段", [item.field_id for item in draft.fields])
    _append_duplicate_issues(issues, "指标", [item.metric_code for item in draft.metrics])
    _append_duplicate_issues(issues, "技能", [item.skill_id for item in draft.skills])
    _append_duplicate_issues(issues, "报表", [item.report_id for item in draft.reports])

    for skill in draft.skills:
        for step in skill.steps:
            missing_metrics = sorted(set(step.metric_codes) - metric_codes)
            missing_fields = sorted(set(step.dimension_field_ids) - field_ids)
            if missing_metrics:
                issues.append(f"技能“{skill.name}”引用了不存在的指标：{', '.join(missing_metrics)}。")
            if missing_fields:
                issues.append(f"技能“{skill.name}”引用了不存在的字段：{', '.join(missing_fields)}。")
    for report in draft.reports:
        missing_metrics = sorted(set(report.metric_codes) - metric_codes)
        missing_skills = sorted(set(report.skill_ids) - skill_ids)
        if missing_metrics:
            issues.append(f"报表“{report.name}”引用了不存在的指标：{', '.join(missing_metrics)}。")
        if missing_skills:
            issues.append(f"报表“{report.name}”引用了不存在的技能：{', '.join(missing_skills)}。")
    for question in draft.acceptance_questions:
        if question.expected_metric_code and question.expected_metric_code not in metric_codes:
            issues.append(f"自检问题“{question.question}”引用了不存在的指标：{question.expected_metric_code}。")
    return issues


def _append_duplicate_issues(issues: list[str], label: str, values: list[str]) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        issues.append(f"{label} ID 重复：{', '.join(duplicates)}。")


def _overlay(base: list[Any], candidates: list[Any], id_field: str) -> list[Any]:
    merged = {getattr(item, id_field): item for item in base}
    merged.update({getattr(item, id_field): item for item in candidates})
    return list(merged.values())


def _normalize_candidate_payload(raw: object) -> dict[str, Any]:
    """Keep the authored contract strict while tolerating harmless LLM extras."""
    payload = raw if isinstance(raw, dict) else {}

    def records(key: str) -> list[dict[str, Any]]:
        value = payload.get(key)
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if isinstance(item, (str, int, float)) and str(item).strip()]

    fields = [{
        "field_id": str(item.get("field_id") or ""),
        "business_name": str(item.get("business_name") or item.get("name") or ""),
        "data_type": str(item.get("data_type") or "TEXT"),
        "description": item.get("description") or None,
        "entity_id": None,
        "synonyms": string_list(item.get("synonyms")),
        "source": "ai_draft",
    } for item in records("fields") if item.get("field_id")]

    metrics: list[dict[str, Any]] = []
    for item in records("metrics"):
        code = str(item.get("metric_code") or item.get("id") or "")
        if not code:
            continue
        formula = item.get("formula") if isinstance(item.get("formula"), dict) else {}
        metrics.append({
            "metric_code": code,
            "name": str(item.get("name") or code),
            "definition": str(item.get("definition") or item.get("description") or ""),
            "formula": {
                "expression": str(formula.get("expression") or item.get("formula_expression") or ""),
                "filters": string_list(formula.get("filters") or item.get("filters")),
                "time_field": str(formula.get("time_field") or item.get("time_field") or "") or None,
            },
            "entity_id": None,
            "synonyms": string_list(item.get("synonyms")),
            "source": "ai_draft",
        })

    skills: list[dict[str, Any]] = []
    for item in records("skills"):
        skill_id = str(item.get("skill_id") or item.get("id") or "")
        if not skill_id:
            continue
        steps = []
        for index, step in enumerate(item.get("steps") or []):
            if not isinstance(step, dict):
                continue
            steps.append({
                "step_id": str(step.get("step_id") or f"step_{index + 1}"),
                "description": str(step.get("description") or step.get("name") or "执行分析"),
                "metric_codes": string_list(step.get("metric_codes")),
                "dimension_field_ids": string_list(step.get("dimension_field_ids")),
            })
        skills.append({
            "skill_id": skill_id,
            "name": str(item.get("name") or skill_id),
            "description": item.get("description") or None,
            "steps": steps,
        })

    reports = [{
        "report_id": str(item.get("report_id") or item.get("id") or ""),
        "name": str(item.get("name") or item.get("report_id") or ""),
        "description": item.get("description") or None,
        "metric_codes": string_list(item.get("metric_codes")),
        "skill_ids": string_list(item.get("skill_ids")),
    } for item in records("reports") if item.get("report_id") or item.get("id")]

    questions = [{
        "question_id": str(item.get("question_id") or item.get("id") or ""),
        "question": str(item.get("question") or item.get("name") or ""),
        "expected_metric_code": item.get("expected_metric_code") or None,
        "expected_answer_hint": item.get("expected_answer_hint") or item.get("description") or None,
    } for item in records("acceptance_questions") if item.get("question_id") or item.get("id")]

    return {
        "entities": [],
        "fields": fields,
        "metrics": metrics,
        "skills": skills,
        "reports": reports,
        "terms": [],
        "acceptance_questions": questions,
    }


def _assemble_candidate(payload: dict[str, Any]) -> tuple[EnterprisePackDraft, list[str]]:
    issues: list[str] = []

    def parse_items(model: Any, key: str, label: str) -> list[Any]:
        parsed: list[Any] = []
        for index, item in enumerate(payload.get(key) or []):
            try:
                parsed.append(model.model_validate(item))
            except Exception:  # noqa: BLE001
                issues.append(f"已忽略结构不完整的{label}候选 #{index + 1}。")
        return parsed

    return EnterprisePackDraft(
        fields=parse_items(PackEnterpriseField, "fields", "标准字段"),
        metrics=parse_items(PackEnterpriseMetric, "metrics", "指标"),
        skills=parse_items(PackSkill, "skills", "技能"),
        reports=parse_items(PackReport, "reports", "报表"),
        acceptance_questions=parse_items(PackAcceptanceQuestion, "acceptance_questions", "自检问题"),
    ), issues


def _drop_physical_sql_metrics(draft: EnterprisePackDraft) -> list[str]:
    forbidden = re.compile(r"\b(SELECT|FROM|JOIN|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|MERGE)\b", re.IGNORECASE)
    kept: list[PackEnterpriseMetric] = []
    issues: list[str] = []
    for metric in draft.metrics:
        if forbidden.search(metric.formula.expression):
            issues.append(f"已忽略包含物理 SQL 的指标候选：{metric.metric_code}。")
        else:
            kept.append(metric)
    draft.metrics = kept
    return issues
