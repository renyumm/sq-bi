from pathlib import Path

import pytest

from sq_bi_runtime.controlled_query import ControlledPlanError
from sq_bi_runtime.semantic_assets import load_semantic_asset_bundle
from sq_bi_runtime.service import AskDataService


class StubLLM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return """
        {
          "intent": "承运商分析",
          "metrics": ["承运商承运量"],
          "dimensions": ["承运商"],
          "time_range": "本月",
          "sql": "select f.carrier_name, count(distinct f.deliver_no) as shipment_cnt from hr_deliver_form f group by f.carrier_name fetch first 10 rows only",
          "explanation": "按承运商统计制单量。"
        }
        """


class SelectStarLLM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        if len(self.calls) == 1:
            return """
            {
              "intent": "样例数据",
              "metrics": [],
              "dimensions": [],
              "time_range": "最近",
              "sql": "select * from hr_deliver_form fetch first 5 rows only",
              "explanation": "抽取样例数据。"
            }
            """
        return """
        {
          "intent": "样例数据",
          "metrics": [],
          "dimensions": [],
          "time_range": "最近",
          "sql": "select f.deliver_no, f.carrier_name from hr_deliver_form f fetch first 5 rows only",
          "explanation": "抽取样例数据。"
        }
        """


class RepairingLLM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        if len(self.calls) == 1:
            return """
            {
              "intent": "RFQ区域分析",
              "metrics": ["询价单量"],
              "dimensions": ["区域"],
              "time_range": "本月",
              "sql": "select ei.area, count(distinct ei.enquiry_no) as enquiry_cnt from rfq_enquiry_info ei group by ei.area",
              "explanation": "按区域统计询价单量。"
            }
            """
        return """
        {
          "intent": "RFQ项目分析",
          "metrics": ["询价单量"],
          "dimensions": ["RFQ项目"],
          "time_range": "本月",
          "sql": "select p.project_name, count(distinct ei.enquiry_no) as enquiry_cnt from rfq_enquiry_info ei join rfq_project_base p on p.id = ei.project_id group by p.project_name fetch first 10 rows only",
          "explanation": "当前 RFQ 数据目录没有区域字段，使用 RFQ 项目名称作为代理维度。"
        }
        """


class ChineseChartFieldLLM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return """
        {
          "intent": "低按时到达率承运商",
          "metrics": ["按时到达率"],
          "dimensions": ["承运商"],
          "time_range": "上月",
          "sql": "select f.carrier_name as carrier_name, count(distinct f.deliver_no) as shipment_count, 86.5 as ontime_rate from hr_deliver_form f group by f.carrier_name order by ontime_rate asc fetch first 8 rows only",
          "display_columns": [
            {"key": "CARRIER_NAME", "label": "承运商"},
            {"key": "SHIPMENT_CNT", "label": "承运量"},
            {"key": "ONTIME_RATE", "label": "按时到达率"}
          ],
          "chart_suggestion": {
            "chart_type": "bar",
            "title": "上月低按时到达率承运商",
            "x_field": "承运商",
            "y_field": "按时到达率",
            "series_field": "按时到达率",
            "description": "按承运商对比上月按时到达率。"
          },
          "explanation": "按承运商对比上月按时到达率，优先关注低值对象。"
        }
        """


class StubDB:
    _DATA: dict[str, list[dict]] = {
        "order by ontime_rate asc": [
            {"CARRIER_NAME": "飞力达", "SHIPMENT_CNT": 42, "ONTIME_RATE": 88.6},
            {"CARRIER_NAME": "中外运", "SHIPMENT_CNT": 35, "ONTIME_RATE": 91.2},
        ],
        "as ontime_rate": [{"ONTIME_RATE": 92.4}],
        "as unsigned_cnt": [{"UNSIGNED_CNT": 36}],
        "as signed_cnt": [{"SIGNED_CNT": 210}],
        "as in_transit_cnt": [{"IN_TRANSIT_CNT": 58}],
        "as delayed_cnt": [
            {"PROJECT_NAME": "天津项目", "DELAYED_CNT": 7},
            {"PROJECT_NAME": "南京项目", "DELAYED_CNT": 4},
            {"PROJECT_NAME": "苏州项目", "DELAYED_CNT": 2},
        ],
        "as enquiry_cnt": [
            {"PROJECT_NAME": "华东 RFQ 项目", "ENQUIRY_CNT": 6},
            {"PROJECT_NAME": "华南 RFQ 项目", "ENQUIRY_CNT": 3},
        ],
    }

    def execute(self, sql: str, params: dict | None = None) -> list[dict]:
        sql_lower = sql.lower()
        for key, data in self._DATA.items():
            if key in sql_lower:
                return data
        return [
            {"CARRIER_NAME": "飞力达", "SHIPMENT_CNT": 10},
            {"CARRIER_NAME": "邮政", "SHIPMENT_CNT": 9},
        ]


