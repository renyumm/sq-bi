from __future__ import annotations

from sq_bi_runtime.edition import (
    COMMUNITY_FEATURES,
    ENTERPRISE_FEATURES,
    get_available_features,
    is_feature_enabled,
)


def test_community_has_basic_features() -> None:
    assert is_feature_enabled("ask_data", "community") is True
    assert is_feature_enabled("metrics", "community") is True
    assert is_feature_enabled("semantic_catalog", "community") is True


def test_community_missing_enterprise_features() -> None:
    assert is_feature_enabled("sso", "community") is False
    assert is_feature_enabled("row_level_security", "community") is False
    assert is_feature_enabled("push_channels", "community") is False


def test_enterprise_has_all_features() -> None:
    for feature in COMMUNITY_FEATURES:
        assert is_feature_enabled(feature, "enterprise") is True
    for feature in ENTERPRISE_FEATURES:
        assert is_feature_enabled(feature, "enterprise") is True


def test_get_available_features_community() -> None:
    features = get_available_features("community")
    assert "ask_data" in features
    assert "sso" not in features


def test_get_available_features_enterprise() -> None:
    features = get_available_features("enterprise")
    assert "sso" in features
    assert "push_channels" in features
