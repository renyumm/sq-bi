"""Project activated enterprise-pack product assets into the product repository.

The runtime asset resolver already serves pack metrics and skills to the ask
flow straight from deployment bindings. Repository-backed surfaces (report
artifact generation, metric listings, workspace templates) still read from the
SQLite product store, so an activated pack must land there too. Projection is
keyed by the pack's asset identity (``enterprise_pack``/``pack_id``): re-runs
upsert in place and removal deletes exactly this pack's rows.
"""

from __future__ import annotations

import logging

from sq_bi_contracts.assets import AssetKey, AssetRef
from sq_bi_contracts.enterprise_pack import EnterprisePack
from sq_bi_contracts.enums import AssetSourceType, AssetType, MetricVisibility
from sq_bi_contracts.metrics import MetricDefinition

logger = logging.getLogger("sq_bi_runtime.pack_projection")


def _pack_asset_ref(pack: EnterprisePack, asset_type: AssetType, local_code: str) -> AssetRef:
    return AssetRef(
        asset=AssetKey(
            source_type=AssetSourceType.ENTERPRISE_PACK,
            source_id=pack.pack_id,
            asset_type=asset_type,
            local_code=local_code,
        ),
        version=pack.version,
    )


def build_pack_metric_definitions(pack: EnterprisePack, data_source_id: str) -> list[MetricDefinition]:
    metrics: list[MetricDefinition] = []
    for item in pack.draft.metrics:
        metrics.append(
            MetricDefinition(
                metric_code=item.metric_code,
                name=item.name,
                definition=item.definition,
                visibility=MetricVisibility.SHARED,
                formula=item.formula,
                data_source_id=data_source_id,
                owner=pack.pack_id,
                version=pack.version,
                synonyms=list(item.synonyms),
                asset_ref=_pack_asset_ref(pack, AssetType.METRIC, item.metric_code),
            )
        )
    return metrics


def build_pack_report_records(pack: EnterprisePack) -> list:
    from sq_bi_semantic.product_repository import ReportRecord

    reports: list[ReportRecord] = []
    for item in pack.draft.reports:
        reports.append(
            ReportRecord(
                report_id=item.report_id,
                name=item.name,
                description=item.description or item.name,
                visibility="shared",
                owner=pack.pack_id,
                outputTypes=["html"],
                flow=item.description or item.name,
                analysis_chain=[
                    {"order": 1, "label": "汇总报表绑定指标", "metrics": list(item.metric_codes)},
                ],
                version=pack.version,
                asset_ref=_pack_asset_ref(pack, AssetType.REPORT, item.report_id),
            )
        )
    return reports


def project_pack_assets(repo, pack: EnterprisePack, data_source_id: str) -> None:
    """Upsert the pack's metrics and reports into the product repository.

    Known limitation: a pack active on several data sources keeps the
    bindings of the most recently activated deployment.
    """
    repo.upsert_pack_assets(
        owner_user_id=pack.pack_id,
        metrics=build_pack_metric_definitions(pack, data_source_id),
        reports=build_pack_report_records(pack),
    )
    logger.info(
        "pack_projection.projected",
        extra={"pack_id": pack.pack_id, "data_source_id": data_source_id},
    )


def remove_pack_assets(repo, pack_id: str) -> None:
    repo.remove_pack_assets(
        source_type=AssetSourceType.ENTERPRISE_PACK.value,
        source_id=pack_id,
    )
    logger.info("pack_projection.removed", extra={"pack_id": pack_id})
