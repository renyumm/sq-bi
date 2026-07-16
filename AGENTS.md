# Repository Guidelines

## Project Overview

**SQ-BI (智慧问数)** is a semantic-layer business intelligence platform for enterprise data (manufacturing, logistics, finance). Architecture uses LLM-as-scheduler + deterministic Skill-engine: the LLM parses natural language intents, extracts entities, and routes to pre-authored Skills (metrics/reports) that execute fixed SQL/API calls — never allowing LLM-generated SQL directly.

Product modules span data source management, metric dictionary, smart Q&A, report/Skill creation, PPT/Word export, secure sharing, and subscriptions. The repo is a uv-managed Python monorepo with a React frontend.

## Architecture & Data Flow

```
packages/contracts/ ─── sq-bi-contracts (Pydantic DTOs, enums, API envelope)
       │
       ▼
services/semantic/  ─── sq-bi-semantic (catalog, metric center, Skill CRUD)
       │
       ▼
services/runtime/   ─── sq-bi-runtime (LLM orchestration, SQL guardrails, query exec)
       │
       ├──▶ services/export/ ─── sq-bi-export (PDF/sharing/subscriptions)
       │
       └──▶ apps/web/        ─── React SPA (Vite + Tailwind)
```

- **LLM protocol**: `OpenAICompatClient` — sync httpx client, `chat(system, user)` returns `str`. Configurable via YAML + env override.
- **DB protocol**: `OracleExecutor` — connection pool via `oracledb`, thread-safe, TTL-cached schema description.
- **Service abstraction**: `@runtime_checkable` Protocol classes (`CatalogRepository`, `MetricRepository`, `SkillRepository`, `LLMProtocol`, `DBProtocol`).
- **API envelope**: `ApiResponse[T]` with exactly one of `data` or `error`. Every endpoint returns `request_id`.
- **Business logic errors**: custom exception classes mapped to `ErrorCode` enums and wrapped by handlers.
- **Config pattern**: YAML file + env var override (`_env_first()`), runtime settings persisted to `.local/runtime_settings.json`.
- **SQL guardrails**: `sqlglot` AST parsing, forbidden DDL/DML keywords, single-statement check, column validation against schema catalog, row-limit enforcement.

## Key Directories

| Path | Purpose |
|---|---|
| `packages/contracts/src/sq_bi_contracts/` | Shared domain types: `ids`, `enums`, `common`, `catalog`, `metrics`, `skills`, `query`, `reports`, `exports`, `api` |
| `services/semantic/src/sq_bi_semantic/` | Semantic catalog, metric center, Skill registry. `interfaces.py` (Protocols), `repository.py` (file-backed), `product_repository.py` (SQLite-backed, 1707 lines), `api.py` (30+ endpoints), `sql_validation.py`, `synonyms.py` |
| `services/runtime/src/sq_bi_runtime/` | Query runtime. `api.py` (1507 lines, 14 endpoints, report asset merging), `service.py` (AskDataService dataclass), `config.py`, `db.py` (OracleExecutor), `llm_client.py`, `guardrails.py`, `prompts.py` (6 system prompts), `schema_catalog.py`, `semantic_assets.py`, `settings.py`, `skill_loader.py` |
| `services/export/src/sq_bi_export/` | Export/sharing. `service.py` (ExportService, in-memory), `api.py` (12 routes), `renderers.py` (minimal PDF-1.4 generator) |
| `apps/web/src/` | React SPA. `App.tsx` (6392-line monolithic component), `api.ts` (typed fetch client), `index.css` (Tailwind v4 + theme tokens) |
| `.local/` | Runtime data: SQLite store, uploads, logs, runtime_settings.json |

## Development Commands

```bash
# Python workspace — sync all packages with dev extras
uv sync --all-packages --extra dev

# Run tests for a specific package
cd packages/contracts && uv run pytest
cd services/semantic && uv run pytest
cd services/runtime && uv run pytest
cd services/export && uv run pytest

# Start a service (dev)
cd services/runtime && uv run uvicorn sq_bi_runtime.api:app --reload

# Web frontend
cd apps/web && npm run dev      # dev server
cd apps/web && npm run build    # tsc -b && vite build (production)
cd apps/web && npm run lint     # eslint

# Demo
cd demo && streamlit run streamlit_app.py
cd demo && uv run uvicorn src.tms_askdata.api:app --reload

# Live smoke test
cd services/runtime && uv run python scripts/live_smoke.py
```

