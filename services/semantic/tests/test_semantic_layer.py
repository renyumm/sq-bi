from __future__ import annotations

import os
from pathlib import Path
import pytest
from sq_bi_contracts.asset_build import AssetBuildEvent, DataSourceBinding, ExecutableAssetContract, ValidationEvidence
from sq_bi_contracts.metrics import MetricDefinition, MetricFormula
from sq_bi_contracts.skills import SkillDefinition, SkillResolveRequest
from sq_bi_contracts.enums import MetricVisibility, SkillType, SkillVisibility

from sq_bi_semantic.repository import FileBackedSemanticRepository
from sq_bi_semantic.product_repository import ReportRecord, SQLiteProductRepository


@pytest.fixture
def repo(tmp_path: Path) -> FileBackedSemanticRepository:
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    user_metrics_file = tmp_path / "user_metrics.json"
    return FileBackedSemanticRepository(data_file=data_file, user_metrics_file=user_metrics_file)


def test_catalog_retrieval(repo: FileBackedSemanticRepository) -> None:
    # 1. Test data sources
    data_sources = repo.list_data_sources()
    assert len(data_sources) >= 1
    assert data_sources[0].data_source_id == "oracle_tms"

    # 2. Test tables
    tables = repo.list_tables()
    assert len(tables) >= 5
    carry_table = repo.get_table("hr_deliver_carry")
    assert carry_table is not None
    assert carry_table.physical_name == "HR_DELIVER_CARRY"

    # 3. Test fields
    fields = repo.list_fields(table_id="hr_deliver_carry")
    assert len(fields) >= 1
    status_field = [f for f in fields if f.physical_name == "CAR_STATUS"][0]
    assert status_field.business_name == "车辆状态"
    assert "3" in status_field.enum_values
    assert status_field.enum_values["3"] == "运输途中"

    metrics = repo.list_metrics()
    metric_names = {metric.name for metric in metrics}
    assert len(metrics) >= 13
    assert "询价单量" in metric_names
    assert "供应商报价次数" in metric_names
    assert "承运商准时到货率" in metric_names


def test_metric_conflict_on_persist(repo: FileBackedSemanticRepository) -> None:
    conflicting_def = MetricDefinition(
        metric_code="user_conflict",
        name="发货制单量",
        definition="conflicting",
        visibility=MetricVisibility.PRIVATE,
        formula=MetricFormula(expression="select count(*) as metric_value from HR_DELIVER_FORM f"),
        data_source_id="oracle_tms",
        owner="user_123",
    )
    with pytest.raises(ValueError, match="conflicts with official metric"):
        repo.create_user_metric(conflicting_def)


def test_skill_lookup_and_synonym_resolution(repo: FileBackedSemanticRepository) -> None:
    # 1. Exact match with synonym
    req_exact = SkillResolveRequest(
        user_id="user_123",
        text="承运商表现",
        trigger="button",
    )
    result_exact = repo.resolve_skill(req_exact)
    assert result_exact.matched_skill is not None
    assert result_exact.matched_skill.skill_id == "tms_carrier_performance"

    # 2. Partial match
    req_partial = SkillResolveRequest(
        user_id="user_123",
        text="承运商",
        trigger="input",
    )
    result_partial = repo.resolve_skill(req_partial)
    assert result_partial.matched_skill is None
    assert len(result_partial.candidates) >= 1
    assert result_partial.candidates[0].skill_id == "tms_carrier_performance"

    # 3. No match
    req_none = SkillResolveRequest(
        user_id="user_123",
        text="不存在的技能名字",
        trigger="input",
    )
    result_none = repo.resolve_skill(req_none)
    assert result_none.matched_skill is None
    assert len(result_none.candidates) == 0


def test_chat_history_groups_messages_by_session(tmp_path: Path) -> None:
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    product_repo = SQLiteProductRepository(data_file=data_file, store_path=tmp_path / "sqbi.sqlite3", file_root=tmp_path / "files")

    first = product_repo.create_chat_message("user_123", "本月发货申请量")
    assistant = product_repo.create_chat_message(
        "user_123",
        "按发货申请表统计本月申请单量。",
        session_id=first.session_id,
        sender="assistant",
        payload={"query_result": {"columns": ["APPLY_CNT"], "rows": [[12]]}},
    )
    second = product_repo.create_chat_message("user_123", "再看准时到货率", session_id=first.session_id)
    sessions = product_repo.list_chat_sessions("user_123")
    messages = product_repo.list_chat_messages("user_123", session_id=first.session_id)

    assert second.session_id == first.session_id
    assert assistant.sender == "assistant"
    assert len(sessions) == 1
    assert sessions[0].message_count == 3
    assert [message.sender for message in messages] == ["user", "assistant", "user"]
    assert messages[1].payload["query_result"]["columns"] == ["APPLY_CNT"]


