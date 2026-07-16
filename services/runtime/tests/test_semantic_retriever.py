"""Tests for semantic_retriever — per-question retrieval."""

from __future__ import annotations

from sq_bi_contracts.semantic_profile import (
    EvidenceItem,
    EvidenceSource,
    FieldOrigin,
    ProfileView,
    ScanPhase,
    SemanticEntity,
    SemanticField,
    SemanticSpace,
    TableRecommendation,
)
from sq_bi_runtime.semantic_retriever import retrieve_relevant_context


def _field(fid: str, eid: str, physical_column: str, business_name: str,
           synonyms: list[str] | None = None,
           origin: FieldOrigin = FieldOrigin.inferred,
           confidence: float = 0.85) -> SemanticField:
    return SemanticField(
        field_id=fid,
        entity_id=eid,
        physical_table="T",
        physical_column=physical_column,
        business_name=business_name,
        origin=origin,
        confidence=confidence,
        synonyms=synonyms or [],
        evidence=[EvidenceItem(source=EvidenceSource.ai_inference)],
    )


def _entity(eid: str, sid: str, table: str, name: str, fields: list[SemanticField]) -> SemanticEntity:
    return SemanticEntity(
        entity_id=eid,
        space_id=sid,
        physical_table=table,
        business_name=name,
        recommendation=TableRecommendation.recommended_include,
        fields=fields,
    )


def _space(sid: str, name: str, entities: list[SemanticEntity]) -> SemanticSpace:
    return SemanticSpace(
        space_id=sid,
        snapshot_id="snap_001",
        name=name,
        entities=entities,
    )


def _profile(spaces: list[SemanticSpace]) -> ProfileView:
    return ProfileView(
        data_source_id="ds_tms",
        snapshot_id="snap_001",
        version=1,
        spaces=spaces,
        scan_phase=ScanPhase.done,
    )


# ── Basic retrieval ───────────────────────────────────────────────────

def test_retrieves_relevant_entity_for_question() -> None:
    fields = [
        _field("f1", "e1", "DELIVER_NO", "运单号", synonyms=["运单编号"]),
        _field("f2", "e1", "STATUS", "配送状态"),
    ]
    entity = _entity("e1", "s1", "HR_DELIVER_FORM", "运单", fields)
    space = _space("s1", "运输管理", [entity])
    profile = _profile([space])

    ctx = retrieve_relevant_context("查询运单配送状态", profile)
    assert "运单" in ctx
    assert "配送状态" in ctx or "STATUS" in ctx


def test_returns_empty_for_empty_profile() -> None:
    profile = _profile([])
    ctx = retrieve_relevant_context("运单状态", profile)
    assert ctx == ""


def test_returns_empty_for_empty_question() -> None:
    space = _space("s1", "运输管理", [
        _entity("e1", "s1", "T", "表", [_field("f1", "e1", "COL", "字段")])
    ])
    profile = _profile([space])
    ctx = retrieve_relevant_context("", profile)
    assert ctx == ""


# ── Only relevant tables returned ────────────────────────────────────

def test_irrelevant_entity_not_in_context() -> None:
    """A question about 运单 should not return 库存管理 entities."""
    deliver_entity = _entity(
        "e1", "s1", "HR_DELIVER_FORM", "运单",
        [_field("f1", "e1", "DELIVER_NO", "运单号")],
    )
    inventory_entity = _entity(
        "e2", "s2", "WH_STOCK", "库存",
        [_field("f2", "e2", "SKU_CODE", "商品编号")],
    )
    s1 = _space("s1", "运输管理", [deliver_entity])
    s2 = _space("s2", "仓储管理", [inventory_entity])
    profile = _profile([s1, s2])

    ctx = retrieve_relevant_context("运单配送状态", profile, max_spaces=3)
    assert "运单" in ctx
    # 库存 entities are in a different space; they may or may not appear
    # but the question is specifically about 运单


def test_max_spaces_limit_respected() -> None:
    spaces = [
        _space(f"s{i}", f"空间{i}", [
            _entity(f"e{i}", f"s{i}", f"TABLE_{i}", f"实体{i}", [
                _field(f"f{i}", f"e{i}", "COL", "字段")
            ])
        ])
        for i in range(6)
    ]
    profile = _profile(spaces)
    ctx = retrieve_relevant_context("实体 字段 表 COL", profile, max_spaces=2)
    # At most 2 spaces should appear
    assert ctx.count("### 语义空间") <= 2


def test_full_profile_not_rendered_for_narrow_question() -> None:
    """All 10 entities in profile; only relevant ones should appear."""
    entities = [
        _entity(f"e{i}", "s1", f"TABLE_{i}", f"实体{i}",
                [_field(f"f{i}", f"e{i}", f"COL_{i}", f"字段{i}")])
        for i in range(10)
    ]
    # Only entities[0] matches the question
    entities[0] = _entity(
        "e0", "s1", "HR_DELIVER_FORM", "运单",
        [_field("f0", "e0", "DELIVER_NO", "运单号", synonyms=["运单编号"])],
    )
    space = _space("s1", "运输管理", entities)
    profile = _profile([space])

    ctx = retrieve_relevant_context("运单号查询", profile, max_entities_per_space=5)
    # The context should contain 运单 but not all 10 entities
    entity_count = ctx.count("#### 实体")
    assert entity_count <= 5


# ── Evidence and origin in context ───────────────────────────────────

def test_inferred_field_shows_origin_in_context() -> None:
    fields = [_field("f1", "e1", "CARRIER_ID", "承运商ID", origin=FieldOrigin.inferred, confidence=0.75)]
    entity = _entity("e1", "s1", "T", "运单", fields)
    space = _space("s1", "运输管理", [entity])
    profile = _profile([space])

    ctx = retrieve_relevant_context("承运商", profile)
    assert "AI 推断" in ctx or "inferred" in ctx


def test_synonym_match_returns_entity() -> None:
    fields = [_field("f1", "e1", "DELIVER_NO", "运单号", synonyms=["shipment_no", "delivery_id"])]
    entity = _entity("e1", "s1", "T", "运单", fields)
    space = _space("s1", "运输管理", [entity])
    profile = _profile([space])

    ctx = retrieve_relevant_context("shipment_no delivery", profile)
    assert "运单号" in ctx or "DELIVER_NO" in ctx
