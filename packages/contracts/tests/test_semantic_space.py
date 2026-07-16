from sq_bi_contracts.field_mount import CreateDeploymentRequest, DeploymentInstance
from sq_bi_contracts.query import QueryResult
from sq_bi_contracts.semantic_profile import (
    CatalogColumnRecord,
    CatalogOverview,
    CatalogTableRecord,
    FieldOrigin,
    FieldStatus,
    SemanticFieldAdjustment,
    SemanticField,
    SemanticSpace,
    SemanticSpaceAdjustment,
    SemanticSpaceVersionState,
    TableRecommendation,
)
from sq_bi_contracts.semantic_space import (
    ChangedFieldEntry,
    CreateSemanticSpaceRequest,
    GapLookupRequest,
    PublishSemanticSpaceRequest,
    SemanticGapCandidate,
    SemanticSpaceDiff,
)


def _field(field_id: str = "field_1", status: FieldStatus | None = None) -> SemanticField:
    return SemanticField(
        field_id=field_id,
        entity_id="ent_1",
        physical_table="orders",
        physical_column="coupon_discount",
        business_name="优惠券抵扣金额",
        origin=FieldOrigin.inferred,
        status=status,
    )


def test_semantic_space_versioning_overlay_is_optional() -> None:
    space = SemanticSpace(space_id="space_1", snapshot_id="snap_1", name="TMS")
    assert space.version is None
    assert space.version_state is None

    published = space.model_copy(
        update={
            "version": 2,
            "version_state": SemanticSpaceVersionState.published,
            "published_at": "2026-07-06T00:00:00Z",
        }
    )
    assert published.version_state == SemanticSpaceVersionState.published
    dumped = published.model_dump(mode="json")
    assert dumped["version_state"] == "published"


def test_semantic_field_status_round_trip() -> None:
    field = _field(status=FieldStatus.confirmed)
    dumped = field.model_dump(mode="json")
    assert dumped["status"] == "confirmed"
    restored = SemanticField.model_validate(dumped)
    assert restored.status == FieldStatus.confirmed


def test_semantic_space_adjustment_serializes_field_statuses() -> None:
    adjustment = SemanticSpaceAdjustment(
        space_id="space_1",
        accepted=True,
        field_statuses={"field_1": FieldStatus.excluded},
    )
    dumped = adjustment.model_dump(mode="json")
    assert dumped["field_statuses"] == {"field_1": "excluded"}


def test_semantic_space_adjustment_serializes_field_updates() -> None:
    adjustment = SemanticSpaceAdjustment(
        space_id="space_1",
        accepted=True,
        field_updates={
            "field_1": SemanticFieldAdjustment(
                business_name="优惠金额",
                description="订单优惠券抵扣金额",
                semantic_role="measure",
                default_aggregation="sum",
                synonyms=["优惠券", "抵扣"],
            )
        },
    )
    dumped = adjustment.model_dump(mode="json")
    assert dumped["field_updates"]["field_1"]["business_name"] == "优惠金额"
    assert dumped["field_updates"]["field_1"]["synonyms"] == ["优惠券", "抵扣"]


def test_create_semantic_space_request_serialization() -> None:
    req = CreateSemanticSpaceRequest(
        data_source_id="ds_1", name="TMS 运输执行", initial_tables=["orders", "shipments"]
    )
    dumped = req.model_dump(mode="json")
    assert dumped["initial_tables"] == ["orders", "shipments"]


def test_semantic_space_diff_serialization() -> None:
    diff = SemanticSpaceDiff(
        space_id="space_1",
        new_fields=[_field("field_new")],
        removed_fields=[],
        changed_fields=[
            ChangedFieldEntry(
                field_id="field_1",
                before={"business_name": "配送状态"},
                after={"business_name": "订单配送状态码"},
            )
        ],
        invalidated_fields=[],
    )
    dumped = diff.model_dump(mode="json")
    assert dumped["new_fields"][0]["field_id"] == "field_new"
    assert dumped["changed_fields"][0]["after"]["business_name"] == "订单配送状态码"


