from __future__ import annotations

from sq_bi_contracts.assets import AssetDescriptor, AssetKey, AssetQuery, AssetRef
from sq_bi_contracts.enums import AssetSourceType, AssetType, RuntimeVisibilityReason
from sq_bi_contracts.metrics import MetricDefinition, MetricFormula
from sq_bi_contracts.runtime_projection import (
    PersonalWorkspaceBinding,
    RuntimeDeploymentBinding,
    RuntimeRequestContext,
)
from sq_bi_runtime.asset_catalog import AssetCatalog, AssetDefinition
from sq_bi_runtime.runtime_asset_resolver import RuntimeAssetResolver


def _ref(source_type: AssetSourceType, source_id: str, code: str, version: str) -> AssetRef:
    return AssetRef(
        asset=AssetKey(
            source_type=source_type,
            source_id=source_id,
            asset_type=AssetType.METRIC,
            local_code=code,
        ),
        version=version,
    )


def _metric(source_type: AssetSourceType, source_id: str, code: str, version: str) -> MetricDefinition:
    return MetricDefinition(
        metric_code=code,
        name=f"{code} metric",
        definition="A metric",
        formula=MetricFormula(expression="select 1 from dual"),
        data_source_id="ds_tms",
        owner="owner",
        version=version,
        asset_ref=_ref(source_type, source_id, code, version),
    )


def _matches(ref: AssetRef, query: AssetQuery | None) -> bool:
    if query is None:
        return True
    key = ref.asset
    return (
        (not query.source_types or key.source_type in query.source_types)
        and (not query.source_ids or key.source_id in query.source_ids)
        and (not query.asset_types or key.asset_type in query.asset_types)
        and (query.local_code is None or key.local_code == query.local_code)
        and (query.version is None or ref.version == query.version)
    )


class FakeAssetProvider:
    """Hand-written stub AssetProvider backed by an in-memory definition list."""

    def __init__(self, definitions: list[AssetDefinition]) -> None:
        self._definitions = definitions

    def list_assets(self, query: AssetQuery | None = None) -> list[AssetDescriptor]:
        return [
            AssetDescriptor(asset_ref=d.asset_ref, name=d.name)
            for d in self._definitions
            if d.asset_ref is not None and _matches(d.asset_ref, query)
        ]

    def get_asset(self, asset_ref: AssetRef) -> AssetDefinition | None:
        for d in self._definitions:
            if d.asset_ref == asset_ref:
                return d
        return None


class FakeDeploymentProvider:
    def __init__(self, bindings: list[RuntimeDeploymentBinding]) -> None:
        self.bindings = bindings

    def list_bindings(self, context: RuntimeRequestContext) -> list[RuntimeDeploymentBinding]:
        return list(self.bindings)


class FakePersonalProvider:
    def __init__(self, binding: PersonalWorkspaceBinding | None) -> None:
        self.binding = binding

    def get_effective_binding(self, context: RuntimeRequestContext) -> PersonalWorkspaceBinding | None:
        return self.binding


def _context(*, workspace_id: str | None = None) -> RuntimeRequestContext:
    return RuntimeRequestContext(
        user_id="u1", data_source_id="ds_tms", workspace_id=workspace_id
    )


def test_official_pack_asset_resolves_through_active_ready_deployment() -> None:
    catalog = AssetCatalog(
        [FakeAssetProvider([_metric(AssetSourceType.OFFICIAL_PACK, "tms", "otd_rate", "1.0.0")])]
    )
    deployment_provider = FakeDeploymentProvider(
        [
            RuntimeDeploymentBinding(
                deployment_id="dep_tms",
                source_type=AssetSourceType.OFFICIAL_PACK,
                source_id="tms",
                exact_version="1.0.0",
                data_source_id="ds_tms",
                semantic_space_ids=["sps_1"],
                is_ready=True,
                is_active=True,
            )
        ]
    )
    resolver = RuntimeAssetResolver(catalog, deployment_provider, FakePersonalProvider(None))

    projection = resolver.resolve(_context())

    assert len(projection.resolved) == 1
    resolved = projection.resolved[0]
    assert resolved.asset_ref.asset.local_code == "otd_rate"
    assert resolved.deployment_id == "dep_tms"
    assert resolved.semantic_space_ids == ["sps_1"]
    assert resolved.visibility_reason == RuntimeVisibilityReason.ACTIVE_DEPLOYMENT
    assert projection.excluded == []


def test_enterprise_pack_published_without_deployment_produces_no_candidates() -> None:
    catalog = AssetCatalog(
        [FakeAssetProvider([_metric(AssetSourceType.ENTERPRISE_PACK, "finance", "total_revenue", "1.0.0")])]
    )
    resolver = RuntimeAssetResolver(catalog, FakeDeploymentProvider([]), FakePersonalProvider(None))

    projection = resolver.resolve(_context())

    assert projection.resolved == []
    assert projection.excluded == []


