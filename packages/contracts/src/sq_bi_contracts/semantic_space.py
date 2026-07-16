"""Contracts for standalone semantic-space management: creation, the
refresh -> diff -> draft -> confirm -> publish lifecycle, and semantic-gap
detection (a field scanned but not adopted into any semantic space).

`SemanticSpace` and `SemanticField` themselves stay defined in
`semantic_profile` — a semantic space is a versioned overlay (field status,
scope) on top of the profile's discovered entities/fields, not a duplicate
copy of them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ContractModel
from .semantic_profile import SemanticField


class CreateSemanticSpaceRequest(ContractModel):
    data_source_id: str
    name: str
    description: str | None = None
    initial_tables: list[str] = Field(default_factory=list)


class ChangedFieldEntry(ContractModel):
    """One field whose profile metadata differs from what this space adopted."""

    field_id: str
    before: dict[str, object] = Field(default_factory=dict)
    after: dict[str, object] = Field(default_factory=dict)


class SemanticSpaceDiff(ContractModel):
    """Result of refreshing a semantic space: metadata diff, no mutation yet."""

    space_id: str
    new_fields: list[SemanticField] = Field(default_factory=list)
    removed_fields: list[SemanticField] = Field(default_factory=list)
    changed_fields: list[ChangedFieldEntry] = Field(default_factory=list)
    invalidated_fields: list[str] = Field(default_factory=list)


class PublishSemanticSpaceRequest(ContractModel):
    """Confirm a subset of a diff's new fields and publish a new version."""

    confirmed_suggestions: list[str] = Field(default_factory=list)
    published_by: str = "system"


class SemanticGapCandidate(ContractModel):
    """A field present in a connection's metadata but not adopted into any
    semantic space bound to the current question/context."""

    field_id: str
    physical_table: str
    physical_column: str
    business_name: str
    description: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    suggested_reason: str
    field_name: str | None = None
    table_name: str | None = None
    connection_id: str | None = None
    suggested_space_id: str | None = None


class GapLookupRequest(ContractModel):
    connection_id: str
    query: str


class FieldImpactReference(ContractModel):
    """One consumer (enterprise pack or deployment) referencing a field that
    was confirmed before a semantic-space publish and no longer is after —
    surfaced as publish-time impact analysis."""

    field_id: str
    physical_table: str
    physical_column: str
    kind: Literal["enterprise_pack", "deployment"]
    ref_id: str
    name: str


class PublishImpactSummary(ContractModel):
    """Publish-time impact analysis result: fields that lost confirmed status
    in this publish, and which packs/deployments referenced them."""

    space_id: str
    version: int
    lost_field_ids: list[str] = Field(default_factory=list)
    references: list[FieldImpactReference] = Field(default_factory=list)
