from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any

from sq_bi_contracts.field_mount import FieldMapping, MappingStatus
from sq_bi_contracts.domain_pack import PackStandardField

logger = logging.getLogger(__name__)

_MAPPING_STATUS_ACTIVE: MappingStatus = "active"

# ── 2.1: DSL Grammar tokens ──────────────────────────────────────────

TOKEN_PATTERN = re.compile(
    r"""
    (?P<FUNC>count_distinct|count|rate|sum|avg|max|min)
    |
    (?P<IDENT>[a-zA-Z_][a-zA-Z0-9_]*)
    |
    (?P<NUMBER>\d+(?:\.\d+)?)
    |
    (?P<STRING>'[^']*')
    |
    (?P<OP>[=!<>]+|>=|<=|<>)
    |
    (?P<COMMA>,)
    |
    (?P<LPAREN>\()
    |
    (?P<RPAREN>\))
    |
    (?P<WS>\s+)
    |
    (?P<INVALID>\S+)
    """,
    re.VERBOSE | re.IGNORECASE,
)

AGG_FUNCS = {"count", "count_distinct", "sum", "avg", "max", "min", "rate"}
DSL_KEYWORDS = AGG_FUNCS | {"and", "or", "not"}


# ── 2.2: AST node types ──────────────────────────────────────────────

class AstNode:
    pass


class AggFunc(AstNode):
    def __init__(self, name: str, arg: AstNode | None = None) -> None:
        self.name = name
        self.arg = arg

    def __repr__(self) -> str:
        return f"AggFunc({self.name}, {self.arg})"


class FieldRef(AstNode):
    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"FieldRef({self.name})"


class GroupBy(AstNode):
    def __init__(self, field: AstNode) -> None:
        self.field = field

    def __repr__(self) -> str:
        return f"GroupBy({self.field})"


class FilterOp(AstNode):
    def __init__(self, field: AstNode, op: str, value: AstNode) -> None:
        self.field = field
        self.op = op
        self.value = value

    def __repr__(self) -> str:
        return f"FilterOp({self.field} {self.op} {self.value})"


class TimeField(AstNode):
    def __init__(self, field: AstNode) -> None:
        self.field = field

    def __repr__(self) -> str:
        return f"TimeField({self.field})"


class ValueLiteral(AstNode):
    def __init__(self, value: str, is_string: bool = False) -> None:
        self.value = value
        self.is_string = is_string

    def __repr__(self) -> str:
        return f"ValueLiteral({self.value})"


# ── 2.2: Tokenizer ──────────────────────────────────────────────────

class DSLParseError(ValueError):
    pass


def tokenize(text: str) -> list[dict[str, object]]:
    tokens: list[dict[str, object]] = []
    for m in TOKEN_PATTERN.finditer(text):
        if m.group("WS"):
            continue
        if m.group("INVALID"):
            raise DSLParseError(f"Unexpected character at position {m.start()}: {m.group()}")
        for name, value in m.groupdict().items():
            if value is not None:
                tokens.append({"type": name, "value": value, "pos": m.start()})
                break
    return tokens


# ── 2.2: Parser ─────────────────────────────────────────────────────

class Parser:
    def __init__(self, tokens: list[dict[str, object]]) -> None:
        self._tokens = tokens
        self._pos = 0

    def peek(self) -> dict[str, object] | None:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def advance(self) -> dict[str, object] | None:
        tok = self.peek()
        if tok:
            self._pos += 1
        return tok

    def expect(self, *types: str) -> dict[str, object]:
        tok = self.peek()
        if tok is None or tok["type"] not in types:
            expected = " or ".join(types)
            got = tok["value"] if tok else "EOF"
            raise DSLParseError(f"Expected {expected}, got {got}")
        return self.advance()


def _parse_value(p: Parser) -> AstNode:
    tok = p.peek()
    if tok is None:
        raise DSLParseError("Unexpected end of expression")
    if tok["type"] == "IDENT":
        p.advance()
        return FieldRef(str(tok["value"]))
    if tok["type"] == "NUMBER":
        p.advance()
        return ValueLiteral(str(tok["value"]))
    if tok["type"] == "STRING":
        p.advance()
        return ValueLiteral(str(tok["value"]), is_string=True)
    raise DSLParseError(f"Expected value, got {tok['value']}")


