from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


SchemaCatalog = dict[str, set[str]]


def load_semantic_schema_catalog(catalog_path: Path | str) -> SchemaCatalog:
    path = Path(catalog_path)
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    catalog: SchemaCatalog = {}

    table_id_to_name: dict[str, str] = {}
    for table in raw.get("tables", []):
        table_id = str(table.get("table_id") or "")
        physical_name = str(table.get("physical_name") or "").upper()
        if table_id and physical_name:
            table_id_to_name[table_id] = physical_name
            catalog.setdefault(physical_name, set())

    for field in raw.get("fields", []):
        table_id = str(field.get("table_id") or "")
        table_name = table_id_to_name.get(table_id)
        physical_name = str(field.get("physical_name") or "").upper()
        if table_name and physical_name:
            catalog.setdefault(table_name, set()).add(physical_name)

    return catalog


def merge_schema_catalogs(*catalogs: dict[str, set[str] | list[str]] | None) -> SchemaCatalog:
    merged: SchemaCatalog = {}
    for catalog in catalogs:
        if not catalog:
            continue
        for table, columns in catalog.items():
            merged.setdefault(table.upper(), set()).update(str(column).upper() for column in columns)
    return merged


def schema_catalog_to_prompt(catalog: dict[str, set[str]], *, tables: list[str] | None = None, max_tables: int = 12) -> str:
    if not catalog:
        return ""
    selected_tables = [table.upper() for table in tables or [] if table.upper() in catalog]
    if not selected_tables:
        selected_tables = sorted(catalog)[:max_tables]
    lines: list[str] = ["# Available Physical Columns"]
    for table in selected_tables:
        columns = ", ".join(sorted(catalog[table]))
        lines.append(f"- {table}: {columns}")
    return "\n".join(lines)


def normalize_live_schema_rows(rows: list[tuple[Any, Any]]) -> SchemaCatalog:
    catalog: SchemaCatalog = {}
    for table_name, column_name in rows:
        table = str(table_name).upper()
        column = str(column_name).upper()
        if table and column:
            catalog.setdefault(table, set()).add(column)
    return catalog
