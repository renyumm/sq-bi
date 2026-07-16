"""TestClient tests for the ask endpoint exploration integration (tasks 4.3 + 5.3)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from sq_bi_contracts.exploration import (
    AnswerPath,
    ConfidenceTier,
    ClarificationRequest,
    ClarificationOption,
    QueryAssumption,
    FieldAssumption,
)
from sq_bi_contracts.metrics import MetricDefinition, MetricFormula, MetricVisibility
from sq_bi_runtime.api import create_app
from sq_bi_runtime.exploration_planner import ExplorationPlan
from sq_bi_runtime.query_router import RouteResult


# ── Shared helpers ────────────────────────────────────────────────────────────

def _cfg(tmp_path: Path) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(
        f"base_url: http://localhost/v1\nkey: k\nmodel: m\nstorage_path: {tmp_path}\n",
        encoding="utf-8",
    )
    return p


def _official_metric() -> MetricDefinition:
    return MetricDefinition(
        metric_code="OTD", name="准时到货率", definition="准时到货率",
        visibility=MetricVisibility.OFFICIAL,
        formula=MetricFormula(expression="SELECT 1"),
        data_source_id="ds_tms", owner="system",
    )


def _private_metric() -> MetricDefinition:
    return MetricDefinition(
        metric_code="INS", name="保险费用", definition="保险费用",
        visibility=MetricVisibility.PRIVATE,
        formula=MetricFormula(expression="SELECT 2"),
        data_source_id="ds_tms", owner="user",
    )


_ASK_PAYLOAD = {
    "sql": "SELECT SUM(INSURANCE_AMT) FROM TMS_ORDER",
    "rows": [[42.0]], "columns": [{"key": "total", "label": "合计"}],
    "narrative": "合计 42", "metrics": [], "tables": ["TMS_ORDER"],
    "physical_columns": ["INSURANCE_AMT"], "chart_type": "bar",
    "explanation": "", "skill_ids": [],
}

_EXPLORATION_PLAN = ExplorationPlan(
    question="各月保险费",
    data_source_id="ds_tms",
    assumption=QueryAssumption(
        fields_used=[FieldAssumption(
            physical_table="TMS_ORDER", physical_column="INSURANCE_AMT",
            business_name="保险费",
        )],
        aggregation="SUM",
    ),
    confidence_tier=ConfidenceTier.high,
    executable=True,
    follow_up_context="# AI 探索解读\n## 使用字段\n- TMS_ORDER.INSURANCE_AMT",
)


# ── Tests: three-path responses (task 4.3) ───────────────────────────────────

def test_official_path_sets_answer_path(tmp_path: pytest.TempPathFactory) -> None:
    route = RouteResult(answer_path=AnswerPath.official, matched_metric=_official_metric(), data_source_id="ds_tms")
    with (
        patch("sq_bi_runtime.query_router.QueryRouter.route", return_value=route),
        patch("sq_bi_runtime.api.get_repository") as mock_get_repo,
        patch("sq_bi_runtime.semantic_retriever.SemanticRetriever") as mock_sr,
            patch("sq_bi_runtime.service.AskDataService.ask_controlled", return_value=_ASK_PAYLOAD),
    ):
        mock_get_repo.return_value = MagicMock(list_metrics=lambda: [_official_metric()])
        mock_sr.return_value.get_context_for_question.return_value = "ctx"
        client = TestClient(create_app(_cfg(tmp_path)), raise_server_exceptions=False)
        resp = client.post("/api/v1/query/ask", json={"question": "准时到货率", "data_source_id": "ds_tms"})

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["answer_path"] == "official"
    assert data["is_exploratory"] is False


def test_enterprise_path_sets_answer_path(tmp_path: pytest.TempPathFactory) -> None:
    route = RouteResult(answer_path=AnswerPath.enterprise, matched_metric=_private_metric(), data_source_id="ds_tms")
    with (
        patch("sq_bi_runtime.query_router.QueryRouter.route", return_value=route),
        patch("sq_bi_runtime.api.get_repository") as mock_get_repo,
        patch("sq_bi_runtime.semantic_retriever.SemanticRetriever") as mock_sr,
            patch("sq_bi_runtime.service.AskDataService.ask_controlled", return_value=_ASK_PAYLOAD),
    ):
        mock_get_repo.return_value = MagicMock(list_metrics=lambda: [_private_metric()])
        mock_sr.return_value.get_context_for_question.return_value = "ctx"
        client = TestClient(create_app(_cfg(tmp_path)), raise_server_exceptions=False)
        resp = client.post("/api/v1/query/ask", json={"question": "保险费用", "data_source_id": "ds_tms"})

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["answer_path"] == "enterprise"
    assert data["is_exploratory"] is False


def test_exploration_path_returns_assumptions(tmp_path: pytest.TempPathFactory) -> None:
    route = RouteResult(answer_path=AnswerPath.ai_exploration, data_source_id="ds_tms")
    with (
        patch("sq_bi_runtime.query_router.QueryRouter.route", return_value=route),
        patch("sq_bi_runtime.api.get_repository") as mock_get_repo,
        patch("sq_bi_runtime.semantic_retriever.SemanticRetriever") as mock_sr,
        patch("sq_bi_runtime.exploration_planner.ExplorationPlanner.plan", return_value=_EXPLORATION_PLAN),
            patch("sq_bi_runtime.service.AskDataService.ask_controlled", return_value=_ASK_PAYLOAD),
    ):
        mock_get_repo.return_value = MagicMock(list_metrics=lambda: [])
        mock_sr.return_value.get_context_for_question.return_value = "ctx"
        client = TestClient(create_app(_cfg(tmp_path)), raise_server_exceptions=False)
        resp = client.post("/api/v1/query/ask", json={"question": "各月保险费", "data_source_id": "ds_tms"})

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["answer_path"] == "ai_exploration"
    assert data["is_exploratory"] is True
    assert len(data["assumptions"]) >= 1
    assert data["assumptions"][0]["fields_used"][0]["physical_column"] == "INSURANCE_AMT"


def test_backward_compatible_no_datasource_id(tmp_path: pytest.TempPathFactory) -> None:
    """Omitting data_source_id: answer_path=None, assumptions=[], is_exploratory=False."""
    with patch("sq_bi_runtime.service.AskDataService.ask_controlled", return_value=_ASK_PAYLOAD):
        client = TestClient(create_app(_cfg(tmp_path)), raise_server_exceptions=False)
        resp = client.post("/api/v1/query/ask", json={"question": "随便问"})

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["answer_path"] is None
    assert data["assumptions"] == []
    assert data["is_exploratory"] is False


def test_clarification_surfaced_on_low_confidence(tmp_path: pytest.TempPathFactory) -> None:
    route = RouteResult(answer_path=AnswerPath.ai_exploration, data_source_id="ds_tms")
    clarification = ClarificationRequest(
        question="请选择费用类型：",
        options=[
            ClarificationOption(label="保险费", description="INSURANCE_AMT", interpretation="INSURANCE_AMT"),
            ClarificationOption(label="合同费", description="CONTRACT_FEE", interpretation="CONTRACT_FEE"),
        ],
    )
    low_plan = ExplorationPlan(
        question="费用",
        data_source_id="ds_tms",
        assumption=QueryAssumption(),
        confidence_tier=ConfidenceTier.low,
        clarification=clarification,
        executable=False,
    )
    with (
        patch("sq_bi_runtime.query_router.QueryRouter.route", return_value=route),
        patch("sq_bi_runtime.api.get_repository") as mock_get_repo,
        patch("sq_bi_runtime.semantic_retriever.SemanticRetriever") as mock_sr,
        patch("sq_bi_runtime.exploration_planner.ExplorationPlanner.plan", return_value=low_plan),
    ):
        mock_get_repo.return_value = MagicMock(list_metrics=lambda: [])
        mock_sr.return_value.get_context_for_question.return_value = "ctx"
        client = TestClient(create_app(_cfg(tmp_path)), raise_server_exceptions=False)
        resp = client.post("/api/v1/query/ask", json={"question": "费用", "data_source_id": "ds_tms"})

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["clarification"]["question"] == "请选择费用类型："
    assert len(data["clarification"]["options"]) == 2
    assert data["rows"] == []


# ── Tests: sedimentation (task 5.3) ──────────────────────────────────────────

def test_sedimentation_persists_full_caliber(tmp_path: pytest.TempPathFactory) -> None:
    saved: list[MetricDefinition] = []

    def fake_create(m: MetricDefinition) -> MetricDefinition:
        saved.append(m)
        return m

    repo = MagicMock()
    repo.create_user_metric.side_effect = fake_create
    repo.list_metrics.return_value = []
    repo.official_metrics = {}

    with patch("sq_bi_runtime.api.get_repository", return_value=repo):
        client = TestClient(create_app(_cfg(tmp_path)), raise_server_exceptions=False)
        resp = client.post("/api/v1/query/exploration/save-metric", json={
            "business_name": "保险费合计",
            "definition": "每单保险费之和",
            "data_source_id": "ds_tms",
            "aggregation": "SUM",
            "synonyms": ["保险费", "insurance cost"],
            "field_mapping": [],
            "filters": [],
            "lineage": {},
            "user_id": "user1",
            "visibility": "enterprise",
        })

    assert resp.status_code == 200, resp.text
    assert len(saved) == 1
    assert saved[0].name == "保险费合计"
    assert "insurance cost" in (saved[0].synonyms or [])
    # P5 sedimentation always creates a workspace-scoped personal asset;
    # enterprise visibility requires the governed promotion workflow.
    assert saved[0].visibility == MetricVisibility.PRIVATE
    personal = resp.json()["data"]["personal_asset"]
    assert personal["workspace_id"] == "user1"
    assert personal["scope"]["data_source_id"] == "ds_tms"


def test_un_saved_exploration_stays_exploration(tmp_path: pytest.TempPathFactory) -> None:
    """An exploration answer that wasn't saved still routes ai_exploration next time."""
    # After sedimentation, the router finds the enterprise metric; before, it finds nothing.
    repo = MagicMock()
    repo.list_metrics.return_value = []  # nothing saved yet
    route = RouteResult(answer_path=AnswerPath.ai_exploration, data_source_id="ds_tms")
    with (
        patch("sq_bi_runtime.query_router.QueryRouter.route", return_value=route),
        patch("sq_bi_runtime.api.get_repository", return_value=repo),
        patch("sq_bi_runtime.semantic_retriever.SemanticRetriever") as mock_sr,
        patch("sq_bi_runtime.exploration_planner.ExplorationPlanner.plan", return_value=_EXPLORATION_PLAN),
            patch("sq_bi_runtime.service.AskDataService.ask_controlled", return_value=_ASK_PAYLOAD),
    ):
        mock_sr.return_value.get_context_for_question.return_value = "ctx"
        client = TestClient(create_app(_cfg(tmp_path)), raise_server_exceptions=False)
        resp = client.post("/api/v1/query/ask", json={"question": "各月保险费", "data_source_id": "ds_tms"})

    assert resp.status_code == 200
    assert resp.json()["data"]["answer_path"] == "ai_exploration"


