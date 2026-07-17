from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import re
from threading import Lock
from time import monotonic
from typing import Any, Callable, Protocol, runtime_checkable
from uuid import uuid4

from sq_bi_contracts.harness import (
    HarnessBudgetUsage,
    HarnessCommandType,
    HarnessConfirmation,
    HarnessFailure,
    HarnessFailureCode,
    HarnessObservation,
    HarnessPlannerCommand,
    HarnessRequest,
    HarnessResult,
    HarnessStatus,
    HarnessToolCall,
    HarnessToolName,
    HarnessTraceStep,
)


# Deep-analysis tools structurally cannot fit the interactive per-tool budget:
# report execution runs bound data queries plus a long-form LLM render, and
# skill execution plans inside a bounded self-repair loop where each repair
# round is another planner call. Both are explicit asset invocations, so they
# get their own timeout ceiling and their runtime is credited back instead of
# consuming the conversational deadline.
_LONG_RUNNING_TOOLS = frozenset({
    HarnessToolName.EXECUTE_REPORT,
    HarnessToolName.EXECUTE_SKILL,
})
_LONG_RUNNING_TOOL_TIMEOUT_MS = 240_000


@runtime_checkable
class HarnessPlanner(Protocol):
    def plan(
        self,
        request: HarnessRequest,
        observations: list[HarnessObservation],
    ) -> HarnessPlannerCommand: ...


class JsonHarnessPlanner:
    """Adapter for planners returning JSON. Validation keeps output non-executable."""

    def __init__(self, generate: Callable[[HarnessRequest, list[HarnessObservation]], str]) -> None:
        self._generate = generate

    def plan(
        self,
        request: HarnessRequest,
        observations: list[HarnessObservation],
    ) -> HarnessPlannerCommand:
        raw = self._generate(request, observations)
        return HarnessPlannerCommand.model_validate_json(raw)


class PolicyHarnessPlanner:
    """AI planner with deterministic enforcement only at product safety boundaries."""

    def __init__(self, planner: HarnessPlanner, fallback: HarnessPlanner | None = None) -> None:
        self._planner = planner
        self._fallback = fallback

    def plan(
        self,
        request: HarnessRequest,
        observations: list[HarnessObservation],
    ) -> HarnessPlannerCommand:
        search = next(
            (item for item in observations if item.data.get("tool") == "search_assets"),
            None,
        )
        if search is None and re.search(r"[@/#][^\s，,。！？!?]+", request.question):
            return _call(HarnessToolName.SEARCH_ASSETS, {"query": request.question})
        if search and search.data.get("explicit_reference") and search.data.get("unavailable"):
            return HarnessPlannerCommand(
                type=HarnessCommandType.FINISH,
                message=str(search.data.get("unavailable_message") or "显式引用的资产当前不可用。"),
                result={"asset_unavailable": True, **search.data},
            )
        # An explicit asset reference has already made the routing decision. Keep the
        # controlled inspect -> execute path deterministic instead of asking the LLM
        # to rediscover the next tool at every step. The LLM still binds business
        # parameters inside the execution tool; only orchestration overhead is removed.
        if search and search.data.get("explicit_reference"):
            assets = list(search.data.get("assets") or [])
            if assets:
                selected = assets[0]
                asset_id = str(selected.get("asset_id") or "")
                tools = [item.data.get("tool") for item in observations]
                if HarnessToolName.INSPECT_ASSET.value not in tools:
                    return _call(HarnessToolName.INSPECT_ASSET, {"asset_id": asset_id})
                execute_tool = {
                    "skill": HarnessToolName.EXECUTE_SKILL,
                    "report": HarnessToolName.EXECUTE_REPORT,
                }.get(str(selected.get("asset_type")), HarnessToolName.EXECUTE_METRIC)
                if execute_tool.value not in tools:
                    return _call(
                        execute_tool,
                        {"asset_id": asset_id, "question": request.question},
                        3,
                    )
                executed = next(
                    item for item in observations
                    if item.data.get("tool") == execute_tool.value
                )
                if executed.data.get("clarification_required"):
                    return HarnessPlannerCommand(
                        type=HarnessCommandType.CLARIFY,
                        message=executed.summary,
                    )
                if not executed.ok:
                    return HarnessPlannerCommand(
                        type=HarnessCommandType.FINISH,
                        message=executed.summary,
                        result={"execution_failed": True, **executed.data},
                    )
                return HarnessPlannerCommand(
                    type=HarnessCommandType.FINISH,
                    message=_execution_message(executed, str(selected.get("name") or "该资产")),
                    result=executed.data,
                )
        try:
            command = self._planner.plan(request, observations)
            asset_tools = {
                HarnessToolName.INSPECT_ASSET,
                HarnessToolName.EXECUTE_METRIC,
                HarnessToolName.EXECUTE_SKILL,
                HarnessToolName.EXECUTE_REPORT,
            }
            if command.call and command.call.tool in asset_tools and search is None:
                return _call(HarnessToolName.SEARCH_ASSETS, {"query": request.question})
            if command.call and command.call.tool in asset_tools and search is not None:
                arguments = dict(command.call.arguments)
                if not str(arguments.get("asset_id") or "").strip():
                    assets = list(search.data.get("assets") or [])
                    requested_name = str(
                        arguments.get("metric_name")
                        or arguments.get("skill_name")
                        or arguments.get("report_name")
                        or arguments.get("name")
                        or ""
                    ).strip().lower()
                    selected = next(
                        (
                            asset for asset in assets
                            if requested_name and requested_name in {
                                str(asset.get("name") or "").strip().lower(),
                                str(asset.get("code") or "").strip().lower(),
                            }
                        ),
                        assets[0] if assets else None,
                    )
                    if selected and selected.get("asset_id"):
                        arguments["asset_id"] = selected["asset_id"]
                        command = command.model_copy(update={
                            "call": command.call.model_copy(update={"arguments": arguments})
                        })
            if command.type == HarnessCommandType.FINISH and not command.result:
                decisive = next(
                    (
                        item for item in reversed(observations)
                        if item.ok and item.data.get("tool") in {
                            HarnessToolName.EXECUTE_METRIC.value,
                            HarnessToolName.EXECUTE_SKILL.value,
                            HarnessToolName.EXECUTE_REPORT.value,
                            HarnessToolName.EXPLORE_FIELDS.value,
                        }
                    ),
                    None,
                )
                if decisive is not None:
                    command = command.model_copy(update={"result": decisive.data})
            return command
        except Exception:
            if self._fallback is None:
                raise
            return self._fallback.plan(request, observations)