## Code Conventions & Common Patterns

### Python

- **File header**: every Python file starts with `from __future__ import annotations`.
- **Sync-only**: all service code is synchronous `def` — no async/await. Threading via `ThreadPoolExecutor` for parallel report asset execution.
- **Pydantic v2 models**: all DTOs use `model_config = ConfigDict(extra="forbid", populate_by_name=True)`. Contract models inherit `ContractModel` base.
- **API pattern**: `FastAPI` + `APIRouter(prefix="/api/v1")`, sync handlers. Every handler generates a `req_id = f"req_{uuid4().hex[:8]}"` and returns `ApiResponse(request_id=req_id, data=...)` or `_api_error(req_id, ErrorCode.VALIDATION_ERROR, str(exc))`.
- **Error handling**: business exceptions (e.g. `ExportNotFoundError`, `ExportPermissionError`) mapped to `ErrorCode` enums via `isinstance` checks in `_handle_error()`. catches `except Exception` with `# noqa: BLE001`.
- **Naming**: `_prefix` for private helpers, PascalCase classes, snake_case functions/vars. Module-level constants UPPER_CASE.
- **Protocol DI**: `@runtime_checkable` Protocol classes for testable abstractions (`CatalogRepository`, `LLMProtocol`, `DBProtocol`, `SummaryProvider`).
- **Config**: `@dataclass` config objects, `load_config(path)` reads YAML + env var overrides. Optional `is_configured` property.
- **SQL**: Oracle dialect via `sqlglot`, `parse_one(sql, read="oracle")`. Guardrails reject DDL/DML, multi-statement, undeclared table aliases, `SELECT *`, cross-schema access.
- **Type aliases**: `UserId = NewType("UserId", str)` for nominal typing.
- **Enums**: `StrEnum` base class, all-lowercase values.
- **ErrorCode enum**: `VALIDATION_ERROR`, `PERMISSION_DENIED`, `NOT_FOUND`, `CONFLICT`, `QUERY_REJECTED`, `EXECUTION_TIMEOUT`, `INTERNAL_ERROR`.
- **ID generation**: prefix-based `f"{prefix}_{uuid4().hex}"` (e.g. `qry_`, `req_`, `sat_`, `lin_`).
- **Tests**: plain pytest, no fixtures framework. `StubLLM`/`FakeDB`/`FakePool` classes, `pytest.raises`, `tmp_path`, `parametrize`. Tests inject stubs via dataclass fields or monkeypatch.
- **Import ordering**: stdlib first, then third-party, then local. Blank line between groups.

### Frontend (TypeScript/React)

- **Monolithic component**: all UI in `App.tsx` (6392 lines) with `useState` hooks, inline sub-components, no router (despite `react-router-dom` in deps), no external state management (despite `@tanstack/react-query` in deps).
- **API client**: custom `api` object in `api.ts` with typed methods per domain. Uses `fetch` with `ApiResponse<T>` envelope pattern.
- **Enums**: exported as union types (`ErrorCode`, `ChartType`, etc.) matching Python `StrEnum` values.
- **CSS**: Tailwind CSS v4 with `@import "tailwindcss"` and custom `@theme` tokens (primary, bg-gray, success, warning, error, dark-*).
- **Charts**: `recharts` (BarChart, LineChart, AreaChart, ResponsiveContainer).
- **Icons**: `lucide-react`.
- **No tests**: no test framework installed.

## Important Files

### Configuration & Build