def _parse_condition(p: Parser) -> AstNode:
    field = _parse_value(p)
    tok = p.peek()
    if tok and tok["type"] == "OP":
        op = str(tok["value"])
        p.advance()
        value = _parse_value(p)
        return FilterOp(field, op, value)
    return field


def parse_expression(text: str) -> AstNode:
    text = text.strip()
    tokens = tokenize(text)
    p = Parser(tokens)

    # Simple expression without parentheses: field or field OP value
    if not any(t["type"] == "LPAREN" for t in tokens):
        return _parse_condition(p)

    # Aggregation function
    tok = p.expect("FUNC")
    func_name = str(tok["value"]).lower()

    if func_name not in AGG_FUNCS:
        raise DSLParseError(f"Unknown function: {func_name}")

    p.expect("LPAREN")

    if func_name == "rate":
        arg = _parse_condition(p)
    else:
        if p.peek() and p.peek()["type"] == "IDENT":
            arg = _parse_value(p)
        else:
            arg = None
        # Also handle NUMBER literal arg
        if p.peek() and p.peek()["type"] == "NUMBER":
            arg = _parse_value(p)

    p.expect("RPAREN")

    # The agg func is the primary node
    node: AstNode = AggFunc(func_name, arg)

    # Parse optional trailing clauses using keyword detection
    # We'll handle post-processing in the compiler rather than in the parser
    # because clauses like group_by/filter/time_field modify the structure
    return node


def parse_full(text: str) -> AstNode:
    """Parse a full expression with optional post-aggregation clauses.

    Supports: agg_func(...) group_by(x) filter(y OP z) time_field(t)
    The clauses are parsed as sibling metadata and returned as a compound node.
    """
    text = text.strip()
    tokens = tokenize(text)
    p = Parser(tokens)

    # Parse aggregate function
    tok = p.expect("FUNC")
    func_name = str(tok["value"]).lower()
    p.expect("LPAREN")

    if func_name == "rate":
        arg = _parse_condition(p)
    else:
        arg = _parse_value(p) if p.peek() and p.peek()["type"] in ("IDENT", "NUMBER") else None
    p.expect("RPAREN")

    primary: AstNode = AggFunc(func_name, arg)

    # Parse trailing clauses: IDENT '(' ... ')'
    # These use IDENT tokens since 'group_by', 'filter', 'time_field' are just identifiers
    result = primary
    while p.peek():
        tok = p.peek()
        if tok["type"] != "IDENT":
            break
        clause_name = str(tok["value"]).lower()
        p.advance()
        if clause_name not in ("group_by", "filter", "time_field"):
            raise DSLParseError(f"Unexpected clause: {clause_name}")
        p.expect("LPAREN")
        if clause_name == "group_by":
            field = _parse_value(p)
            result = _ClauseGroup(result, GroupBy(field))
        elif clause_name == "filter":
            cond = _parse_condition(p)
            if not isinstance(cond, FilterOp):
                raise DSLParseError(
                    f"filter() requires a comparison expression (e.g. field = 'value'), got {type(cond).__name__}"
                )
            result = _ClauseGroup(result, cond)
        elif clause_name == "time_field":
            field = _parse_value(p)
            result = _ClauseGroup(result, TimeField(field))
        p.expect("RPAREN")

    return result


class _ClauseGroup(AstNode):
    """Wraps an agg function with its trailing clauses."""
    def __init__(self, agg: AstNode, clause: AstNode) -> None:
        self.agg = agg
        self.clause = clause

    def __repr__(self) -> str:
        return f"ClauseGroup({self.agg}, {self.clause})"


# ── 2.3: Validator ──────────────────────────────────────────────────

def validate_logical_expression(
    expression: str,
    standard_fields: dict[str, PackStandardField],
) -> list[str]:
    try:
        ast = parse_full(expression)
    except DSLParseError as exc:
        return [str(exc)]

    refs = _collect_field_refs(ast)
    errors: list[str] = []
    for ref in refs:
        if ref.lower() in DSL_KEYWORDS:
            continue
        if ref not in standard_fields:
            errors.append(f"Standard field '{ref}' not declared in pack")
    return errors


def _collect_field_refs(node: AstNode) -> set[str]:
    refs: set[str] = set()
    stack: list[AstNode] = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, FieldRef):
            refs.add(n.name)
        if isinstance(n, AggFunc) and n.arg:
            stack.append(n.arg)
        if isinstance(n, _ClauseGroup):
            stack.append(n.agg)
            stack.append(n.clause)
        if isinstance(n, GroupBy):
            stack.append(n.field)
        if isinstance(n, FilterOp):
            stack.append(n.field)
            stack.append(n.value)
        if isinstance(n, TimeField):
            stack.append(n.field)
    return refs


