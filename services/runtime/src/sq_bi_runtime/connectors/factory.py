from __future__ import annotations

from sq_bi_contracts.datasource import DataSourceConnectionConfig, DataSourceConnector
from sq_bi_contracts.enums import DatabaseType


def build_connector(ds_record: dict) -> DataSourceConnector:
    """Build a connector from a datasource JSON-store record dict."""
    raw_engine = str(ds_record.get("database_type") or "oracle").lower()
    try:
        engine = DatabaseType(raw_engine)
    except ValueError:
        engine = DatabaseType.ORACLE

    cfg = DataSourceConnectionConfig(
        data_source_id=str(ds_record.get("data_source_id") or ""),
        name=str(ds_record.get("name") or ""),
        engine=engine,
        host=str(ds_record.get("host") or ""),
        port=int(ds_record.get("port") or 1521),
        database=str(ds_record.get("database") or ""),
        username=str(ds_record.get("username") or ""),
        password=str(ds_record.get("password") or ""),
        service_name=ds_record.get("service_name") or None,
        sid=ds_record.get("sid") or None,
        dsn=ds_record.get("dsn") or None,
        connect_timeout_seconds=ds_record.get("connect_timeout_seconds") or None,
        extra={
            "pool_min": str(ds_record.get("pool_min") or 1),
            "pool_max": str(ds_record.get("pool_max") or 4),
            "pool_wait_timeout_ms": str(ds_record.get("pool_wait_timeout_ms") or 15000),
        },
    )
    return create_connector(cfg)


def create_connector(config: DataSourceConnectionConfig) -> DataSourceConnector:
    """Factory: instantiate the right connector for the given engine type."""
    engine = config.engine

    if engine == DatabaseType.ORACLE:
        from .oracle_connector import OracleConnector

        return OracleConnector(config)

    if engine == DatabaseType.MYSQL:
        from .mysql_connector import MySQLConnector

        return MySQLConnector(config)

    if engine == DatabaseType.POSTGRESQL:
        from .pg_connector import PostgreSQLConnector

        return PostgreSQLConnector(config)

    if engine == DatabaseType.CLICKHOUSE:
        from .clickhouse_connector import ClickHouseConnector

        return ClickHouseConnector(config)

    msg = f"Unsupported database engine: {engine}"
    raise ValueError(msg)
