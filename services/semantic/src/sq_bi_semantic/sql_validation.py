from __future__ import annotations

import re

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


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--.*?$", " ", sql, flags=re.M)
    return sql


def validate_metric_select_sql(sql: str) -> str:
    cleaned = _strip_comments(sql).strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    if not cleaned:
        raise ValueError("指标 SQL 不能为空。")
    if ";" in cleaned:
        raise ValueError("指标 SQL 只能包含一条 SELECT 语句。")

    upper = cleaned.upper()
    if any(re.search(pattern, upper) for pattern in FORBIDDEN_KEYWORDS):
        raise ValueError("指标 SQL 只能使用只读 SELECT，不能包含写入或 DDL 操作。")

    try:
        tree = parse_one(cleaned, read="oracle")
    except ParseError as exc:
        raise ValueError("指标 SQL 无法解析，请提供完整 SELECT SQL。") from exc

    if not isinstance(tree, (exp.Select, exp.Union)):
        raise ValueError("指标定义必须是完整 SELECT SQL，不能只是表达式或条件片段。")

    declared_aliases: set[str] = set()
    for table in tree.find_all(exp.Table):
        alias = table.alias_or_name
        if alias:
            declared_aliases.add(alias.upper())
        if table.name:
            declared_aliases.add(table.name.upper())
    for cte in tree.find_all(exp.CTE):
        alias = cte.alias
        if alias:
            declared_aliases.add(alias.upper())
    for subquery in tree.find_all(exp.Subquery):
        alias = subquery.alias
        if alias:
            declared_aliases.add(alias.upper())

    for column in tree.find_all(exp.Column):
        table = column.table
        if table and table.upper() not in declared_aliases:
            raise ValueError(f"指标 SQL 引用了未声明的表别名：{table}。")

    return cleaned
