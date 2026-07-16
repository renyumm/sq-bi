from __future__ import annotations

from threading import Lock
import time
from types import SimpleNamespace

from sqlglot import parse_one

from sq_bi_runtime.api import ReportRuntimeAsset, _execute_report_runtime_assets


class AliasEchoDB:
    def __init__(self) -> None:
        self.sqls: list[str] = []

    def execute(self, sql: str, max_rows: int = 200) -> dict:
        self.sqls.append(sql)
        tree = parse_one(sql, read="oracle")
        columns = [projection.alias_or_name.upper() for projection in tree.expressions]
        return {"columns": columns, "rows": [tuple(range(1, len(columns) + 1))]}


class SlowDB:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.lock = Lock()

    def execute(self, sql: str, max_rows: int = 200) -> dict:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.05)
        finally:
            with self.lock:
                self.active -= 1
        return {"columns": ["VALUE"], "rows": [(1,)]}


def test_report_runtime_merges_same_source_scalar_metrics() -> None:
    db = AliasEchoDB()
    service = SimpleNamespace(
        db_executor=db,
        allowed_schemas=(),
        schema_catalog={
            "HR_DELIVER_CARRY": {"DELIVER_NO", "PLAN_TIME", "ACTUAL_TIME"},
        },
    )
    assets = [
        ReportRuntimeAsset(
            asset_type="metric",
            asset_id="execution_count",
            name="执行单量",
            description="执行单总量",
            sql="select count(distinct c.DELIVER_NO) as execution_count from HR_DELIVER_CARRY c",
        ),
        ReportRuntimeAsset(
            asset_type="metric",
            asset_id="delayed_count",
            name="延期单量",
            description="延期执行单",
            sql=(
                "select count(distinct c.DELIVER_NO) as delayed_count "
                "from HR_DELIVER_CARRY c "
                "where c.ACTUAL_TIME > c.PLAN_TIME"
            ),
        ),
    ]

    results = _execute_report_runtime_assets(service, assets)

    assert len(db.sqls) == 1
    assert "CASE WHEN" in db.sqls[0].upper()
    assert [item["asset_id"] for item in results] == ["execution_count", "delayed_count"]
    assert results[0]["execution_strategy"] == "merged_scalar_metric"
    assert results[0]["rows"] == [{"execution_count": 1}]
    assert results[1]["rows"] == [{"delayed_count": 2}]


def test_report_runtime_executes_remaining_assets_concurrently(monkeypatch) -> None:
    monkeypatch.setenv("SQ_BI_REPORT_SQL_MAX_WORKERS", "4")
    db = SlowDB()
    service = SimpleNamespace(
        db_executor=db,
        allowed_schemas=(),
        schema_catalog={
            "HR_DELIVER_FORM": {"DELIVER_NO", "CARRIER_NAME"},
        },
    )
    assets = [
        ReportRuntimeAsset(
            asset_type="skill",
            asset_id=f"skill_{index}",
            name=f"Skill {index}",
            description="按承运商聚合",
            sql=(
                "select f.CARRIER_NAME as carrier_name, count(distinct f.DELIVER_NO) as shipment_count "
                "from HR_DELIVER_FORM f group by f.CARRIER_NAME"
            ),
        )
        for index in range(4)
    ]

    results = _execute_report_runtime_assets(service, assets)

    assert len(results) == 4
    assert db.max_active > 1
