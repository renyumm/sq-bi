from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field

from .common import ContractModel
from .metrics import MetricFormula


class PackCreateMode(str, Enum):
    extend_official = "extend_official"
    blank = "blank"


class PackVersionState(str, Enum):
    draft = "draft"
    published = "published"


class ExtensionLayerState(str, Enum):
    """The reversible lifecycle of the one additive layer owned by a pack."""

    draft = "draft"
    active = "active"
    inactive = "inactive"
    archived = "archived"


class PackEntity(ContractModel):
    entity_id: str
    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    source: str = "enterprise"


class PackEnterpriseField(ContractModel):
    """A portable standard field owned by an enterprise delta.

    Physical columns belong to a deployment mapping, never this definition.
    The historic class name is retained for API compatibility.
    """
    field_id: str
    business_name: str
    data_type: str
    description: str | None = None
    entity_id: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    source: str = "enterprise"


class PackTerm(ContractModel):
    term_id: str
    term: str
    definition: str
    synonyms: list[str] = Field(default_factory=list)
    related_field_ids: list[str] = Field(default_factory=list)


class PackAcceptanceQuestion(ContractModel):
    question_id: str
    question: str
    expected_metric_code: str | None = None
    expected_answer_hint: str | None = None


class PackEnterpriseMetric(ContractModel):
    metric_code: str
    name: str
    definition: str
    formula: MetricFormula
    entity_id: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    source: str = "enterprise"


class PackSkillStep(ContractModel):
    step_id: str
    description: str
    metric_codes: list[str] = Field(default_factory=list)
    dimension_field_ids: list[str] = Field(default_factory=list)


class PackSkill(ContractModel):
    skill_id: str
    name: str
    description: str | None = None
    steps: list[PackSkillStep] = Field(default_factory=list)


class PackReport(ContractModel):
    report_id: str
    name: str
    description: str | None = None
    metric_codes: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)


class EnterprisePackDraft(ContractModel):
    entities: list[PackEntity] = Field(default_factory=list)
    fields: list[PackEnterpriseField] = Field(default_factory=list)
    metrics: list[PackEnterpriseMetric] = Field(default_factory=list)
    skills: list[PackSkill] = Field(default_factory=list)
    reports: list[PackReport] = Field(default_factory=list)
    terms: list[PackTerm] = Field(default_factory=list)
    acceptance_questions: list[PackAcceptanceQuestion] = Field(default_factory=list)


class EnterprisePack(ContractModel):
    pack_id: str
    name: str
    description: str | None = None
    business_context: str | None = None
    version: str = "0.1.0"
    version_state: PackVersionState = PackVersionState.draft
    base_pack_id: str | None = None
    base_pack_version: str | None = None
    legacy_review_required: bool = False
    legacy_authoring_evidence: dict[str, object] = Field(default_factory=dict)
    create_mode: PackCreateMode = PackCreateMode.blank
    draft: EnterprisePackDraft = Field(default_factory=EnterprisePackDraft)
    created_by: str = "system"
    created_at: str | None = None
    updated_at: str | None = None


class PackExtensionLayer(ContractModel):
    """An additive, non-top-level layer attached to exactly one base pack.

    ``base_kind`` keeps the identity unambiguous: a base can be either an
    official registry pack or a standalone enterprise pack.  The draft only
    contains additions; callers must resolve it with the pinned base version.
    """

    extension_id: str
    base_pack_id: str
    base_pack_version: str
    base_kind: Literal["official", "enterprise"]
    version: str = "0.1.0"
    version_state: PackVersionState = PackVersionState.draft
    state: ExtensionLayerState = ExtensionLayerState.draft
    draft: EnterprisePackDraft = Field(default_factory=EnterprisePackDraft)
    audit: list[dict[str, object]] = Field(default_factory=list)
    created_by: str = "system"
    created_at: str | None = None
    updated_at: str | None = None


class EffectiveDomainPackAsset(ContractModel):
    """Effective browser/runtime asset with base-versus-extension provenance."""

    asset_id: str
    name: str
    asset_type: Literal["field", "metric", "skill", "report"]
    source: Literal["base", "extension"]
    definition: dict[str, object] = Field(default_factory=dict)


class EffectiveDomainPack(ContractModel):
    """Read-only computed content for a base pack and its optional layer."""

    base_pack_id: str
    base_pack_version: str
    base_kind: Literal["official", "enterprise"]
    extension_layer: PackExtensionLayer | None = None
    fields: list[EffectiveDomainPackAsset] = Field(default_factory=list)
    metrics: list[EffectiveDomainPackAsset] = Field(default_factory=list)
    skills: list[EffectiveDomainPackAsset] = Field(default_factory=list)
    reports: list[EffectiveDomainPackAsset] = Field(default_factory=list)


class CreateEnterprisePackRequest(ContractModel):
    name: str
    description: str | None = None
    business_context: str | None = None
    mode: PackCreateMode = PackCreateMode.blank
    base_pack_id: str | None = None
    base_pack_version: str | None = None
    created_by: str = "system"


class PackDraftRequest(ContractModel):
    data_source_id: str
    pack_id: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    user_id: str = "system"


class PublishPackRequest(ContractModel):
    version: str | None = None
    published_by: str = "system"


class PackDraftResult(ContractModel):
    draft: EnterprisePackDraft
    dropped_fields: list[str] = Field(default_factory=list)
    rejected_metrics: list[str] = Field(default_factory=list)
    rejection_reasons: dict[str, str] = Field(default_factory=dict)


# ── Effective extension view (official-pack-extension-layer) ───────────


class EffectivePackAssetRef(ContractModel):
    """One asset in an extension's effective (base + delta) content, with
    provenance so the editor/resolver can render the official base as
    read-only and enterprise additions as editable."""

    asset_id: str
    name: str
    source: Literal["official", "enterprise"]


class EffectivePackView(ContractModel):
    """An extension's read-only official base followed by its editable
    enterprise additions. Computed on demand from the immutable official
    manifest plus the enterprise draft — never persisted, never copied
    into the enterprise pack definition."""

    pack_id: str
    base_pack_id: str | None = None
    base_pack_version: str | None = None
    base_standard_fields: list[EffectivePackAssetRef] = Field(default_factory=list)
    enterprise_standard_fields: list[EffectivePackAssetRef] = Field(default_factory=list)
    base_metrics: list[EffectivePackAssetRef] = Field(default_factory=list)
    enterprise_metrics: list[EffectivePackAssetRef] = Field(default_factory=list)
    base_skills: list[EffectivePackAssetRef] = Field(default_factory=list)
    enterprise_skills: list[EffectivePackAssetRef] = Field(default_factory=list)
    base_reports: list[EffectivePackAssetRef] = Field(default_factory=list)
    enterprise_reports: list[EffectivePackAssetRef] = Field(default_factory=list)
