from __future__ import annotations

import pytest
from sq_bi_contracts.common import UserContext
from sq_bi_contracts.rls import RlsScopeMapping, RlsScopePolicy, RlsScopeResolved
from sq_bi_runtime.rls import apply_rls_to_sql, build_rls_middleware, resolve_scope

BASE_USER = UserContext(
    user_id="u_base",
    display_name="Base User",
    org_id="o1",
    role_ids=["base_user"],
)

ADMIN_USER = UserContext(
    user_id="u_admin",
    display_name="Admin",
    org_id="o1",
    role_ids=["admin"],
)

POLICY = RlsScopePolicy(
    policy_id="rls_1",
    data_source_id="ds_tms",
    mappings=[
        RlsScopeMapping(
            target_type="role",
            target_id="base_user",
            table_physical="fact_delivery",
            column_physical="factory_code",
            operator="=",
            value="'天津厂'",
        ),
    ],
    enabled=True,
)

ADMIN_BYPASS = {"admin"}


def test_resolve_scope_with_matching_role() -> None:
    resolved = resolve_scope(BASE_USER, POLICY, "fact_delivery")
    assert resolved.is_full_access is False
    assert len(resolved.predicates) == 1
    assert "factory_code = '天津厂'" in resolved.predicates[0]


def test_resolve_scope_admin_full_access() -> None:
    resolved = resolve_scope(ADMIN_USER, POLICY, "fact_delivery", bypass_roles=ADMIN_BYPASS)
    assert resolved.is_full_access is True
    assert resolved.predicates == []


def test_resolve_scope_no_mapping_fail_closed() -> None:
    user = UserContext(
        user_id="u_restricted",
        display_name="Restricted",
        org_id="o1",
        role_ids=["restricted_role"],
    )
    resolved = resolve_scope(user, POLICY, "fact_delivery")
    assert resolved.is_full_access is False
    assert resolved.predicates == []  # fail closed


def test_resolve_scope_unrelated_table() -> None:
    resolved = resolve_scope(BASE_USER, POLICY, "other_table")
    assert resolved.is_full_access is True


def test_apply_rls_adds_where_clause() -> None:
    resolved = resolve_scope(BASE_USER, POLICY, "fact_delivery")
    sql = "select factory_code, ontime_rate from fact_delivery"
    rewritten = apply_rls_to_sql(sql, resolved)
    assert "factory_code = '天津厂'" in rewritten


def test_apply_rls_combines_with_existing_where() -> None:
    resolved = resolve_scope(BASE_USER, POLICY, "fact_delivery")
    sql = "select factory_code, ontime_rate from fact_delivery where ontime_rate > 90"
    rewritten = apply_rls_to_sql(sql, resolved)
    assert "factory_code = '天津厂'" in rewritten
    assert "ontime_rate > 90" in rewritten


def test_apply_rls_pass_through_for_admin() -> None:
    resolved = resolve_scope(ADMIN_USER, POLICY, "fact_delivery", bypass_roles=ADMIN_BYPASS)
    sql = "select * from fact_delivery"
    rewritten = apply_rls_to_sql(sql, resolved)
    assert rewritten == sql


def test_apply_rls_fails_closed_on_empty_predicates() -> None:
    resolved = RlsScopeResolved(
        user_id="u_restricted",
        data_source_id="ds_tms",
        table_physical="fact_delivery",
        predicates=[],
        is_full_access=False,
    )
    with pytest.raises(ValueError, match="no scope mapping"):
        apply_rls_to_sql("select * from fact_delivery", resolved)


def test_rls_middleware_uses_policies() -> None:
    interceptor = build_rls_middleware([POLICY])
    sql = "select factory_code, ontime_rate from fact_delivery"
    rewritten = interceptor(sql, BASE_USER, "ds_tms")
    assert "factory_code = '天津厂'" in rewritten


def test_rls_middleware_passthrough_admin() -> None:
    interceptor = build_rls_middleware([POLICY], bypass_roles=ADMIN_BYPASS)
    sql = "select * from fact_delivery"
    rewritten = interceptor(sql, ADMIN_USER, "ds_tms")
    assert rewritten == sql


