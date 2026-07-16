from __future__ import annotations

from typing import Callable

from sqlglot import exp, parse_one

from sq_bi_contracts.common import UserContext
from sq_bi_contracts.rls import RlsScopePolicy, RlsScopeResolved


def resolve_scope(
    user: UserContext,
    policy: RlsScopePolicy,
    table_physical: str,
    bypass_roles: set[str] | None = None,
) -> RlsScopeResolved:
    """Resolve scope predicates for a user against one table.

    Args:
        user: The requesting user.
        policy: The RLS policy for this data source.
        table_physical: Physical table name.
        bypass_roles: Role ids that bypass scope restrictions.

    Returns:
        is_full_access=True: user can see all data (bypass role or no mappings).
        predicates=[...]: user is scoped to these WHERE predicates.
        [] AND is_full_access=False: fail closed (denied).
    """
    if not policy.enabled:
        return RlsScopeResolved(
            user_id=user.user_id,
            data_source_id=policy.data_source_id,
            table_physical=table_physical,
            is_full_access=True,
        )

    user_role_ids = set(user.role_ids)

    if bypass_roles and user_role_ids & bypass_roles:
        return RlsScopeResolved(
            user_id=user.user_id,
            data_source_id=policy.data_source_id,
            table_physical=table_physical,
            is_full_access=True,
        )

    table_mappings = [
        m for m in policy.mappings if m.table_physical.upper() == table_physical.upper()
    ]

    if not table_mappings:
        return RlsScopeResolved(
            user_id=user.user_id,
            data_source_id=policy.data_source_id,
            table_physical=table_physical,
            is_full_access=True,
        )

    predicates: list[str] = []
    for mapping in table_mappings:
        if mapping.target_type == "role" and mapping.target_id in user_role_ids:
            predicates.append(f"{mapping.column_physical} {mapping.operator} {mapping.value}")
        elif mapping.target_type == "user" and mapping.target_id == user.user_id:
            predicates.append(f"{mapping.column_physical} {mapping.operator} {mapping.value}")

    return RlsScopeResolved(
        user_id=user.user_id,
        data_source_id=policy.data_source_id,
        table_physical=table_physical,
        predicates=predicates,
        is_full_access=False,
    )


def apply_rls_to_sql(sql: str, resolved: RlsScopeResolved, dialect: str = "oracle") -> str:
    """Rewrite SQL to inject row-level scope predicates."""
    if resolved.is_full_access:
        return sql

    if not resolved.predicates:
        msg = (
            f"User {resolved.user_id} has no scope mapping for "
            f"{resolved.data_source_id}.{resolved.table_physical}. "
            "Query denied (fail closed)."
        )
        raise ValueError(msg)

    try:
        tree = parse_one(sql, read=dialect)
    except Exception as exc:
        raise ValueError("RLS: Could not parse SQL for rewriting.") from exc

    if not isinstance(tree, (exp.Select, exp.Union)):
        return sql

    scope_condition = " AND ".join(resolved.predicates)

    for select in tree.find_all(exp.Select):
        where = select.args.get("where")
        if where is None:
            select.set("where", exp.Where(this=exp.condition(scope_condition)))
        else:
            combined = exp.And(this=where.this, expression=exp.condition(scope_condition))
            select.set("where", exp.Where(this=combined))

    return tree.sql(dialect=dialect)


def build_rls_middleware(
    policies: list[RlsScopePolicy],
    bypass_roles: set[str] | None = None,
) -> Callable[..., str]:
    """Factory: return an RLS interceptor for the given policy set."""

    def rls_interceptor(
        sql: str,
        user: UserContext | None,
        data_source_id: str,
        dialect: str = "oracle",
    ) -> str:
        if user is None:
            return sql

        policy: RlsScopePolicy | None = None
        for p in policies:
            if p.data_source_id == data_source_id and p.enabled:
                policy = p
                break

        if policy is None:
            return sql

        try:
            tree = parse_one(sql, read=dialect)
        except Exception:
            return sql

        tables = list(tree.find_all(exp.Table))
        rewritten = sql
        for table in tables:
            table_name = table.name.upper()
            resolved = resolve_scope(user, policy, table_name, bypass_roles=bypass_roles)
            if not resolved.is_full_access and not resolved.predicates:
                raise ValueError(
                    f"RLS denied: {user.user_id} has no mapping for "
                    f"{data_source_id}.{table_name}"
                )
            rewritten = apply_rls_to_sql(rewritten, resolved, dialect=dialect)
        return rewritten

    return rls_interceptor
