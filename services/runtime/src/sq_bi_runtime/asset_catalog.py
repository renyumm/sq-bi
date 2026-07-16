from __future__ import annotations

from typing import Protocol, TypeAlias, runtime_checkable

import yaml

from sq_bi_contracts.assets import AssetDescriptor, AssetKey, AssetQuery, AssetRef
from sq_bi_contracts.enums import (
    AssetSourceType,
    AssetType,
    MetricVisibility,
    SkillType,
    SkillVisibility,
)
from sq_bi_contracts.metrics import LogicalMetricFormula, MetricDefinition, MetricFormula
from sq_bi_contracts.reports import ReportDefinition, ReportWidget
from sq_bi_contracts.skills import SkillDefinition
from sq_bi_semantic.product_repository import ReportRecord, SQLiteProductRepository

from .enterprise_pack_store import EnterprisePackStore
from .pack_loader import PackRegistry


AssetDefinition: TypeAlias = MetricDefinition | SkillDefinition | ReportDefinition


@runtime_checkable
class AssetProvider(Protocol):
    def list_assets(self, query: AssetQuery | None = None) -> list[AssetDescriptor]: ...

    def get_asset(self, asset_ref: AssetRef) -> AssetDefinition | None: ...


class AssetCatalog:
    """Aggregates source-specific, read-only providers behind exact asset refs."""

    def __init__(self, providers: list[AssetProvider]) -> None:
        self._providers = list(providers)

    def list_assets(self, query: AssetQuery | None = None) -> list[AssetDescriptor]:
        by_ref: dict[tuple[str, str], AssetDescriptor] = {}
        for provider in self._providers:
            for descriptor in provider.list_assets(query):
                key = (
                    descriptor.asset_ref.asset.asset_id,
                    descriptor.asset_ref.version,
                )
                if key in by_ref:
                    raise ValueError(
                        f"Duplicate asset provider result for {key[0]}@{key[1]}."
                    )
                by_ref[key] = descriptor
        return sorted(
            by_ref.values(),
            key=lambda item: (
                item.asset_ref.asset.asset_id,
                item.asset_ref.version,
            ),
        )

    def get_asset(self, asset_ref: AssetRef) -> AssetDefinition | None:
        matches = [
            definition
            for provider in self._providers
            if (definition := provider.get_asset(asset_ref)) is not None
        ]
        if len(matches) > 1:
            raise ValueError(
                f"Duplicate asset provider result for "
                f"{asset_ref.asset.asset_id}@{asset_ref.version}."
            )
        return matches[0] if matches else None


