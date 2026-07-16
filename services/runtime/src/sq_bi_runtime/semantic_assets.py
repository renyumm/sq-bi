from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


SYSTEM_COMPILER_SKILLS = [
    {
        "skill_id": "system_metric_definition_compiler",
        "name": "指标定义自然语言转 Skill",
        "asset_type": "nl_to_metric_skill",
        "description": "将指标定义页面的自然语言业务口径转换为可保存的指标 Skill，输出完整只读 SELECT SQL 合同。",
        "inputs": ["指标名称", "自然语言业务定义", "数据库语义 Skill", "TMS 业务说明 Skill", "已有指标 Skill"],
        "outputs": ["MetricDraft", "MetricDefinition", "complete_select_sql", "time_field"],
    },
    {
        "skill_id": "system_analysis_skill_compiler",
        "name": "技能中心自然语言转 Skill",
        "asset_type": "nl_to_analysis_skill",
        "description": "将技能中心页面的自然语言分析思路转换为可保存的分析 Skill，必须声明指标、参数、真实数据查询 SQL、时间字段、分析步骤和输出格式。",
        "inputs": ["技能名称", "分析描述", "绑定指标", "数据库语义 Skill", "TMS 业务说明 Skill"],
        "outputs": ["SkillDefinition", "complete_select_sql", "time_fields"],
    },
    {
        "skill_id": "system_report_factory_compiler",
        "name": "报表工坊自然语言转 Skill",
        "asset_type": "nl_to_report_skill",
        "description": "将报表工坊页面的自然语言报表诉求转换为可保存的报表 Skill，编排可执行指标 Skill、分析 Skill、运行时过滤和渲染步骤；模板仅作为样式参考。",
        "inputs": ["报表标题", "模板", "绑定指标", "绑定技能", "输出类型", "报表说明"],
        "outputs": ["ReportRecord", "data_producing_analysis_chain"],
    },
]


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _as_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    return {}


def _value(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def _load_yaml_assets(catalog_path: Path | str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    path = Path(catalog_path)
    if not path.exists():
        return [], [], [], []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return (
        list(raw.get("tables", [])),
        list(raw.get("fields", [])),
        list(raw.get("metrics", [])),
        list(raw.get("skills", [])),
    )


def _repository_assets(repository: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    tables = [_as_dict(item) for item in repository.list_tables()]
    fields = [_as_dict(item) for item in repository.list_fields()]
    metrics = [_as_dict(item) for item in repository.list_metrics()]
    skills = [_as_dict(item) for item in repository.list_skills()]
    reports: list[dict[str, Any]] = []
    if hasattr(repository, "list_reports"):
        reports = [_as_dict(item) for item in repository.list_reports()]
    return tables, fields, metrics, skills, reports


def _render_database_skill(tables: list[dict[str, Any]], fields: list[dict[str, Any]]) -> list[str]:
    fields_by_table: dict[str, list[dict[str, Any]]] = {}
    for field in fields:
        table_id = str(field.get("table_id") or "")
        if table_id:
            fields_by_table.setdefault(table_id, []).append(field)

    parts: list[str] = ["# Database Schema Skill Assets"]
    for table in tables:
        table_id = str(table.get("table_id") or "")
        physical_name = str(table.get("physical_name") or "")
        business_name = str(table.get("business_name") or "")
        description = str(table.get("description") or "")
        parts.append(f"- {physical_name} ({business_name}): {description}")
        column_parts: list[str] = []
        for field in fields_by_table.get(table_id, []):
            physical_field = str(field.get("physical_name") or "")
            field_name = str(field.get("business_name") or "")
            field_desc = str(field.get("description") or "")
            if physical_field:
                column_parts.append(f"{physical_field}={field_name}({field_desc})")
        if column_parts:
            parts.append(f"  columns: {'; '.join(column_parts)}")
    return parts


def _render_metric_skills(metrics: list[dict[str, Any]]) -> list[str]:
    parts: list[str] = ["\n# Metric Definition Skill Assets"]
    for metric in metrics:
        formula = metric.get("formula") or {}
        parts.append(
            "- "
            f"{metric.get('name')} ({metric.get('metric_code')}): "
            f"{metric.get('definition')} | SQL={formula.get('expression')}"
        )
    return parts


def _render_analysis_skills(skills: list[dict[str, Any]]) -> list[str]:
    parts: list[str] = ["\n# Skill Center Analysis Skill Assets"]
    for skill in skills:
        parts.append(f"## {skill.get('name')} ({skill.get('skill_id')})")
        parts.append(f"- type: {skill.get('skill_type')}; visibility: {skill.get('visibility')}")
        parts.append(f"- description: {skill.get('description')}")
        if skill.get("synonyms"):
            parts.append(f"- synonyms: {_compact(skill.get('synonyms'))}")
        if skill.get("parameters"):
            parts.append(f"- parameters: {_compact(skill.get('parameters'))}")
        if skill.get("output_schema"):
            parts.append(f"- output_schema: {_compact(skill.get('output_schema'))}")
    return parts


def _render_report_skills(reports: list[dict[str, Any]]) -> list[str]:
    parts: list[str] = ["\n# Report Factory Skill Assets"]
    for report in reports:
        parts.append(f"## {report.get('name')} ({report.get('report_id')})")
        parts.append(f"- visibility: {report.get('visibility')}; owner: {report.get('owner')}")
        parts.append(f"- outputTypes: {_compact(report.get('outputTypes') or [])}")
        parts.append(f"- template: {report.get('template')}; templateLabel: {report.get('templateLabel')}")
        parts.append(f"- description: {report.get('description')}")
        if report.get("flow"):
            parts.append(f"- flow: {report.get('flow')}")
        if report.get("sections"):
            parts.append(f"- sections: {_compact(report.get('sections'))}")
        if report.get("analysis_chain"):
            parts.append(f"- analysis_chain: {_compact(report.get('analysis_chain'))}")
    return parts


def _render_compiler_skills() -> list[str]:
    parts: list[str] = ["\n# Natural Language To Skill Compiler Assets"]
    for skill in SYSTEM_COMPILER_SKILLS:
        parts.append(f"## {skill['name']} ({skill['skill_id']})")
        parts.append(f"- asset_type: {skill['asset_type']}")
        parts.append(f"- description: {skill['description']}")
        parts.append(f"- inputs: {_compact(skill['inputs'])}")
        parts.append(f"- outputs: {_compact(skill['outputs'])}")
    return parts


def load_semantic_asset_bundle(
    catalog_path: Path | str,
    *,
    repository: Any | None = None,
    include_compiler_skills: bool = True,
) -> str:
    if repository is not None:
        try:
            tables, fields, metrics, skills, reports = _repository_assets(repository)
        except Exception:
            tables, fields, metrics, skills = _load_yaml_assets(catalog_path)
            reports = []
    else:
        tables, fields, metrics, skills = _load_yaml_assets(catalog_path)
        reports = []

    parts: list[str] = ["# Classified Skill Asset Store"]
    parts.extend(_render_database_skill(tables, fields))
    parts.extend(_render_metric_skills(metrics))
    parts.extend(_render_analysis_skills(skills))
    parts.extend(_render_report_skills(reports))
    if include_compiler_skills:
        parts.extend(_render_compiler_skills())

    return "\n".join(parts)
