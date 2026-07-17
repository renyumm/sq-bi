from __future__ import annotations

from time import sleep

from sq_bi_contracts.harness import (
    HarnessBudgetLimits,
    HarnessCommandType,
    HarnessObservation,
    HarnessPlannerCommand,
    HarnessRequest,
    HarnessStatus,
    HarnessToolCall,
    HarnessToolName,
)
from sq_bi_contracts.runtime_projection import RuntimeRequestContext
from sq_bi_runtime.harness import (
    ConfirmationStore,
    ControlledToolRegistry,
    HarnessService,
    PolicyHarnessPlanner,
)
from sq_bi_runtime.api import _match_explicit_asset_candidates, _remove_inferred_asset_triggers


class SequencePlanner:
    def __init__(self, commands: list[HarnessPlannerCommand]) -> None:
        self.commands = commands

    def plan(self, request: HarnessRequest, observations: list[HarnessObservation]) -> HarnessPlannerCommand:
        del request
        return self.commands[len(observations)]


def _request(**updates: object) -> HarnessRequest:
    values = {
        "question": "运输收入",
        "context": RuntimeRequestContext(user_id="u1", data_source_id="ds1"),
        "permissions": ["harness:*"],
    }
    values.update(updates)
    return HarnessRequest(**values)


def _call(tool: HarnessToolName, arguments: dict | None = None, cost: int = 1) -> HarnessPlannerCommand:
    return HarnessPlannerCommand(
        type=HarnessCommandType.CALL_TOOL,
        call=HarnessToolCall(tool=tool, arguments=arguments or {}, cost_units=cost),
    )


def _finish() -> HarnessPlannerCommand:
    return HarnessPlannerCommand(type=HarnessCommandType.FINISH, message="done", result={"value": 1})


def test_multi_step_completion_has_trace_and_redaction() -> None:
    registry = ControlledToolRegistry()
    registry.register(HarnessToolName.RESOLVE_SCOPE, lambda request, args: HarnessObservation(ok=True, summary="scope"))
    registry.register(HarnessToolName.SEARCH_ASSETS, lambda request, args: HarnessObservation(ok=True, summary="assets"))
    service = HarnessService(SequencePlanner([
        _call(HarnessToolName.RESOLVE_SCOPE, {"token": "secret"}),
        _call(HarnessToolName.SEARCH_ASSETS),
        _finish(),
    ]), registry)
    result = service.run(_request())
    assert result.status == HarnessStatus.COMPLETED
    assert [step.tool for step in result.trace] == [HarnessToolName.RESOLVE_SCOPE, HarnessToolName.SEARCH_ASSETS]
    assert result.trace[0].arguments["token"] == "***"
    assert result.budget.steps == 2


def test_permission_and_unknown_tool_fail_closed() -> None:
    registry = ControlledToolRegistry()
    registry.register(HarnessToolName.SEARCH_ASSETS, lambda request, args: HarnessObservation(ok=True, summary="no"))
    result = HarnessService(SequencePlanner([_call(HarnessToolName.SEARCH_ASSETS)]), registry).run(
        _request(permissions=["harness:resolve_scope"])
    )
    assert result.failure and result.failure.code.value == "permission_denied"


def test_duplicate_step_and_cost_limits() -> None:
    registry = ControlledToolRegistry()
    registry.register(HarnessToolName.RESOLVE_SCOPE, lambda request, args: HarnessObservation(ok=True, summary="ok"))
    duplicate = HarnessService(SequencePlanner([
        _call(HarnessToolName.RESOLVE_SCOPE),
        _call(HarnessToolName.RESOLVE_SCOPE),
    ]), registry).run(_request())
    assert duplicate.failure and duplicate.failure.code.value == "duplicate_call"
    costly = HarnessService(SequencePlanner([_call(HarnessToolName.RESOLVE_SCOPE, cost=3)]), registry).run(
        _request(budget=HarnessBudgetLimits(max_cost_units=2))
    )
    assert costly.failure and costly.failure.code.value == "cost_limit"


def test_step_limit_and_tool_timeout() -> None:
    registry = ControlledToolRegistry()
    registry.register(HarnessToolName.RESOLVE_SCOPE, lambda request, args: HarnessObservation(ok=True, summary="ok"))
    limited = HarnessService(SequencePlanner([_call(HarnessToolName.RESOLVE_SCOPE)]), registry).run(
        _request(budget=HarnessBudgetLimits(max_steps=1))
    )
    assert limited.failure and limited.failure.code.value == "step_limit"
    registry.register(HarnessToolName.RESOLVE_SCOPE, lambda request, args: (sleep(0.1), HarnessObservation(ok=True, summary="late"))[1])
    timed = HarnessService(SequencePlanner([_call(HarnessToolName.RESOLVE_SCOPE)]), registry).run(
        _request(budget=HarnessBudgetLimits(per_tool_timeout_ms=50))
    )
    assert timed.failure and timed.failure.code.value == "tool_timeout"


