from __future__ import annotations

from pathlib import Path

from sq_bi_contracts.assets import AssetKey, AssetRef
from sq_bi_contracts.enums import AssetSourceType, AssetType, ExecutionFailureCode, ExecutionPath
from sq_bi_contracts.execution import ResolvedExecutionRequest
from sq_bi_contracts.field_mount import FieldMapping
from sq_bi_contracts.metrics import LogicalMetricFormula, MetricDefinition, MetricFormula
from sq_bi_contracts.runtime_projection import ResolvedRuntimeAsset, RuntimeRequestContext
from sq_bi_runtime.deterministic_execution import DeterministicExecutionPipeline
from sq_bi_runtime.field_mapping_store import FieldMappingStore


class FakeDB:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, sql: str, max_rows: int = 200) -> dict:
        self.calls.append(sql)
        return {"columns": ["TOTAL"], "rows": [[3]]}


def _asset(metric: MetricDefinition, deployment_id: str = "dep1") -> ResolvedRuntimeAsset:
    ref = AssetRef(
        asset=AssetKey(
            source_type=AssetSourceType.OFFICIAL_PACK,
            source_id="tms",
            asset_type=AssetType.METRIC,
            local_code=metric.metric_code,
        ),
        version="1.0.0",
    )
    return ResolvedRuntimeAsset(
        asset_ref=ref,
        definition=metric.model_copy(update={"asset_ref": ref}),
        data_source_id="ds1",
        deployment_id=deployment_id,
    )


def _request(asset: ResolvedRuntimeAsset) -> ResolvedExecutionRequest:
    return ResolvedExecutionRequest(
        question="total orders",
        context=RuntimeRequestContext(user_id="u1", data_source_id="ds1"),
        execution_path=ExecutionPath.FORMAL_METRIC,
        selected_asset=asset,
    )


def test_logical_metric_compiles_from_selected_deployment_mapping(tmp_path: Path) -> None:
    store = FieldMappingStore(tmp_path / "mapping.sqlite3")
    store.upsert(
        FieldMapping(
            mapping_id="map1",
            pack_id="tms",
            standard_field_id="order_id",
            data_source_id="ds1",
            physical_table="ORDERS",
            physical_column="ID",
            deployment_id="dep1",
        )
    )
    metric = MetricDefinition(
        metric_code="order_count",
        name="Order count",
        definition="Count orders",
        formula=MetricFormula(expression=""),
        logical_formula=LogicalMetricFormula(
            expression="count(order_id)", referenced_standard_fields=["order_id"]
        ),
        data_source_id="ds1",
        owner="official",
    )
    db = FakeDB()
    result = DeterministicExecutionPipeline(store, db).execute(_request(_asset(metric)))
    assert result.failure is None
    assert result.provenance and result.provenance.deployment_id == "dep1"
    assert db.calls and "COUNT(ID)" in db.calls[0].upper()


def test_missing_mapping_fails_before_database_access(tmp_path: Path) -> None:
    metric = MetricDefinition(
        metric_code="amount",
        name="Amount",
        definition="Amount",
        formula=MetricFormula(expression=""),
        logical_formula=LogicalMetricFormula(
            expression="sum(amount)", referenced_standard_fields=["amount"]
        ),
        data_source_id="ds1",
        owner="official",
    )
    db = FakeDB()
    result = DeterministicExecutionPipeline(FieldMappingStore(tmp_path / "m.sqlite3"), db).execute(
        _request(_asset(metric))
    )
    assert result.failure and result.failure.code == ExecutionFailureCode.MISSING_MAPPING
    assert db.calls == []


def test_legacy_mutating_sql_is_rejected_before_database_access(tmp_path: Path) -> None:
    metric = MetricDefinition(
        metric_code="bad",
        name="Bad",
        definition="Bad",
        formula=MetricFormula(expression="DELETE FROM ORDERS"),
        data_source_id="ds1",
        owner="official",
    )
    db = FakeDB()
    result = DeterministicExecutionPipeline(FieldMappingStore(tmp_path / "m.sqlite3"), db).execute(
        _request(_asset(metric))
    )
    assert result.failure and result.failure.code == ExecutionFailureCode.QUERY_REJECTED
    assert db.calls == []
