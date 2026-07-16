from __future__ import annotations

import pytest
from pydantic import ValidationError

from sq_bi_contracts.assets import AssetKey, AssetRef
from sq_bi_contracts.enums import AssetSourceType, AssetType
from sq_bi_contracts.personal_assets import (
    AssetDependencyGraph,
    PersonalAssetScope,
    PromotionPreviewRequest,
)


def _ref(code: str, version: str = "1.0.0") -> AssetRef:
    return AssetRef(
        asset=AssetKey(
            source_type=AssetSourceType.PERSONAL_WORKSPACE,
            source_id="u1",
            asset_type=AssetType.METRIC,
            local_code=code,
        ),
        version=version,
    )


def test_dependency_graph_rejects_direct_cycle() -> None:
    ref = _ref("orders")
    with pytest.raises(ValidationError, match="self cycle"):
        AssetDependencyGraph(
            asset_ref=ref,
            dependency_refs=[ref],
            effective_scope=PersonalAssetScope(
                workspace_id="u1", data_source_id="ds1"
            ),
        )


def test_promotion_request_preserves_exact_versions() -> None:
    request = PromotionPreviewRequest(
        workspace_id="u1",
        target_pack_id="ep1",
        asset_refs=[_ref("orders", "2.1.0")],
        requested_by="u1",
    )
    assert request.asset_refs[0].version == "2.1.0"