# ── 2.4: Oracle compiler ────────────────────────────────────────────

def compile_oracle(
    expression: str,
    mappings: dict[str, FieldMapping],
    standard_fields: dict[str, PackStandardField],
) -> str:
    """Compile DSL expression + mappings to Oracle SQL."""
    ast = parse_full(expression)
    referenced_fields = _collect_field_refs(ast)
    relevant_mappings = {
        field_id: mapping
        for field_id in referenced_fields
        if (mapping := mappings.get(field_id)) is not None
    }
    referenced_tables = {
        mapping.physical_table
        for mapping in relevant_mappings.values()
        if mapping.status == _MAPPING_STATUS_ACTIVE and mapping.physical_table.strip()
    }
    if len(referenced_tables) > 1:
        raise ValueError(
            "Logical expression spans multiple physical tables but declares no "
            "approved join path: " + ", ".join(sorted(referenced_tables))
        )

    def _resolve(field_id: str) -> str:
        if field_id.lower() in DSL_KEYWORDS:
            return field_id
        mapping = mappings.get(field_id)
        if mapping is None or mapping.status != _MAPPING_STATUS_ACTIVE:
            status_hint = f" (status={mapping.status!r})" if mapping else ""
            raise ValueError(
                f"Standard field '{field_id}' has no active mapping for this data source{status_hint}"
            )
        col = mapping.physical_column
        if mapping.transform and (
            mapping.transform.startswith("enum:") or mapping.transform.startswith("{")
        ):
            return _apply_enum_transform(col, mapping.transform)
        return col

    return _compile_node_to_oracle(ast, _resolve, relevant_mappings)


def _compile_node_to_oracle(
    node: AstNode,
    resolver,
    mappings: dict[str, FieldMapping],
) -> str:
    """Compile an AST node to Oracle SQL."""
    # Unwrap ClauseGroup
    if isinstance(node, _ClauseGroup):
        return _compile_clause_group(node, resolver, mappings)

    if isinstance(node, AggFunc):
        select_col = _compile_agg_select(node, resolver)
        return _build_select(select_col, mappings)

    if isinstance(node, FieldRef):
        return _build_select(resolver(node.name), mappings)

    if isinstance(node, FilterOp):
        return _build_select(_compile_filter(node, resolver), mappings)

    raise ValueError(f"Cannot compile AST node: {type(node).__name__}")


def _compile_clause_group(
    node: _ClauseGroup,
    resolver,
    mappings: dict[str, FieldMapping],
) -> str:
    """Compile agg + trailing clauses."""
    # Build the aggregation part
    if isinstance(node.agg, AggFunc):
        select_col = _compile_agg_select(node.agg, resolver)
    else:
        select_col = str(node.agg)

    # Handle the clause
    clause = node.clause
    where_parts: list[str] = []
    group_parts: list[str] = []
    from_table = _infer_from_table(mappings)

    if isinstance(clause, GroupBy):
        if isinstance(clause.field, FieldRef):
            group_parts.append(resolver(clause.field.name))
    elif isinstance(clause, FilterOp):
        where_parts.append(_compile_filter(clause, resolver))
    elif isinstance(clause, TimeField):
        pass  # time field is informational for now

    sql = f"SELECT {select_col} FROM {from_table}"
    if where_parts:
        sql += f" WHERE {' AND '.join(where_parts)}"
    if group_parts:
        sql += f" GROUP BY {', '.join(group_parts)}"
    return sql


def _compile_agg_select(agg: AggFunc, resolver) -> str:
    func = agg.name
    if func == "count" and agg.arg is None:
        return "count(*)"
    if func == "count":
        return f"count({_resolve_field_ref(agg.arg, resolver)})"
    if func == "count_distinct":
        return f"count(distinct {_resolve_field_ref(agg.arg, resolver)})"
    if func == "rate":
        cond = _compile_condition_expr(agg.arg, resolver)
        return (
            f"round(100 * count(case when {cond} then 1 end) "
            f"/ nullif(count(1), 0), 2)"
        )
    if func in ("sum", "avg", "max", "min"):
        return f"{func}({_resolve_field_ref(agg.arg, resolver)})"
    raise ValueError(f"Unsupported function: {func}")


