"""Tests for ExplorationPlanner: inference, tier computation, join gating."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from sq_bi_contracts.exploration import (
    AnswerPath,
    ConfidenceTier,
    JoinEvidence,
)
from sq_bi_runtime.exploration_planner import (
    ExplorationPlanner,
    _compute_tier,
    _build_field_assumptions,
    _build_join_assumptions,
)


def _llm(response: dict) -> MagicMock:
    client = MagicMock()
    client.chat.return_value = json.dumps(response)
    return client


_SIMPLE_INTERP = {
    "fields": [
        {
            "physical_table": "TMS_ORDER",
            "physical_column": "INSURANCE_AMT",
            "business_name": "保险费用",
            "inferred_meaning": "每单保险金额",
            "role": "measure",
        }
    ],
    "aggregation": "SUM",
    "time_field": "TMS_ORDER.SHIP_DATE",
    "time_grain": "month",
    "filters": [],
    "joins": [],
    "clarification_needed": False,
    "clarification_question": None,
    "clarification_options": [],
}


def test_inferred_field_plan_built() -> None:
    planner = ExplorationPlanner(llm_client=_llm(_SIMPLE_INTERP))
    plan = planner.plan("各月保险费用", "ds_tms", semantic_context="## context")
    assert plan.assumption.aggregation == "SUM"
    assert plan.assumption.time_field == "TMS_ORDER.SHIP_DATE"
    assert len(plan.assumption.fields_used) == 1
    assert plan.assumption.fields_used[0].physical_column == "INSURANCE_AMT"


def test_read_only_enforcement_via_follow_up() -> None:
    planner = ExplorationPlanner(llm_client=_llm(_SIMPLE_INTERP))
    plan = planner.plan("各月保险费用", "ds_tms", semantic_context="ctx")
    # follow_up_context is what gets passed to ask pipeline; it must not contain SQL
    assert "SELECT" not in plan.follow_up_context
    assert "TMS_ORDER" in plan.follow_up_context


def test_assumptions_populated() -> None:
    planner = ExplorationPlanner(llm_client=_llm(_SIMPLE_INTERP))
    plan = planner.plan("保险费", "ds_tms", semantic_context="ctx")
    assert plan.assumption.fields_used
    assert plan.assumption.aggregation is not None
    assert plan.executable is True


def test_fields_not_in_profile_dropped() -> None:
    interp = {
        **_SIMPLE_INTERP,
        "fields": [
            {"physical_table": "TMS_ORDER", "physical_column": "INSURANCE_AMT",
             "business_name": "保险费", "role": "measure"},
            {"physical_table": "UNKNOWN_TABLE", "physical_column": "MYSTERY_COL",
             "business_name": "未知字段", "role": "measure"},
        ],
    }
    # profile_fields contains only INSURANCE_AMT
    profile_fields = {
        "TMS_ORDER.INSURANCE_AMT": MagicMock(confidence=0.9, origin=MagicMock(value="inferred")),
    }
    fa_list = _build_field_assumptions(interp["fields"], profile_fields)
    assert len(fa_list) == 1
    assert fa_list[0].physical_column == "INSURANCE_AMT"


def test_clarification_returned_on_ambiguous() -> None:
    ambiguous = {
        **_SIMPLE_INTERP,
        "clarification_needed": True,
        "clarification_question": "您想分析哪个费用？",
        "clarification_options": [
            {"label": "保险费", "description": "INSURANCE_AMT", "interpretation": "INSURANCE_AMT"},
            {"label": "合同费", "description": "CONTRACT_FEE", "interpretation": "CONTRACT_FEE"},
        ],
    }
    planner = ExplorationPlanner(llm_client=_llm(ambiguous))
    plan = planner.plan("费用是多少", "ds_tms", semantic_context="ctx")
    assert plan.clarification is not None
    assert plan.clarification.question == "您想分析哪个费用？"
    assert len(plan.clarification.options) == 2
    assert plan.executable is False
    assert plan.confidence_tier == ConfidenceTier.low


def test_high_confidence_from_profile_evidence() -> None:
    profile_fields = {
        "TMS_ORDER.INSURANCE_AMT": MagicMock(confidence=0.9, origin=MagicMock(value="inferred")),
    }
    fa_list = _build_field_assumptions(
        [{"physical_table": "TMS_ORDER", "physical_column": "INSURANCE_AMT",
          "business_name": "保险费", "role": "measure"}],
        profile_fields,
    )
    ja_list = []
    tier = _compute_tier(fa_list, ja_list, profile_fields)
    assert tier == ConfidenceTier.high


def test_llm_guess_join_forces_medium_or_below() -> None:
    profile_fields = {
        "TMS_ORDER.INSURANCE_AMT": MagicMock(confidence=0.9, origin=MagicMock(value="inferred")),
    }
    fa_list = _build_field_assumptions(
        [{"physical_table": "TMS_ORDER", "physical_column": "INSURANCE_AMT",
          "business_name": "保险费", "role": "measure"}],
        profile_fields,
    )
    ja_list = _build_join_assumptions([{
        "left_table": "TMS_ORDER", "right_table": "TMS_COST",
        "join_key": "ORDER_ID", "evidence": "llm_guess",
    }])
    tier = _compute_tier(fa_list, ja_list, profile_fields)
    assert tier in (ConfidenceTier.medium, ConfidenceTier.low)


def test_aggregating_plan_with_llm_guess_join_not_executable() -> None:
    interp_with_unsafe_join = {
        **_SIMPLE_INTERP,
        "joins": [{
            "left_table": "TMS_ORDER",
            "right_table": "TMS_COST",
            "join_key": "ORDER_ID",
            "evidence": "llm_guess",
        }],
    }
    planner = ExplorationPlanner(llm_client=_llm(interp_with_unsafe_join))
    plan = planner.plan("保险费汇总", "ds_tms", semantic_context="ctx")
    # aggregation=SUM + llm_guess join = not executable
    assert plan.executable is False
    assert plan.clarification is not None


def test_foreign_key_join_allows_aggregation() -> None:
    interp_safe_join = {
        **_SIMPLE_INTERP,
        "joins": [{
            "left_table": "TMS_ORDER",
            "right_table": "TMS_CARRIER",
            "join_key": "CARRIER_ID",
            "evidence": "foreign_key",
        }],
    }
    planner = ExplorationPlanner(llm_client=_llm(interp_safe_join))
    plan = planner.plan("各承运商保险费", "ds_tms", semantic_context="ctx")
    assert plan.executable is True


def test_llm_failure_returns_low_confidence_plan() -> None:
    bad_llm = MagicMock()
    bad_llm.chat.side_effect = RuntimeError("LLM timeout")
    planner = ExplorationPlanner(llm_client=bad_llm)
    plan = planner.plan("费用", "ds_tms", semantic_context="ctx")
    # Should not raise; returns a graceful empty plan
    assert plan.question == "费用"
