from __future__ import annotations

from threading import Lock
from typing import Any

from sq_bi_contracts.datasource import DataSourceConnectionConfig, DataSourceConnector

from .resource_pool import ResourcePool


class PostgreSQLConnector:
    """PostgreSQL implementation of DataSourceConnector.

    Requires: pip install psycopg2-binary  (optional dependency)
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
                    import psycopg2  # noqa: F401
                except ImportError as exc:
                    msg = (
                        "PostgreSQL connector requires 'psycopg2'. "
                        "Install it with: pip install sq-bi-runtime[postgres]"
                    )
                    raise ImportError(msg) from exc
                self._pool = ResourcePool(
                    lambda: psycopg2.connect(
                        host=self._config.host,
                        port=self._config.port,
                        dbname=self._config.database,
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
                    SELECT c.TABLE_NAME,
                           c.COLUMN_NAME,
                           c.DATA_TYPE,
                           c.IS_NULLABLE,
                           pg_catalog.col_description(
                             (quote_ident(c.TABLE_SCHEMA) || '.' || quote_ident(c.TABLE_NAME))::regclass::oid,
                             c.ORDINAL_POSITION
                           ) AS COMMENT
                    FROM INFORMATION_SCHEMA.COLUMNS c
                    WHERE c.TABLE_SCHEMA = COALESCE(%s, 'public')
                    ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
                    """,
                    (schema or "public",),
                )
                for table_name, column_name, data_type, is_nullable, comment in cur.fetchall():
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
                    "WHERE TABLE_SCHEMA = 'public' ORDER BY TABLE_NAME, ORDINAL_POSITION"
                )
                for table_name, column_name in cur.fetchall():
                    catalog.setdefault(str(table_name), []).append(str(column_name))
        return catalog

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None