def test_tool_raised_timeout_is_recorded_as_dependency_failure() -> None:
    registry = ControlledToolRegistry()

    def dependency_timeout(request: HarnessRequest, arguments: dict) -> HarnessObservation:
        del request, arguments
        raise TimeoutError("model dependency timed out")

    registry.register(HarnessToolName.RESOLVE_SCOPE, dependency_timeout)
    result = HarnessService(SequencePlanner([
        _call(HarnessToolName.RESOLVE_SCOPE),
        _finish(),
    ]), registry).run(_request())

    assert result.status == HarnessStatus.FAILED
    assert result.trace[0].observation is not None
    assert result.trace[0].observation.failure_code is not None
    assert result.trace[0].observation.failure_code.value == "tool_failed"
    assert result.trace[0].observation.summary == "model dependency timed out"


def test_planner_cannot_finish_successfully_after_failed_tool() -> None:
    registry = ControlledToolRegistry()
    registry.register(
        HarnessToolName.RESOLVE_SCOPE,
        lambda request, arguments: HarnessObservation(
            ok=False,
            summary="dependency unavailable",
            failure_code="tool_failed",
        ),
    )
    result = HarnessService(SequencePlanner([
        _call(HarnessToolName.RESOLVE_SCOPE),
        _finish(),
    ]), registry).run(_request())

    assert result.status == HarnessStatus.FAILED
    assert result.failure is not None
    assert result.failure.code.value == "tool_failed"


def test_confirmation_is_bound_and_single_use() -> None:
    store = ConfirmationStore()
    operation = {"proposal": {"name": "收入"}}
    confirmation = store.issue("u1", operation)
    assert not store.consume(confirmation.token, "u2", operation)
    assert not store.consume(confirmation.token, "u1", {"proposal": {"name": "成本"}})
    assert store.consume(confirmation.token, "u1", operation)
    assert not store.consume(confirmation.token, "u1", operation)


def test_confirmation_continuation_executes_original_operation_once() -> None:
    registry = ControlledToolRegistry()
    saved: list[dict] = []
    registry.register(
        HarnessToolName.SAVE_PERSONAL_ASSET,
        lambda request, args: (
            saved.append(args),
            HarnessObservation(ok=True, summary="saved", data={"asset_id": "a1"}),
        )[1],
    )
    operation = {"proposal": {"name": "收入"}, "question": "保存收入"}
    store = ConfirmationStore()
    confirmation = store.issue("u1", operation)
    service = HarnessService(SequencePlanner([_finish()]), registry, store)
    continued = _request(continuation={
        "run_id": "hrn_1",
        "confirmation_token": confirmation.token,
    })
    result = service.run(continued)
    assert result.status == HarnessStatus.COMPLETED
    assert saved == [operation]
    replay = service.run(continued)
    assert replay.failure and replay.failure.code.value == "confirmation_invalid"


def test_clarification_terminates_without_tool_call() -> None:
    command = HarnessPlannerCommand(type=HarnessCommandType.CLARIFY, message="请选择数据源")
    result = HarnessService(SequencePlanner([command]), ControlledToolRegistry()).run(_request())
    assert result.status == HarnessStatus.CLARIFICATION_REQUIRED
    assert result.trace == []


def test_explicit_asset_call_is_forced_through_active_asset_search() -> None:
    ai = SequencePlanner([HarnessPlannerCommand(type=HarnessCommandType.FINISH, message="explore")])
    planner = PolicyHarnessPlanner(ai)
    command = planner.plan(_request(question="@准时到货率 分析上个月"), [])
    assert command.call is not None
    assert command.call.tool == HarnessToolName.SEARCH_ASSETS


def test_explicit_asset_uses_deterministic_inspect_execute_flow() -> None:
    class PlannerThatMustNotRun:
        def plan(self, request: HarnessRequest, observations: list[HarnessObservation]) -> HarnessPlannerCommand:
            del request, observations
            raise AssertionError("explicit asset orchestration must not call the AI planner")

    planner = PolicyHarnessPlanner(PlannerThatMustNotRun())
    search = HarnessObservation(
        ok=True,
        summary="found",
        data={
            "tool": "search_assets",
            "explicit_reference": True,
            "assets": [{
                "asset_id": "asset:v1:enterprise_pack:sim:metric:avg_cost",
                "asset_type": "metric",
                "name": "仿真单均运输成本",
            }],
        },
    )
    inspect = HarnessObservation(
        ok=True,
        summary="inspected",
        data={"tool": "inspect_asset"},
    )
    executed = HarnessObservation(
        ok=True,
        summary="executed",
        data={"tool": "execute_metric", "columns": ["value"], "rows": [[128.5]]},
    )

    inspect_command = planner.plan(_request(question="@仿真单均运输成本 最近的"), [search])
    assert inspect_command.call and inspect_command.call.tool == HarnessToolName.INSPECT_ASSET
    execute_command = planner.plan(_request(question="@仿真单均运输成本 最近的"), [search, inspect])
    assert execute_command.call and execute_command.call.tool == HarnessToolName.EXECUTE_METRIC
    finished = planner.plan(_request(question="@仿真单均运输成本 最近的"), [search, inspect, executed])
    assert finished.type == HarnessCommandType.FINISH
    assert finished.result == executed.data
    assert "128.5" in str(finished.message)


