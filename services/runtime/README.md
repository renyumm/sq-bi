# SQ-BI AI-Native Runtime

This worktree implements the AI-native AskData runtime and security governance path for SQ-BI.

It consumes `sq_bi_contracts` and exposes the current LLM-first query surface:

- execute `/api/v1/query/ask` through the saved Skill context and LLM
- return `QueryResult` with `audit_id`, `lineage`, and chart suggestion
- reject destructive or non-read-only SQL
- enforce SQL guardrails before execution

## Local Setup

Each worktree owns its own `.venv`:

```bash
uv sync --extra dev
uv run pytest tests/test_service.py tests/test_config.py tests/test_guardrails.py
```

If PyPI access is blocked, use compile-only verification as a minimum:

```bash
PYTHONPYCACHEPREFIX=/tmp/sq_bi_runtime_pycache python -m compileall src tests
```

## Standard Field Layer & Domain Pack Mounting

Domain packs define logical **standard fields** (`pack.yaml > standard_fields`) instead of
physical table/column names.  Metrics reference these fields via a DSL expression.

### Authoring a metric (DSL reference)

| Pattern | Example |
|---|---|
| Count | `count_distinct(deliver_no)` |
| Rate | `rate(actual_time <= plan_time)` |
| With filter | `count_distinct(deliver_no) filter(car_status = '3')` |
| With dimension | `count_distinct(deliver_no) group_by(carrier_name)` |

Supported operators in `filter()` and `rate()`: `=`, `!=`, `<`, `>`, `<=`, `>=`.

### Official pack requirements

A pack declared `official: true` in `pack.yaml` **must** have every metric either:
- `logical_formula` — DSL expression + `referenced_standard_fields` list, **or**
- `escape_hatch: true` + `escape_hatch_reason` — documents why the DSL cannot express it (e.g., multi-table JOIN, Oracle date arithmetic).

`load_manifest()` enforces this at load time and raises `ValueError` on violation.

### Escape hatch guidance

Complex metrics that cannot be expressed in DSL (multi-table JOINs, date arithmetic, `count(*)`)
should retain their `formula.expression` physical SQL and declare:

```yaml
escape_hatch: true
escape_hatch_reason: "requires JOIN between TABLE_A and TABLE_B; DSL does not support multi-table JOINs"
```

### Default field mappings

Place per-data-source default mappings in `field_mappings/<data_source_id>.yaml` inside the pack
directory and declare them as an asset in `pack.yaml`:

```yaml
assets:
  - asset_type: field_mappings
    path: field_mappings/oracle_tms.yaml
```

The mapping file lists `standard_field_id → physical_table + physical_column` with `source: auto`
and `confidence: 1.0` for deterministic matches.

### Admin mounting API

Once standard fields and mappings are defined, the admin HTTP API handles the full lifecycle:

```
POST /api/v1/admin/deployments        # create deployment + trigger auto-mount
GET  /api/v1/admin/deployments/{id}/pending   # review pending mappings with evidence
POST /api/v1/admin/deployments/{id}/confirm   # confirm a mapping
POST /api/v1/admin/deployments/{id}/smoke-test # compile/run smoke tests
GET  /api/v1/admin/deployments/{id}/status    # coverage + validation_status
```

All admin endpoints require an `X-Session-Id` header with an admin-role session.

---

## Semantic Discovery

The semantic discovery pipeline builds a structured, versioned database semantic profile for each
data source automatically — no required documents.

### Scan phases

**Phase 1 — Metadata scan** (`schema_scanner.py`)
Introspects all authorized-schema metadata via the connector's `describe_schema` / `get_schema_catalog`
interfaces (no row reads).  Applies default exclusion heuristics for temp/backup/log/date-suffixed tables
and respects user `include_rules` / `exclude_rules`.  Wide schemas are chunked before LLM ingestion.

**Phase 2 — Profiling + discovery** (`schema_profiler.py`, `semantic_discovery.py`)
For AI-recommended tables only: collects desensitized samples (capped at 30 rows), enum distributions,
null/unique rates, time ranges, and candidate FK relations.  An LLM stage (`semantic_discovery.py`) then
clusters tables into `SemanticSpace`s and proposes `SemanticEntity` / `SemanticField` interpretations.

### Profile model

Stored in SQLite (`semantic_profile_store.py`) keyed by `data_source_id` + snapshot version.

| Model | Description |
|---|---|
| `SchemaSnapshot` | Versioned scan result; re-scan creates a new version |
| `SemanticSpace` | Clustered business domain (e.g. "运输管理") |
| `SemanticEntity` | Physical table mapped to a business entity |
| `SemanticField` | Column with `origin` (`standard`/`enterprise`/`inferred`), `confidence`, `evidence` |
| `EvidenceItem` | Provenance signal: comment / document / name / sample / user_note / official_pack / ai_inference |
| `DataSourceDocument` | Uploaded data-dictionary file (Excel/CSV/Word/PDF/text) |

