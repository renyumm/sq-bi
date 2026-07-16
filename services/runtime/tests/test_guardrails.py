import pytest

from sq_bi_runtime.guardrails import SQLValidationError, validate_sql


def test_validate_sql_accepts_main_chain_query() -> None:
    sql = """
    select count(distinct f.deliver_no) as shipment_cnt
    from hr_deliver_form f
    join hr_deliver_carry c
      on f.deliver_no = c.deliver_no
    where c.car_status = '3'
    """
    result = validate_sql(sql)
    assert "HR_DELIVER_FORM" in result.tables
    assert "HR_DELIVER_CARRY" in result.tables


def test_validate_sql_accepts_carry_project_business_key() -> None:
    sql = """
    select p.delivery_factory, count(distinct c.deliver_no) as delayed_cnt
    from hr_deliver_carry c
    join hr_project_base p
      on p.id = c.project_id
    where c.plan_time is not null
      and c.actual_time > c.plan_time
    group by p.delivery_factory
    """
    result = validate_sql(sql)
    assert "HR_PROJECT_BASE" in result.tables
    assert "HR_DELIVER_CARRY" in result.tables


def test_validate_sql_allows_broad_select_table_coverage() -> None:
    result = validate_sql("select * from dual")
    assert result.tables == ["DUAL"]


def test_validate_sql_allows_select_star_for_exploration() -> None:
    result = validate_sql("select * from hr_deliver_form")
    assert result.tables == ["HR_DELIVER_FORM"]


def test_validate_sql_allows_unmodeled_select_join() -> None:
    sql = """
    select p.project_name
    from hr_project_base p
    join hr_deliver_form f
      on p.project_name = f.carrier_name
    """
    result = validate_sql(sql)
    assert result.tables == ["HR_PROJECT_BASE", "HR_DELIVER_FORM"]


def test_validate_sql_rejects_multiple_statements_after_trailing_semicolon() -> None:
    with pytest.raises(SQLValidationError):
        validate_sql("select id from hr_deliver_form; delete from hr_deliver_form")


def test_validate_sql_rejects_cross_schema_when_allowed_schema_is_configured() -> None:
    with pytest.raises(SQLValidationError):
        validate_sql("select table_name from sys.dba_tables", allowed_schemas=("TMS_ORACLE",))


def test_validate_sql_accepts_current_connection_schema_prefix() -> None:
    result = validate_sql(
        "select f.deliver_no from tms_oracle.hr_deliver_form f",
        allowed_schemas=("TMS_ORACLE",),
    )
    assert result.tables == ["HR_DELIVER_FORM"]
    assert "tms_oracle." not in result.sql.lower()


def test_validate_sql_adds_default_row_limit() -> None:
    result = validate_sql("select f.deliver_no from hr_deliver_form f")
    assert "fetch first 200 rows only" in result.sql.lower()


def test_validate_sql_keeps_existing_row_limit() -> None:
    result = validate_sql("select f.deliver_no from hr_deliver_form f fetch first 10 rows only")
    assert "fetch first 10 rows only" in result.sql.lower()
    assert "fetch first 200 rows only" not in result.sql.lower()


@pytest.mark.parametrize("column", ["region", "area"])
def test_validate_sql_rejects_unknown_physical_column_with_schema_catalog(column: str) -> None:
    schema_catalog = {
        "RFQ_ENQUIRY_INFO": {"ENQUIRY_NO", "PROJECT_ID", "CREATED_TIME"},
    }
    with pytest.raises(SQLValidationError, match=f"RFQ_ENQUIRY_INFO.{column.upper()}"):
        validate_sql(
            f"select ei.{column}, count(distinct ei.enquiry_no) as enquiry_cnt from rfq_enquiry_info ei group by ei.{column}",
            schema_catalog=schema_catalog,
        )


def test_validate_sql_accepts_known_columns_with_schema_catalog() -> None:
    schema_catalog = {
        "RFQ_ENQUIRY_INFO": {"ENQUIRY_NO", "PROJECT_ID", "CREATED_TIME"},
    }
    result = validate_sql(
        "select e.project_id, count(distinct e.enquiry_no) as enquiry_cnt from rfq_enquiry_info e group by e.project_id",
        schema_catalog=schema_catalog,
    )
    assert result.tables == ["RFQ_ENQUIRY_INFO"]


# ─── Dialect matrix tests (Task 2.5) ───────────────────────────────

DIALECTS = ["oracle", "mysql", "postgres", "clickhouse"]


@pytest.mark.parametrize("dialect", DIALECTS)
def test_validate_sql_accepts_select_across_dialects(dialect: str) -> None:
    sql = "select id, name from users where status = 'active'"
    result = validate_sql(sql, dialect=dialect)
    assert "USERS" in result.tables


@pytest.mark.parametrize("dialect", DIALECTS)
def test_validate_sql_rejects_dml_across_dialects(dialect: str) -> None:
    with pytest.raises(SQLValidationError, match="Only read-only SELECT"):
        validate_sql("delete from users", dialect=dialect)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_validate_sql_rejects_multi_statement_across_dialects(dialect: str) -> None:
    with pytest.raises(SQLValidationError, match="single SQL statement"):
        validate_sql("select 1; select 2", dialect=dialect)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_validate_sql_rejects_ddl_across_dialects(dialect: str) -> None:
    with pytest.raises(SQLValidationError, match="Only read-only SELECT"):
        validate_sql("drop table users", dialect=dialect)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_ensure_row_limit_dialect_specific(dialect: str) -> None:
    from sq_bi_runtime.guardrails import ensure_row_limit

    sql = "select id from users"
    limited = ensure_row_limit(sql, dialect=dialect)
    if dialect == "oracle":
        assert "fetch first" in limited.lower()
    else:
        assert limited.lower().strip().endswith("limit 200")


@pytest.mark.parametrize("dialect", DIALECTS)
def test_column_validation_works_with_dialect_scoped_catalog(dialect: str) -> None:
    schema_catalog = {"USERS": {"ID", "NAME", "STATUS"}}
    result = validate_sql(
        "select id, name from users where status = 'active'",
        schema_catalog=schema_catalog,
        dialect=dialect,
    )
    assert result.tables == ["USERS"]
    assert "users" in result.sql.lower()


@pytest.mark.parametrize("dialect", DIALECTS)
def test_dialect_rejects_unknown_column(dialect: str) -> None:
    schema_catalog = {"USERS": {"ID", "NAME"}}
    with pytest.raises(SQLValidationError, match="Column not found"):
        validate_sql(
            "select id, nonexistent from users",
            schema_catalog=schema_catalog,
            dialect=dialect,
        )
