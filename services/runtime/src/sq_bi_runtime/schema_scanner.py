"""Phase-one metadata scanner.

Introspects all authorized-schema metadata via the connector's
``describe_schema`` / ``get_schema_catalog`` interfaces.  No row reads.
Applies default exclusion heuristics, respects user overrides, and chunks
the result so a wide schema is never sent to the LLM in one request.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sq_bi_contracts.datasource import DataSourceConnector
from sq_bi_contracts.semantic_profile import TableRecommendation

logger = logging.getLogger(__name__)

# ── Exclusion heuristics ──────────────────────────────────────────────

_DEFAULT_EXCLUDE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r".*_TMP$", re.IGNORECASE),
    re.compile(r".*_TEMP$", re.IGNORECASE),
    re.compile(r".*_BAK$", re.IGNORECASE),
    re.compile(r".*_BACKUP$", re.IGNORECASE),
    re.compile(r".*_LOG$", re.IGNORECASE),
    re.compile(r".*_LOGS$", re.IGNORECASE),
    re.compile(r".*_AUDIT$", re.IGNORECASE),
    re.compile(r".*_HISTORY$", re.IGNORECASE),
    re.compile(r".*_HIST$", re.IGNORECASE),
    # Date-suffixed tables: NAME_20240101, NAME_202401
    re.compile(r".*_\d{6,8}$"),
    # Archive tables
    re.compile(r".*_ARCH$", re.IGNORECASE),
    re.compile(r".*_ARCHIVE$", re.IGNORECASE),
    # Recycle bin / sys objects (Oracle)
    re.compile(r"^BIN\$.*", re.IGNORECASE),
    re.compile(r"^SYS_.*", re.IGNORECASE),
    re.compile(r"^MLOG\$.*", re.IGNORECASE),
]

_CHUNK_SIZE_DEFAULT = 30


@dataclass
class ColumnMeta:
    name: str
    data_type: str | None = None
    comment: str | None = None
    nullable: bool = True
    is_pk: bool = False
    is_fk: bool = False
    has_index: bool = False


@dataclass
class TableMeta:
    name: str
    schema: str | None = None
    row_count_approx: int | None = None
    comment: str | None = None
    columns: list[ColumnMeta] = field(default_factory=list)
    recommendation: TableRecommendation = TableRecommendation.recommended_include
    excluded: bool = False
    excluded_reason: str | None = None


@dataclass
class ScanMetadata:
    """Full result of a phase-one scan."""
    data_source_id: str
    scanned_schemas: list[str]
    tables: list[TableMeta]

    @property
    def included(self) -> list[TableMeta]:
        return [t for t in self.tables if not t.excluded]

    @property
    def excluded(self) -> list[TableMeta]:
        return [t for t in self.tables if t.excluded]


# ── Pattern helpers ───────────────────────────────────────────────────

def _compile_user_patterns(rules: list[str]) -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = []
    for rule in rules:
        try:
            patterns.append(re.compile(rule, re.IGNORECASE))
        except re.error:
            logger.warning("schema_scanner.invalid_pattern", extra={"rule": rule})
    return patterns


def _matches_any(name: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(p.match(name) for p in patterns)


def _should_exclude_by_default(table_name: str) -> tuple[bool, str]:
    for pat in _DEFAULT_EXCLUDE_PATTERNS:
        if pat.match(table_name):
            return True, f"default_exclusion:{pat.pattern}"
    return False, ""


# ── Scanner ───────────────────────────────────────────────────────────

class SchemaScanner:
    """Introspects schema metadata without reading any row data."""

    def __init__(
        self,
        connector: DataSourceConnector,
        data_source_id: str,
        *,
        authorized_schemas: list[str] | None = None,
        include_rules: list[str] | None = None,
        exclude_rules: list[str] | None = None,
        chunk_size: int = _CHUNK_SIZE_DEFAULT,
    ) -> None:
        self._connector = connector
        self._data_source_id = data_source_id
        self._authorized_schemas = authorized_schemas or []
        self._include_patterns = _compile_user_patterns(include_rules or [])
        self._exclude_patterns = _compile_user_patterns(exclude_rules or [])
        self._chunk_size = chunk_size

    def scan(self) -> ScanMetadata:
        """Run phase-one: collect metadata, apply exclusions, return result."""
        logger.info(
            "schema_scanner.scan.start",
            extra={"data_source_id": self._data_source_id},
        )
        raw_catalog = self._connector.get_schema_catalog()
        raw_describe: list[dict] = []
        try:
            for schema in self._authorized_schemas or [None]:  # type: ignore[list-item]
                rows = self._connector.describe_schema(schema)
                raw_describe.extend(rows)
        except Exception as exc:
            logger.warning(
                "schema_scanner.describe_schema.failed",
                extra={"error": str(exc)},
            )

        tables = self._build_table_metas(raw_catalog, raw_describe)
        scanned_schemas = self._authorized_schemas or ["(default)"]

        logger.info(
            "schema_scanner.scan.done",
            extra={
                "data_source_id": self._data_source_id,
                "total": len(tables),
                "included": sum(1 for t in tables if not t.excluded),
            },
        )
        return ScanMetadata(
            data_source_id=self._data_source_id,
            scanned_schemas=scanned_schemas,
            tables=tables,
        )

    def _build_table_metas(
        self,
        catalog: dict[str, list[str]],
        describe_rows: list[dict],
    ) -> list[TableMeta]:
        # Build a column-detail index from describe_schema output
        col_detail: dict[str, dict[str, dict]] = {}
        for row in describe_rows:
            tbl = str(row.get("table") or "").upper()
            col = str(row.get("column") or "").upper()
            if tbl and col:
                col_detail.setdefault(tbl, {})[col] = row

        tables: list[TableMeta] = []
        for table_name, columns in catalog.items():
            tbl_upper = table_name.upper()
            meta = TableMeta(name=tbl_upper)

            # Populate columns
            for col_name in columns:
                col_upper = col_name.upper()
                detail = col_detail.get(tbl_upper, {}).get(col_upper, {})
                meta.columns.append(
                    ColumnMeta(
                        name=col_upper,
                        data_type=detail.get("data_type") or detail.get("type"),
                        comment=detail.get("comment"),
                        nullable=bool(detail.get("nullable", True)),
                        is_pk=bool(detail.get("is_pk", False)),
                        is_fk=bool(detail.get("is_fk", False)),
                        has_index=bool(detail.get("has_index", False)),
                    )
                )

            # Apply exclusion rules (user override before default)
            excluded, reason = self._classify_table(tbl_upper)
            meta.excluded = excluded
            meta.excluded_reason = reason or None

            tables.append(meta)

        return tables

    def _classify_table(self, table_name: str) -> tuple[bool, str]:
        """Return (excluded, reason)."""
        # User include takes highest precedence — keeps the table even if default excludes
        if self._include_patterns and _matches_any(table_name, self._include_patterns):
            return False, ""

        # User explicit exclude
        if _matches_any(table_name, self._exclude_patterns):
            return True, "user_exclude_rule"

        # Default exclusion heuristics
        excluded, reason = _should_exclude_by_default(table_name)
        return excluded, reason

    def chunk_metadata_for_llm(
        self,
        metadata: ScanMetadata,
        *,
        include_only: bool = True,
    ) -> list[list[TableMeta]]:
        """Chunk included (or all) tables into groups of ``chunk_size``."""
        source = metadata.included if include_only else metadata.tables
        return [
            source[i : i + self._chunk_size]
            for i in range(0, len(source), self._chunk_size)
        ]

    @staticmethod
    def render_chunk_for_llm(chunk: list[TableMeta]) -> str:
        """Render a chunk of TableMeta as a compact text for LLM consumption."""
        lines: list[str] = []
        for tbl in chunk:
            comment_part = f"  -- {tbl.comment}" if tbl.comment else ""
            lines.append(f"TABLE: {tbl.name}{comment_part}")
            for col in tbl.columns:
                flags: list[str] = []
                if col.is_pk:
                    flags.append("PK")
                if col.is_fk:
                    flags.append("FK")
                if col.has_index:
                    flags.append("IDX")
                flag_str = f" [{','.join(flags)}]" if flags else ""
                type_str = f" {col.data_type}" if col.data_type else ""
                comment_str = f"  -- {col.comment}" if col.comment else ""
                lines.append(f"  {col.name}{type_str}{flag_str}{comment_str}")
        return "\n".join(lines)
