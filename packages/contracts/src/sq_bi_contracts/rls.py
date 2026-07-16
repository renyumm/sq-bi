from __future__ import annotations

from pydantic import Field

from .common import ContractModel


class RlsScopeMapping(ContractModel):
    """A single scope rule: role or user → physical column predicate."""

    target_type: str  # "role" | "user"
    target_id: str
    table_physical: str
    column_physical: str
    operator: str = "="
    value: str  # literal or a SQL fragment the rewriter plugs in
    description: str | None = None


class RlsScopePolicy(ContractModel):
    """Complete row-level scope policy for a data source."""

    policy_id: str
    data_source_id: str
    mappings: list[RlsScopeMapping] = Field(default_factory=list)
    enabled: bool = True


class RlsScopeResolved(ContractModel):
    """Resolved scope predicates for one user against one data source / table."""

    user_id: str
    data_source_id: str
    table_physical: str
    predicates: list[str] = Field(default_factory=list)
    is_full_access: bool = False
