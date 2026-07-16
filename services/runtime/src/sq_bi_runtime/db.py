from __future__ import annotations

from contextlib import contextmanager
import os
from threading import Lock
from time import monotonic
from typing import Any

import oracledb

from .config import DBConfig
from .schema_catalog import SchemaCatalog, normalize_live_schema_rows


class OracleExecutor:
    def __init__(self, config: DBConfig) -> None:
        if not config.is_configured:
            raise ValueError("Database config is incomplete.")
        self.config = config
        self._pool: oracledb.ConnectionPool | None = None
        self._pool_lock = Lock()
        self._schema_description_cache: dict[tuple[int, int], tuple[float, str]] = {}
        self._schema_description_lock = Lock()

    def _get_pool(self) -> oracledb.ConnectionPool:
        if self._pool is not None:
            return self._pool
        with self._pool_lock:
            if self._pool is None:
                pool_min = max(1, int(self.config.pool_min))
                pool_max = max(pool_min, int(self.config.pool_max))
                pool_increment = max(1, int(self.config.pool_increment))
                self._pool = oracledb.create_pool(
                    user=self.config.user,
                    password=self.config.password,
                    dsn=self.config.dsn,
                    min=pool_min,
                    max=pool_max,
                    increment=pool_increment,
                    getmode=oracledb.POOL_GETMODE_TIMEDWAIT,
                    wait_timeout=max(1, int(self.config.pool_wait_timeout_ms)),
                    tcp_connect_timeout=max(0.5, float(self.config.tcp_connect_timeout_seconds)),
                    timeout=60,
                    ping_interval=60,
                )
            return self._pool

    @contextmanager
    def _connection(self):
        pool = self._get_pool()
        connection = pool.acquire()
        try:
            yield connection
        finally:
            connection.close()

    def close(self) -> None:
        with self._pool_lock:
            if self._pool is not None:
                self._pool.close()
                self._pool = None
        with self._schema_description_lock:
            self._schema_description_cache.clear()

    def execute(self, sql: str, max_rows: int = 200) -> dict[str, Any]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchmany(max_rows)
                columns = [col[0] for col in cursor.description] if cursor.description else []
        return {"columns": columns, "rows": rows}

    def get_schema_catalog(self, max_tables: int = 200, max_columns: int = 4000) -> SchemaCatalog:
        table_limit = max(1, int(max_tables))
        column_limit = max(1, int(max_columns))
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select c.table_name, c.column_name
                    from user_tab_columns c
                    where c.table_name in (
                      select table_name
                      from user_tables
                      order by table_name
                      fetch first {table_limit} rows only
                    )
                    order by c.table_name, c.column_id
                    fetch first {column_limit} rows only
                    """
                )
                return normalize_live_schema_rows(cursor.fetchall())

    def describe_schema(self, max_tables: int = 80, max_columns: int = 800) -> str:
        table_limit = max(1, int(max_tables))
        column_limit = max(1, int(max_columns))
        cache_key = (table_limit, column_limit)
        ttl_seconds = _schema_description_cache_ttl_seconds()
        if ttl_seconds > 0:
            now = monotonic()
            with self._schema_description_lock:
                cached = self._schema_description_cache.get(cache_key)
                if cached is not None and now - cached[0] <= ttl_seconds:
                    return cached[1]

        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select table_name, comments
                    from user_tab_comments
                    where table_type = 'TABLE'
                    order by table_name
                    fetch first {table_limit} rows only
                    """
                )
                table_comments = {
                    str(table_name): str(comments or "")
                    for table_name, comments in cursor.fetchall()
                }
                cursor.execute(
                    f"""
                    select c.table_name,
                           c.column_name,
                           c.data_type,
                           cc.comments
                    from user_tab_columns c
                    left join user_col_comments cc
                      on cc.table_name = c.table_name
                     and cc.column_name = c.column_name
                    where c.table_name in (
                      select table_name
                      from user_tables
                      order by table_name
                      fetch first {table_limit} rows only
                    )
                    order by c.table_name, c.column_id
                    fetch first {column_limit} rows only
                    """
                )
                rows = cursor.fetchall()

        lines = ["# Live Oracle Table And Field Comments"]
        current_table = ""
        for table_name, column_name, data_type, comments in rows:
            table_name = str(table_name)
            if table_name != current_table:
                current_table = table_name
                table_comment = table_comments.get(table_name) or "无表说明"
                lines.append(f"\n## {table_name} - {table_comment}")
            column_comment = str(comments or "无字段说明")
            lines.append(f"- {column_name} ({data_type}): {column_comment}")
        description = "\n".join(lines)
        if ttl_seconds > 0:
            with self._schema_description_lock:
                self._schema_description_cache[cache_key] = (monotonic(), description)
        return description


def _schema_description_cache_ttl_seconds() -> float:
    raw_value = os.getenv("SQ_BI_SCHEMA_DESCRIPTION_CACHE_TTL_SECONDS", "300")
    try:
        return max(0.0, float(raw_value))
    except ValueError:
        return 300.0