class DeterministicHarnessPlanner:
    """Safe default planner for the common search then execute flow."""

    def plan(
        self,
        request: HarnessRequest,
        observations: list[HarnessObservation],
    ) -> HarnessPlannerCommand:
        if not observations:
            return _call(HarnessToolName.RESOLVE_SCOPE)
        tools = [item.data.get("tool") for item in observations]
        if "search_assets" not in tools:
            return _call(HarnessToolName.SEARCH_ASSETS, {"query": request.question})
        search = next(item for item in observations if item.data.get("tool") == "search_assets")
        assets = search.data.get("assets") or []
        if search.data.get("explicit_reference") and search.data.get("unavailable"):
            return HarnessPlannerCommand(
                type=HarnessCommandType.FINISH,
                message=str(search.data.get("unavailable_message") or "显式引用的资产当前不可用。"),
                result={"asset_unavailable": True, **search.data},
            )
        if assets:
            selected = assets[0]
            asset_id = str(selected.get("asset_id") or selected.get("asset_ref") or "")
            if "inspect_asset" not in tools:
                return _call(HarnessToolName.INSPECT_ASSET, {"asset_id": asset_id})
            execute_tool = {
                "skill": HarnessToolName.EXECUTE_SKILL,
                "report": HarnessToolName.EXECUTE_REPORT,
            }.get(str(selected.get("asset_type")), HarnessToolName.EXECUTE_METRIC)
            if execute_tool.value not in tools:
                return _call(execute_tool, {"asset_id": asset_id, "question": request.question}, 3)
            executed = next(item for item in observations if item.data.get("tool") == execute_tool.value)
            if executed.data.get("clarification_required"):
                return HarnessPlannerCommand(
                    type=HarnessCommandType.CLARIFY,
                    message=executed.summary,
                )
            if not executed.ok:
                return HarnessPlannerCommand(
                    type=HarnessCommandType.FINISH,
                    message=executed.summary,
                    result={"execution_failed": True, **executed.data},
                )
            return HarnessPlannerCommand(
                type=HarnessCommandType.FINISH,
                message=executed.summary,
                result=executed.data,
            )
        if "lookup_semantic_gap" not in tools:
            return _call(HarnessToolName.LOOKUP_SEMANTIC_GAP, {"query": request.question})
        if "explore_fields" not in tools:
            return _call(HarnessToolName.EXPLORE_FIELDS, {"question": request.question}, 3)
        explored = next(item for item in observations if item.data.get("tool") == "explore_fields")
        if not explored.ok:
            return HarnessPlannerCommand(
                type=HarnessCommandType.CLARIFY,
                message=explored.summary,
            )
        if "保存" in request.question or "save" in request.question.lower():
            return _call(
                HarnessToolName.SAVE_PERSONAL_ASSET,
                {"proposal": explored.data, "question": request.question},
                2,
            )
        return HarnessPlannerCommand(
            type=HarnessCommandType.FINISH,
            message=explored.summary,
            result=explored.data,
        )