def test_rls_middleware_none_user_passthrough() -> None:
    interceptor = build_rls_middleware([POLICY])
    sql = "select * from fact_delivery"
    rewritten = interceptor(sql, None, "ds_tms")
    assert rewritten == sql


def test_rls_middleware_no_policy_passthrough() -> None:
    interceptor = build_rls_middleware([])
    sql = "select * from fact_delivery"
    rewritten = interceptor(sql, BASE_USER, "ds_unknown")
    assert rewritten == sql


def test_resolve_scope_user_mapping() -> None:
    """User-specific scope mapping (target_type='user') is applied."""
    from sq_bi_contracts.rls import RlsScopeMapping, RlsScopePolicy
    from sq_bi_contracts.common import UserContext
    from sq_bi_runtime.rls import resolve_scope
    policy = RlsScopePolicy(
        policy_id="p2",
        data_source_id="ds1",
        mappings=[
            RlsScopeMapping(
                target_type="user",
                target_id="u_specific",
                table_physical="fact_delivery",
                column_physical="plant_id",
                operator="=",
                value="'plant_A'",
            )
        ],
        enabled=True,
    )
    user = UserContext(user_id="u_specific", display_name="Specific", org_id="o1", role_ids=["user"])
    resolved = resolve_scope(user, policy, "fact_delivery")
    assert resolved.is_full_access is False
    assert any("plant_A" in p for p in resolved.predicates)


def test_rls_disabled_policy_passthrough() -> None:
    """Disabled policy → full access regardless of user roles."""
    from sq_bi_contracts.rls import RlsScopePolicy
    disabled_policy = POLICY.model_copy(update={"enabled": False})
    resolved = resolve_scope(BASE_USER, disabled_policy, "fact_delivery")
    assert resolved.is_full_access is True


def test_rls_multi_table_sql_rewrites_all_tables() -> None:
    """Middleware rewrites all tables present in a multi-table SQL query."""
    from sq_bi_contracts.rls import RlsScopeMapping, RlsScopePolicy
    from sq_bi_runtime.rls import build_rls_middleware
    policy = RlsScopePolicy(
        policy_id="p3",
        data_source_id="ds_tms",
        mappings=[
            RlsScopeMapping(
                target_type="role",
                target_id="base_user",
                table_physical="FACT_DELIVERY",
                column_physical="factory_code",
                operator="=",
                value="'天津厂'",
            ),
            RlsScopeMapping(
                target_type="role",
                target_id="base_user",
                table_physical="DIM_CARRIER",
                column_physical="region_code",
                operator="=",
                value="'north'",
            ),
        ],
        enabled=True,
    )
    interceptor = build_rls_middleware([policy])
    sql = "select f.factory_code, c.region_code from fact_delivery f join dim_carrier c on f.carrier_id = c.id"
    rewritten = interceptor(sql, BASE_USER, "ds_tms")
    assert "factory_code = '天津厂'" in rewritten
    assert "region_code = 'north'" in rewritten


def test_rls_middleware_fail_closed_on_restricted_table() -> None:
    """Middleware raises when restricted user has no predicate for a scoped table."""
    from sq_bi_contracts.rls import RlsScopeMapping, RlsScopePolicy
    from sq_bi_contracts.common import UserContext
    from sq_bi_runtime.rls import build_rls_middleware
    policy = RlsScopePolicy(
        policy_id="p4",
        data_source_id="ds_tms",
        mappings=[
            RlsScopeMapping(
                target_type="role",
                target_id="base_user",  # only for base_user, not for restricted_role
                table_physical="FACT_DELIVERY",
                column_physical="factory_code",
                operator="=",
                value="'天津厂'",
            ),
        ],
        enabled=True,
    )
    restricted = UserContext(user_id="u_r", display_name="R", org_id="o1", role_ids=["restricted_role"])
    interceptor = build_rls_middleware([policy])
    with pytest.raises(ValueError, match="RLS denied"):
        interceptor("select * from fact_delivery", restricted, "ds_tms")
