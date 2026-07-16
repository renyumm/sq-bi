from __future__ import annotations

from enum import Enum

from pydantic import Field

from .common import ContractModel


class AnswerPath(str, Enum):
    official = "official"
    enterprise = "enterprise"
    personal = "personal"
    ai_exploration = "ai_exploration"


class ConfidenceTier(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


# Ordered strongest → weakest; rank() encodes the ordering.
_JOIN_EVIDENCE_RANK: dict[str, int] = {
    "foreign_key": 0,
    "declared_relation": 1,
    "document": 2,
    "name_uniqueness_validated": 3,
    "llm_guess": 4,
}


class JoinEvidence(str, Enum):
    foreign_key = "foreign_key"
    declared_relation = "declared_relation"
    document = "document"
    name_uniqueness_validated = "name_uniqueness_validated"
    llm_guess = "llm_guess"

    def rank(self) -> int:
        """Lower rank = stronger evidence."""
        return _JOIN_EVIDENCE_RANK[self.value]

    def is_safe_for_aggregation(self) -> bool:
        """Anything stronger than a pure LLM guess is safe for aggregating Joins."""
        return self.rank() < _JOIN_EVIDENCE_RANK["llm_guess"]


class FieldAssumption(ContractModel):
    physical_table: str
    physical_column: str
    business_name: str
    inferred_meaning: str | None = None
    origin: str = "inferred"


class JoinAssumption(ContractModel):
    left_table: str
    right_table: str
    join_key: str
    evidence: JoinEvidence
    note: str | None = None


class QueryAssumption(ContractModel):
    fields_used: list[FieldAssumption] = Field(default_factory=list)
    aggregation: str | None = None
    time_field: str | None = None
    time_grain: str | None = None
    filters: list[str] = Field(default_factory=list)
    joins: list[JoinAssumption] = Field(default_factory=list)
    best_join_evidence: JoinEvidence | None = None
    caliber_label: str = "企业数据库字段，非官方标准口径"

    def worst_join_evidence(self) -> JoinEvidence | None:
        """Return the weakest Join evidence in the plan (the gating evidence)."""
        if not self.joins:
            return None
        return max(self.joins, key=lambda j: j.evidence.rank()).evidence

    def join_safe_for_aggregation(self) -> bool:
        """True when every Join in the plan is safe for aggregating queries."""
        worst = self.worst_join_evidence()
        return worst is None or worst.is_safe_for_aggregation()


class ClarificationOption(ContractModel):
    label: str
    description: str | None = None
    interpretation: str


class ClarificationRequest(ContractModel):
    question: str
    options: list[ClarificationOption] = Field(default_factory=list)


class SaveExplorationAsMetricRequest(ContractModel):
    business_name: str
    definition: str
    data_source_id: str
    entity: str | None = None
    aggregation: str
    time_field: str | None = None
    filters: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    field_mapping: list[FieldAssumption] = Field(default_factory=list)
    sql: str | None = None
    lineage: dict[str, object] = Field(default_factory=dict)
    test_result: str | None = None
    visibility: str = "private"
    user_id: str = "anonymous"
    target_pack_id: str | None = None
    environment: str = "default"
    semantic_space_ids: list[str] = Field(default_factory=list)
    execution_provenance: dict[str, object] = Field(default_factory=dict)