def test_asset_execution_cannot_skip_search_and_binds_resolved_asset_id() -> None:
    direct_execute = HarnessPlannerCommand(
        type=HarnessCommandType.CALL_TOOL,
        call=HarnessToolCall(
            tool=HarnessToolName.EXECUTE_METRIC,
            arguments={"metric_name": "准时到货率"},
        ),
    )
    planner = PolicyHarnessPlanner(SequencePlanner([direct_execute, direct_execute]))
    first = planner.plan(_request(question="哪个供应商最好"), [])
    assert first.call and first.call.tool == HarnessToolName.SEARCH_ASSETS

    search = HarnessObservation(
        ok=True,
        summary="found",
        data={
            "tool": "search_assets",
            "assets": [{
                "asset_id": "asset:v1:official_pack:tms:metric:carrier_ontime_rate",
                "name": "准时到货率",
                "code": "carrier_ontime_rate",
            }],
        },
    )
    bound = planner.plan(_request(question="哪个供应商最好"), [search])
    assert bound.call
    assert bound.call.arguments["asset_id"] == "asset:v1:official_pack:tms:metric:carrier_ontime_rate"


def test_ai_finish_reuses_controlled_execution_evidence() -> None:
    ai = SequencePlanner([
        HarnessPlannerCommand(type=HarnessCommandType.FINISH, message="unused"),
        HarnessPlannerCommand(type=HarnessCommandType.FINISH, message="done"),
    ])
    planner = PolicyHarnessPlanner(ai)
    observation = HarnessObservation(
        ok=True,
        summary="executed",
        data={"tool": "execute_metric", "columns": ["VALUE"], "rows": [[3]]},
    )
    command = planner.plan(_request(), [observation])
    assert command.result == observation.data


def test_explicit_asset_match_keeps_attached_follow_up_condition_out_of_name() -> None:
    candidates = [
        {"name": "准时到货率", "code": "ontime_rate", "asset_id": "metric-general"},
        {"name": "承运商准时到货率", "code": "carrier_ontime_rate", "asset_id": "metric-carrier"},
    ]

    matched = _match_explicit_asset_candidates("准时到货率最好", candidates)

    assert [item["asset_id"] for item in matched] == ["metric-general"]


def test_context_rewrite_cannot_invent_a_forced_asset_trigger() -> None:
    assert _remove_inferred_asset_triggers(
        "哪个供应商最好，哪个最差",
        "@准时到货率 上个月按供应商比较最好和最差",
    ) == "准时到货率 上个月按供应商比较最好和最差"
    assert _remove_inferred_asset_triggers(
        "@准时到货率 哪个供应商最好",
        "@准时到货率 按供应商比较",
    ) == "@准时到货率 按供应商比较"


def test_context_rewrite_can_preserve_the_same_previous_asset() -> None:
    assert _remove_inferred_asset_triggers(
        "按承运商看哪个最高",
        "@仿真单均运输成本 最近七天按承运商比较最高",
        "@仿真单均运输成本",
    ) == "@仿真单均运输成本 最近七天按承运商比较最高"
    assert _remove_inferred_asset_triggers(
        "按承运商看哪个最高",
        "/仿真承运商履约分析 最近七天",
        "@仿真单均运输成本",
    ) == "仿真承运商履约分析 最近七天"


def test_long_running_report_tool_gets_extended_budget() -> None:
    registry = ControlledToolRegistry()
    registry.register(
        HarnessToolName.EXECUTE_REPORT,
        lambda request, args: (sleep(0.2), HarnessObservation(ok=True, summary="报表已生成", data={"ok": True}))[1],
    )
    # per_tool_timeout 50ms and max_elapsed 100ms would both fail a 200ms tool;
    # report generation is a long-running artifact tool and gets its own budget.
    result = HarnessService(SequencePlanner([
        _call(HarnessToolName.EXECUTE_REPORT),
        _finish(),
    ]), registry).run(
        _request(budget=HarnessBudgetLimits(per_tool_timeout_ms=50, max_elapsed_ms=100))
    )
    assert result.status == HarnessStatus.COMPLETED
    assert result.trace[0].observation is not None and result.trace[0].observation.ok