def test_publish_semantic_space_request_defaults() -> None:
    req = PublishSemanticSpaceRequest()
    assert req.confirmed_suggestions == []
    assert req.published_by == "system"


def test_semantic_gap_candidate_serialization() -> None:
    candidate = SemanticGapCandidate(
        field_id="field_ord_coupon",
        physical_table="orders",
        physical_column="coupon_discount",
        business_name="优惠券抵扣金额",
        suggested_reason="用户提问提及了优惠券折扣",
        confidence=0.92,
    )
    dumped = candidate.model_dump(mode="json")
    assert dumped["suggested_reason"]
    assert dumped["confidence"] == 0.92


def test_gap_lookup_request_serialization() -> None:
    req = GapLookupRequest(connection_id="ds_1", query="优惠券折扣是多少")
    assert req.connection_id == "ds_1"


def test_query_result_gap_candidates_default_empty_and_additive() -> None:
    result = QueryResult(
        query_id="qry_1",
        audit_id="aud_1",
        columns=["a"],
        rows=[[1]],
        chart_suggestion={"chart_type": "table", "title": "t"},
        lineage={"lineage_id": "lin_1", "source_system": "sq-bi", "data_source_id": "ds_1"},
    )
    assert result.gap_candidates == []

    with_gap = result.model_copy(
        update={
            "gap_candidates": [
                SemanticGapCandidate(
                    field_id="field_ord_coupon",
                    physical_table="orders",
                    physical_column="coupon_discount",
                    business_name="优惠券抵扣金额",
                    suggested_reason="匹配用户提问",
                )
            ]
        }
    )
    assert len(with_gap.gap_candidates) == 1


def test_deployment_semantic_space_ids_additive_backward_compatible() -> None:
    legacy = CreateDeploymentRequest(pack_id="pack_1", data_source_id="ds_1")
    assert legacy.semantic_space_ids == []

    scoped = CreateDeploymentRequest(
        pack_id="pack_1", data_source_id="ds_1", semantic_space_ids=["space_1", "space_2"]
    )
    assert scoped.semantic_space_ids == ["space_1", "space_2"]

    dep = DeploymentInstance(
        deployment_id="dep_1",
        pack_id="pack_1",
        pack_version="1.0.0",
        data_source_id="ds_1",
        semantic_space_ids=["space_1"],
    )
    assert dep.semantic_space_ids == ["space_1"]


def test_catalog_table_record_with_columns() -> None:
    table = CatalogTableRecord(
        schema_name="TMS",
        table_name="TMS_SHIPMENT",
        comment="运单表",
        classification=TableRecommendation.recommended_include,
        columns=[
            CatalogColumnRecord(
                table_name="TMS_SHIPMENT", column_name="CARRIER_NAME", data_type="VARCHAR2"
            )
        ],
    )
    dumped = table.model_dump(mode="json")
    assert dumped["columns"][0]["column_name"] == "CARRIER_NAME"
    assert dumped["excluded"] is False


def test_catalog_overview_serialization() -> None:
    overview = CatalogOverview(
        data_source_id="ds_1",
        snapshot_id="snap_1",
        version=1,
        schema_count=2,
        table_count=10,
        column_count=80,
        included_table_count=8,
        excluded_table_count=2,
        excluded_tables=[
            CatalogTableRecord(
                table_name="TMP_STAGING", excluded=True, excluded_reason="default_exclusion:TMP_.*"
            )
        ],
        suspected_business_tables=[CatalogTableRecord(table_name="TMS_SHIPMENT")],
    )
    dumped = overview.model_dump(mode="json")
    assert dumped["excluded_tables"][0]["excluded_reason"] == "default_exclusion:TMP_.*"
    assert len(dumped["suspected_business_tables"]) == 1
