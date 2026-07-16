from __future__ import annotations

from pathlib import Path

import pytest

from sq_bi_contracts.assets import AssetKey, AssetRef
from sq_bi_contracts.enums import AssetSourceType, AssetType
from sq_bi_contracts.personal_assets import PersonalAssetScope
from sq_bi_contracts.enums import MetricVisibility
from sq_bi_contracts.metrics import MetricDefinition, MetricFormula
from sq_bi_runtime.personal_asset_store import PersonalAssetStore, new_personal_record


def _ref(code: str, asset_type: AssetType = AssetType.METRIC) -> AssetRef:
    return AssetRef(
        asset=AssetKey(
            source_type=AssetSourceType.PERSONAL_WORKSPACE,
            source_id="u1",
            asset_type=asset_type,
            local_code=code,
        ),
        version="1.0.0",
    )


def _scope(spaces: list[str] | None = None) -> PersonalAssetScope:
    return PersonalAssetScope(
        workspace_id="u1",
        data_source_id="ds1",
        semantic_space_ids=spaces or ["space_a"],
        physical_tables=["ORDERS"],
        physical_fields=["ORDERS.ID"],
    )


def test_workspace_isolation_and_exact_version(tmp_path: Path) -> None:
    store = PersonalAssetStore(tmp_path / "personal.sqlite3")
    ref = _ref("orders")
    store.save_asset(new_personal_record(asset_ref=ref, name="Orders", owner_user_id="u1", scope=_scope()))
    assert store.get_asset(ref, workspace_id="u1") is not None
    assert store.get_asset(ref, workspace_id="u2") is None


def test_dependency_scope_intersection_and_conflict(tmp_path: Path) -> None:
    store = PersonalAssetStore(tmp_path / "personal.sqlite3")
    first = _ref("a")
    second = _ref("b")
    store.save_asset(new_personal_record(asset_ref=first, name="A", owner_user_id="u1", scope=_scope(["x", "y"])))
    store.save_asset(new_personal_record(asset_ref=second, name="B", owner_user_id="u1", scope=_scope(["y", "z"])))
    assert store.effective_scope([first, second], "u1").semantic_space_ids == ["y"]

    third = _ref("c")
    store.save_asset(new_personal_record(asset_ref=third, name="C", owner_user_id="u1", scope=_scope(["other"])))
    with pytest.raises(ValueError, match="INCOMPATIBLE"):
        store.effective_scope([first, third], "u1")


def test_direct_dependency_cycle_rejected(tmp_path: Path) -> None:
    store = PersonalAssetStore(tmp_path / "personal.sqlite3")
    ref = _ref("skill", AssetType.SKILL)
    with pytest.raises(ValueError, match="CYCLE"):
        store.save_asset(
            new_personal_record(
                asset_ref=ref,
                name="Skill",
                owner_user_id="u1",
                scope=_scope(),
                dependency_refs=[ref],
            )
        )


def test_indirect_dependency_cycle_rejected(tmp_path: Path) -> None:
    store = PersonalAssetStore(tmp_path / "personal.sqlite3")
    first = _ref("first", AssetType.SKILL)
    second = _ref("second", AssetType.SKILL)
    store.save_asset(
        new_personal_record(
            asset_ref=second, name="Second", owner_user_id="u1", scope=_scope()
        )
    )
    store.save_asset(
        new_personal_record(
            asset_ref=first,
            name="First",
            owner_user_id="u1",
            scope=_scope(),
            dependency_refs=[second],
        )
    )
    with pytest.raises(ValueError, match="CYCLE"):
        store.save_asset(
            new_personal_record(
                asset_ref=second,
                name="Second",
                owner_user_id="u1",
                scope=_scope(),
                dependency_refs=[first],
            )
        )


def test_legacy_metric_backfill_preserves_personal_identity(tmp_path: Path) -> None:
    ref = _ref("legacy")

    class Repo:
        def list_metrics(self):
            return [
                MetricDefinition(
                    metric_code="legacy",
                    name="Legacy",
                    definition="Legacy",
                    visibility=MetricVisibility.PRIVATE,
                    formula=MetricFormula(expression="SELECT 1 FROM DUAL"),
                    data_source_id="ds_legacy",
                    owner="u1",
                    asset_ref=ref,
                )
            ]

        def list_skills(self):
            return []

    store = PersonalAssetStore(tmp_path / "personal.sqlite3")
    assert store.backfill_from_repository(Repo()) == 1
    record = store.get_asset(ref, workspace_id="u1")
    assert record is not None and record.scope.data_source_id == "ds_legacy"
