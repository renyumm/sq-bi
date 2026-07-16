"""Runtime semantic context retrieval.

Given a question, selects a small relevant subset of the semantic profile
(spaces, entities, fields) via name/synonym/keyword matching and renders a
compact "database semantic context" string for the ask pipeline.

Never sends the full profile to the model.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sq_bi_contracts.semantic_profile import (
    ProfileView,
    SemanticEntity,
    SemanticField,
    SemanticSpace,
)

logger = logging.getLogger(__name__)

_MAX_SPACES = 3
_MAX_ENTITIES_PER_SPACE = 5
_MAX_FIELDS_PER_ENTITY = 8
_MIN_SCORE = 0.1


@dataclass
class RelevanceScore:
    space: SemanticSpace
    entity: SemanticEntity
    field: SemanticField
    score: float


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase CJK characters and ASCII words."""
    tokens: set[str] = set()
    # ASCII words
    tokens.update(re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', text.lower()))
    # Individual CJK characters as tokens (single chars too short, use bigrams)
    cjk = re.findall(r'[一-鿿]', text)
    for i in range(len(cjk)):
        tokens.add(cjk[i])
        if i + 1 < len(cjk):
            tokens.add(cjk[i] + cjk[i + 1])
    return tokens


def _score_text(question_tokens: set[str], candidate: str) -> float:
    if not candidate:
        return 0.0
    cand_tokens = _tokenize(candidate)
    if not cand_tokens:
        return 0.0
    overlap = len(question_tokens & cand_tokens)
    return overlap / max(len(question_tokens), len(cand_tokens))


def _score_entity(question_tokens: set[str], entity: SemanticEntity) -> float:
    scores = [
        _score_text(question_tokens, entity.physical_table),
        _score_text(question_tokens, entity.business_name),
        _score_text(question_tokens, entity.description or ""),
    ]
    # Boost from field-level matches (column names, business names, synonyms)
    for field in entity.fields:
        scores.append(_score_field(question_tokens, field))
    return max(scores)


def _score_field(question_tokens: set[str], field: SemanticField) -> float:
    scores = [
        _score_text(question_tokens, field.physical_column),
        _score_text(question_tokens, field.business_name),
        _score_text(question_tokens, field.description or ""),
    ]
    for syn in field.synonyms:
        scores.append(_score_text(question_tokens, syn))
    return max(scores)


def retrieve_relevant_context(
    question: str,
    profile: ProfileView,
    *,
    max_spaces: int = _MAX_SPACES,
    max_entities_per_space: int = _MAX_ENTITIES_PER_SPACE,
    max_fields_per_entity: int = _MAX_FIELDS_PER_ENTITY,
    min_score: float = _MIN_SCORE,
) -> str:
    """Select the most relevant profile slice and render it as a text context string.

    Returns an empty string if the profile is empty or nothing matches.
    """
    if not profile.spaces:
        return ""

    question_tokens = _tokenize(question)
    if not question_tokens:
        return ""

    context_lines: list[str] = ["## 数据库语义上下文"]

    selected_spaces = 0
    for space in profile.spaces:
        if selected_spaces >= max_spaces:
            break

        relevant_entities: list[tuple[SemanticEntity, float]] = []
        for entity in space.entities:
            score = _score_entity(question_tokens, entity)
            if score >= min_score:
                relevant_entities.append((entity, score))

        if not relevant_entities:
            continue

        relevant_entities.sort(key=lambda x: x[1], reverse=True)
        relevant_entities = relevant_entities[:max_entities_per_space]

        context_lines.append(f"\n### 语义空间: {space.name}")
        if space.description:
            context_lines.append(f"  {space.description}")

        for entity, _ in relevant_entities:
            context_lines.append(f"\n#### 实体: {entity.business_name} ({entity.physical_table})")
            if entity.description:
                context_lines.append(f"  {entity.description}")

            # Score fields within entity
            relevant_fields = [
                (f, _score_field(question_tokens, f))
                for f in entity.fields
            ]
            relevant_fields.sort(key=lambda x: x[1], reverse=True)
            relevant_fields = relevant_fields[:max_fields_per_entity]

            for fld, _ in relevant_fields:
                origin_label = {
                    "standard": "标准",
                    "enterprise": "企业",
                    "inferred": "AI 推断",
                }.get(fld.origin.value, fld.origin.value)
                conf_str = f" (置信度: {fld.confidence:.0%})" if fld.confidence < 0.9 else ""
                syn_str = f" 别名: {', '.join(fld.synonyms[:3])}" if fld.synonyms else ""
                role_str = f" [{fld.semantic_role}]" if fld.semantic_role else ""
                context_lines.append(
                    f"  - {fld.business_name} ({fld.physical_column})"
                    f"{role_str}: 来源={origin_label}{conf_str}{syn_str}"
                )
                if fld.description:
                    context_lines.append(f"    {fld.description}")

        selected_spaces += 1

    if selected_spaces == 0:
        return ""

    return "\n".join(context_lines)


class SemanticRetriever:
    """Integrates semantic retrieval into the ask pipeline."""

    def __init__(self, profile_store: object) -> None:
        self._store = profile_store

    def get_context_for_question(
        self,
        question: str,
        data_source_id: str,
        **kwargs: object,
    ) -> str:
        """Retrieve and render semantic context for the given question."""
        if not hasattr(self._store, "load_profile"):
            return ""
        try:
            profile = self._store.load_profile(data_source_id)
            if not profile:
                return ""
            return retrieve_relevant_context(question, profile, **kwargs)  # type: ignore[arg-type]
        except Exception as exc:
            logger.warning(
                "semantic_retriever.get_context.failed",
                extra={"error": str(exc), "data_source_id": data_source_id},
            )
            return ""
