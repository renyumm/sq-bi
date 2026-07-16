from __future__ import annotations

from contextlib import contextmanager
from queue import Empty, Full, LifoQueue
from threading import Lock
from typing import Any, Callable, Iterator


class ResourcePool:
    """Small thread-safe bounded pool for DB-API connections and clients."""

    def __init__(
        self,
        factory: Callable[[], Any],
        *,
        min_size: int = 1,
        max_size: int = 4,
        acquire_timeout_seconds: float = 15.0,
        close_resource: Callable[[Any], None] | None = None,
    ) -> None:
        self._factory = factory
        self._min_size = max(0, int(min_size))
        self._max_size = max(1, int(max_size), self._min_size)
        self._acquire_timeout_seconds = max(0.1, float(acquire_timeout_seconds))
        self._close_resource = close_resource or (lambda resource: resource.close())
        self._available: LifoQueue[Any] = LifoQueue(maxsize=self._max_size)
        self._lock = Lock()
        self._created = 0
        self._closed = False

    def _create(self) -> Any:
        with self._lock:
            if self._closed:
                raise RuntimeError("Resource pool is closed.")
            if self._created >= self._max_size:
                return None
            self._created += 1
        try:
            return self._factory()
        except Exception:
            with self._lock:
                self._created -= 1
            raise

    def warm(self) -> None:
        for _ in range(self._min_size):
            resource = self._create()
            if resource is not None:
                self._available.put_nowait(resource)

    @contextmanager
    def acquire(self) -> Iterator[Any]:
        try:
            resource = self._available.get_nowait()
        except Empty:
            resource = self._create()
            if resource is None:
                try:
                    resource = self._available.get(timeout=self._acquire_timeout_seconds)
                except Empty as exc:
                    raise TimeoutError("Timed out waiting for a database connection.") from exc
        broken = False
        try:
            yield resource
        except Exception:
            broken = True
            raise
        finally:
            if broken or self._closed:
                try:
                    self._close_resource(resource)
                finally:
                    with self._lock:
                        self._created = max(0, self._created - 1)
            else:
                try:
                    self._available.put_nowait(resource)
                except Full:
                    self._close_resource(resource)
                    with self._lock:
                        self._created = max(0, self._created - 1)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        while True:
            try:
                resource = self._available.get_nowait()
            except Empty:
                break
            try:
                self._close_resource(resource)
            finally:
                with self._lock:
                    self._created = max(0, self._created - 1)

