from __future__ import annotations

from pathlib import Path

from sq_bi_contracts.domain_pack import DomainPackManifest
from sq_bi_contracts.enterprise_pack import CreateEnterprisePackRequest
from sq_bi_contracts.assets import AssetKey, AssetRef
from sq_bi_contracts.enums import (
    AssetSourceType,
    AssetType,
    MetricVisibility,
    RuntimeVisibilityReason,
)
from sq_bi_contracts.metrics import MetricDefinition, MetricFormula
from sq_bi_contracts.runtime_projection import RuntimeRequestContext
from sq_bi_contracts.runtime_projection import ResolvedRuntimeAsset, RuntimeAssetProjection
from sq_bi_runtime.enterprise_pack_store import EnterprisePackStore
from sq_bi_runtime.field_mapping_store import FieldMappingStore
from sq_bi_runtime.pack_loader import PackRegistry
from sq_bi_runtime.runtime_asset_providers import (
    FieldMappingDeploymentProvider,
    NullPersonalBindingProvider,
    ResolverBackedMetricCandidates,
)


def _official_manifest(pack_id: str) -> DomainPackManifest:
    return DomainPackManifest(
        pack_id=pack_id, namespace=pack_id, name=pack_id, version="1.0.0",
    )


def _ready(_deployment: object) -> tuple[float, str, list[str]]:
    return 1.0, "ready", []


def _unready(_deployment: object) -> tuple[float, str, list[str]]:
    return 0.0, "unvalidated", ["not mapped"]


def _context(data_source_id: str = "ds_a", environment: str = "default") -> RuntimeRequestContext:
    return RuntimeRequestContext(user_id="u1", data_source_id=data_source_id, environment=environment)


def test_official_pack_deployment_maps_to_official_source_type(tmp_path: Path) -> None:
    registry = PackRegistry()
    registry.install(_official_manifest("tms"), tmp_path / "packs" / "tms")
    ep_store = EnterprisePackStore(tmp_path / "enterprise.sqlite3")
    mapping_store = FieldMappingStore(tmp_path / "mappings.sqlite3")
    deployment = mapping_store.get_or_create_deployment(
        pack_id="tms", pack_version="1.0.0", data_source_id="ds_a",
    )
    mapping_store.activate_deployment(deployment.deployment_id, "admin")

    provider = FieldMappingDeploymentProvider(mapping_store, registry, ep_store, _ready)
    bindings = provider.list_bindings(_context())

    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.deployment_id == deployment.deployment_id
    assert binding.source_type == AssetSourceType.OFFICIAL_PACK
    assert binding.source_id == "tms"
    assert binding.exact_version == "1.0.0"
    assert binding.is_ready is True
    assert binding.is_active is True


def test_enterprise_pack_deployment_maps_to_enterprise_source_type(tmp_path: Path) -> None:
    registry = PackRegistry()
    ep_store = EnterprisePackStore(tmp_path / "enterprise.sqlite3")
    pack = ep_store.create(
        CreateEnterprisePackRequest(
            name="Finance pack", created_by="admin",
        )
    )
    mapping_store = FieldMappingStore(tmp_path / "mappings.sqlite3")
    mapping_store.get_or_create_deployment(
        pack_id=pack.pack_id, pack_version="1.0.0", data_source_id="ds_a",
    )

    provider = FieldMappingDeploymentProvider(mapping_store, registry, ep_store, _unready)
    bindings = provider.list_bindings(_context())

    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.source_type == AssetSourceType.ENTERPRISE_PACK
    assert binding.source_id == pack.pack_id
    assert binding.is_ready is False
    assert binding.is_active is False


def test_deployment_for_unknown_pack_is_skipped(tmp_path: Path) -> None:
    registry = PackRegistry()
    ep_store = EnterprisePackStore(tmp_path / "enterprise.sqlite3")
    mapping_store = FieldMappingStore(tmp_path / "mappings.sqlite3")
    mapping_store.get_or_create_deployment(
        pack_id="ghost_pack", pack_version="1.0.0", data_source_id="ds_a",
    )

    provider = FieldMappingDeploymentProvider(mapping_store, registry, ep_store, _ready)
    bindings = provider.list_bindings(_context())

    assert bindings == []


