from __future__ import annotations

from pydantic import Field

from .common import ContractModel


class PackDependency(ContractModel):
    pack_id: str
    version_spec: str
    optional: bool = False


class PackAsset(ContractModel):
    path: str
    asset_type: str
    description: str | None = None


class PackStandardField(ContractModel):
    """A standard field declaration inside a domain pack manifest."""

    field_id: str
    business_name: str
    data_type: str  # DataType enum value
    description: str | None = None
    enum_values: list[str] = Field(default_factory=list)
    required: bool = False


class DomainPackManifest(ContractModel):
    pack_id: str
    namespace: str
    name: str
    version: str = "1.0.0"
    description: str | None = None
    author: str | None = None
    min_engine_version: str | None = None
    dependencies: list[PackDependency] = Field(default_factory=list)
    assets: list[PackAsset] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    # Standard-field layer support (task 7.1)
    standard_fields: list[PackStandardField] = Field(default_factory=list)


class PackLoadResult(ContractModel):
    pack_id: str
    success: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