def test_inactive_deployment_excludes_with_reason() -> None:
    catalog = AssetCatalog(
        [FakeAssetProvider([_metric(AssetSourceType.ENTERPRISE_PACK, "finance", "total_revenue", "1.0.0")])]
    )
    deployment_provider = FakeDeploymentProvider(
        [
            RuntimeDeploymentBinding(
                deployment_id="dep_fin",
                source_type=AssetSourceType.ENTERPRISE_PACK,
                source_id="finance",
                exact_version="1.0.0",
                data_source_id="ds_tms",
                is_ready=True,
                is_active=False,
            )
        ]
    )
    resolver = RuntimeAssetResolver(catalog, deployment_provider, FakePersonalProvider(None))

    projection = resolver.resolve(_context())

    assert projection.resolved == []
    assert len(projection.excluded) == 1
    assert projection.excluded[0].reason == RuntimeVisibilityReason.DEPLOYMENT_INACTIVE
    assert projection.excluded[0].deployment_id == "dep_fin"


def test_unvalidated_deployment_excludes_with_reason() -> None:
    catalog = AssetCatalog(
        [FakeAssetProvider([_metric(AssetSourceType.ENTERPRISE_PACK, "finance", "total_revenue", "1.0.0")])]
    )
    deployment_provider = FakeDeploymentProvider(
        [
            RuntimeDeploymentBinding(
                deployment_id="dep_fin",
                source_type=AssetSourceType.ENTERPRISE_PACK,
                source_id="finance",
                exact_version="1.0.0",
                data_source_id="ds_tms",
                is_ready=False,
                is_active=True,
            )
        ]
    )
    resolver = RuntimeAssetResolver(catalog, deployment_provider, FakePersonalProvider(None))

    projection = resolver.resolve(_context())

    assert projection.resolved == []
    assert projection.excluded[0].reason == RuntimeVisibilityReason.DEPLOYMENT_UNVALIDATED


def test_missing_exact_version_excludes_with_reason() -> None:
    catalog = AssetCatalog(
        [FakeAssetProvider([_metric(AssetSourceType.ENTERPRISE_PACK, "finance", "total_revenue", "1.0.0")])]
    )
    deployment_provider = FakeDeploymentProvider(
        [
            RuntimeDeploymentBinding(
                deployment_id="dep_fin",
                source_type=AssetSourceType.ENTERPRISE_PACK,
                source_id="finance",
                exact_version="2.0.0",  # published catalog only has 1.0.0
                data_source_id="ds_tms",
                is_ready=True,
                is_active=True,
            )
        ]
    )
    resolver = RuntimeAssetResolver(catalog, deployment_provider, FakePersonalProvider(None))

    projection = resolver.resolve(_context())

    assert projection.resolved == []
    assert projection.excluded[0].reason == RuntimeVisibilityReason.VERSION_NOT_DEPLOYED


def test_personal_asset_resolves_through_effective_binding() -> None:
    catalog = AssetCatalog(
        [FakeAssetProvider([_metric(AssetSourceType.PERSONAL_WORKSPACE, "workspace-a", "my_metric", "1")])]
    )
    personal_provider = FakePersonalProvider(
        PersonalWorkspaceBinding(workspace_id="workspace-a", data_source_id="ds_tms")
    )
    resolver = RuntimeAssetResolver(catalog, FakeDeploymentProvider([]), personal_provider)

    projection = resolver.resolve(_context(workspace_id="workspace-a"))

    assert len(projection.resolved) == 1
    resolved = projection.resolved[0]
    assert resolved.workspace_id == "workspace-a"
    assert resolved.deployment_id is None
    assert resolved.visibility_reason == RuntimeVisibilityReason.PERSONAL_WORKSPACE_BINDING
    assert projection.excluded == []


def test_cross_workspace_personal_asset_is_excluded() -> None:
    catalog = AssetCatalog(
        [FakeAssetProvider([_metric(AssetSourceType.PERSONAL_WORKSPACE, "workspace-b", "my_metric", "1")])]
    )
    # Provider misbehaves / stale binding: returns workspace-b for a workspace-a requester.
    personal_provider = FakePersonalProvider(
        PersonalWorkspaceBinding(workspace_id="workspace-b", data_source_id="ds_tms")
    )
    resolver = RuntimeAssetResolver(catalog, FakeDeploymentProvider([]), personal_provider)

    projection = resolver.resolve(_context(workspace_id="workspace-a"))

    assert projection.resolved == []
    assert projection.excluded[0].reason == RuntimeVisibilityReason.FOREIGN_WORKSPACE
    assert projection.excluded[0].source_id == "workspace-a"


def test_personal_workspace_without_effective_binding_is_excluded() -> None:
    catalog = AssetCatalog([FakeAssetProvider([])])
    resolver = RuntimeAssetResolver(catalog, FakeDeploymentProvider([]), FakePersonalProvider(None))

    projection = resolver.resolve(_context(workspace_id="workspace-a"))

    assert projection.resolved == []
    assert projection.excluded[0].reason == RuntimeVisibilityReason.NO_WORKSPACE_BINDING
    assert projection.excluded[0].source_id == "workspace-a"


