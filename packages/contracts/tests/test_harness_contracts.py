from __future__ import annotations

import pytest
from pydantic import ValidationError

from sq_bi_contracts import API_ROUTES
from sq_bi_contracts.harness import (
    HarnessCommandType,
    HarnessPlannerCommand,
    HarnessRequest,
    HarnessToolCall,
    HarnessToolName,
)
from sq_bi_contracts.runtime_projection import RuntimeRequestContext


def test_harness_request_round_trip_and_route() -> None:
    request = HarnessRequest(
        question="查询运输收入",
        context=RuntimeRequestContext(user_id="u1", data_source_id="ds1"),
        permissions=["harness:*"],
    )
    assert HarnessRequest.model_validate_json(request.model_dump_json()) == request
    assert any(route.path == "/api/v1/query/harness" for route in API_ROUTES)


def test_harness_command_shape_and_sql_are_rejected() -> None:
    with pytest.raises(ValidationError):
        HarnessPlannerCommand(type=HarnessCommandType.CALL_TOOL)
    with pytest.raises(ValidationError):
        HarnessToolCall(
            tool=HarnessToolName.EXPLORE_FIELDS,
            arguments={"sql": "select * from secrets"},
        )


def test_contract_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        HarnessRequest.model_validate({
            "question": "x",
            "context": {"user_id": "u", "data_source_id": "d"},
            "unexpected": True,
        })