def test_official_packs_untouched_by_sedimentation(tmp_path: pytest.TempPathFactory) -> None:
    """save-metric never modifies official metrics."""
    official = _official_metric()
    repo = MagicMock()
    repo.list_metrics.return_value = [official]
    repo.create_user_metric.return_value = MetricDefinition(
        metric_code="exp_user1::保险费合计", name="保险费合计", definition="保险费合计",
        visibility=MetricVisibility.SHARED,
        formula=MetricFormula(expression="-- exploration"),
        data_source_id="ds_tms", owner="user1",
    )

    with patch("sq_bi_runtime.api.get_repository", return_value=repo):
        client = TestClient(create_app(_cfg(tmp_path)), raise_server_exceptions=False)
        resp = client.post("/api/v1/query/exploration/save-metric", json={
            "business_name": "准时到货率",  # same name as official — but saving enterprise copy
            "definition": "用户自定义版本",
            "data_source_id": "ds_tms",
            "aggregation": "COUNT",
            "synonyms": [],
            "field_mapping": [],
            "filters": [],
            "lineage": {},
            "user_id": "user1",
            "visibility": "enterprise",
        })

    # Whatever happens, the official metric was never mutated
    assert official.visibility == MetricVisibility.OFFICIAL
    assert official.metric_code == "OTD"