| File | Purpose |
|---|---|
| `pyproject.toml` | Root uv workspace — members: `packages/contracts`, `services/semantic`, `services/runtime`, `services/export` |
| `uv.lock` | Single workspace lockfile (328 KB) |
| `apps/web/package.json` | React 19 + Vite 8 + Tailwind 4 + TypeScript 6 |
| `apps/web/vite.config.ts` | Vite config with react() + tailwindcss() plugins |
| `apps/web/tsconfig.app.json` | TS strict config, es2023, bundler resolution |
| `.gitignore` | Ignores `.venv/`, `.worktrees/`, `.local/`, `demo/`, `__pycache__/`, etc. |

### Source Entry Points

| File | Purpose |
|---|---|
| `packages/contracts/src/sq_bi_contracts/__init__.py` | Re-exports `API_ROUTES`, `ApiRoute`, `ApiError`, `ApiResponse`, `Page`, `PageRequest`, `UserContext` |
| `services/semantic/src/sq_bi_semantic/api.py` | FastAPI app with `router = APIRouter(prefix="/api/v1")`, 30+ endpoints, global `_repo_instance` |
| `services/runtime/src/sq_bi_runtime/api.py` | FastAPI app factory `create_app()`, 14 endpoints, LLM+Oracle orchestration |
| `services/export/src/sq_bi_export/api.py` | FastAPI app factory `create_app()`, 12 endpoints, CORS for localhost |
| `apps/web/src/main.tsx` | React DOM entry point |
| `apps/web/src/App.tsx` | Main single-component SPA (6392 lines) |

### Data & Content

| File | Purpose |
|---|---|
| `services/semantic/data/tms_semantic.yaml` | 1410-line YAML: TMS semantic data (12 tables, 70 fields, 13 metrics, 8 skills) |
| `packages/contracts/docs/` | `contract_index.md`, `type_model.md`, `api_contract.md` |

## Runtime/Tooling Preferences

- **Python**: >=3.11 required.
- **Package manager**: `uv` for Python workspace. Single `uv.lock` at root.
- **Build system**: **hatchling** for all Python packages (configured per `pyproject.toml`).
- **Frontend**: Node.js (via `npm`). `package-lock.json` at `apps/web/`.
- **Database**: Oracle Database (production via `oracledb`), SQLite (local dev store at `.local/sqbi.sqlite3`).
- **Python test runner**: pytest (per package, no root harness). No coverage or linting tools configured for Python.
- **Frontend lint**: ESLint 10 with flat config (`typescript-eslint`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`).
- **Runtime settings**: persisted to `.local/runtime_settings.json` (JSON with masking for secrets).
- **No Python type checker**: mypy/pyright not configured for backend code.

## Testing & QA

### Python Testing

- **Framework**: pytest >=8.3 (per-package dev dependency).
- **Patterns**: pure pytest — no fixtures framework, no mocks library.
  - **Stubs**: hand-written classes (`StubLLM`, `StubDB`, `FakeLLM`, `FakeDB`, `FakePool`) injected via Protocol/dataclass fields.
  - **Parametrize**: `@pytest.mark.parametrize` for edge cases (guardrails, column validation).
  - **Temp files**: `tmp_path` for ephemeral SQLite databases in semantic tests.
  - **Monkeypatch**: `monkeypatch.setattr` for oracledb/httpx module patching.
- **Test style**: direct assertion + `pytest.raises(ValidationError)` for validation.
- **Per-package test areas**:
  - `packages/contracts/tests/` — 9 contract-shape tests (envelope, serialization, route registry).
  - `services/semantic/tests/` — ~18 tests (catalog, metrics, skills, synonyms, SQL validation, reports, chat, asset revision).
  - `services/runtime/tests/` — 7 files: `test_service.py`, `test_config.py`, `test_guardrails.py`, `test_db.py`, `test_llm_client.py`, `test_prompts.py`, `test_schema_catalog.py`.
  - `services/export/tests/` — 3 integration tests (export+download, share+password verify, subscription).
- **Not configured**: coverage thresholds, mypy, ruff, or any Python linter/formatter.

### Frontend Testing

- **None**: no test framework, no test files, no coverage.

### Running Tests

```bash
# Single package
cd services/runtime && uv run pytest -v

# All packages (manual, no root harness)
for pkg in packages/contracts services/semantic services/runtime services/export; do
  (cd "$pkg" && uv run pytest)
done
```