def test_metric_namespace_allows_shared_name_collision(tmp_path: Path) -> None:
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    product_repo = SQLiteProductRepository(data_file=data_file, store_path=tmp_path / "sqbi.sqlite3", file_root=tmp_path / "files")
    shared = MetricDefinition(
        metric_code="user_lisi::延迟单量",
        name="延迟单量",
        definition="李四共享口径",
        visibility=MetricVisibility.SHARED,
        formula=MetricFormula(expression="select count(distinct c.DELIVER_NO) as delay_count from HR_DELIVER_CARRY c"),
        data_source_id="oracle_tms",
        owner="lisi",
    )
    mine = MetricDefinition(
        metric_code="user_analyst::延迟单量",
        name="延迟单量",
        definition="任宇甍私有口径",
        visibility=MetricVisibility.PRIVATE,
        formula=MetricFormula(expression="select count(distinct c.DELIVER_NO) as delay_count from HR_DELIVER_CARRY c where c.ACTUAL_TIME > c.PLAN_TIME"),
        data_source_id="oracle_tms",
        owner="analyst",
    )

    product_repo.create_user_metric(shared)
    persisted = product_repo.create_user_metric(mine)

    assert persisted.metric_code == "user_analyst::延迟单量"
    assert persisted.owner == "analyst"


def test_metric_delete_and_unshare_blocked_by_scheduled_dependency(tmp_path: Path) -> None:
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    product_repo = SQLiteProductRepository(data_file=data_file, store_path=tmp_path / "sqbi.sqlite3", file_root=tmp_path / "files")
    metric = MetricDefinition(
        metric_code="user_analyst::delay_rate",
        name="自定义延期风险率",
        definition="延期单量占比",
        visibility=MetricVisibility.PRIVATE,
        formula=MetricFormula(expression="select round(100 * count(case when c.ACTUAL_TIME > c.PLAN_TIME then 1 end) / nullif(count(1), 0), 2) as delay_rate from HR_DELIVER_CARRY c"),
        data_source_id="oracle_tms",
        owner="analyst",
    )
    product_repo.create_user_metric(metric)
    product_repo.update_metric_visibility(metric.metric_code, MetricVisibility.SHARED, "analyst")
    product_repo.create_scheduled_job(
        user_id="analyst",
        entity_type="report",
        entity_id="华北区周度运费监控分发",
        schedule_text="每天 8 点",
        payload={"title": "华北区周度运费监控分发", "bound_metric_codes": [metric.metric_code]},
    )

    deps = product_repo.list_metric_dependencies(metric.metric_code)
    assert any(dep.blocking for dep in deps)
    with pytest.raises(ValueError, match="阻断"):
        product_repo.update_metric_visibility(metric.metric_code, MetricVisibility.PRIVATE, "analyst")
    with pytest.raises(ValueError, match="阻断"):
        product_repo.delete_metric(metric.metric_code, "analyst")


def test_metric_owner_can_edit_private_metric(tmp_path: Path) -> None:
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    product_repo = SQLiteProductRepository(data_file=data_file, store_path=tmp_path / "sqbi.sqlite3", file_root=tmp_path / "files")
    metric = MetricDefinition(
        metric_code="user_analyst::edit_metric",
        name="可编辑指标",
        definition="原定义",
        visibility=MetricVisibility.PRIVATE,
        formula=MetricFormula(expression="select count(1) as metric_value from HR_DELIVER_FORM f"),
        data_source_id="oracle_tms",
        owner="analyst",
    )
    product_repo.create_user_metric(metric)

    updated = product_repo.update_metric(
        metric.metric_code,
        {
            "name": "可编辑指标新版",
            "definition": "新定义",
            "formula": {"expression": "select count(distinct f.DELIVER_NO) as form_count from HR_DELIVER_FORM f"},
            "synonyms": ["编辑测试"],
        },
        "analyst",
    )

    assert updated.name == "可编辑指标新版"
    assert updated.definition == "新定义"
    assert updated.formula.expression == "select count(distinct f.DELIVER_NO) as form_count from HR_DELIVER_FORM f"
    assert updated.synonyms == ["编辑测试"]


