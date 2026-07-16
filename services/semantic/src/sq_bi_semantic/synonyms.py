from __future__ import annotations

import re


def normalize_text(text: str) -> str:
    """Helper to lowercase and strip all whitespace and common punctuation."""
    if not text:
        return ""
    # Lowercase and remove all whitespace
    text = re.sub(r"\s+", "", text).lower()
    # Remove common Chinese/English punctuation for better match
    text = re.sub(r'[，。！？、；：“”‘’\'"`.,!?_()（）-]', "", text)
    return text


def match_synonyms(query: str, name: str, synonyms: list[str]) -> bool:
    """Check if the query matches the name or any of the synonyms exactly after normalization."""
    normalized_query = normalize_text(query)
    if not normalized_query:
        return False

    if normalized_query == normalize_text(name):
        return True

    for syn in synonyms:
        if normalized_query == normalize_text(syn):
            return True

    return False


def is_partial_match(query: str, name: str, synonyms: list[str]) -> bool:
    """Check if query is a substring of name/synonyms, or vice-versa, after normalization."""
    normalized_query = normalize_text(query)
    if not normalized_query:
        return False

    normalized_name = normalize_text(name)
    if normalized_query in normalized_name or normalized_name in normalized_query:
        return True

    for syn in synonyms:
        normalized_syn = normalize_text(syn)
        if normalized_query in normalized_syn or normalized_syn in normalized_query:
            return True

    return False