class RecordingDB:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, sql: str, params: dict | None = None) -> list[dict]:
        self.calls.append(sql)
        return []


def test_controlled_exploration_never_executes_raw_llm_sql() -> None:
    db = RecordingDB()
    service = AskDataService(
        skill_context="skill",
        llm_client=StubLLM(),
        db_executor=db,
        schema_catalog={"HR_DELIVER_FORM": {"CARRIER_NAME", "DELIVER_NO"}},
    )
    with pytest.raises(ControlledPlanError, match="raw SQL"):
        service.ask_controlled("本月哪些承运商承运量最高？")
    assert db.calls == []


def test_service_generates_and_executes_sql() -> None:
    llm = StubLLM()
    service = AskDataService(skill_context="skill", llm_client=llm, db_executor=StubDB())
    result = service.ask("本月哪些承运商承运量最高？")
    assert result["intent"] == "承运商分析"
    assert result["columns"] == ["CARRIER_NAME", "SHIPMENT_CNT"]
    assert len(result["rows"]) == 2
    assert result["chart_suggestion"]["chart_type"] == "bar"
    assert len(llm.calls) == 1
    assert "Skill" in llm.calls[0][1]


def test_service_uses_llm_for_open_analysis_questions() -> None:
    llm = StubLLM()
    service = AskDataService(skill_context="skill", llm_client=llm, db_executor=StubDB())
    result = service.ask("分析一下这个月物流可能出现的隐患问题")
    assert result["intent"] == "承运商分析"
    assert result["columns"] == ["CARRIER_NAME", "SHIPMENT_CNT"]
    assert len(llm.calls) == 1


def test_service_injects_saved_skill_context_into_llm_prompt() -> None:
    llm = StubLLM()
    service = AskDataService(
        skill_context="base skill context",
        llm_client=llm,
        db_executor=StubDB(),
        asset_context_provider=lambda: "# Dynamic Classified Assets\n\nfresh_metric_skill",
    )
    result = service.ask(
        "/carrier_performance 本月履约风险",
        execute_sql=False,
        extra_context="# Saved Product Skill To Execute\n\ncarrier_performance",
    )
    assert result["intent"] == "承运商分析"
    assert "base skill context" in llm.calls[0][1]
    assert "fresh_metric_skill" in llm.calls[0][1]
    assert "Saved Product Skill To Execute" in llm.calls[0][1]
    assert "carrier_performance" in llm.calls[0][1]


def test_service_maps_chinese_chart_fields_to_sql_output_keys() -> None:
    llm = ChineseChartFieldLLM()
    service = AskDataService(skill_context="skill", llm_client=llm, db_executor=StubDB())

    result = service.ask("上月按时到达率比较低的承运商")

    assert result["columns"] == [
        {"key": "CARRIER_NAME", "label": "承运商"},
        {"key": "SHIPMENT_CNT", "label": "承运量"},
        {"key": "ONTIME_RATE", "label": "按时到达率"},
    ]
    assert result["chart_suggestion"]["x_field"] == "CARRIER_NAME"
    assert result["chart_suggestion"]["y_field"] == "ONTIME_RATE"
    assert result["chart_suggestion"]["series_field"] == "按时到达率"


def test_service_allows_select_star_for_exploration_queries() -> None:
    llm = SelectStarLLM()
    service = AskDataService(skill_context="skill", llm_client=llm, db_executor=StubDB())

    result = service.ask("查样例数据，返回前5条供核对")

    assert len(llm.calls) == 1
    assert "select *" in result["sql"].lower()
    assert result["columns"] == ["CARRIER_NAME", "SHIPMENT_CNT"]


def test_service_repairs_unknown_column_before_execution() -> None:
    llm = RepairingLLM()
    semantic_catalog_path = Path(__file__).resolve().parents[3] / "services" / "semantic" / "data" / "tms_semantic.yaml"
    service = AskDataService(
        skill_context=load_semantic_asset_bundle(semantic_catalog_path),
        llm_client=llm,
        db_executor=StubDB(),
        schema_catalog={
            "RFQ_ENQUIRY_INFO": {"ENQUIRY_NO", "PROJECT_ID", "CREATED_TIME"},
            "RFQ_PROJECT_BASE": {"ID", "PROJECT_NAME"},
        },
    )

    result = service.ask("RFQ 询比价分析 按区域对比")

    assert len(llm.calls) == 2
    assert "Skill Center Analysis Skill Assets" in llm.calls[0][1]
    assert "RFQ 询比价分析" in llm.calls[0][1]
    assert "RFQ 项目维度代理" in llm.calls[0][1]
    assert "RFQ_ENQUIRY_INFO.AREA" in llm.calls[1][1]
    assert "rfq_project_base" in result["sql"].lower()
    assert "project_name" in result["sql"].lower()
    assert result["columns"] == ["PROJECT_NAME", "ENQUIRY_CNT"]