def test_metric_sql_rejects_undeclared_alias(tmp_path: Path) -> None:
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    product_repo = SQLiteProductRepository(data_file=data_file, store_path=tmp_path / "sqbi.sqlite3", file_root=tmp_path / "files")
    metric = MetricDefinition(
        metric_code="user_analyst::bad_metric",
        name="坏指标",
        definition="别名未声明",
        visibility=MetricVisibility.PRIVATE,
        formula=MetricFormula(expression="select count(distinct c.DELIVER_NO) as metric_value from HR_DELIVER_FORM f"),
        data_source_id="oracle_tms",
        owner="analyst",
    )

    with pytest.raises(ValueError, match="未声明的表别名"):
        product_repo.create_user_metric(metric)


def test_report_owner_can_update_and_delete_custom_report(tmp_path: Path) -> None:
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    product_repo = SQLiteProductRepository(data_file=data_file, store_path=tmp_path / "sqbi.sqlite3", file_root=tmp_path / "files")
    report = ReportRecord(
        report_id="user_analyst_report_edit",
        name="月度经营汇报",
        description="原始说明",
        visibility="private",
        owner="analyst",
        outputTypes=["html"],
        channels=[],
        flow="创建 -> 预览",
        sections=["封面", "指标页"],
        tags=["HTML"],
        version="1.0.0",
    )
    product_repo.create_report(report, "analyst")

    updated = product_repo.update_report(
        report.report_id,
        {
            "name": "月度经营汇报新版",
            "description": "更新说明",
            "outputTypes": ["push"],
            "flow": "编辑 -> 预览 -> 保存",
            "sections": ["摘要", "正文"],
            "tags": ["PUSH"],
        },
        "analyst",
    )

    assert updated.name == "月度经营汇报新版"
    assert updated.outputTypes == ["push"]
    assert updated.sections == ["摘要", "正文"]

    product_repo.delete_report(report.report_id, "analyst")
    assert all(item.report_id != report.report_id for item in product_repo.list_reports())


def test_custom_skill_name_is_validated_on_create(tmp_path: Path) -> None:
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    product_repo = SQLiteProductRepository(data_file=data_file, store_path=tmp_path / "sqbi.sqlite3", file_root=tmp_path / "files")
    skill = SkillDefinition(
        skill_id="user_analyst_duplicate_skill",
        namespace="user",
        name="重复技能",
        skill_type=SkillType.REPORT,
        visibility=SkillVisibility.PRIVATE,
        owner_user_id="analyst",
        description="首次创建。",
        parameters=[],
        output_schema={"schema": {"steps": ["查询数据"]}},
    )
    product_repo.create_skill(skill, "analyst")

    with pytest.raises(ValueError, match="already own a skill"):
        product_repo.create_skill(
            skill.model_copy(update={"skill_id": "user_analyst_duplicate_skill_2"}),
            "analyst",
        )


def test_custom_report_name_is_validated_on_create(tmp_path: Path) -> None:
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    product_repo = SQLiteProductRepository(data_file=data_file, store_path=tmp_path / "sqbi.sqlite3", file_root=tmp_path / "files")
    report = ReportRecord(
        report_id="user_analyst_duplicate_report",
        name="重复报表",
        description="首次创建。",
        visibility="private",
        owner="analyst",
        outputTypes=["html"],
        channels=[],
        flow="创建 -> 保存",
        sections=["摘要"],
        tags=["HTML"],
        version="1.0.0",
    )
    product_repo.create_report(report, "analyst")

    with pytest.raises(ValueError, match="already own a report"):
        product_repo.create_report(
            report.model_copy(update={"report_id": "user_analyst_duplicate_report_2"}),
            "analyst",
        )


def test_product_asset_revision_changes_when_report_assets_change(tmp_path: Path) -> None:
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    product_repo = SQLiteProductRepository(data_file=data_file, store_path=tmp_path / "sqbi.sqlite3", file_root=tmp_path / "files")
    before = product_repo.asset_revision()

    product_repo.create_report(
        ReportRecord(
            report_id="user_analyst_revision_check",
            name="资产版本检查",
            description="用于验证资产上下文缓存失效。",
            visibility="private",
            owner="analyst",
            outputTypes=["html"],
            channels=[],
            flow="创建 -> 保存",
            sections=["摘要"],
            tags=["HTML"],
            version="1.0.0",
        ),
        "analyst",
    )

    assert product_repo.asset_revision() != before


