from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import ErrorCode

T = TypeVar("T")


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ApiError(ContractModel):
    code: ErrorCode
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ApiResponse(ContractModel, Generic[T]):
    request_id: str
    data: T | None = None
    error: ApiError | None = None

    @model_validator(mode="after")
    def exactly_one_payload(self) -> "ApiResponse[T]":
        has_data = self.data is not None
        has_error = self.error is not None
        if has_data == has_error:
            raise ValueError("ApiResponse requires exactly one of data or error.")
        return self


class PageRequest(ContractModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)


class Page(ContractModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=500)


class UserContext(ContractModel):
    user_id: str
    display_name: str
    org_id: str
    org_name: str | None = None
    role_ids: list[str] = Field(default_factory=list)
    data_scope: dict[str, list[str]] = Field(default_factory=dict)
    locale: str = "zh-CN"
    timezone: str = "Asia/Shanghai"


class TimeRange(ContractModel):
    start: datetime | None = None
    end: datetime | None = None
    grain: str | None = None
    label: str | None = None
