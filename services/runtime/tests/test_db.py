from __future__ import annotations

from sq_bi_runtime.config import DBConfig
from sq_bi_runtime.db import OracleExecutor


class FakeCursor:
    description = [("VALUE",)]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql: str) -> None:
        self.sql = sql

    def fetchmany(self, max_rows: int):
        return [(max_rows,)]


class FakeConnection:
    def cursor(self) -> FakeCursor:
        return FakeCursor()

    def close(self) -> None:
        return None


class FakePool:
    def __init__(self) -> None:
        self.acquire_count = 0

    def acquire(self) -> FakeConnection:
        self.acquire_count += 1
        return FakeConnection()

    def close(self) -> None:
        return None


def test_oracle_executor_reuses_connection_pool(monkeypatch) -> None:
    calls: list[dict] = []
    pool = FakePool()

    def fake_create_pool(**kwargs):
        calls.append(kwargs)
        return pool

    monkeypatch.setattr("sq_bi_runtime.db.oracledb.create_pool", fake_create_pool)
    executor = OracleExecutor(
        DBConfig(
            user="u",
            password="p",
            dsn="db",
            pool_min=1,
            pool_max=4,
            pool_wait_timeout_ms=2500,
            tcp_connect_timeout_seconds=3,
        )
    )

    executor.execute("select 1 from dual")
    executor.execute("select 2 from dual")

    assert len(calls) == 1
    assert calls[0]["max"] == 4
    assert calls[0]["wait_timeout"] == 2500
    assert calls[0]["tcp_connect_timeout"] == 3
    assert pool.acquire_count == 2
