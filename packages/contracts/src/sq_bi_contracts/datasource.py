from __future__ import annotations

from typing import Protocol, runtime_checkable

from .common import ContractModel
from .enums import DatabaseType


class DataSourceConnectionConfig(ContractModel):
    """Declarative connection parameters — technical connection only.

    Business scope (authorized schemas, business description, include/exclude
    rules) belongs to semantic-space configuration, not the connection.
    """

    data_source_id: str
    name: str
    engine: DatabaseType
    host: str
    port: int
    database: str
    username: str
    password: str  # placeholder — the connector resolves via secret provider
    extra: dict[str, str] = {}
    # Oracle alternate connect-descriptor forms; at most one is normally set.
    # Priority when building the DSN: dsn > service_name > sid > database.
    service_name: str | None = None
    sid: str | None = None
    dsn: str | None = None
    connect_timeout_seconds: float | None = None


@runtime_checkable
class DataSourceConnector(Protocol):
    """Interface every database connector implements.

    The runtime depends on this protocol, never on an Oracle-specific class.
    """

    def execute(self, sql: str, params: dict | None = None) -> list[dict]:
        """Execute a read-only SELECT and return rows as dicts."""
        ...

    def describe_schema(self, schema: str | None = None) -> list[dict]:
        """Return table/column metadata for the given schema (or default)."""
        ...

    def get_schema_catalog(self) -> dict[str, list[str]]:
        """Return {table_name: [column_name, ...]} for the entire catalog."""
        ...
