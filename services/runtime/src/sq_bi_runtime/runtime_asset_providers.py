from __future__ import annotations

from typing import Callable

from sq_bi_contracts.enums import AssetSourceType, MetricVisibility
from sq_bi_contracts.field_mount import DeploymentInstance, ValidationStatus
from sq_bi_contracts.metrics import MetricDefinition
from sq_bi_contracts.runtime_projection import (
    PersonalWorkspaceBinding,
    RuntimeDeploymentBinding,
    RuntimeRequestContext,
    ResolvedRuntimeAsset,
)

from .enterprise_pack_store import EnterprisePackStore
from .field_mapping_store import FieldMappingStore
from .pack_loader import PackRegistry
from .runtime_asset_resolver import RuntimeAssetResolver
from .personal_asset_store import PersonalAssetStore

ReadinessFn = Callable[[DeploymentInstance], tuple[float, ValidationStatus, list[str]]]


class FieldMappingDeploymentProvider:
    """`RuntimeDeploymentProvider` backed by `FieldMappingStore` deployment rows.

    Maps each persisted deployment's ``pack_id`` to its exact
    `AssetSourceType` by checking the official `PackRegistry` first, then the
    `EnterprisePackStore`; a deployment whose pack is registered in neither
    is skipped rather than guessed at (P3 runtime-asset-projection task 4.1).
    Readiness is delegated to *readiness_fn* so this provider does not
    duplicate the space-scoped coverage logic the admin mounting API already
    owns (see api.py `_compute_deployment_readiness`).
    """

    def __init__(
        self,
        mapping_store: FieldMappingStore,
        pack_registry: PackRegistry,
        enterprise_pack_store: EnterprisePackStore,
        readiness_fn: ReadinessFn,
    ) -> None:
        self._mapping_store = mapping_store
        self._pack_registry = pack_registry
        self._enterprise_pack_store = enterprise_pack_store
        self._readiness_fn = readiness_fn

    def list_bindings(self, context: RuntimeRequestContext) -> list[RuntimeDeploymentBinding]:
        bindings: list[RuntimeDeploymentBinding] = []
        for deployment in self._mapping_store.list_deployments():
            if deployment.data_source_id != context.data_source_id:
                continue
            if deployment.environment != context.environment:
                continue
            source_type = self._resolve_source_type(deployment.pack_id)
            if source_type is None:
                continue
            _coverage, status, _blocking = self._readiness_fn(deployment)
            if deployment.extension_layer_id:
                layer = self._enterprise_pack_store.get_extension(deployment.extension_layer_id)
                if layer is None:
                    continue
                # A single deployment deliberately resolves into two catalog
                # bindings: immutable base at its pinned version, followed by
                # the active delta at its own version.  Both share lifecycle
                # gating and deployment provenance, so runtime consumers see
                # the effective base-plus-extension set without copying base
                # assets into the layer.
                bindings.append(
                    RuntimeDeploymentBinding(
                        deployment_id=deployment.deployment_id,
                        source_type=source_type,
                        source_id=deployment.pack_id,
                        exact_version=layer.base_pack_version,
                        data_source_id=deployment.data_source_id,
                        environment=deployment.environment,
                        semantic_space_ids=deployment.semantic_space_ids,
                        is_ready=status == "ready",
                        is_active=deployment.is_active,
                    )
                )
                bindings.append(
                    RuntimeDeploymentBinding(
                        deployment_id=deployment.deployment_id,
                        source_type=AssetSourceType.ENTERPRISE_PACK,
                        source_id=layer.extension_id,
                        exact_version=layer.version,
                        data_source_id=deployment.data_source_id,
                        environment=deployment.environment,
                        semantic_space_ids=deployment.semantic_space_ids,
                        is_ready=status == "ready",
                        is_active=deployment.is_active,
                    )
                )
                continue
            bindings.append(
                RuntimeDeploymentBinding(
                    deployment_id=deployment.deployment_id,
                    source_type=source_type,
                    source_id=deployment.pack_id,
                    exact_version=deployment.pack_version,
                    data_source_id=deployment.data_source_id,
                    environment=deployment.environment,
                    semantic_space_ids=deployment.semantic_space_ids,
                    is_ready=status == "ready",
                    is_active=deployment.is_active,
                )
            )
        return bindings

    def _resolve_source_type(self, pack_id: str) -> AssetSourceType | None:
        if any(manifest.pack_id == pack_id for manifest in self._pack_registry.list_packs()):
            return AssetSourceType.OFFICIAL_PACK
        if self._enterprise_pack_store.get(pack_id) is not None:
            return AssetSourceType.ENTERPRISE_PACK
        return None