class OfficialPackAssetProvider:
    def __init__(self, registry: PackRegistry) -> None:
        self._registry = registry

    def list_assets(self, query: AssetQuery | None = None) -> list[AssetDescriptor]:
        return [
            _descriptor(definition)
            for definition in self._definitions()
            if _matches(definition.asset_ref, query)
        ]

    def get_asset(self, asset_ref: AssetRef) -> AssetDefinition | None:
        if asset_ref.asset.source_type != AssetSourceType.OFFICIAL_PACK:
            return None
        for definition in self._definitions():
            if definition.asset_ref == asset_ref:
                return definition
        return None

    def _definitions(self) -> list[AssetDefinition]:
        definitions: list[AssetDefinition] = []
        for manifest, pack_dir in self._registry.list_enabled_pack_entries():
            for pack_asset in manifest.assets:
                if pack_asset.asset_type != "semantic":
                    continue
                semantic_path = pack_dir / pack_asset.path
                raw = yaml.safe_load(semantic_path.read_text(encoding="utf-8")) or {}
                for metric_raw in raw.get("metrics") or []:
                    payload = _known_fields(MetricDefinition, metric_raw)
                    for field_name, nested_model in (
                        ("formula", MetricFormula),
                        ("logical_formula", LogicalMetricFormula),
                    ):
                        if isinstance(payload.get(field_name), dict):
                            payload[field_name] = _known_fields(
                                nested_model, payload[field_name]
                            )
                    metric = MetricDefinition(**payload)
                    ref = _ref(
                        AssetSourceType.OFFICIAL_PACK,
                        manifest.pack_id,
                        AssetType.METRIC,
                        metric.metric_code,
                        manifest.version,
                    )
                    definitions.append(metric.model_copy(update={"asset_ref": ref}))
                for skill_raw in raw.get("skills") or []:
                    payload = _known_fields(SkillDefinition, skill_raw)
                    skill = SkillDefinition(**payload)
                    ref = _ref(
                        AssetSourceType.OFFICIAL_PACK,
                        manifest.pack_id,
                        AssetType.SKILL,
                        skill.skill_id,
                        manifest.version,
                    )
                    definitions.append(skill.model_copy(update={"asset_ref": ref}))
                metric_refs = {
                    definition.metric_code: definition.asset_ref
                    for definition in definitions
                    if isinstance(definition, MetricDefinition)
                    and definition.asset_ref is not None
                    and definition.asset_ref.asset.source_id == manifest.pack_id
                }
                for report_raw in raw.get("reports") or []:
                    payload = _known_fields(ReportDefinition, report_raw)
                    payload["widgets"] = [
                        ReportWidget(**_known_fields(ReportWidget, widget))
                        for widget in report_raw.get("widgets") or []
                    ]
                    report = ReportDefinition(**payload)
                    dependencies = [
                        metric_refs[metric_code]
                        for widget in report.widgets
                        for metric_code in widget.metric_codes
                        if metric_code in metric_refs
                    ]
                    ref = _ref(
                        AssetSourceType.OFFICIAL_PACK,
                        manifest.pack_id,
                        AssetType.REPORT,
                        report.report_skill_id,
                        manifest.version,
                    )
                    definitions.append(
                        report.model_copy(
                            update={
                                "asset_ref": ref,
                                "dependency_refs": _unique_refs(dependencies),
                            }
                        )
                    )
        return definitions


class EnterprisePackAssetProvider:
    def __init__(self, store: EnterprisePackStore) -> None:
        self._store = store

    def list_assets(self, query: AssetQuery | None = None) -> list[AssetDescriptor]:
        return [
            _descriptor(definition)
            for definition in self._definitions()
            if _matches(definition.asset_ref, query)
        ]

    def get_asset(self, asset_ref: AssetRef) -> AssetDefinition | None:
        if asset_ref.asset.source_type != AssetSourceType.ENTERPRISE_PACK:
            return None
        for definition in self._definitions(asset_ref.asset.source_id):
            if definition.asset_ref == asset_ref:
                return definition
        return None

    def _definitions(self, pack_id: str | None = None) -> list[AssetDefinition]:
        definitions: list[AssetDefinition] = []
        for pack, version, draft in self._store.list_snapshots(pack_id):
            metric_refs = {
                metric.metric_code: _ref(
                    AssetSourceType.ENTERPRISE_PACK,
                    pack.pack_id,
                    AssetType.METRIC,
                    metric.metric_code,
                    version,
                )
                for metric in draft.metrics
            }
            skill_refs = {
                skill.skill_id: _ref(
                    AssetSourceType.ENTERPRISE_PACK,
                    pack.pack_id,
                    AssetType.SKILL,
                    skill.skill_id,
                    version,
                )
                for skill in draft.skills
            }
            for metric in draft.metrics:
                definitions.append(
                    MetricDefinition(
                        metric_code=metric.metric_code,
                        name=metric.name,
                        definition=metric.definition,
                        visibility=MetricVisibility.SHARED,
                        formula=metric.formula,
                        data_source_id="unbound",
                        owner=pack.created_by,
                        version=version,
                        synonyms=metric.synonyms,
                        asset_ref=metric_refs[metric.metric_code],
                    )
                )
            for skill in draft.skills:
                dependencies = [
                    metric_refs[code]
                    for step in skill.steps
                    for code in step.metric_codes
                    if code in metric_refs
                ]
                definitions.append(
                    SkillDefinition(
                        skill_id=skill.skill_id,
                        namespace=pack.pack_id,
                        name=skill.name,
                        skill_type=SkillType.REPORT,
                        visibility=SkillVisibility.SHARED,
                        owner_user_id=pack.created_by,
                        description=skill.description or skill.name,
                        output_schema={"version": version},
                        asset_ref=skill_refs[skill.skill_id],
                        dependency_refs=_unique_refs(dependencies),
                    )
                )
            for report in draft.reports:
                dependencies = [
                    metric_refs[code]
                    for code in report.metric_codes
                    if code in metric_refs
                ] + [
                    skill_refs[code] for code in report.skill_ids if code in skill_refs
                ]
                definitions.append(
                    ReportDefinition(
                        report_skill_id=report.report_id,
                        namespace=pack.pack_id,
                        name=report.name,
                        owner_user_id=pack.created_by,
                        visibility=SkillVisibility.SHARED,
                        description=report.description,
                        asset_ref=_ref(
                            AssetSourceType.ENTERPRISE_PACK,
                            pack.pack_id,
                            AssetType.REPORT,
                            report.report_id,
                            version,
                        ),
                        dependency_refs=_unique_refs(dependencies),
                    )
                )
        return definitions


