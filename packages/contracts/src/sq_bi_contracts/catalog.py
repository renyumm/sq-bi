from __future__ import annotations

from pydantic import Field

from .common import ContractModel
from .enums import DatabaseType


class DataSource(ContractModel):
    data_source_id: str
    name: str
    database_type: DatabaseType
    connection_alias: str
    is_read_only: bool = True
    owner: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)


class SemanticTable(ContractModel):
    table_id: str
    data_source_id: str
    physical_name: str
    business_name: str
    description: str
    owner: str | None = None
    tags: list[str] = Field(default_factory=list)


class SemanticField(ContractModel):
    field_id: str
    table_id: str
    physical_name: str
    business_name: str
    data_type: str
    description: str | None = None
    enum_values: dict[str, str] = Field(default_factory=dict)
    sensitivity_level: str = "normal"
    is_dimension: bool = False
    is_measure: bool = False