### Runtime retrieval

`semantic_retriever.py` selects a small relevant subset of the profile per question
(name/synonym/keyword match) and renders a compact "database semantic context" string
that is prepended to the ask-pipeline prompt.  The full profile is never sent to the model.

### API reference

```
# Scan management (admin)
POST /api/v1/datasources/{id}/scan                  # start scan → {scan_id, phase, ...}
GET  /api/v1/datasources/{id}/scan/{scan_id}        # poll scan status

# Profile (authenticated; read available to non-admin)
GET  /api/v1/datasources/{id}/profile               # full profile view

# Space adjustments (admin)
PUT  /api/v1/datasources/{id}/semantic-spaces       # accept/adjust candidate spaces

# Document ingestion (admin)
POST /api/v1/datasources/{id}/documents             # upload data-dictionary file
GET  /api/v1/datasources/{id}/documents             # list uploaded documents
```

Mutating routes require `X-Session-Id` with an admin-role session.
Profile read requires any authenticated session.

## AI Exploration (Phase 3)

When a question is submitted with `data_source_id`, the ask pipeline classifies it before any SQL is generated:

### Three answer paths

| Path | Trigger | Response |
|---|---|---|
| `official` | Question matches an **official** pack metric by name or synonym | SQL from the official formula, `is_exploratory: false` |
| `enterprise` | Matches a user-saved (**enterprise/private**) metric | SQL from the saved formula, `is_exploratory: false` |
| `ai_exploration` | No metric match — inferred from database semantic profile | AI-generated SQL under a caliber disclaimer, `is_exploratory: true` |

Resolution is deterministic (no LLM call for routing). Matching uses synonym + partial-text overlap from `sq_bi_semantic.synonyms`.

### Confidence tiers

Computed from Phase-1 semantic profile evidence — **not** from LLM self-rating:

| Tier | Condition | Behavior |
|---|---|---|
| `high` | All used fields have `confidence ≥ 0.75` or `origin=standard/enterprise` | Execute + label "企业数据库字段，非官方标准口径" |
| `medium` | Average field confidence ≥ 0.40 | Execute + return `assumptions` list |
| `low` | Below threshold or LLM-guess join on aggregation | Return `ClarificationRequest`, no SQL executed |

### Join evidence threshold

Join evidence is ordered from strongest to weakest:

```
foreign_key (0) > declared_relation (1) > document (2) > name_uniqueness_validated (3) > llm_guess (4)
```

An aggregating plan (`SUM`, `COUNT`, etc.) whose **worst** join evidence is `llm_guess` is **blocked** — the endpoint returns a clarification, not SQL. Foreign-key and declared-relation joins are always allowed.

### QueryAssumption on the response

Every exploration response includes `assumptions: [QueryAssumption]` listing:
- `fields_used` — physical table/column, business name, origin
- `aggregation`, `time_field`, `time_grain`, `filters`
- `joins` — each with `evidence` and `note`
- `caliber_label` — displayed verbatim in the UI

### Sedimentation

Save an exploration result as a reusable enterprise metric:

```
POST /api/v1/query/exploration/save-metric
```

Body: `SaveExplorationAsMetricRequest` (business name, definition, data_source_id, aggregation, synonyms, field_mapping, sql, lineage, visibility, user_id).

After saving, the same question will route to `enterprise` on the next ask, bypassing AI inference.

### API reference

```
POST /api/v1/query/ask                            # ask endpoint — three-path routing when data_source_id present
POST /api/v1/query/exploration/save-metric        # seiment exploration as enterprise metric
```

### Mock flag (frontend)

Set `VITE_MOCK_EXPLORATION=true` in `.env.local` to get deterministic mock exploration responses during frontend development, without a running backend.

## Enterprise Domain Pack (Phase 4)

Enterprise packs let an organization assemble entities, enterprise fields, a metric system, analysis Skills, reports, business terms, and acceptance questions into one versioned, publishable pack — layered on top of read-only official packs.

### Creation modes

| Mode | Description |
|---|---|
| `extend_official` | Copies an official pack's standard-field and metric surface into a new editable enterprise layer (official files are never written) |
| `clone_enterprise` | Deep-copies an existing enterprise pack into a new draft with a new identity |
| `ai_from_profile` | Generates a structured `EnterprisePackDraft` from the database semantic profile + uploaded pack documents |
| `blank` | Empty draft — start from scratch |

### AI pack drafting

`PackDrafter` builds grounding context from `SemanticProfileStore` + uploaded documents, asks the LLM for structured JSON (never raw SQL), validates fields against the profile (drops unknowns), and compiles metric formulas through the deterministic guardrail before accepting them into the draft.

| Validation | Rule |
|---|---|
| Field validation | Drop any field whose `physical_table.physical_column` is absent from the semantic profile |
| Metric formula | Must compile through `validate_sql()` and must NOT be a full SELECT statement |

### Versioning & publish