class ExtensionLayerAssetProvider:
    """Runtime definitions for the active additive half of a deployed pack.

    The companion deployment provider emits the pinned base binding as well
    as this layer binding.  Keeping delta assets under the extension identity
    makes the two provenance paths explicit without copying base definitions.
    """

    def __init__(self, store: EnterprisePackStore) -> None:
        self._store = store

    def list_assets(self, query: AssetQuery | None = None) -> list[AssetDescriptor]:
        return [
            _descriptor(definition)
            for definition in self._definitions()
            if _matches(definition.asset_ref, query)
        ]

    def get_asset(self, asset_ref: AssetRef) -> AssetDefinition | None:
        if asset_ref.asset.source_type != AssetSourceType.ENTERPRISE_PACK:
            return None
        layer = self._store.get_extension(asset_ref.asset.source_id)
        if layer is None:
            return None
        for definition in self._definitions_for_layer(layer):
            if definition.asset_ref == asset_ref:
                return definition
        return None

    def _definitions(self) -> list[AssetDefinition]:
        definitions: list[AssetDefinition] = []
        for layer in self._store.list_extensions(active_only=True):
            definitions.extend(self._definitions_for_layer(layer))
        return definitions

    @staticmethod
    def _definitions_for_layer(layer: object) -> list[AssetDefinition]:
        # Delayed structural access keeps the public provider focused on the
        # store contract rather than duplicating its persistence model.
        from sq_bi_contracts.enterprise_pack import PackExtensionLayer

        assert isinstance(layer, PackExtensionLayer)
        metric_refs = {
            metric.metric_code: _ref(
                AssetSourceType.ENTERPRISE_PACK, layer.extension_id,
                AssetType.METRIC, metric.metric_code, layer.version,
            )
            for metric in layer.draft.metrics
        }
        skill_refs = {
            skill.skill_id: _ref(
                AssetSourceType.ENTERPRISE_PACK, layer.extension_id,
                AssetType.SKILL, skill.skill_id, layer.version,
            )
            for skill in layer.draft.skills
        }
        definitions: list[AssetDefinition] = []
        for metric in layer.draft.metrics:
            definitions.append(MetricDefinition(
                metric_code=metric.metric_code, name=metric.name,
                definition=metric.definition, visibility=MetricVisibility.SHARED,
                formula=metric.formula, data_source_id="unbound",
                owner=layer.created_by, version=layer.version,
                synonyms=metric.synonyms, asset_ref=metric_refs[metric.metric_code],
            ))
        for skill in layer.draft.skills:
            dependencies = [
                metric_refs[code] for step in skill.steps for code in step.metric_codes
                if code in metric_refs
            ]
            definitions.append(SkillDefinition(
                skill_id=skill.skill_id, namespace=layer.base_pack_id,
                name=skill.name, skill_type=SkillType.REPORT,
                visibility=SkillVisibility.SHARED, owner_user_id=layer.created_by,
                description=skill.description or skill.name,
                output_schema={"version": layer.version}, asset_ref=skill_refs[skill.skill_id],
                dependency_refs=_unique_refs(dependencies),
            ))
        for report in layer.draft.reports:
            dependencies = [metric_refs[code] for code in report.metric_codes if code in metric_refs]
            dependencies += [skill_refs[code] for code in report.skill_ids if code in skill_refs]
            definitions.append(ReportDefinition(
                report_skill_id=report.report_id, namespace=layer.base_pack_id,
                name=report.name, owner_user_id=layer.created_by,
                visibility=SkillVisibility.SHARED, description=report.description,
                asset_ref=_ref(
                    AssetSourceType.ENTERPRISE_PACK, layer.extension_id,
                    AssetType.REPORT, report.report_id, layer.version,
                ),
                dependency_refs=_unique_refs(dependencies),
            ))
        return definitions