def test_no_workspace_context_skips_personal_resolution_entirely() -> None:
    catalog = AssetCatalog(
        [FakeAssetProvider([_metric(AssetSourceType.PERSONAL_WORKSPACE, "workspace-a", "my_metric", "1")])]
    )
    resolver = RuntimeAssetResolver(catalog, FakeDeploymentProvider([]), FakePersonalProvider(None))

    projection = resolver.resolve(_context(workspace_id=None))

    assert projection.resolved == []
    assert projection.excluded == []


def test_same_local_code_collision_preserved_across_sources() -> None:
    catalog = AssetCatalog(
        [
            FakeAssetProvider(
                [
                    _metric(AssetSourceType.OFFICIAL_PACK, "tms", "total_revenue", "1.0.0"),
                    _metric(AssetSourceType.ENTERPRISE_PACK, "finance", "total_revenue", "1.0.0"),
                    _metric(AssetSourceType.PERSONAL_WORKSPACE, "workspace-a", "total_revenue", "1"),
                ]
            )
        ]
    )
    deployment_provider = FakeDeploymentProvider(
        [
            RuntimeDeploymentBinding(
                deployment_id="dep_tms",
                source_type=AssetSourceType.OFFICIAL_PACK,
                source_id="tms",
                exact_version="1.0.0",
                data_source_id="ds_tms",
                is_ready=True,
                is_active=True,
            ),
            RuntimeDeploymentBinding(
                deployment_id="dep_fin",
                source_type=AssetSourceType.ENTERPRISE_PACK,
                source_id="finance",
                exact_version="1.0.0",
                data_source_id="ds_tms",
                is_ready=True,
                is_active=True,
            ),
        ]
    )
    personal_provider = FakePersonalProvider(
        PersonalWorkspaceBinding(workspace_id="workspace-a", data_source_id="ds_tms")
    )
    resolver = RuntimeAssetResolver(catalog, deployment_provider, personal_provider)

    projection = resolver.resolve(_context(workspace_id="workspace-a"))

    assert len(projection.resolved) == 3
    codes = {
        (item.asset_ref.asset.source_type, item.asset_ref.asset.local_code)
        for item in projection.resolved
    }
    assert codes == {
        (AssetSourceType.OFFICIAL_PACK, "total_revenue"),
        (AssetSourceType.ENTERPRISE_PACK, "total_revenue"),
        (AssetSourceType.PERSONAL_WORKSPACE, "total_revenue"),
    }


def test_multi_space_and_multi_environment_deployments_both_preserved() -> None:
    catalog = AssetCatalog(
        [FakeAssetProvider([_metric(AssetSourceType.ENTERPRISE_PACK, "finance", "total_revenue", "1.0.0")])]
    )
    deployment_provider = FakeDeploymentProvider(
        [
            RuntimeDeploymentBinding(
                deployment_id="dep_fin_north",
                source_type=AssetSourceType.ENTERPRISE_PACK,
                source_id="finance",
                exact_version="1.0.0",
                data_source_id="ds_tms",
                environment="production",
                semantic_space_ids=["sps_north"],
                is_ready=True,
                is_active=True,
            ),
            RuntimeDeploymentBinding(
                deployment_id="dep_fin_south",
                source_type=AssetSourceType.ENTERPRISE_PACK,
                source_id="finance",
                exact_version="1.0.0",
                data_source_id="ds_tms",
                environment="staging",
                semantic_space_ids=["sps_south"],
                is_ready=True,
                is_active=True,
            ),
        ]
    )
    resolver = RuntimeAssetResolver(catalog, deployment_provider, FakePersonalProvider(None))

    projection = resolver.resolve(_context())

    assert len(projection.resolved) == 2
    provenance = {
        (item.deployment_id, item.environment, tuple(item.semantic_space_ids))
        for item in projection.resolved
    }
    assert provenance == {
        ("dep_fin_north", "production", ("sps_north",)),
        ("dep_fin_south", "staging", ("sps_south",)),
    }
    # Same exact asset ref is preserved under both deployments, not overwritten.
    assert {item.asset_ref for item in projection.resolved} == {
        _ref(AssetSourceType.ENTERPRISE_PACK, "finance", "total_revenue", "1.0.0")
    }


def test_deployment_deactivation_removes_asset_from_projection() -> None:
    catalog = AssetCatalog(
        [FakeAssetProvider([_metric(AssetSourceType.ENTERPRISE_PACK, "finance", "total_revenue", "1.0.0")])]
    )
    active_binding = RuntimeDeploymentBinding(
        deployment_id="dep_fin",
        source_type=AssetSourceType.ENTERPRISE_PACK,
        source_id="finance",
        exact_version="1.0.0",
        data_source_id="ds_tms",
        is_ready=True,
        is_active=True,
    )
    deployment_provider = FakeDeploymentProvider([active_binding])
    resolver = RuntimeAssetResolver(catalog, deployment_provider, FakePersonalProvider(None))

    before = resolver.resolve(_context())
    assert len(before.resolved) == 1

    # Administrator deactivates the deployment; the provider now reflects that.
    deployment_provider.bindings = [active_binding.model_copy(update={"is_active": False})]

    after = resolver.resolve(_context())
    assert after.resolved == []
    assert after.excluded[0].reason == RuntimeVisibilityReason.DEPLOYMENT_INACTIVE
