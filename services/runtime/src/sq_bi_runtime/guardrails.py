from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError

FORBIDDEN_KEYWORDS = [
    r"\bINSERT\b",
    r"\bUPDATE\b",
    r"\bDELETE\b",
    r"\bMERGE\b",
    r"\bTRUNCATE\b",
    r"\bALTER\b",
    r"\bDROP\b",
    r"\bCREATE\b",
    r"\bGRANT\b",
    r"\bREVOKE\b",
    r"\bCALL\b",
    r"\bBEGIN\b",
    r"\bDECLARE\b",
    r"\bEXECUTE\s+IMMEDIATE\b",
]

ROW_LIMIT_PATTERN = re.compile(r"\b(FETCH\s+FIRST|LIMIT)\b", re.I)

class SQLValidationError(ValueError):
    pass


@dataclass
class ValidationResult:
    sql: str
    tables: list[str]


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--.*?$", " ", sql, flags=re.M)
    return sql


def _normalize_schema_name(schema: object) -> str:
    return str(schema).strip('"').upper()


def _strip_allowed_schema_prefixes(sql: str, allowed_schemas: set[str]) -> str:
    normalized = sql
    for schema in allowed_schemas:
        normalized = re.sub(rf"\b{re.escape(schema)}\s*\.\s*", "", normalized, flags=re.I)
    return normalized


def _normalize_schema_catalog(schema_catalog: Mapping[str, set[str] | list[str] | tuple[str, ...]] | None) -> dict[str, set[str]]:
    if not schema_catalog:
        return {}
    return {
        table.upper(): {column.upper() for column in columns}
        for table, columns in schema_catalog.items()
    }


def _projection_aliases(tree: exp.Expression) -> set[str]:
    aliases: set[str] = set()
    for select in tree.find_all(exp.Select):
        for projection in select.expressions:
            alias = projection.alias
            if alias:
                aliases.add(alias.upper())
    return aliases


def _validate_columns(tree: exp.Expression, alias_map: dict[str, str], schema_catalog: dict[str, set[str]]) -> None:
    if not schema_catalog:
        return
    output_aliases = _projection_aliases(tree)
    table_names = set(alias_map.values())

    for table_name in table_names:
        if table_name != "DUAL" and table_name not in schema_catalog:
            raise SQLValidationError(f"Table not found in semantic catalog: {table_name}")

    for column in tree.find_all(exp.Column):
        column_name = column.name.upper()
        if column_name == "*":
            continue
        table_alias = (column.table or "").upper()
        if table_alias:
            table_name = alias_map.get(table_alias)
            if table_name is None:
                raise SQLValidationError(f"SQL references undeclared table alias: {table_alias}")
            if table_name in schema_catalog and column_name not in schema_catalog[table_name]:
                raise SQLValidationError(f"Column not found: {table_name}.{column_name}")
            continue

        if column_name in output_aliases:
            continue
        matching_tables = [
            table_name
            for table_name in table_names
            if table_name in schema_catalog and column_name in schema_catalog[table_name]
        ]
        if not matching_tables and table_names:
            raise SQLValidationError(f"Column not found in selected tables: {column_name}")
        if len(matching_tables) > 1:
            raise SQLValidationError(f"Ambiguous column reference, qualify with table alias: {column_name}")


def validate_sql(
    sql: str,
    allowed_schemas: tuple[str, ...] = (),
    schema_catalog: Mapping[str, set[str] | list[str] | tuple[str, ...]] | None = None,
    dialect: str = "oracle",
) -> ValidationResult:
    cleaned = _strip_comments(sql).strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    upper = cleaned.upper()
    if ";" in cleaned:
        raise SQLValidationError("Only a single SQL statement is allowed.")
    if any(re.search(pattern, upper) for pattern in FORBIDDEN_KEYWORDS):
        raise SQLValidationError("Only read-only SELECT statements are allowed.")

    try:
        tree = parse_one(cleaned, read=dialect)
    except ParseError as exc:
        raise SQLValidationError("SQL could not be parsed.") from exc
    if not isinstance(tree, (exp.Select, exp.Union)):
        raise SQLValidationError("SQL must be a SELECT statement.")

    normalized_allowed_schemas = {_normalize_schema_name(schema) for schema in allowed_schemas if schema}
    normalized_schema_catalog = _normalize_schema_catalog(schema_catalog)
    alias_map: dict[str, str] = {}
    tables: list[str] = []
    for table in tree.find_all(exp.Table):
        table_name = table.name.upper()
        tables.append(table_name)
        alias_map[table.alias_or_name.upper()] = table_name
        if normalized_allowed_schemas and table.db and _normalize_schema_name(table.db) not in normalized_allowed_schemas:
            raise SQLValidationError("Cross-schema access is not allowed.")
    _validate_columns(tree, alias_map, normalized_schema_catalog)

    executable_sql = _strip_allowed_schema_prefixes(cleaned, normalized_allowed_schemas)
    return ValidationResult(sql=ensure_row_limit(executable_sql, dialect=dialect), tables=tables)


def ensure_row_limit(sql: str, max_rows: int = 200, dialect: str = "oracle") -> str:
    cleaned = sql.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    if ROW_LIMIT_PATTERN.search(cleaned):
        return cleaned
    if dialect == "mysql" or dialect == "postgres" or dialect == "clickhouse":
        return f"{cleaned}\nlimit {max_rows}"
    return f"{cleaned}\nfetch first {max_rows} rows only"
