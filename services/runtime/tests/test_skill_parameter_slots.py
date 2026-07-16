from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sq_bi_contracts.asset_build import ExecutableAssetContract, ParameterSlot
from sq_bi_contracts.enums import SkillType, SkillVisibility
from sq_bi_contracts.skills import SkillDefinition, SkillParameter

from sq_bi_runtime.api import _resolve_skill_parameter_slots, create_app
from sq_bi_runtime.service import AskDataService


class StubSlotLLM:
    def chat(self, system: str, user: str) -> str:
        del system, user
        return '{"slots":[{"name":"region","value":"华东","status":"resolved"},{"name":"period","value":"最近3个月","status":"resolved"}]}'


def _skill() -> SkillDefinition:
    return SkillDefinition(
        skill_id="root_cause",
        namespace="test",
        name="履约归因",
        skill_type=SkillType.REPORT,
        visibility=SkillVisibility.PRIVATE,
        description="按区域和时间分析履约原因",
        parameters=[
            SkillParameter(name="region", data_type="string", required=True, description="区域", allowed_values=["华东", "华南"]),
            SkillParameter(name="period", data_type="string", required=True, description="时间范围"),
            SkillParameter(name="top_n", data_type="integer", required=False, description="展示数量"),
        ],
        execution_contract=ExecutableAssetContract(
            asset_kind="skill",
            parameter_slots=[ParameterSlot(name="top_n", data_type="integer", required=False, default_value=10)],
        ),
    )


def test_required_skill_slots_are_not_silently_guessed() -> None:
    slots = _resolve_skill_parameter_slots(_skill(), "帮我做一次履约归因")

    assert slots[0]["status"] == "unresolved"
    assert slots[1]["status"] == "unresolved"
    assert slots[1]["value"] is None
    assert slots[1]["resolution_source"] == "declared_contract"
    assert slots[2]["status"] == "resolved"
    assert slots[2]["value"] == 10


def test_skill_slots_record_resolution_source() -> None:
    slots = _resolve_skill_parameter_slots(
        _skill(), "分析华东最近3个月的履约原因", llm=StubSlotLLM()
    )

    assert slots[0]["value"] == "华东"
    assert slots[0]["resolution_source"] == "ai_context_binding"
    assert slots[1]["value"] == "最近3个月"
    assert slots[1]["resolution_source"] == "ai_context_binding"


def test_skill_execution_is_blocked_until_required_slots_are_resolved(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        f"base_url: http://localhost/v1\nkey: test\nmodel: test\nstorage_path: {tmp_path}\n",
        encoding="utf-8",
    )
    with patch.object(AskDataService, "ask_controlled") as controlled:
        response = TestClient(create_app(config), raise_server_exceptions=False).post(
            "/api/v1/ai/skills/execute",
            json={
                "user_id": "tester",
                "question": "帮我做一次履约归因",
                "execute": True,
                "skill": _skill().model_dump(mode="json"),
            },
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["clarification_required"] is True
    assert {slot["name"] for slot in payload["parameter_slots"] if slot["status"] == "unresolved"} == {"region", "period"}
    controlled.assert_not_called()


def test_asset_draft_test_uses_declared_time_default_and_returns_result(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        f"base_url: http://localhost/v1\nkey: test\nmodel: test\nstorage_path: {tmp_path}\n",
        encoding="utf-8",
    )
    controlled_result = {
        "intent": "controlled_exploration",
        "metrics": ["shipment_count"],
        "dimensions": [],
        "sql": "select count(1) as shipment_count from shipment fetch first 200 rows only",
        "columns": ["shipment_count"],
        "rows": [[12]],
        "tables": ["SHIPMENT"],
        "explanation": "受控执行完成",
        "execution_timings": [{"stage": "guardrail", "duration_ms": 1}],
    }
    with patch.object(AskDataService, "ask_controlled", return_value=controlled_result) as controlled:
        response = TestClient(create_app(config), raise_server_exceptions=False).post(
            "/api/v1/ai/assets/test",
            json={
                "user_id": "tester",
                "asset_type": "report",
                "name": "经营周报",
                "description": "汇总经营指标",
                "default_time_range": "本月",
                "execute": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["rows"] == [[12]]
    assert payload["answer_path"] == "personal"
    assert payload["clarification"] is None
    prompt_context = controlled.call_args.kwargs["extra_context"]
    assert '"default_time_range": "本月"' in prompt_context
