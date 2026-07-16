from __future__ import annotations

from typing import Protocol, runtime_checkable

from sq_bi_contracts.assets import AssetQuery
from sq_bi_contracts.enums import AssetSourceType, RuntimeVisibilityReason
from sq_bi_contracts.runtime_projection import (
    ExcludedRuntimeBinding,
    PersonalWorkspaceBinding,
    ResolvedRuntimeAsset,
    RuntimeAssetProjection,
    RuntimeDeploymentBinding,
    RuntimeRequestContext,
)

from .asset_catalog import AssetCatalog


@runtime_checkable
class RuntimeDeploymentProvider(Protocol):
    """Synchronous source of official/enterprise pack deployment bindings.

    Scoping by data source and environment is the provider's responsibility
    (e.g. a SQL WHERE clause); the resolver only enforces activation,
    validation, and exact-version eligibility on what is returned.
    """

    def list_bindings(
        self, context: RuntimeRequestContext
    ) -> list[RuntimeDeploymentBinding]: ...


@runtime_checkable
class PersonalBindingProvider(Protocol):
    """Synchronous source of the requester's effective personal-workspace binding."""

    def get_effective_binding(
        self, context: RuntimeRequestContext
    ) -> PersonalWorkspaceBinding | None: ...


class RuntimeAssetResolver:
    """Projects `AssetCatalog` definitions into runtime-visible assets.

    Deployment activation/readiness and personal-workspace ownership gate
    eligibility; the catalog remains the sole source of asset definitions,
    so a pack version that only exists as a draft is never seen here.
    """

    def __init__(
        self,
        catalog: AssetCatalog,
        deployment_provider: RuntimeDeploymentProvider,
        personal_provider: PersonalBindingProvider,
    ) -> None:
        self._catalog = catalog
        self._deployment_provider = deployment_provider
        self._personal_provider = personal_provider

    def resolve(self, context: RuntimeRequestContext) -> RuntimeAssetProjection:
        resolved: list[ResolvedRuntimeAsset] = []
        excluded: list[ExcludedRuntimeBinding] = []

        for binding in self._deployment_provider.list_bindings(context):
            self._resolve_binding(binding, resolved, excluded)

        if context.workspace_id:
            self._resolve_personal(context, resolved, excluded)

        return RuntimeAssetProjection(resolved=resolved, excluded=excluded)

    def _resolve_binding(
        self,
        binding: RuntimeDeploymentBinding,
        resolved: list[ResolvedRuntimeAsset],
        excluded: list[ExcludedRuntimeBinding],
    ) -> None:
        if not binding.is_active:
            excluded.append(
                ExcludedRuntimeBinding(
                    source_type=binding.source_type,
                    source_id=binding.source_id,
                    deployment_id=binding.deployment_id,
                    reason=RuntimeVisibilityReason.DEPLOYMENT_INACTIVE,
                )
            )
            return
        if not binding.is_ready:
            excluded.append(
                ExcludedRuntimeBinding(
                    source_type=binding.source_type,
                    source_id=binding.source_id,
                    deployment_id=binding.deployment_id,
                    reason=RuntimeVisibilityReason.DEPLOYMENT_UNVALIDATED,
                )
            )
            return

        descriptors = self._catalog.list_assets(
            AssetQuery(
                source_types=[binding.source_type],
                source_ids=[binding.source_id],
                version=binding.exact_version,
            )
        )
        if not descriptors:
            excluded.append(
                ExcludedRuntimeBinding(
                    source_type=binding.source_type,
                    source_id=binding.source_id,
                    deployment_id=binding.deployment_id,
                    reason=RuntimeVisibilityReason.VERSION_NOT_DEPLOYED,
                )
            )
            return

        for descriptor in descriptors:
            definition = self._catalog.get_asset(descriptor.asset_ref)
            if definition is None:
                continue
            resolved.append(
                ResolvedRuntimeAsset(
                    asset_ref=descriptor.asset_ref,
                    definition=definition,
                    data_source_id=binding.data_source_id,
                    environment=binding.environment,
                    semantic_space_ids=binding.semantic_space_ids,
                    deployment_id=binding.deployment_id,
                    visibility_reason=RuntimeVisibilityReason.ACTIVE_DEPLOYMENT,
                )
            )

    def _resolve_personal(
        self,
        context: RuntimeRequestContext,
        resolved: list[ResolvedRuntimeAsset],
        excluded: list[ExcludedRuntimeBinding],
    ) -> None:
        workspace_id = context.workspace_id
        assert workspace_id is not None

        binding = self._personal_provider.get_effective_binding(context)
        if binding is None:
            excluded.append(
                ExcludedRuntimeBinding(
                    source_type=AssetSourceType.PERSONAL_WORKSPACE,
                    source_id=workspace_id,
                    reason=RuntimeVisibilityReason.NO_WORKSPACE_BINDING,
                )
            )
            return
        if binding.workspace_id != workspace_id:
            excluded.append(
                ExcludedRuntimeBinding(
                    source_type=AssetSourceType.PERSONAL_WORKSPACE,
                    source_id=workspace_id,
                    reason=RuntimeVisibilityReason.FOREIGN_WORKSPACE,
                )
            )
            return

        descriptors = self._catalog.list_assets(
            AssetQuery(
                source_types=[AssetSourceType.PERSONAL_WORKSPACE],
                source_ids=[binding.workspace_id],
            )
        )
        for descriptor in descriptors:
            eligibility = getattr(self._personal_provider, "is_asset_eligible", None)
            if callable(eligibility) and not eligibility(descriptor.asset_ref, context):
                continue
            definition = self._catalog.get_asset(descriptor.asset_ref)
            if definition is None:
                continue
            resolved.append(
                ResolvedRuntimeAsset(
                    asset_ref=descriptor.asset_ref,
                    definition=definition,
                    data_source_id=binding.data_source_id,
                    environment=binding.environment,
                    deployment_id=None,
                    workspace_id=binding.workspace_id,
                    visibility_reason=RuntimeVisibilityReason.PERSONAL_WORKSPACE_BINDING,
                )
            )
