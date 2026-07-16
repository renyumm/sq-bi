from __future__ import annotations

import json

from sq_bi_contracts.enterprise_pack import (
    EnterprisePackDraft,
    PackEnterpriseField,
    PackReport,
    PackSkill,
    PackSkillStep,
)

from sq_bi_runtime.domain_pack_authoring import (
    DomainPackAuthoringService,
    validate_domain_pack,
)


class StubLLM:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        assert system_prompt
        assert user_prompt
        return json.dumps(self.payload, ensure_ascii=False)


def test_suggest_returns_portable_candidate() -> None:
    llm = StubLLM({
        "summary": "候选已生成",
        "suggestions": ["确认时间口径"],
        "draft": {
            "fields": [{
                "field_id": "order_amount", "business_name": "订单金额",
                "data_type": "NUMBER", "description": "订单含税金额",
            }],
            "metrics": [{
                "metric_code": "total_order_amount", "name": "订单总额",
                "definition": "订单金额合计",
                "formula": {"expression": "SUM(order_amount)", "filters": []},
            }],
        },
    })
    result = DomainPackAuthoringService(llm).suggest(
        scope="all",
        name="订单经营",
        description="订单分析",
        business_context="管理层关注规模和趋势",
        draft=EnterprisePackDraft(),
    )

    assert result["summary"] == "候选已生成"
    assert result["draft"]["fields"][0]["field_id"] == "order_amount"
    assert result["draft"]["metrics"][0]["formula"]["expression"] == "SUM(order_amount)"


def test_suggest_drops_physical_sql_without_losing_entire_response() -> None:
    llm = StubLLM({
        "draft": {
            "metrics": [{
                "metric_code": "bad", "name": "错误指标", "definition": "错误",
                "formula": {"expression": "SELECT SUM(amount) FROM orders", "filters": []},
            }],
        },
    })
    result = DomainPackAuthoringService(llm).suggest(
        scope="metrics", name="测试", description="", business_context="",
        draft=EnterprisePackDraft(),
    )
    assert result["draft"]["metrics"] == []
    assert any("物理 SQL" in issue for issue in result["issues"])


def test_all_scope_can_reject_insufficient_business_context() -> None:
    llm = StubLLM({
        "input_assessment": {"reasonable": False, "feedback": "请补充业务目标和使用角色。"},
        "summary": "当前信息不足，暂不生成草稿。",
        "draft": {"fields": [{"field_id": "invented", "business_name": "不应采用", "data_type": "TEXT"}]},
    })
    result = DomainPackAuthoringService(llm).suggest(
        scope="all", name="测试", description="", business_context="",
        draft=EnterprisePackDraft(),
    )

    assert result["input_assessment"]["reasonable"] is False
    assert result["draft"]["fields"] == []


def test_suggest_ignores_unsupported_term_shape_and_harmless_extras() -> None:
    llm = StubLLM({
        "input_assessment": {"reasonable": True, "feedback": "信息充分。"},
        "draft": {
            "fields": [{
                "field_id": "shipment_id", "business_name": "运单号",
                "data_type": "TEXT", "physical_column": "SHIPMENT_ID",
            }],
            "terms": [{
                "term_id": "otd_sla", "name": "准时送达协议", "description": "模型扩展字段",
            }],
        },
    })
    result = DomainPackAuthoringService(llm).suggest(
        scope="all", name="运输履约", description="履约分析",
        business_context="关注运输准时率和延误归因", draft=EnterprisePackDraft(),
    )

    assert result["draft"]["fields"][0]["field_id"] == "shipment_id"
    assert result["draft"]["terms"] == []


def test_deterministic_review_detects_missing_dependencies() -> None:
    draft = EnterprisePackDraft(
        fields=[PackEnterpriseField(field_id="region", business_name="区域", data_type="TEXT")],
        skills=[PackSkill(
            skill_id="risk_scan",
            name="风险扫描",
            steps=[PackSkillStep(
                step_id="step_1",
                description="扫描异常",
                metric_codes=["missing_metric"],
                dimension_field_ids=["missing_field"],
            )],
        )],
        reports=[PackReport(
            report_id="weekly_report",
            name="周报",
            metric_codes=["missing_metric"],
            skill_ids=["missing_skill"],
        )],
    )

    issues = validate_domain_pack(draft, include_empty=False)
    assert any("不存在的指标" in issue for issue in issues)
    assert any("不存在的字段" in issue for issue in issues)
    assert any("不存在的技能" in issue for issue in issues)
