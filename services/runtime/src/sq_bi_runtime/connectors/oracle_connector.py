from __future__ import annotations

import re
from typing import Any

from sq_bi_contracts.datasource import DataSourceConnectionConfig, DataSourceConnector

from ..db import OracleExecutor
from ..config import DBConfig


def _build_oracle_dsn(config: DataSourceConnectionConfig) -> str:
    """Priority: explicit dsn > service_name > sid > database (legacy default).

    Easy-connect syntax has no distinct SID form, so ``sid`` is placed in the
    same slot as a service name — sufficient for MVP; a raw ``dsn`` override
    is available for anything the easy-connect builder can't express.
    """
    if config.dsn:
        return config.dsn
    if config.service_name:
        return f"{config.host}:{config.port}/{config.service_name}"
    if config.sid:
        return f"{config.host}:{config.port}/{config.sid}"
    return f"{config.host}:{config.port}/{config.database}"


class OracleConnector:
    """Oracle implementation of DataSourceConnector.

    Wraps the existing OracleExecutor to conform to the protocol.
    """

    def __init__(self, config: DataSourceConnectionConfig | DBConfig) -> None:
        if isinstance(config, DataSourceConnectionConfig):
            db_kwargs: dict[str, Any] = {
                "user": config.username,
                "password": config.password,
                "dsn": _build_oracle_dsn(config),
            }
            if config.connect_timeout_seconds is not None:
                db_kwargs["tcp_connect_timeout_seconds"] = config.connect_timeout_seconds
            db_kwargs["pool_min"] = int(config.extra.get("pool_min", 1))
            db_kwargs["pool_max"] = int(config.extra.get("pool_max", 4))
            db_kwargs["pool_wait_timeout_ms"] = int(config.extra.get("pool_wait_timeout_ms", 15000))
            self._db_config = DBConfig(**db_kwargs)
        else:
            self._db_config = config
        self._executor: OracleExecutor | None = None

    def _get_executor(self) -> OracleExecutor:
        if self._executor is None:
            self._executor = OracleExecutor(self._db_config)
        return self._executor

    def execute(self, sql: str, params: dict | None = None) -> list[dict]:
        result = self._get_executor().execute(sql)
        columns: list[str] = result.get("columns", [])
        rows: list[list[Any]] = result.get("rows", [])
        return [dict(zip(columns, row)) for row in rows]

    def describe_schema(self, schema: str | None = None) -> list[dict]:
        owner = str(schema or "").strip().upper()
        if owner and not re.fullmatch(r"[A-Z0-9_]+", owner):
            owner = ""
        if owner:
            sql = f"""
                SELECT c.table_name AS table_name,
                       c.column_name AS column_name,
                       c.data_type AS data_type,
                       c.nullable AS nullable,
                       cc.comments AS comments
                FROM all_tab_columns c
                LEFT JOIN all_col_comments cc
                  ON cc.owner = c.owner
                 AND cc.table_name = c.table_name
                 AND cc.column_name = c.column_name
                WHERE c.owner = '{owner}'
                ORDER BY c.table_name, c.column_id
            """
        else:
            sql = """
                SELECT c.table_name AS table_name,
                       c.column_name AS column_name,
                       c.data_type AS data_type,
                       c.nullable AS nullable,
                       cc.comments AS comments
                FROM user_tab_columns c
                LEFT JOIN user_col_comments cc
                  ON cc.table_name = c.table_name
                 AND cc.column_name = c.column_name
                ORDER BY c.table_name, c.column_id
            """
        result = self._get_executor().execute(sql, max_rows=5000)
        columns = [str(col).upper() for col in result.get("columns", [])]
        rows = result.get("rows", [])
        records: list[dict] = []
        for row in rows:
            item = dict(zip(columns, row))
            records.append({
                "table": item.get("TABLE_NAME"),
                "column": item.get("COLUMN_NAME"),
                "data_type": item.get("DATA_TYPE"),
                "comment": item.get("COMMENTS"),
                "nullable": item.get("NULLABLE") != "N",
            })
        return records

    def get_schema_catalog(self) -> dict[str, list[str]]:
        from ..schema_catalog import SchemaCatalog

        catalog: SchemaCatalog = self._get_executor().get_schema_catalog()
        return {table: list(columns) for table, columns in catalog.items()}

    def close(self) -> None:
        if self._executor is not None:
            self._executor.close()
            self._executor = None
