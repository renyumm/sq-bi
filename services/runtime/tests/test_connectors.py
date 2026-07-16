from __future__ import annotations

import pytest

from sq_bi_contracts.enums import DatabaseType
from sq_bi_contracts.datasource import DataSourceConnectionConfig


def test_factory_importable_without_optional_drivers() -> None:
    """The core factory module imports without any optional database drivers."""
    from sq_bi_runtime.connectors.factory import create_connector

    assert callable(create_connector)


def test_oracle_connector_importable() -> None:
    from sq_bi_runtime.connectors.oracle_connector import OracleConnector

    assert OracleConnector is not None


def test_mysql_connector_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "pymysql", None)
    from sq_bi_runtime.connectors.mysql_connector import MySQLConnector

    config = DataSourceConnectionConfig(
        data_source_id="ds1",
        name="MySQL Test",
        engine=DatabaseType.MYSQL,
        host="localhost",
        port=3306,
        database="test",
        username="user",
        password="pass",
    )
    connector = MySQLConnector(config)
    with pytest.raises(ImportError, match="pymysql"):
        connector.execute("select 1")


def test_pg_connector_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "psycopg2", None)
    from sq_bi_runtime.connectors.pg_connector import PostgreSQLConnector

    config = DataSourceConnectionConfig(
        data_source_id="ds2",
        name="PG Test",
        engine=DatabaseType.POSTGRESQL,
        host="localhost",
        port=5432,
        database="test",
        username="user",
        password="pass",
    )
    connector = PostgreSQLConnector(config)
    with pytest.raises(ImportError, match="psycopg2"):
        connector.execute("select 1")


def test_clickhouse_connector_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "clickhouse_connect", None)
    from sq_bi_runtime.connectors.clickhouse_connector import ClickHouseConnector

    config = DataSourceConnectionConfig(
        data_source_id="ds3",
        name="CH Test",
        engine=DatabaseType.CLICKHOUSE,
        host="localhost",
        port=8123,
        database="default",
        username="user",
        password="pass",
    )
    connector = ClickHouseConnector(config)
    with pytest.raises(ImportError, match="clickhouse-connect"):
        connector.execute("select 1")