- `version_state: draft | published` — start as `draft`, publish explicitly
- Publish freezes an immutable snapshot; editing a published pack creates a new `draft` at the next patch version
- Official packs are never touched by publish/fork operations

### Sedimentation target

`POST /api/v1/query/exploration/save-metric` now accepts an optional `target_pack_id`. When set, the saved metric is also attached to that enterprise pack's draft (in addition to the standalone user-metric creation). Omitting `target_pack_id` preserves Phase 3 behavior unchanged.

### API reference

```
GET  /api/v1/admin/enterprise-packs               # list (filter: ?data_source_id=)
GET  /api/v1/admin/enterprise-packs/{id}          # get by id
POST /api/v1/admin/enterprise-packs               # create (CreateEnterprisePackRequest)
PUT  /api/v1/admin/enterprise-packs/{id}          # update draft or meta
POST /api/v1/admin/enterprise-packs/draft         # AI pack draft (PackDraftRequest)
POST /api/v1/admin/enterprise-packs/{id}/publish  # publish (PublishPackRequest)
POST /api/v1/admin/enterprise-packs/{id}/fork     # fork published → new draft
POST /api/v1/query/exploration/save-metric        # sedimentation (optional target_pack_id)
```

All admin endpoints require `X-Session-Id` with an admin-role session.

### Mock flag (frontend)

Set `VITE_MOCK_ENTERPRISE_PACK=true` in `.env.local` to run the enterprise pack authoring UI against typed mock data without a running backend. When set to `false`, real endpoints are called with identical client signatures.

## Semantic Space Management

A **semantic space** is a standalone, versioned, publishable entity scoped to one business
sub-domain (e.g. "TMS 运输执行" vs "运费结算") within a data source — not a substructure of the
whole-connection semantic profile. A data source may have many semantic spaces, each with its own
scope, field-adoption status, and publish lifecycle. `SemanticSpace`/`SemanticField` themselves stay
defined in `semantic_profile.py`; a semantic space is a versioning overlay on top of the profile's
discovered entities/fields, not a duplicate copy.

Scan-time candidate clusters produced by `save_spaces()` (the existing `semantic_discovery.py`
pipeline) are untouched by any of this — they keep `version_state=None`. A space becomes "managed"
only once explicitly created via `create_space()`, distinguishing it from a raw candidate cluster.

### Field status

Each field adopted into a managed space carries a `status`: `confirmed` / `pending` / `excluded` /
`sensitive` / `invalid`. The same physical field can be `confirmed` in one space and `excluded` in
another.

### Refresh → diff → publish lifecycle

Updating a space is never a single opaque "resync":

1. **Refresh** (`refresh_space`) — compares the space's adopted fields against the connection's
   latest scan-candidate pool. Returns a `SemanticSpaceDiff` (new/removed/changed fields) without
   mutating anything.
2. **Publish** (`publish_space`) — given a list of confirmed field ids from the diff, re-parents
   those fields from the candidate pool into the space's own entities (creating entities as
   needed), bumps the version, and freezes a snapshot into `semantic_space_versions` so prior
   versions remain queryable (`list_space_versions` / `get_space_version`).

### Unadopted-field ledger & semantic gap detection

`list_unadopted_fields(data_source_id)` returns every scan-candidate field not yet adopted into any
managed space. `lookup_gap_candidates(data_source_id, query)` matches an ask-data question against
that ledger (via `sq_bi_semantic.synonyms.is_partial_match`) and returns `SemanticGapCandidate`s
instead of silently ignoring the term. The `/api/v1/query/ask` endpoint populates
`QueryResult.gap_candidates` with these on the `ai_exploration` path.

### Domain-pack / deployment / mounting scoping

`CreateDeploymentRequest`/`DeploymentInstance`/`DeploymentListItem`/`MountStatus` gained an additive
`semantic_space_ids: list[str]`. When a deployment is bound to specific spaces,
`MountingPipeline.trigger(..., allowed_tables=...)` restricts both deterministic and LLM matching to
those spaces' adopted tables — a column outside scope is never proposed. A deployment with no
`semantic_space_ids` behaves exactly as before (whole-connection scope).

### API reference

```
GET  /api/v1/datasources/{id}/semantic-spaces               # list managed spaces (authenticated)
POST /api/v1/datasources/{id}/semantic-spaces               # create (CreateSemanticSpaceRequest, admin)
GET  /api/v1/datasources/{id}/semantic-spaces/{space_id}    # get (authenticated)
POST /api/v1/datasources/{id}/semantic-spaces/{space_id}/refresh   # diff (admin)
POST /api/v1/datasources/{id}/semantic-spaces/{space_id}/publish   # publish (PublishSemanticSpaceRequest, admin)
POST /api/v1/query/gap-lookup                                # semantic-gap lookup (GapLookupRequest, authenticated)
```

### Mock flag (frontend)

Set `VITE_MOCK_SEMANTIC_SPACE=true` in `.env.local` to run the semantic-space workbench and
gap-suggestion UI against typed mock data without a running backend.