class LegacyPersonalAssetProvider:
    def __init__(self, repository: SQLiteProductRepository) -> None:
        self._repository = repository

    def list_assets(self, query: AssetQuery | None = None) -> list[AssetDescriptor]:
        if query is None or not query.source_ids:
            return []
        if query.source_types and AssetSourceType.PERSONAL_WORKSPACE not in query.source_types:
            return []
        definitions: list[AssetDefinition] = [
            *self._repository.list_metrics(),
            *self._repository.list_skills(),
            *(_report_definition(report) for report in self._repository.list_reports()),
        ]
        return [
            _descriptor(definition)
            for definition in definitions
            if definition.asset_ref is not None
            and definition.asset_ref.asset.source_type
            == AssetSourceType.PERSONAL_WORKSPACE
            and _matches(definition.asset_ref, query)
        ]

    def get_asset(self, asset_ref: AssetRef) -> AssetDefinition | None:
        if asset_ref.asset.source_type != AssetSourceType.PERSONAL_WORKSPACE:
            return None
        if asset_ref.asset.asset_type == AssetType.METRIC:
            return self._repository.get_metric_by_ref(asset_ref)
        if asset_ref.asset.asset_type == AssetType.SKILL:
            return self._repository.get_skill_by_ref(asset_ref)
        report = self._repository.get_report_by_ref(asset_ref)
        return _report_definition(report) if report is not None else None


def _ref(
    source_type: AssetSourceType,
    source_id: str,
    asset_type: AssetType,
    local_code: str,
    version: str,
) -> AssetRef:
    return AssetRef(
        asset=AssetKey(
            source_type=source_type,
            source_id=source_id,
            asset_type=asset_type,
            local_code=local_code,
        ),
        version=version,
    )


def _known_fields(model: type, payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key in model.model_fields}


def _matches(asset_ref: AssetRef | None, query: AssetQuery | None) -> bool:
    if asset_ref is None:
        return False
    if query is None:
        return True
    key = asset_ref.asset
    return (
        (not query.source_types or key.source_type in query.source_types)
        and (not query.source_ids or key.source_id in query.source_ids)
        and (not query.asset_types or key.asset_type in query.asset_types)
        and (query.local_code is None or key.local_code == query.local_code)
        and (query.version is None or asset_ref.version == query.version)
    )


def _descriptor(definition: AssetDefinition) -> AssetDescriptor:
    asset_ref = definition.asset_ref
    assert asset_ref is not None
    description = getattr(definition, "description", None)
    return AssetDescriptor(
        asset_ref=asset_ref,
        name=definition.name,
        description=description,
    )


def _report_definition(report: ReportRecord) -> ReportDefinition:
    return ReportDefinition(
        report_skill_id=report.report_id,
        namespace=(
            report.asset_ref.asset.source_id
            if report.asset_ref is not None
            else "personal"
        ),
        name=report.name,
        owner_user_id=report.owner,
        visibility=SkillVisibility(report.visibility),
        description=report.description,
        asset_ref=report.asset_ref,
        dependency_refs=report.dependency_refs,
    )


def _unique_refs(refs: list[AssetRef]) -> list[AssetRef]:
    unique: dict[tuple[str, str], AssetRef] = {}
    for ref in refs:
        unique[(ref.asset.asset_id, ref.version)] = ref
    return list(unique.values())
