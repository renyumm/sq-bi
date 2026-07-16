from __future__ import annotations

from threading import Lock
from typing import Any

from sq_bi_contracts.datasource import DataSourceConnectionConfig, DataSourceConnector


class ClickHouseConnector:
    """ClickHouse implementation of DataSourceConnector.

    Requires: pip install clickhouse-connect  (optional dependency)
    """

    def __init__(self, config: DataSourceConnectionConfig) -> None:
        self._config = config
        self._client: Any = None
        self._client_lock = Lock()

    def _connect(self) -> Any:
        if self._client is None:
            with self._client_lock:
                if self._client is not None:
                    return self._client
                try:
                    import clickhouse_connect  # noqa: F401
                except ImportError as exc:
                    msg = (
                        "ClickHouse connector requires 'clickhouse-connect'. "
                        "Install it with: pip install sq-bi-runtime[clickhouse]"
                    )
                    raise ImportError(msg) from exc
                # clickhouse-connect uses an HTTP connection pool internally;
                # keeping one client per datasource preserves that pool.
                self._client = clickhouse_connect.get_client(
                    host=self._config.host,
                    port=self._config.port,
                    database=self._config.database,
                    username=self._config.username,
                    password=self._config.password,
                )
        return self._client

    def execute(self, sql: str, params: dict | None = None) -> list[dict]:
        client = self._connect()
        result = client.query(sql, parameters=params or {})
        columns = [str(col) for col in result.column_names] if hasattr(result, "column_names") else []
        rows = result.result_rows if hasattr(result, "result_rows") else []
        return [dict(zip(columns, row)) for row in rows]

    def describe_schema(self, schema: str | None = None) -> list[dict]:
        client = self._connect()
        catalog: list[dict] = []
        database = schema or self._config.database
        for table_name in client.query(f"SHOW TABLES FROM {database}").result_columns[0]:
            cols = client.query(f"DESCRIBE TABLE {database}.{table_name}")
            for row in cols.result_rows:
                catalog.append({
                    "table": str(table_name),
                    "column": str(row[0]),
                    "data_type": str(row[1]) if len(row) > 1 else None,
                    "comment": str(row[5]) if len(row) > 5 and row[5] else None,
                })
        return catalog

    def get_schema_catalog(self) -> dict[str, list[str]]:
        client = self._connect()
        catalog: dict[str, list[str]] = {}
        database = self._config.database
        for table_name in client.query(f"SHOW TABLES FROM {database}").result_columns[0]:
            cols = client.query(f"DESCRIBE TABLE {database}.{table_name}")
            catalog[str(table_name)] = [str(row[0]) for row in cols.result_rows]
        return catalog

    def close(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            self._client.close()
        self._client = None
