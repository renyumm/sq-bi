from __future__ import annotations

from urllib.parse import quote

from pydantic import ConfigDict, Field, model_validator

from .common import ContractModel
from .enums import AssetSourceType, AssetType


def _asset_id_component(value: str) -> str:
    return quote(value, safe="-._~")


class AssetKey(ContractModel):
    """Stable identity for an asset, independent of any concrete version."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)

    source_type: AssetSourceType
    source_id: str = Field(min_length=1)
    asset_type: AssetType
    local_code: str = Field(min_length=1)
    asset_id: str = ""

    @model_validator(mode="after")
    def validate_asset_id(self) -> "AssetKey":
        expected = ":".join(
            (
                "asset",
                "v1",
                self.source_type.value,
                _asset_id_component(self.source_id),
                self.asset_type.value,
                _asset_id_component(self.local_code),
            )
        )
        if self.asset_id and self.asset_id != expected:
            raise ValueError("asset_id does not match the structured asset identity.")
        object.__setattr__(self, "asset_id", expected)
        return self


class AssetRef(ContractModel):
    """An exact, immutable reference to one version of an asset."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)

    asset: AssetKey
    version: str = Field(min_length=1)


class AssetDescriptor(ContractModel):
    asset_ref: AssetRef
    name: str
    description: str | None = None


class AssetQuery(ContractModel):
    source_types: list[AssetSourceType] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    asset_types: list[AssetType] = Field(default_factory=list)
    local_code: str | None = None
    version: str | None = None