def test_bindings_are_scoped_to_request_data_source_and_environment(tmp_path: Path) -> None:
    registry = PackRegistry()
    registry.install(_official_manifest("tms"), tmp_path / "packs" / "tms")
    ep_store = EnterprisePackStore(tmp_path / "enterprise.sqlite3")
    mapping_store = FieldMappingStore(tmp_path / "mappings.sqlite3")
    mapping_store.get_or_create_deployment(
        pack_id="tms", pack_version="1.0.0", data_source_id="ds_a", environment="default",
    )
    mapping_store.get_or_create_deployment(
        pack_id="tms", pack_version="1.0.0", data_source_id="ds_b", environment="default",
    )
    mapping_store.get_or_create_deployment(
        pack_id="tms", pack_version="1.0.0", data_source_id="ds_a", environment="staging",
    )

    provider = FieldMappingDeploymentProvider(mapping_store, registry, ep_store, _ready)

    default_bindings = provider.list_bindings(_context(data_source_id="ds_a", environment="default"))
    staging_bindings = provider.list_bindings(_context(data_source_id="ds_a", environment="staging"))
    other_ds_bindings = provider.list_bindings(_context(data_source_id="ds_b", environment="default"))

    assert len(default_bindings) == 1
    assert default_bindings[0].environment == "default"
    assert len(staging_bindings) == 1
    assert staging_bindings[0].environment == "staging"
    assert len(other_ds_bindings) == 1
    assert other_ds_bindings[0].data_source_id == "ds_b"


def test_null_personal_binding_provider_always_returns_none(tmp_path: Path) -> None:
    provider = NullPersonalBindingProvider()
    assert provider.get_effective_binding(_context(data_source_id="ds_a")) is None


class _StubResolver:
    def __init__(self, projection: RuntimeAssetProjection) -> None:
        self.projection = projection
        self.contexts: list[RuntimeRequestContext] = []

    def resolve(self, context: RuntimeRequestContext) -> RuntimeAssetProjection:
        self.contexts.append(context)
        return self.projection


def _resolved_metric(
    code: str,
    *,
    visibility: MetricVisibility,
    deployment_id: str,
) -> ResolvedRuntimeAsset:
    asset_ref = AssetRef(
        asset=AssetKey(
            source_type=AssetSourceType.OFFICIAL_PACK,
            source_id="tms",
            asset_type=AssetType.METRIC,
            local_code=code,
        ),
        version="1.0.0",
    )
    return ResolvedRuntimeAsset(
        asset_ref=asset_ref,
        definition=MetricDefinition(
            metric_code=code,
            name=code.replace("_", " "),
            definition=f"Definition for {code}",
            visibility=visibility,
            formula=MetricFormula(expression="select 1 from dual"),
            data_source_id="ds_a",
            owner="official",
            asset_ref=asset_ref,
        ),
        data_source_id="ds_a",
        deployment_id=deployment_id,
        visibility_reason=RuntimeVisibilityReason.ACTIVE_DEPLOYMENT,
    )


def test_resolver_backed_candidates_only_return_resolved_metrics() -> None:
    official = _resolved_metric(
        "shipment_count",
        visibility=MetricVisibility.OFFICIAL,
        deployment_id="dep_active",
    )
    resolver = _StubResolver(RuntimeAssetProjection(resolved=[official]))
    context = _context()

    candidates = ResolverBackedMetricCandidates(resolver, context)  # type: ignore[arg-type]

    assert candidates.list_metrics() == [official.definition]
    assert candidates.list_metrics(MetricVisibility.OFFICIAL) == [official.definition]
    assert candidates.list_metrics(MetricVisibility.PRIVATE) == []
    assert resolver.contexts == [context, context, context]


def test_resolver_backed_candidates_do_not_reintroduce_excluded_assets() -> None:
    resolver = _StubResolver(RuntimeAssetProjection())

    candidates = ResolverBackedMetricCandidates(resolver, _context())  # type: ignore[arg-type]

    assert candidates.list_metrics() == []
