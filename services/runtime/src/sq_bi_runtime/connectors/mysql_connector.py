from __future__ import annotations

from threading import Lock
from typing import Any

from sq_bi_contracts.datasource import DataSourceConnectionConfig, DataSourceConnector

from .resource_pool import ResourcePool


class MySQLConnector:
    """MySQL implementation of DataSourceConnector.

    Requires: pip install pymysql  (optional dependency)
    """

    def __init__(self, config: DataSourceConnectionConfig) -> None:
        self._config = config
        self._pool: ResourcePool | None = None
        self._pool_lock = Lock()

    def _get_pool(self) -> ResourcePool:
        if self._pool is None:
            with self._pool_lock:
                if self._pool is not None:
                    return self._pool
                try:
                    import pymysql  # noqa: F401
                except ImportError as exc:
                    msg = (
                        "MySQL connector requires 'pymysql'. "
                        "Install it with: pip install sq-bi-runtime[mysql]"
                    )
                    raise ImportError(msg) from exc
                self._pool = ResourcePool(
                    lambda: pymysql.connect(
                        host=self._config.host,
                        port=self._config.port,
                        database=self._config.database,
                        user=self._config.username,
                        password=self._config.password,
                        connect_timeout=int(self._config.connect_timeout_seconds or 5),
                    ),
                    min_size=int(self._config.extra.get("pool_min", 1)),
                    max_size=int(self._config.extra.get("pool_max", 4)),
                    acquire_timeout_seconds=int(self._config.extra.get("pool_wait_timeout_ms", 15000)) / 1000,
                )
                self._pool.warm()
        return self._pool

    def execute(self, sql: str, params: dict | None = None) -> list[dict]:
        with self._get_pool().acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                columns = [desc[0] for desc in cur.description] if cur.description else []
                rows = cur.fetchall()
                return [dict(zip(columns, row)) for row in rows]

    def describe_schema(self, schema: str | None = None) -> list[dict]:
        catalog: list[dict] = []
        with self._get_pool().acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT TABLE_NAME,
                           COLUMN_NAME,
                           COLUMN_TYPE,
                           COLUMN_COMMENT,
                           IS_NULLABLE
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = COALESCE(%s, DATABASE())
                    ORDER BY TABLE_NAME, ORDINAL_POSITION
                    """,
                    (schema or self._config.database,),
                )
                for table_name, column_name, data_type, comment, is_nullable in cur.fetchall():
                    catalog.append({
                        "table": table_name,
                        "column": column_name,
                        "data_type": data_type,
                        "comment": comment,
                        "nullable": str(is_nullable).upper() == "YES",
                    })
        return catalog

    def get_schema_catalog(self) -> dict[str, list[str]]:
        catalog: dict[str, list[str]] = {}
        with self._get_pool().acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME, ORDINAL_POSITION"
                )
                for table_name, column_name in cur.fetchall():
                    catalog.setdefault(str(table_name), []).append(str(column_name))
        return catalog

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None
