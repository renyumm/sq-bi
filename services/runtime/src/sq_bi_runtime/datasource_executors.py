from __future__ import annotations

import json
from threading import Lock
from typing import Any, Callable

from .connectors.factory import build_connector


class ConnectorExecutor:
    def __init__(self, connector: Any) -> None:
        self._connector = connector
        self._column_types: dict[str, dict[str, str]] | None = None

    def execute(self, sql: str, max_rows: int = 200) -> dict[str, Any]:
        rows = self._connector.execute(sql)
        limited = rows[:max_rows]
        columns = list(limited[0].keys()) if limited else []
        return {"columns": columns, "rows": [[row.get(column) for column in columns] for row in limited]}

    def get_schema_catalog(self) -> dict[str, set[str]]:
        return {table: set(columns) for table, columns in self._connector.get_schema_catalog().items()}

    def get_schema_column_types(self) -> dict[str, dict[str, str]]:
        """Return {TABLE: {COLUMN: data_type}} from connector introspection.

        Keys are upper-cased for case-insensitive lookups; the result is cached
        for the executor's lifetime (the registry rebuilds executors whenever
        connection parameters change).
        """
        if self._column_types is None:
            column_types: dict[str, dict[str, str]] = {}
            for item in self._connector.describe_schema() or []:
                table = str(item.get("table") or "").upper()
                column = str(item.get("column") or "").upper()
                data_type = str(item.get("data_type") or "").strip().lower()
                if table and column and data_type:
                    column_types.setdefault(table, {})[column] = data_type
            self._column_types = column_types
        return self._column_types

    def close(self) -> None:
        close = getattr(self._connector, "close", None)
        if callable(close):
            close()


class DataSourceExecutorRegistry:
    """Long-lived executor per configured data source, invalidated on edits."""

    def __init__(self, record_loader: Callable[[], list[dict[str, Any]]]) -> None:
        self._record_loader = record_loader
        self._lock = Lock()
        self._entries: dict[str, tuple[str, ConnectorExecutor]] = {}

    @staticmethod
    def _fingerprint(record: dict[str, Any]) -> str:
        relevant = {
            key: record.get(key)
            for key in (
                "database_type", "host", "port", "database", "service_name", "sid", "dsn",
                "username", "password", "connect_timeout_seconds", "pool_min", "pool_max",
                "pool_wait_timeout_ms",
            )
        }
        return json.dumps(relevant, sort_keys=True, default=str)

    def get(self, data_source_id: str) -> ConnectorExecutor:
        record = next(
            (item for item in self._record_loader() if item.get("data_source_id") == data_source_id),
            None,
        )
        if record is None:
            raise KeyError(f"Data source '{data_source_id}' not found.")
        fingerprint = self._fingerprint(record)
        with self._lock:
            cached = self._entries.get(data_source_id)
            if cached is not None and cached[0] == fingerprint:
                return cached[1]
            if cached is not None:
                cached[1].close()
            executor = ConnectorExecutor(build_connector(record))
            self._entries[data_source_id] = (fingerprint, executor)
            return executor

    def invalidate(self, data_source_id: str) -> None:
        with self._lock:
            cached = self._entries.pop(data_source_id, None)
        if cached is not None:
            cached[1].close()

    def close(self) -> None:
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for _, executor in entries:
            executor.close()

