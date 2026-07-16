from __future__ import annotations

from pathlib import Path

from sq_bi_contracts.assets import AssetKey, AssetRef
from sq_bi_contracts.enterprise_pack import CreateEnterprisePackRequest
from sq_bi_contracts.enums import AssetSourceType, AssetType, MetricVisibility
from sq_bi_contracts.metrics import MetricDefinition, MetricFormula
from sq_bi_contracts.personal_assets import ConfirmPromotionRequest, PersonalAssetScope, PromotionPreviewRequest
from sq_bi_runtime.enterprise_pack_store import EnterprisePackStore
from sq_bi_runtime.personal_asset_store import PersonalAssetStore, new_personal_record
from sq_bi_runtime.promotion_service import PersonalAssetPromotionService


class ProductRepo:
    def __init__(self, ref: AssetRef) -> None:
        self.metric = MetricDefinition(
            metric_code=ref.asset.local_code,
            name="Order count",
            definition="Orders",
            visibility=MetricVisibility.PRIVATE,
            formula=MetricFormula(expression="SELECT COUNT(ID) FROM ORDERS"),
            data_source_id="ds1",
            owner="u1",
            asset_ref=ref,
        )

    def get_metric_by_ref(self, asset_ref: AssetRef):
        return self.metric if asset_ref == self.metric.asset_ref else None

    def get_skill_by_ref(self, asset_ref: AssetRef):
        return None

    def get_report_by_ref(self, asset_ref: AssetRef):
        return None


def _ref() -> AssetRef:
    return AssetRef(
        asset=AssetKey(
            source_type=AssetSourceType.PERSONAL_WORKSPACE,
            source_id="u1",
            asset_type=AssetType.METRIC,
            local_code="order_count",
        ),
        version="1.0.0",
    )


def test_preview_generates_candidates_and_confirm_keeps_source(tmp_path: Path) -> None:
    personal = PersonalAssetStore(tmp_path / "personal.sqlite3")
    enterprise = EnterprisePackStore(tmp_path / "enterprise.sqlite3")
    pack = enterprise.create(
        CreateEnterprisePackRequest(name="Ops", created_by="u1")
    )
    ref = _ref()
    source = new_personal_record(
        asset_ref=ref,
        name="Order count",
        owner_user_id="u1",
        scope=PersonalAssetScope(
            workspace_id="u1",
            data_source_id="ds1",
            physical_tables=["ORDERS"],
            physical_fields=["ORDERS.ID"],
        ),
    )
    personal.save_asset(source)
    service = PersonalAssetPromotionService(personal, enterprise, ProductRepo(ref))
    request = PromotionPreviewRequest(
        workspace_id="u1", target_pack_id=pack.pack_id, asset_refs=[ref], requested_by="u1"
    )
    preview = service.preview(request)
    assert preview.eligible
    assert preview.standard_fields[0].physical_column == "ID"

    promotion = service.confirm(ConfirmPromotionRequest(**request.model_dump()))
    assert promotion.source_refs == [ref]
    assert personal.get_asset(ref, workspace_id="u1") == source
    updated = enterprise.get(pack.pack_id)
    assert updated is not None and updated.draft.metrics[0].metric_code == "order_count"


def test_unauthorized_workspace_preview_is_ineligible(tmp_path: Path) -> None:
    personal = PersonalAssetStore(tmp_path / "personal.sqlite3")
    enterprise = EnterprisePackStore(tmp_path / "enterprise.sqlite3")
    pack = enterprise.create(CreateEnterprisePackRequest(name="Ops"))
    service = PersonalAssetPromotionService(personal, enterprise, ProductRepo(_ref()))
    preview = service.preview(
        PromotionPreviewRequest(
            workspace_id="u2", target_pack_id=pack.pack_id, asset_refs=[_ref()], requested_by="u1"
        )
    )
    assert not preview.eligible
    assert {item.code for item in preview.conflicts} >= {"WORKSPACE_FORBIDDEN", "ASSET_NOT_FOUND"}