def _call(
    tool: HarnessToolName,
    arguments: dict[str, Any] | None = None,
    cost: int = 1,
) -> HarnessPlannerCommand:
    return HarnessPlannerCommand(
        type=HarnessCommandType.CALL_TOOL,
        call=HarnessToolCall(tool=tool, arguments=arguments or {}, cost_units=cost),
    )


def _execution_message(observation: HarnessObservation, asset_name: str) -> str:
    columns = list(observation.data.get("columns") or [])
    rows = list(observation.data.get("rows") or [])
    views = observation.data.get("views")
    if isinstance(views, list) and views:
        titles = [str(item.get("title") or "分析视图") for item in views if isinstance(item, dict)]
        return f"已基于“{asset_name}”完成{'、'.join(titles)}。"
    ranking = observation.data.get("ranking")
    if isinstance(ranking, dict) and rows:
        row = rows[0]
        values = list(row.values()) if isinstance(row, dict) else list(row)
        if len(values) >= 2:
            qualifier = "最高" if ranking.get("direction") == "desc" else "最低"
            return f"{asset_name}{qualifier}的是 **{values[0]}**，结果为 **{values[-1]}**。"
    if len(columns) == 1 and len(rows) == 1:
        row = rows[0]
        value = next(iter(row.values()), None) if isinstance(row, dict) else (row[0] if row else None)
        if value is not None:
            return f"{asset_name}：**{value}**"
    return f"已完成“{asset_name}”的确定性查询，结果如下。"


ToolHandler = Callable[[HarnessRequest, dict[str, Any]], HarnessObservation]


class ControlledToolRegistry:
    def __init__(self) -> None:
        self._handlers: dict[HarnessToolName, ToolHandler] = {}

    def register(self, name: HarnessToolName, handler: ToolHandler) -> None:
        self._handlers[name] = handler

    def invoke(
        self,
        call: HarnessToolCall,
        request: HarnessRequest,
    ) -> HarnessObservation:
        handler = self._handlers.get(call.tool)
        if handler is None:
            return HarnessObservation(
                ok=False,
                summary="Tool is not registered.",
                failure_code=HarnessFailureCode.UNKNOWN_TOOL,
            )
        required = f"harness:{call.tool.value}"
        if request.permissions and required not in request.permissions and "harness:*" not in request.permissions:
            return HarnessObservation(
                ok=False,
                summary="Permission denied.",
                failure_code=HarnessFailureCode.PERMISSION_DENIED,
            )
        observation = handler(request, call.arguments)
        return observation.model_copy(update={"data": {**observation.data, "tool": call.tool.value}})


@dataclass
class _ConfirmationEntry:
    user_id: str
    operation_digest: str
    expires_at: datetime
    operation: dict[str, Any]
    consumed: bool = False