def test_seeded_reports_include_skill_analysis_chain(tmp_path: Path) -> None:
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    product_repo = SQLiteProductRepository(data_file=data_file, store_path=tmp_path / "sqbi.sqlite3", file_root=tmp_path / "files")

    report = next(item for item in product_repo.list_reports() if item.report_id == "official_tms_management_pack")

    assert report.analysis_chain
    assert any(step.get("skill_id") == "tms_carrier_performance" for step in report.analysis_chain)
    assert any(step.get("type") == "report_renderer" for step in report.analysis_chain)


def test_existing_store_backfills_ai_native_report_chain(tmp_path: Path) -> None:
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    store_path = tmp_path / "sqbi.sqlite3"
    SQLiteProductRepository(data_file=data_file, store_path=store_path, file_root=tmp_path / "files")

    import json
    import sqlite3

    with sqlite3.connect(store_path) as conn:
        row = conn.execute(
            "select payload from product_reports where report_id = ?",
            ("official_tms_management_pack",),
        ).fetchone()
        payload = json.loads(row[0])
        payload["analysis_chain"] = []
        conn.execute(
            "update product_reports set payload = ? where report_id = ?",
            (json.dumps(payload, ensure_ascii=False), "official_tms_management_pack"),
        )
        conn.execute("delete from meta where key = ?", ("product_seed_v2_ai_native_reports",))

    product_repo = SQLiteProductRepository(data_file=data_file, store_path=store_path, file_root=tmp_path / "files")
    report = next(item for item in product_repo.list_reports() if item.report_id == "official_tms_management_pack")

    assert report.analysis_chain
    assert any(step.get("type") == "report_renderer" for step in report.analysis_chain)


def test_seeded_metric_and_skill_assets_are_mixed_by_visibility(tmp_path: Path) -> None:
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    product_repo = SQLiteProductRepository(data_file=data_file, store_path=tmp_path / "sqbi.sqlite3", file_root=tmp_path / "files")

    metrics_by_code = {metric.metric_code: metric for metric in product_repo.list_metrics()}
    skills_by_id = {skill.skill_id: skill for skill in product_repo.list_skills()}

    assert metrics_by_code["ontime_rate"].visibility == MetricVisibility.PRIVATE
    assert metrics_by_code["carrier_shipment_count"].visibility == MetricVisibility.SHARED
    assert metrics_by_code["apply_count"].visibility == MetricVisibility.OFFICIAL
    assert skills_by_id["tms_carrier_performance"].visibility.value == "private"
    assert skills_by_id["tms_logistics_risk_scan"].visibility.value == "shared"
    assert skills_by_id["tms_system_askdata"].visibility.value == "official"


def test_report_derivatives_require_html_primary_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SQBI_REPORT_RENDER_ENDPOINT", raising=False)
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    product_repo = SQLiteProductRepository(data_file=data_file, store_path=tmp_path / "sqbi.sqlite3", file_root=tmp_path / "files")

    with pytest.raises(ValueError, match="REPORT_HTML_SOURCE_REQUIRED"):
        product_repo.generate_report_file(
            "official_tms_management_pack",
            user_id="analyst",
            output_type="pdf",
            title="云端渲染测试",
            content="报表内容",
        )

    html_record = product_repo.generate_report_file(
        "official_tms_management_pack",
        user_id="analyst",
        output_type="html",
        title="云端渲染测试",
        content='<!doctype html><html lang="zh-CN"><body><h1>运输管理报告</h1></body></html>',
    )
    for output_type, expected_content_type in (
        ("pdf", "application/pdf"),
        ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ):
        derived = product_repo.generate_report_file(
            "official_tms_management_pack",
            user_id="analyst",
            output_type=output_type,
            title="云端渲染测试",
        )
        assert derived.content_type == expected_content_type
        assert derived.derived_from == html_record.file_id
        assert derived.converter_version == "sqbi-html-derived-v1"


