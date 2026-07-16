from __future__ import annotations

from dataclasses import dataclass, field

# ── Edition / Feature Gating ──────────────────────────────────────────

COMMUNITY_FEATURES: set[str] = {
    "ask_data",
    "metrics",
    "skills",
    "reports",
    "oracle_connector",
    "semantic_catalog",
    "basic_auth",
}

ENTERPRISE_FEATURES: set[str] = COMMUNITY_FEATURES | {
    "sso",
    "row_level_security",
    "advanced_audit",
    "audit_postgres_backend",
    "push_channels",
    "feature_gating_admin",
    "domain_pack_commercial",
    "license_validation",
}

ALL_FEATURES: set[str] = COMMUNITY_FEATURES | ENTERPRISE_FEATURES


@dataclass
class LicenseInfo:
    """Offline license information for enterprise edition."""

    edition: str = "community"  # "community" | "enterprise"
    features: set[str] = field(default_factory=set)
    licensed_to: str = ""
    expires_at: str = ""
    valid: bool = True


def is_feature_enabled(feature: str, edition: str = "community") -> bool:
    """Check if a feature is available in the given edition."""
    if edition == "enterprise":
        return feature in ENTERPRISE_FEATURES
    return feature in COMMUNITY_FEATURES


def get_available_features(edition: str = "community") -> set[str]:
    """Return the set of available features for the given edition."""
    if edition == "enterprise":
        return ENTERPRISE_FEATURES
    return COMMUNITY_FEATURES


# ── SSO extension point ──────────────────────────────────────────────

from typing import Protocol, runtime_checkable
from sq_bi_contracts.common import UserContext


@runtime_checkable
class SSOProvider(Protocol):
    """Protocol for pluggable SSO backends (OIDC/SAML/LDAP)."""

    def authenticate(self, token: str) -> UserContext | None: ...

    def get_login_url(self, redirect: str = "") -> str: ...


class PlaceholderSSOProvider:
    """Placeholder that raises NotImplementedError until SSO is configured."""

    def authenticate(self, token: str) -> UserContext | None:
        raise NotImplementedError("SSO is not configured. Use local authentication.")

    def get_login_url(self, redirect: str = "") -> str:
        raise NotImplementedError("SSO is not configured.")
