from __future__ import annotations

from sq_bi_contracts.domain_pack import PackStandardField
from sq_bi_contracts.field_mount import ScopeCandidateTable
from sq_bi_contracts.semantic_profile import CatalogTableRecord, TableRecommendation

from .mounting_pipeline import PhysicalColumn, deterministic_match

# A table needs at least one standard-field candidate at or above this
# confidence to count as pack evidence. This mirrors mounting_pipeline's own
# _CONFIDENCE_CANDIDATE_MIN ("plausible candidate worth surfacing"), not
# CONFIDENCE_AUTO_APPLY ("safe to auto-apply without review") — table-scope
# decisions only gate whether a table is *considered*, not whether a field
# mapping is auto-applied, so the bar is intentionally low: an exact
# normalized field_id↔column match alone (no comment/enum corroboration)
# should already count as real pack evidence for a table.
_TABLE_MATCH_MIN_CONFIDENCE = 0.2


def recommend_scope_for_pack(
    standard_fields: list[PackStandardField],
    catalog_tables: list[CatalogTableRecord],
) -> list[ScopeCandidateTable]:
    """Score each scanned table's relevance to a pack's standard fields.

    Replaces the pack-agnostic "include every scanned table not classified
    not_relevant" default with pack-aware candidate scope, per
    .design/asset_semantic_space_harness_operating_model.md §2.3: a complex,
    multi-domain connection should get a generated candidate scope, with
    only the ambiguous part requiring admin confirmation — not every table
    silently swept into the implicit default space.

    Tiers:
      - recommended: matches >=1 pack standard field with real evidence, or
        (when the pack has zero textual signal anywhere in this schema) the
        table's generic scan classification is not not_relevant.
      - ambiguous: generic scan classification suggests possible relevance
        but no pack-specific evidence confirms it (or contradicts it).
      - excluded: explicitly excluded during scanning, or classified
        not_relevant with no pack evidence to override that.
    """
    table_matches: dict[str, list[str]] = {}
    for table in catalog_tables:
        if not standard_fields or not table.columns or table.excluded:
            continue
        columns = [
            PhysicalColumn(
                table=table.table_name,
                column=c.column_name,
                data_type=c.data_type or "",
                comment=c.comment or "",
            )
            for c in table.columns
        ]
        matched = [
            std_field.field_id
            for std_field in standard_fields
            if (best := deterministic_match(std_field, columns))
            and best[0].confidence >= _TABLE_MATCH_MIN_CONFIDENCE
        ]
        if matched:
            table_matches[table.table_name] = matched

    # No pack field textually matches anything in this schema at all: there
    # is no pack-specific signal to add, so fall back to the generic
    # classification wholesale rather than flagging everything ambiguous.
    has_any_pack_signal = bool(table_matches)

    results: list[ScopeCandidateTable] = []
    for table in catalog_tables:
        if table.excluded:
            results.append(ScopeCandidateTable(
                table_name=table.table_name,
                tier="excluded",
                reason="已在数据源扫描中标记为排除。",
            ))
            continue

        if not has_any_pack_signal:
            if table.classification == TableRecommendation.not_relevant:
                results.append(ScopeCandidateTable(
                    table_name=table.table_name,
                    tier="excluded",
                    reason="通用表分类判定为不相关。",
                ))
            else:
                results.append(ScopeCandidateTable(
                    table_name=table.table_name,
                    tier="recommended",
                    reason="扩展包字段与该数据源无文本匹配信号，采用通用表分类结果。",
                ))
            continue

        matched = table_matches.get(table.table_name, [])
        if matched:
            results.append(ScopeCandidateTable(
                table_name=table.table_name,
                tier="recommended",
                matched_field_ids=matched,
                reason=f"匹配到扩展包 {len(matched)} 个标准字段：{', '.join(matched)}。",
            ))
        elif table.classification == TableRecommendation.not_relevant:
            results.append(ScopeCandidateTable(
                table_name=table.table_name,
                tier="excluded",
                reason="通用表分类判定为不相关，且未匹配到该扩展包的任何标准字段。",
            ))
        else:
            results.append(ScopeCandidateTable(
                table_name=table.table_name,
                tier="ambiguous",
                reason="通用表分类判定可能相关，但未直接匹配到该扩展包的标准字段，需人工确认。",
            ))

    return results