def test_ai_native_build_trace_persists_for_each_asset_type(tmp_path: Path) -> None:
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    product_repo = SQLiteProductRepository(data_file=data_file, store_path=tmp_path / "sqbi.sqlite3", file_root=tmp_path / "files")
    event = AssetBuildEvent(event_id="evt_confirm", event_type="confirmation", title="用户确认")
    evidence = ValidationEvidence(check="controlled_execution", status="passed")

    metric = product_repo.create_user_metric(MetricDefinition(
        metric_code="user_trace_metric",
        name="追溯测试指标",
        definition="验证构建记录",
        visibility=MetricVisibility.PRIVATE,
        formula=MetricFormula(expression="select 1 as metric_value from dual"),
        data_source_id="oracle_tms",
        owner="trace_user",
        execution_contract=ExecutableAssetContract(
            asset_kind="metric",
            logical_sql="select 1 as metric_value from dual",
            data_source_bindings=[DataSourceBinding(data_source_id="oracle_tms", name="TMS Oracle")],
        ),
        build_trace=[event],
        validation_evidence=[evidence],
    ))
    skill = product_repo.create_skill(SkillDefinition(
        skill_id="user_trace_skill",
        namespace="user",
        name="追溯测试技能",
        skill_type=SkillType.REPORT,
        visibility=SkillVisibility.PRIVATE,
        description="验证构建记录",
        data_source_bindings=[DataSourceBinding(data_source_id="oracle_tms", name="TMS Oracle", role="inherited")],
        execution_contract=ExecutableAssetContract(asset_kind="skill"),
        build_trace=[event],
        validation_evidence=[evidence],
    ), "trace_user")
    report = product_repo.create_report(ReportRecord(
        report_id="user_trace_report",
        name="追溯测试报表",
        description="验证构建记录",
        owner="trace_user",
        flow="HTML-first",
        execution_contract=ExecutableAssetContract(asset_kind="report").model_dump(mode="json"),
        data_source_bindings=[{"data_source_id": "oracle_tms", "name": "TMS Oracle", "role": "inherited"}],
        build_trace=[event.model_dump(mode="json")],
        validation_evidence=[evidence.model_dump(mode="json")],
    ), "trace_user")

    assert metric.build_trace[0].event_id == "evt_confirm"
    assert skill.execution_contract and skill.execution_contract.asset_kind == "skill"
    assert skill.data_source_bindings[0].data_source_id == "oracle_tms"
    assert report.validation_evidence[0]["status"] == "passed"
    assert report.data_source_bindings[0]["data_source_id"] == "oracle_tms"


def test_html_report_generation_requires_complete_html_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SQBI_REPORT_RENDER_ENDPOINT", raising=False)
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    product_repo = SQLiteProductRepository(data_file=data_file, store_path=tmp_path / "sqbi.sqlite3", file_root=tmp_path / "files")

    report = next(item for item in product_repo.list_reports() if item.report_id == "official_tms_management_pack")
    with pytest.raises(ValueError, match="REPORT_HTML_CONTENT_INVALID"):
        product_repo.generate_report_file(
            report.report_id,
            user_id="analyst",
            output_type="html",
            title="TMS 在线经营分析报告",
            content="\n".join(
                [
                    "## 管理层摘要",
                    "- 本期重点关注厂区履约差异、承运商时效波动和项目延期集中度。",
                    "## 履约风险扫描",
                    "- 对未签收、在途积压和延期项目做风险分层。",
                    "## 行动建议",
                    "- 建议按厂区和承运商建立闭环跟踪清单。",
                ]
            ),
        )


def test_ai_native_html_report_is_published_without_local_template_wrapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SQBI_REPORT_RENDER_ENDPOINT", raising=False)
    data_file = Path(__file__).parent.parent / "data" / "tms_semantic.yaml"
    product_repo = SQLiteProductRepository(data_file=data_file, store_path=tmp_path / "sqbi.sqlite3", file_root=tmp_path / "files")

    html_content = "<!doctype html><html lang=\"zh-CN\"><body><main><h1>AI 原生报告</h1><p>真实数据分析。</p></main></body></html>"
    generated = product_repo.generate_report_file(
        "shared_carrier_weekly_digest",
        user_id="analyst",
        output_type="html",
        title="承运商履约周报",
        content=html_content,
        bound_metric_codes=["carrier_shipment_count"],
        bound_skill_ids=["tms_carrier_performance"],
    )

    assert generated.render_provider == "llm_html"
    html = (tmp_path / "files" / "generated" / generated.filename).read_text(encoding="utf-8")
    assert html == html_content
    assert "SQ-BI TMS ONLINE REPORT" not in html