class NullPersonalBindingProvider:
    """`PersonalBindingProvider` with no effective bindings.

    Personal-asset authoring and workspace binding is P5 scope (see
    openspec/changes/runtime-asset-projection/design.md Non-Goals). This
    keeps `RuntimeAssetResolver` fully constructible today — a requested
    workspace is correctly excluded via
    `RuntimeVisibilityReason.NO_WORKSPACE_BINDING` rather than the resolver
    being unusable until P5 lands a real provider.
    """

    def get_effective_binding(
        self, context: RuntimeRequestContext
    ) -> PersonalWorkspaceBinding | None:
        return None


class StoredPersonalBindingProvider:
    """Resolve only the requester's explicitly scoped personal workspace."""

    def __init__(self, store: PersonalAssetStore) -> None:
        self._store = store

    def get_effective_binding(
        self, context: RuntimeRequestContext
    ) -> PersonalWorkspaceBinding | None:
        workspace_id = context.workspace_id
        if not workspace_id or workspace_id != PersonalAssetStore.workspace_id_for(context.user_id):
            return None
        records = self._store.list_assets(workspace_id)
        if not any(
            record.scope.data_source_id == context.data_source_id
            and record.scope.environment == context.environment
            for record in records
        ):
            return None
        return PersonalWorkspaceBinding(
            workspace_id=workspace_id,
            data_source_id=context.data_source_id,
            environment=context.environment,
        )

    def is_asset_eligible(self, asset_ref: object, context: RuntimeRequestContext) -> bool:
        from sq_bi_contracts.assets import AssetRef

        if not isinstance(asset_ref, AssetRef) or context.workspace_id is None:
            return False
        record = self._store.get_asset(asset_ref, workspace_id=context.workspace_id)
        return bool(
            record
            and record.scope.data_source_id == context.data_source_id
            and record.scope.environment == context.environment
        )


class ResolverBackedMetricCandidates:
    """`MetricRepository`-shaped view over `RuntimeAssetResolver` for `QueryRouter`.

    P3 task 4.2: ask candidate enumeration must read through the resolver
    (only exact-version assets from ready, active deployments) instead of
    querying the product repository directly, so a published-but-inactive
    pack's metrics never reach routing. `QueryRouter`'s matching and
    `AnswerPath` labeling logic is untouched — it still reads
    `MetricVisibility` off each `MetricDefinition` returned here, so
    resolver-sourced official/enterprise/personal metrics route exactly as
    repository-sourced ones did.
    """

    def __init__(self, resolver: RuntimeAssetResolver, context: RuntimeRequestContext) -> None:
        self._resolver = resolver
        self._context = context

    def list_metrics(self, visibility: MetricVisibility | None = None) -> list[MetricDefinition]:
        assets = self.list_resolved_assets()
        metrics = [
            asset.definition
            for asset in assets
            if isinstance(asset.definition, MetricDefinition)
        ]
        if visibility is not None:
            metrics = [metric for metric in metrics if metric.visibility == visibility]
        return metrics

    def list_resolved_assets(self) -> list[ResolvedRuntimeAsset]:
        return self._resolver.resolve(self._context).resolved