def _resolve_field_ref(node: AstNode | None, resolver) -> str:
    if node is None:
        return "*"
    if isinstance(node, FieldRef):
        return resolver(node.name)
    if isinstance(node, ValueLiteral):
        return node.value
    return str(node)


def _compile_condition_expr(node: AstNode | None, resolver) -> str:
    if node is None:
        return "1=1"
    if isinstance(node, FilterOp):
        return _compile_filter(node, resolver)
    if isinstance(node, FieldRef):
        return resolver(node.name)
    if isinstance(node, ValueLiteral):
        return node.value
    return str(node)


def _compile_filter(filter_node: FilterOp, resolver) -> str:
    field = _resolve_field_ref(filter_node.field, resolver)
    value = _resolve_field_ref(filter_node.value, resolver)
    return f"{field} {filter_node.op} {value}"


def _build_select(select_col: str, mappings: dict[str, FieldMapping]) -> str:
    from_table = _infer_from_table(mappings)
    return f"SELECT {select_col} FROM {from_table}"


def _infer_from_table(mappings: dict[str, FieldMapping]) -> str:
    tables: Counter[str] = Counter()
    for m in mappings.values():
        if m.status == _MAPPING_STATUS_ACTIVE and m.physical_table.strip():
            tables[m.physical_table] += 1
    if not tables:
        raise ValueError("No active mappings found to infer FROM table")
    return tables.most_common(1)[0][0]


def _apply_enum_transform(column: str, transform: str) -> str:
    """Apply an enum value transform to a SQL column expression.

    Accepts two formats:
    - JSON DSL (preferred): ``{"type": "enum_map", "mapping": {"SRC": "DST", ...}}``
    - Legacy text format: ``enum:SRC->DST,SRC2->DST2``
    """
    transform = transform.strip()

    # JSON DSL format: {"type": "enum_map", "mapping": {...}}
    if transform.startswith("{"):
        try:
            parsed = json.loads(transform)
            if parsed.get("type") == "enum_map" and isinstance(parsed.get("mapping"), dict):
                cases = [
                    f"WHEN '{src}' THEN '{dst}'"
                    for src, dst in parsed["mapping"].items()
                ]
                if cases:
                    return f"CASE {column} {' '.join(cases)} ELSE {column} END"
        except (json.JSONDecodeError, AttributeError):
            logger.warning(
                "dsl_compiler.enum_transform_json_parse_error",
                extra={"column": column, "transform": transform[:100]},
            )
        return column

    # Legacy text format: enum:SRC->DST,...
    if not transform.startswith("enum:"):
        return column
    mapping_str = transform[5:]
    cases = [
        f"WHEN '{std_val.strip()}' THEN '{phys_val.strip()}'"
        for part in (p.strip() for p in mapping_str.split(","))
        if "->" in part
        for std_val, phys_val in (part.split("->", 1),)
    ]
    if not cases:
        logger.warning(
            "dsl_compiler.enum_transform_no_pairs",
            extra={"column": column, "transform": transform},
        )
        return column
    return f"CASE {column} {' '.join(cases)} ELSE {column} END"


# ── 2.8: Multi-dialect dispatch ──────────────────────────────────────

def compile_for_dialect(
    expression: str,
    mappings: dict[str, FieldMapping],
    standard_fields: dict[str, PackStandardField],
    dialect: str = "oracle",
) -> str:
    if dialect == "oracle":
        return compile_oracle(expression, mappings, standard_fields)
    raise NotImplementedError(
        f"Logical-to-physical compilation for dialect '{dialect}' is not yet implemented"
    )


# ── 2.6/2.7: Wire through guardrails ────────────────────────────────

def compile_and_validate(
    expression: str,
    mappings: dict[str, FieldMapping],
    standard_fields: dict[str, PackStandardField],
    dialect: str = "oracle",
    max_rows: int = 200,
) -> str:
    from .guardrails import validate_sql

    sql = compile_for_dialect(expression, mappings, standard_fields, dialect=dialect)
    logger.debug(
        "dsl_compiler.compile_and_validate",
        extra={"dialect": dialect, "max_rows": max_rows, "sql_preview": sql[:120]},
    )
    result = validate_sql(sql, dialect=dialect, max_rows=max_rows)
    if result.sql != sql:
        logger.debug(
            "dsl_compiler.guardrails_modified_sql",
            extra={"original": sql[:120], "modified": result.sql[:120]},
        )
    return result.sql
