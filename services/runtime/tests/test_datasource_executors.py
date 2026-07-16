from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time

from sq_bi_runtime.connectors.resource_pool import ResourcePool
from sq_bi_runtime.datasource_executors import DataSourceExecutorRegistry


class _Resource:
    def __init__(self, identifier: int) -> None:
        self.identifier = identifier
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_resource_pool_is_bounded_and_reuses_resources() -> None:
    created: list[_Resource] = []
    active = 0
    max_active = 0
    lock = Lock()

    def factory() -> _Resource:
        resource = _Resource(len(created) + 1)
        created.append(resource)
        return resource

    pool = ResourcePool(factory, min_size=1, max_size=2)
    pool.warm()

    def use_resource() -> int:
        nonlocal active, max_active
        with pool.acquire() as resource:
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return resource.identifier

    with ThreadPoolExecutor(max_workers=4) as executor:
        identifiers = list(executor.map(lambda _: use_resource(), range(4)))

    assert len(created) == 2
    assert max_active == 2
    assert set(identifiers) == {1, 2}
    pool.close()
    assert all(resource.closed for resource in created)


class _Connector:
    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.closed = False

    def execute(self, _sql: str) -> list[dict]:
        return [{"marker": self.marker}]

    def get_schema_catalog(self) -> dict[str, list[str]]:
        return {"T": ["C"]}

    def close(self) -> None:
        self.closed = True


def test_registry_keeps_one_executor_per_datasource_and_invalidates(monkeypatch) -> None:
    records = [{"data_source_id": "a", "database_type": "oracle", "password": "one"}]
    connectors: list[_Connector] = []

    def build(record: dict) -> _Connector:
        connector = _Connector(str(record["password"]))
        connectors.append(connector)
        return connector

    monkeypatch.setattr("sq_bi_runtime.datasource_executors.build_connector", build)
    registry = DataSourceExecutorRegistry(lambda: records)

    first = registry.get("a")
    assert registry.get("a") is first
    records[0]["password"] = "two"
    second = registry.get("a")

    assert second is not first
    assert connectors[0].closed is True
    registry.close()
    assert connectors[1].closed is True
