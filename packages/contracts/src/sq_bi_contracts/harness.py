from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from .common import ContractModel
from .runtime_projection import RuntimeRequestContext


class HarnessStatus(StrEnum):
    COMPLETED = "completed"
    CLARIFICATION_REQUIRED = "clarification_required"
    CONFIRMATION_REQUIRED = "confirmation_required"
    FAILED = "failed"


class HarnessCommandType(StrEnum):
    CALL_TOOL = "call_tool"
    FINISH = "finish"
    CLARIFY = "clarify"
    REQUEST_CONFIRMATION = "request_confirmation"


class HarnessToolName(StrEnum):
    RESOLVE_SCOPE = "resolve_scope"
    SEARCH_ASSETS = "search_assets"
    INSPECT_ASSET = "inspect_asset"
    EXECUTE_METRIC = "execute_metric"
    EXECUTE_SKILL = "execute_skill"
    EXECUTE_REPORT = "execute_report"
    EXPLORE_FIELDS = "explore_fields"
    LOOKUP_SEMANTIC_GAP = "lookup_semantic_gap"
    SAVE_PERSONAL_ASSET = "save_personal_asset"


class HarnessFailureCode(StrEnum):
    INVALID_PLAN = "invalid_plan"
    UNKNOWN_TOOL = "unknown_tool"
    DUPLICATE_CALL = "duplicate_call"
    PERMISSION_DENIED = "permission_denied"
    STEP_LIMIT = "step_limit"
    COST_LIMIT = "cost_limit"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    TOOL_TIMEOUT = "tool_timeout"
    CONFIRMATION_INVALID = "confirmation_invalid"
    TOOL_FAILED = "tool_failed"
    ASSET_UNAVAILABLE = "asset_unavailable"


class HarnessBudgetLimits(ContractModel):
    max_steps: int = Field(default=8, ge=1, le=20)
    max_elapsed_ms: int = Field(default=60_000, ge=100, le=120_000)
    # Runtime parameter binding is an LLM-backed controlled tool. Ten seconds was
    # shorter than normal production latency and caused healthy local DB queries to
    # be cancelled before execution.
    per_tool_timeout_ms: int = Field(default=45_000, ge=50, le=60_000)
    max_cost_units: int = Field(default=20, ge=1, le=100)


class HarnessBudgetUsage(ContractModel):
    steps: int = 0
    elapsed_ms: int = 0
    cost_units: int = 0


class HarnessContinuation(ContractModel):
    run_id: str
    clarification: str | None = None
    confirmation_token: str | None = None


class HarnessConversationTurn(ContractModel):
    role: Literal["user", "assistant", "system"]
    text: str


class HarnessRequest(ContractModel):
    question: str = Field(min_length=1)
    context: RuntimeRequestContext
    permissions: list[str] = Field(default_factory=list)
    execute: bool = True
    budget: HarnessBudgetLimits = Field(default_factory=HarnessBudgetLimits)
    continuation: HarnessContinuation | None = None
    session_id: str | None = None
    conversation: list[HarnessConversationTurn] = Field(default_factory=list)
    data_source_ids: list[str] = Field(default_factory=list)


class HarnessToolCall(ContractModel):
    tool: HarnessToolName
    arguments: dict[str, Any] = Field(default_factory=dict)
    cost_units: int = Field(default=1, ge=1, le=20)

    @model_validator(mode="after")
    def reject_sql(self) -> "HarnessToolCall":
        if any("sql" in str(key).lower() for key in self.arguments):
            raise ValueError("Harness tool arguments cannot contain SQL.")
        return self


class HarnessPlannerCommand(ContractModel):
    type: HarnessCommandType
    call: HarnessToolCall | None = None
    message: str | None = None
    result: dict[str, Any] | None = None

    @model_validator(mode="after")
    def command_shape(self) -> "HarnessPlannerCommand":
        if self.type == HarnessCommandType.CALL_TOOL and self.call is None:
            raise ValueError("call_tool requires call.")
        if self.type != HarnessCommandType.CALL_TOOL and self.call is not None:
            raise ValueError("Only call_tool accepts call.")
        return self


class HarnessObservation(ContractModel):
    ok: bool
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    failure_code: HarnessFailureCode | None = None


class HarnessTraceStep(ContractModel):
    index: int = Field(ge=1)
    command: HarnessCommandType
    tool: HarnessToolName | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    observation: HarnessObservation | None = None
    duration_ms: int = Field(default=0, ge=0)
    cost_units: int = Field(default=0, ge=0)


class HarnessConfirmation(ContractModel):
    token: str
    operation_digest: str
    prompt: str
    expires_at: datetime


class HarnessFailure(ContractModel):
    code: HarnessFailureCode
    message: str
    step: int | None = None


class HarnessResult(ContractModel):
    run_id: str
    status: HarnessStatus
    answer: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    clarification: str | None = None
    confirmation: HarnessConfirmation | None = None
    trace: list[HarnessTraceStep] = Field(default_factory=list)
    budget: HarnessBudgetUsage = Field(default_factory=HarnessBudgetUsage)
    failure: HarnessFailure | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
