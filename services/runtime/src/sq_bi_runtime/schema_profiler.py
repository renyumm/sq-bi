"""Phase-two schema profiler.

For AI-recommended tables only: collects desensitized samples (capped),
enum distributions, null rates, uniqueness, time range, and candidate FK
relations.  Never samples excluded or sensitive tables.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any

from sq_bi_contracts.datasource import DataSourceConnector

from .schema_scanner import TableMeta

logger = logging.getLogger(__name__)

_MAX_SAMPLE_ROWS: int = 30
_MAX_ENUM_VALUES: int = 20
_MAX_PROFILE_TABLES: int = 8
_MAX_PROFILE_COLUMNS_PER_TABLE: int = 6
_SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r".*(PASSWORD|PASSWD|PWD).*", re.IGNORECASE),
    re.compile(r".*(SECRET|TOKEN|API_KEY).*", re.IGNORECASE),
    re.compile(r".*(ID_CARD|SSN|SOCIAL).*", re.IGNORECASE),
    re.compile(r".*(MOBILE|PHONE|TEL).*", re.IGNORECASE),
    re.compile(r".*(EMAIL|MAIL_ADDR).*", re.IGNORECASE),
    re.compile(r".*(BANK_ACCT|CARD_NO).*", re.IGNORECASE),
]


def _is_sensitive_column(col_name: str) -> bool:
    return any(p.match(col_name) for p in _SENSITIVE_PATTERNS)


@dataclass
class ColumnProfile:
    name: str
    null_rate: float | None = None
    unique_rate: float | None = None
    sample_values: list[str] = field(default_factory=list)
    enum_distribution: dict[str, int] = field(default_factory=dict)
    min_value: str | None = None
    max_value: str | None = None
    is_sensitive: bool = False


@dataclass
class TableProfile:
    table_name: str
    row_count_approx: int | None = None
    columns: list[ColumnProfile] = field(default_factory=list)
    candidate_fk_pairs: list[tuple[str, str]] = field(default_factory=list)


def select_profile_targets(
    tables: list[TableMeta],
    *,
    max_tables: int = _MAX_PROFILE_TABLES,
    max_columns_per_table: int = _MAX_PROFILE_COLUMNS_PER_TABLE,
) -> list[TableMeta]:
    """Select a bounded, representative subset for supplementary sampling.

    Discovery still receives every scanned table and column. This only caps the
    expensive row-reading profile queries used as additional model evidence.
    """
    if max_tables <= 0 or max_columns_per_table <= 0 or not tables:
        return []
    if len(tables) <= max_tables:
        selected_tables = tables
    else:
        selected_indexes = (
            {
                round(index * (len(tables) - 1) / (max_tables - 1))
                for index in range(max_tables)
            }
            if max_tables > 1
            else {0}
        )
        selected_tables = [tables[index] for index in sorted(selected_indexes)]

    targets: list[TableMeta] = []
    for table in selected_tables:
        ranked_columns = sorted(
            enumerate(table.columns),
            key=lambda item: (
                not (item[1].is_pk or item[1].is_fk or item[1].has_index),
                not bool(item[1].comment),
                item[0],
            ),
        )
        columns = [column for _, column in ranked_columns[:max_columns_per_table]]
        targets.append(replace(table, columns=columns))
    return targets


class SchemaProfiler:
    """Profiles recommended tables via read-only, desensitized queries."""

    def __init__(
        self,
        connector: DataSourceConnector,
        *,
        max_sample_rows: int = _MAX_SAMPLE_ROWS,
    ) -> None:
        self._connector = connector
        self._max_sample_rows = max_sample_rows

    def profile_table(self, table: TableMeta) -> TableProfile:
        """Profile one table.  Returns an empty profile on any error."""
        if table.excluded:
            raise ValueError(f"Table {table.name} is excluded — will not profile.")

        col_profiles: list[ColumnProfile] = []
        for col in table.columns:
            col_profile = self._profile_column(table.name, col.name)
            col_profiles.append(col_profile)

        candidate_fks = self._detect_candidate_fks(table)

        row_count = self._count_rows(table.name)

        return TableProfile(
            table_name=table.name,
            row_count_approx=row_count,
            columns=col_profiles,
            candidate_fk_pairs=candidate_fks,
        )

    def _profile_column(self, table_name: str, col_name: str) -> ColumnProfile:
        if _is_sensitive_column(col_name):
            return ColumnProfile(name=col_name, is_sensitive=True)

        profile = ColumnProfile(name=col_name)
        try:
            # Null rate
            rows = self._connector.execute(
                f"SELECT COUNT(*) as total, "
                f"SUM(CASE WHEN {col_name} IS NULL THEN 1 ELSE 0 END) as nulls "
                f"FROM {table_name}",
            )
            if rows:
                total = rows[0].get("total") or rows[0].get("TOTAL", 0)
                nulls = rows[0].get("nulls") or rows[0].get("NULLS", 0)
                if total and int(total) > 0:
                    profile.null_rate = round(int(nulls) / int(total), 4)
                    # Approximate unique rate via distinct count
                    try:
                        dist_rows = self._connector.execute(
                            f"SELECT COUNT(DISTINCT {col_name}) as dcount FROM {table_name}"
                        )
                        if dist_rows:
                            dcount = dist_rows[0].get("dcount") or dist_rows[0].get("DCOUNT", 0)
                            profile.unique_rate = round(int(dcount) / int(total), 4)
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug(
                "schema_profiler.null_rate.failed",
                extra={"table": table_name, "col": col_name, "error": str(exc)},
            )
            return profile

        try:
            # Desensitized samples
            sample_rows = self._connector.execute(
                f"SELECT {col_name} FROM {table_name} "
                f"WHERE {col_name} IS NOT NULL "
                f"FETCH FIRST {self._max_sample_rows} ROWS ONLY"
            )
            raw_samples = [
                str(r.get(col_name) or r.get(col_name.upper(), ""))
                for r in sample_rows
            ]
            # Deduplicate while preserving order
            seen: set[str] = set()
            unique_samples: list[str] = []
            for s in raw_samples:
                if s not in seen:
                    seen.add(s)
                    unique_samples.append(s)
            profile.sample_values = unique_samples[:_MAX_ENUM_VALUES]

            # If few unique values, treat as enum distribution
            if len(unique_samples) <= _MAX_ENUM_VALUES:
                dist_rows = self._connector.execute(
                    f"SELECT {col_name}, COUNT(*) as cnt FROM {table_name} "
                    f"WHERE {col_name} IS NOT NULL "
                    f"GROUP BY {col_name} ORDER BY cnt DESC "
                    f"FETCH FIRST {_MAX_ENUM_VALUES} ROWS ONLY"
                )
                for r in dist_rows:
                    val = str(r.get(col_name) or r.get(col_name.upper(), ""))
                    cnt = int(r.get("cnt") or r.get("CNT", 0))
                    profile.enum_distribution[val] = cnt
        except Exception as exc:
            logger.debug(
                "schema_profiler.samples.failed",
                extra={"table": table_name, "col": col_name, "error": str(exc)},
            )

        try:
            # Min/max range (useful for date/numeric columns)
            range_rows = self._connector.execute(
                f"SELECT MIN({col_name}) as min_v, MAX({col_name}) as max_v FROM {table_name}"
            )
            if range_rows:
                r = range_rows[0]
                profile.min_value = str(r.get("min_v") or r.get("MIN_V", "") or "")
                profile.max_value = str(r.get("max_v") or r.get("MAX_V", "") or "")
        except Exception:
            pass

        return profile

    def _count_rows(self, table_name: str) -> int | None:
        try:
            rows = self._connector.execute(f"SELECT COUNT(*) as cnt FROM {table_name}")
            if rows:
                return int(rows[0].get("cnt") or rows[0].get("CNT", 0))
        except Exception:
            pass
        return None

    def _detect_candidate_fks(self, table: TableMeta) -> list[tuple[str, str]]:
        """Detect column pairs that look like foreign keys by naming convention."""
        candidates: list[tuple[str, str]] = []
        col_names = {c.name for c in table.columns}
        for col in table.columns:
            if col.is_fk:
                candidates.append((col.name, f"(FK: {col.name})"))
            elif col.name.endswith("_ID") and col.name != "ID":
                ref_prefix = col.name[:-3]
                candidates.append((col.name, f"REF:{ref_prefix}"))
        return candidates
