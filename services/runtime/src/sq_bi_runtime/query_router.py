from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sq_bi_contracts.exploration import AnswerPath
from sq_bi_contracts.metrics import MetricDefinition
from sq_bi_contracts.enums import MetricVisibility
from sq_bi_contracts.runtime_projection import ResolvedRuntimeAsset

if TYPE_CHECKING:
    from sq_bi_semantic.interfaces import MetricRepository


@dataclass
class RouteResult:
    answer_path: AnswerPath
    matched_metric: MetricDefinition | None = None
    data_source_id: str | None = None
    selected_asset: ResolvedRuntimeAsset | None = None


class QueryRouter:
    """Classify a question into official / enterprise / ai_exploration.

    Resolution order:
      1. Official metrics (MetricVisibility.OFFICIAL) for this data source.
      2. Enterprise/private metrics (non-OFFICIAL) for this data source.
      3. ai_exploration fallback.

    Matching uses synonym + partial match from sq_bi_semantic, keeping routing
    deterministic (no LLM call) and cheap.
    """

    def __init__(self, metric_repo: MetricRepository) -> None:
        self._repo = metric_repo

    def route(self, question: str, data_source_id: str | None = None) -> RouteResult:
        from sq_bi_semantic.synonyms import match_synonyms, is_partial_match

        list_assets = getattr(type(self._repo), "list_resolved_assets", None)
        resolved_assets: list[ResolvedRuntimeAsset] = (
            self._repo.list_resolved_assets() if callable(list_assets) else []
        )
        asset_by_definition_id = {id(asset.definition): asset for asset in resolved_assets}
        all_metrics = (
            [asset.definition for asset in resolved_assets if isinstance(asset.definition, MetricDefinition)]
            if resolved_assets
            else self._repo.list_metrics()
        )

        # Scope to data_source_id when provided.
        if data_source_id:
            all_metrics = [m for m in all_metrics if m.data_source_id == data_source_id]

        # Pass 1: official metrics
        for metric in all_metrics:
            if metric.visibility != MetricVisibility.OFFICIAL:
                continue
            if self._matches(question, metric, match_synonyms, is_partial_match):
                return RouteResult(
                    answer_path=AnswerPath.official,
                    matched_metric=metric,
                    data_source_id=data_source_id,
                    selected_asset=asset_by_definition_id.get(id(metric)),
                )

        # Pass 2: enterprise / private metrics
        for metric in all_metrics:
            if metric.visibility == MetricVisibility.OFFICIAL:
                continue
            if self._matches(question, metric, match_synonyms, is_partial_match):
                return RouteResult(
                    answer_path=AnswerPath.enterprise,
                    matched_metric=metric,
                    data_source_id=data_source_id,
                    selected_asset=asset_by_definition_id.get(id(metric)),
                )

        return RouteResult(answer_path=AnswerPath.ai_exploration, data_source_id=data_source_id)

    @staticmethod
    def _matches(
        question: str,
        metric: MetricDefinition,
        match_synonyms_fn,  # noqa: ANN001
        is_partial_match_fn,  # noqa: ANN001
    ) -> bool:
        synonyms = list(metric.synonyms or [])
        name = metric.name or ""
        return match_synonyms_fn(question, name, synonyms) or is_partial_match_fn(
            question, name, synonyms
        )
