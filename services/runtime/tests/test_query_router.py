"""Tests for QueryRouter: three-path resolution, data-source isolation."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sq_bi_contracts.exploration import AnswerPath
from sq_bi_contracts.enums import MetricVisibility
from sq_bi_contracts.metrics import MetricDefinition, MetricFormula
from sq_bi_runtime.query_router import QueryRouter


def _metric(
    code: str,
    name: str,
    visibility: MetricVisibility,
    data_source_id: str = "ds_tms",
    synonyms: list[str] | None = None,
) -> MetricDefinition:
    return MetricDefinition(
        metric_code=code,
        name=name,
        definition=name,
        visibility=visibility,
        formula=MetricFormula(expression=f"SELECT 1 -- {code}"),
        data_source_id=data_source_id,
        owner="test",
        synonyms=synonyms or [],
    )


def _router(*metrics: MetricDefinition) -> QueryRouter:
    repo = MagicMock()
    repo.list_metrics.return_value = list(metrics)
    return QueryRouter(repo)


# ── Official wins ───────────────────────────────────────────────────────────

def test_official_metric_resolves_first() -> None:
    official = _metric("OTD", "准时到货率", MetricVisibility.OFFICIAL)
    private = _metric("OTD_P", "准时到货率", MetricVisibility.PRIVATE)
    router = _router(official, private)
    result = router.route("准时到货率", data_source_id="ds_tms")
    assert result.answer_path == AnswerPath.official
    assert result.matched_metric is not None
    assert result.matched_metric.metric_code == "OTD"


def test_official_matches_by_synonym() -> None:
    official = _metric("OTD", "准时到货率", MetricVisibility.OFFICIAL, synonyms=["OTD", "按时交货率"])
    router = _router(official)
    result = router.route("OTD", data_source_id="ds_tms")
    assert result.answer_path == AnswerPath.official


def test_official_matches_partial() -> None:
    official = _metric("OTD", "承运商准时到货率", MetricVisibility.OFFICIAL)
    router = _router(official)
    result = router.route("准时到货率", data_source_id="ds_tms")
    assert result.answer_path == AnswerPath.official


# ── Enterprise fallback ──────────────────────────────────────────────────────

def test_enterprise_fallback_when_no_official() -> None:
    private = _metric("INS", "保险费用", MetricVisibility.PRIVATE)
    router = _router(private)
    result = router.route("保险费用", data_source_id="ds_tms")
    assert result.answer_path == AnswerPath.enterprise
    assert result.matched_metric is not None
    assert result.matched_metric.metric_code == "INS"


def test_enterprise_not_chosen_when_official_matches() -> None:
    official = _metric("OTD", "准时到货率", MetricVisibility.OFFICIAL)
    shared = _metric("OTD_S", "准时到货率", MetricVisibility.SHARED)
    router = _router(official, shared)
    result = router.route("准时到货率", data_source_id="ds_tms")
    assert result.answer_path == AnswerPath.official


# ── Exploration fallback ──────────────────────────────────────────────────────

def test_exploration_fallback_no_match() -> None:
    official = _metric("OTD", "准时到货率", MetricVisibility.OFFICIAL)
    router = _router(official)
    result = router.route("货物温度", data_source_id="ds_tms")
    assert result.answer_path == AnswerPath.ai_exploration
    assert result.matched_metric is None


def test_exploration_fallback_empty_repo() -> None:
    router = _router()
    result = router.route("任意问题")
    assert result.answer_path == AnswerPath.ai_exploration


# ── Data-source isolation ────────────────────────────────────────────────────

def test_metrics_from_other_datasource_excluded() -> None:
    tms_metric = _metric("OTD", "准时到货率", MetricVisibility.OFFICIAL, data_source_id="ds_tms")
    other_metric = _metric("OTD2", "准时到货率", MetricVisibility.OFFICIAL, data_source_id="ds_other")
    router = _router(tms_metric, other_metric)
    # Asking with ds_other — only other_metric should be in scope
    result = router.route("准时到货率", data_source_id="ds_other")
    assert result.answer_path == AnswerPath.official
    assert result.matched_metric is not None
    assert result.matched_metric.data_source_id == "ds_other"


def test_datasource_none_searches_all() -> None:
    tms_metric = _metric("OTD", "准时到货率", MetricVisibility.OFFICIAL, data_source_id="ds_tms")
    router = _router(tms_metric)
    result = router.route("准时到货率", data_source_id=None)
    assert result.answer_path == AnswerPath.official


# ── answer_path always populated ─────────────────────────────────────────────

def test_answer_path_always_present() -> None:
    router = _router()
    for question in ["foo", "bar", "准时到货率", ""]:
        result = router.route(question)
        assert result.answer_path in (
            AnswerPath.official, AnswerPath.enterprise, AnswerPath.ai_exploration
        )
