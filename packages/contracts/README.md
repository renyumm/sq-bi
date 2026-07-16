# SQ-BI Product Foundation Contracts

This worktree defines the shared domain types, response envelopes, and API contract baseline for the formal SQ-BI product.

It is intentionally independent from any single business domain. TMS data can be used as sample semantic input, but this package must stay platform-level.

## Responsibilities

- Define stable IDs, enums, request models, response models, and shared DTOs.
- Define the API namespace and response envelope used by all services.
- Provide tests that protect contract shape and serialization behavior.
- Serve as the first branch other product worktrees depend on.

## Local Setup

Each worktree owns its own `.venv`:

```bash
uv sync --extra dev
uv run pytest
```

If `uv` is unavailable in the shell, install or enable it first before creating the local environment.

## Package

The public package is `sq_bi_contracts`.

Primary modules:

- `ids`: typed ID aliases.
- `enums`: shared enum values.
- `common`: response envelope, errors, pagination, user context.
- `catalog`: data source, semantic table, semantic field contracts.
- `metrics`: official and user metric contracts.
- `skills`: Skill definition and resolution contracts.
- `query`: AI-native AskData result, lineage, and audit contracts.
- `reports`: report Skill contracts.
- `exports`: export, sharing, and subscription contracts.
- `api`: API route registry.

## Rule

No endpoint accepts user-provided free SQL. LLM output can become a draft, Skill/report definition, or guarded read-only query result, but never executable authority without guardrails.