class ConfirmationStore:
    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, _ConfirmationEntry] = {}
        self._lock = Lock()

    @staticmethod
    def digest(operation: dict[str, Any]) -> str:
        payload = json.dumps(operation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode()).hexdigest()

    def issue(self, user_id: str, operation: dict[str, Any]) -> HarnessConfirmation:
        token = "hcf_" + uuid4().hex
        digest = self.digest(operation)
        expiry = datetime.now(UTC) + timedelta(seconds=self._ttl)
        with self._lock:
            self._entries[token] = _ConfirmationEntry(user_id, digest, expiry, operation)
        return HarnessConfirmation(
            token=token,
            operation_digest=digest,
            prompt="确认将当前探索保存为个人资产？",
            expires_at=expiry,
        )

    def consume(self, token: str, user_id: str, operation: dict[str, Any]) -> bool:
        with self._lock:
            entry = self._entries.get(token)
            if (
                entry is None
                or entry.consumed
                or entry.expires_at <= datetime.now(UTC)
                or entry.user_id != user_id
                or entry.operation_digest != self.digest(operation)
            ):
                return False
            entry.consumed = True
            return True

    def consume_operation(self, token: str, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._entries.get(token)
            if (
                entry is None
                or entry.consumed
                or entry.expires_at <= datetime.now(UTC)
                or entry.user_id != user_id
            ):
                return None
            entry.consumed = True
            return entry.operation


class HarnessService:
    def __init__(
        self,
        planner: HarnessPlanner,
        tools: ControlledToolRegistry,
        confirmations: ConfirmationStore | None = None,
    ) -> None:
        self._planner = planner
        self._tools = tools
        self._confirmations = confirmations or ConfirmationStore()

    def run(self, request: HarnessRequest) -> HarnessResult:
        run_id = request.continuation.run_id if request.continuation else "hrn_" + uuid4().hex
        started = monotonic()
        observations: list[HarnessObservation] = []
        trace: list[HarnessTraceStep] = []
        calls: set[str] = set()
        cost = 0
        long_tool_credit_ms = 0
        confirmation_token = request.continuation.confirmation_token if request.continuation else None
        if confirmation_token:
            operation = self._confirmations.consume_operation(
                confirmation_token, request.context.user_id
            )
            if operation is None:
                return self._failed(
                    run_id,
                    trace,
                    cost,
                    0,
                    HarnessFailureCode.CONFIRMATION_INVALID,
                    "Confirmation is invalid, expired, or consumed.",
                )
            call = HarnessToolCall(
                tool=HarnessToolName.SAVE_PERSONAL_ASSET,
                arguments=operation,
                cost_units=2,
            )
            observation = self._tools.invoke(call, request)
            trace.append(HarnessTraceStep(
                index=1,
                command=HarnessCommandType.CALL_TOOL,
                tool=call.tool,
                arguments=_redact(call.arguments),
                observation=observation,
                cost_units=call.cost_units,
            ))
            if not observation.ok:
                return self._failed(
                    run_id,
                    trace,
                    call.cost_units,
                    int((monotonic() - started) * 1000),
                    observation.failure_code or HarnessFailureCode.TOOL_FAILED,
                    observation.summary,
                )
            return HarnessResult(
                run_id=run_id,
                status=HarnessStatus.COMPLETED,
                answer=observation.summary,
                result=observation.data,
                trace=trace,
                budget=HarnessBudgetUsage(
                    steps=1,
                    elapsed_ms=int((monotonic() - started) * 1000),
                    cost_units=call.cost_units,
                ),
                provenance={"tools": [HarnessToolName.SAVE_PERSONAL_ASSET.value]},
            )
        while True:
            elapsed = int((monotonic() - started) * 1000)
            if len(trace) >= request.budget.max_steps:
                return self._failed(run_id, trace, cost, elapsed, HarnessFailureCode.STEP_LIMIT, "Harness step limit reached.")
            if elapsed - long_tool_credit_ms >= request.budget.max_elapsed_ms:
                return self._failed(run_id, trace, cost, elapsed, HarnessFailureCode.DEADLINE_EXCEEDED, "Harness deadline exceeded.")
            try:
                command = self._planner.plan(request, observations)
            except Exception as exc:  # noqa: BLE001
                return self._failed(run_id, trace, cost, elapsed, HarnessFailureCode.INVALID_PLAN, str(exc))
            if command.type == HarnessCommandType.FINISH:
                result = command.result or {}
                if observations and not observations[-1].ok:
                    latest = observations[-1]
                    return self._failed(
                        run_id,
                        trace,
                        cost,
                        elapsed,
                        latest.failure_code or HarnessFailureCode.TOOL_FAILED,
                        command.message or latest.summary,
                    )
                if result.get("asset_unavailable"):
                    return self._failed(
                        run_id,
                        trace,
                        cost,
                        elapsed,
                        HarnessFailureCode.ASSET_UNAVAILABLE,
                        command.message or "显式引用的资产当前不可用。",
                    )
                result_provenance = result.get("provenance")
                return HarnessResult(
                    run_id=run_id,
                    status=HarnessStatus.COMPLETED,
                    answer=command.message,
                    result=result,
                    trace=trace,
                    budget=HarnessBudgetUsage(steps=len(trace), elapsed_ms=elapsed, cost_units=cost),
                    provenance={
                        "tools": [step.tool.value for step in trace if step.tool],
                        **(result_provenance if isinstance(result_provenance, dict) else {}),
                        **({"session_id": request.session_id} if request.session_id else {}),
                    },
                )
            if command.type == HarnessCommandType.CLARIFY:
                return HarnessResult(
                    run_id=run_id,
                    status=HarnessStatus.CLARIFICATION_REQUIRED,
                    clarification=command.message or "请补充必要信息。",
                    trace=trace,
                    budget=HarnessBudgetUsage(steps=len(trace), elapsed_ms=elapsed, cost_units=cost),
                )
            if command.type != HarnessCommandType.CALL_TOOL or command.call is None:
                return self._failed(run_id, trace, cost, elapsed, HarnessFailureCode.INVALID_PLAN, "Unsupported planner command.")
            call = command.call
            fingerprint = sha256(call.model_dump_json().encode()).hexdigest()
            if fingerprint in calls:
                return self._failed(run_id, trace, cost, elapsed, HarnessFailureCode.DUPLICATE_CALL, "Duplicate tool call rejected.")
            if cost + call.cost_units > request.budget.max_cost_units:
                return self._failed(run_id, trace, cost, elapsed, HarnessFailureCode.COST_LIMIT, "Harness cost limit reached.")
            if call.tool == HarnessToolName.SAVE_PERSONAL_ASSET:
                confirmation = self._confirmations.issue(request.context.user_id, call.arguments)
                return HarnessResult(
                    run_id=run_id,
                    status=HarnessStatus.CONFIRMATION_REQUIRED,
                    confirmation=confirmation,
                    trace=trace,
                    budget=HarnessBudgetUsage(steps=len(trace), elapsed_ms=elapsed, cost_units=cost),
                )
            calls.add(fingerprint)
            tool_started = monotonic()
            tool_timeout_ms = request.budget.per_tool_timeout_ms
            if call.tool in _LONG_RUNNING_TOOLS:
                tool_timeout_ms = max(tool_timeout_ms, _LONG_RUNNING_TOOL_TIMEOUT_MS)
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(self._tools.invoke, call, request)
            try:
                observation = future.result(timeout=tool_timeout_ms / 1000)
            except FutureTimeout as exc:
                # ``concurrent.futures.TimeoutError`` is an alias of the built-in
                # ``TimeoutError``. A controlled tool may therefore finish by
                # raising its own timeout (for example an LLM client deadline),
                # which must not be mistaken for this outer Harness deadline.
                if future.done():
                    executor.shutdown(wait=False, cancel_futures=True)
                    observation = HarnessObservation(
                        ok=False,
                        summary=str(exc) or "Controlled tool dependency timed out.",
                        failure_code=HarnessFailureCode.TOOL_FAILED,
                        data={"tool": call.tool.value},
                    )
                else:
                    future.cancel()
                    executor.shutdown(wait=False, cancel_futures=True)
                    return self._failed(run_id, trace, cost, int((monotonic() - started) * 1000), HarnessFailureCode.TOOL_TIMEOUT, "Controlled tool timed out.")
            except Exception as exc:  # noqa: BLE001
                executor.shutdown(wait=False, cancel_futures=True)
                observation = HarnessObservation(
                    ok=False,
                    summary=str(exc),
                    failure_code=HarnessFailureCode.TOOL_FAILED,
                    data={"tool": call.tool.value},
                )
            else:
                executor.shutdown(wait=True)
            duration = int((monotonic() - tool_started) * 1000)
            if call.tool in _LONG_RUNNING_TOOLS:
                long_tool_credit_ms += duration
            cost += call.cost_units
            trace.append(HarnessTraceStep(
                index=len(trace) + 1,
                command=HarnessCommandType.CALL_TOOL,
                tool=call.tool,
                arguments=_redact(call.arguments),
                observation=observation,
                duration_ms=duration,
                cost_units=call.cost_units,
            ))
            observations.append(observation)
            if not observation.ok and observation.failure_code in {
                HarnessFailureCode.PERMISSION_DENIED,
                HarnessFailureCode.UNKNOWN_TOOL,
                HarnessFailureCode.ASSET_UNAVAILABLE,
            }:
                return self._failed(run_id, trace, cost, int((monotonic() - started) * 1000), observation.failure_code, observation.summary)

    @staticmethod
    def _failed(
        run_id: str,
        trace: list[HarnessTraceStep],
        cost: int,
        elapsed: int,
        code: HarnessFailureCode,
        message: str,
    ) -> HarnessResult:
        return HarnessResult(
            run_id=run_id,
            status=HarnessStatus.FAILED,
            trace=trace,
            budget=HarnessBudgetUsage(steps=len(trace), elapsed_ms=elapsed, cost_units=cost),
            failure=HarnessFailure(code=code, message=message, step=len(trace) + 1),
        )


def _redact(value: dict[str, Any]) -> dict[str, Any]:
    secret_parts = ("password", "token", "secret", "credential", "sql")
    return {
        key: "***" if any(part in key.lower() for part in secret_parts) else item
        for key, item in value.items()
    }
