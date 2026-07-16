from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generator

from .secret_provider import is_secret_field, MASK

# ── Structured logging ────────────────────────────────────────────────

_STRUCTURED_LOGGER = logging.getLogger("sq_bi")


def configure_structured_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_StructuredFormatter())
    _STRUCTURED_LOGGER.addHandler(handler)
    _STRUCTURED_LOGGER.setLevel(level)
    _STRUCTURED_LOGGER.propagate = False


class _StructuredFormatter(logging.Formatter):
    """Emit JSON-structured log lines with timestamp, level, message, and extras."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            entry["request_id"] = record.request_id
        if hasattr(record, "user_id"):
            entry["user_id"] = record.user_id
        if hasattr(record, "org_id"):
            entry["org_id"] = record.org_id
        # Mask any secret fields in extra data
        extra = {k: v for k, v in record.__dict__.items()
                 if k not in ("args", "asctime", "created", "exc_info", "exc_text",
                              "filename", "funcName", "levelname", "levelno",
                              "lineno", "module", "msecs", "msg", "name",
                              "pathname", "process", "processName", "relativeCreated",
                              "stack_info", "thread", "threadName", "request_id",
                              "user_id", "org_id")}
        for key, value in extra.items():
            if is_secret_field(key):
                entry[key] = MASK
            else:
                entry[key] = value if isinstance(value, (str, int, float, bool, list, dict)) else str(value)
        return json.dumps(entry, ensure_ascii=False)


def log_info(msg: str, **extra: Any) -> None:
    _STRUCTURED_LOGGER.info(msg, extra=extra)


def log_error(msg: str, **extra: Any) -> None:
    _STRUCTURED_LOGGER.error(msg, extra=extra)


# ── Runtime metrics ───────────────────────────────────────────────────

_METRICS: dict[str, Any] = {
    "requests_total": 0,
    "errors_total": 0,
    "llm_calls_total": 0,
    "llm_duration_ms_total": 0,
    "db_calls_total": 0,
    "db_duration_ms_total": 0,
    "latency_buckets_ms": defaultdict(int),  # histogram
}

_METRICS_LOCK = threading.Lock()


def incr_metric(name: str, value: int = 1) -> None:
    with _METRICS_LOCK:
        if name in _METRICS:
            _METRICS[name] += value
        else:
            _METRICS[name] = value


def record_duration(name: str, duration_ms: float) -> None:
    with _METRICS_LOCK:
        _METRICS.setdefault(f"{name}_total", 0)
        _METRICS[f"{name}_total"] += 1
        _METRICS.setdefault(f"{name}_duration_ms_total", 0.0)
        _METRICS[f"{name}_duration_ms_total"] += duration_ms
        bucket_key = f"{name}_bucket"
        _METRICS.setdefault(bucket_key, defaultdict(int))
        for bound in (10, 50, 100, 500, 1000, 5000):
            if duration_ms <= bound:
                _METRICS[bucket_key][bound] += 1


def get_metrics_snapshot() -> dict[str, Any]:
    with _METRICS_LOCK:
        snapshot = dict(_METRICS)
        # Convert defaultdicts to plain dicts for JSON serialization
        for k, v in snapshot.items():
            if isinstance(v, defaultdict):
                snapshot[k] = dict(v)
        return snapshot


# ── Request-scoped tracing ────────────────────────────────────────────

_trace_store: dict[str, list[dict[str, Any]]] = {}

_TRACE_STORE_MAX_ENTRIES = 2_000


def start_trace(request_id: str) -> None:
    if len(_trace_store) >= _TRACE_STORE_MAX_ENTRIES:
        oldest = next(iter(_trace_store))
        _trace_store.pop(oldest, None)
    _trace_store[request_id] = []


def add_span(
    request_id: str,
    operation: str,
    duration_ms: float,
    metadata: dict[str, Any] | None = None,
) -> None:
    span = {
        "operation": operation,
        "duration_ms": duration_ms,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if metadata:
        span["metadata"] = metadata
    spans = _trace_store.get(request_id)
    if spans is not None:
        spans.append(span)


def get_trace(request_id: str) -> list[dict[str, Any]]:
    return _trace_store.get(request_id, [])


@contextmanager
def trace_span(request_id: str, operation: str, **metadata: Any) -> Generator[None, None, None]:
    start = time.monotonic()
    try:
        yield
    finally:
        duration_ms = (time.monotonic() - start) * 1000
        add_span(request_id, operation, duration_ms, metadata or None)
        record_duration(operation, duration_ms)


# ── Metrics endpoint formatter (Prometheus-compatible text) ───────────

def format_prometheus_metrics() -> str:
    snapshot = get_metrics_snapshot()
    lines: list[str] = []
    lines.append("# HELP sq_bi_requests_total Total requests processed")
    lines.append("# TYPE sq_bi_requests_total counter")
    lines.append(f'sq_bi_requests_total {snapshot.get("requests_total", 0)}')
    lines.append("")
    lines.append("# HELP sq_bi_errors_total Total errors")
    lines.append("# TYPE sq_bi_errors_total counter")
    lines.append(f'sq_bi_errors_total {snapshot.get("errors_total", 0)}')
    lines.append("")
    lines.append("# HELP sq_bi_llm_duration_ms_total Total LLM call duration")
    lines.append("# TYPE sq_bi_llm_duration_ms_total counter")
    lines.append(f'sq_bi_llm_duration_ms_total {snapshot.get("llm_duration_ms_total", 0)}')
    lines.append("")
    lines.append("# HELP sq_bi_db_duration_ms_total Total DB call duration")
    lines.append("# TYPE sq_bi_db_duration_ms_total counter")
    lines.append(f'sq_bi_db_duration_ms_total {snapshot.get("db_duration_ms_total", 0)}')
    lines.append("")
    return "\n".join(lines)
