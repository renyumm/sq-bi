# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.x     | :white_check_mark: |

## Reporting a Vulnerability

SQ-BI handles sensitive enterprise data. If you discover a security vulnerability, please **do not** file a public issue.

Instead, send a description of the vulnerability to the maintainers directly. You can expect:

- Acknowledgment within 48 hours.
- A timeline for investigation and fix.
- Credit for the discovery (if desired) after the fix is released.

## Security Features

- **SQL Guardrails**: All queries pass through deterministic SQL parsing and validation before execution. LLM-generated SQL is never executed directly.
- **Row-Level Security**: RLS predicates are injected by the middleware, independent of model output. Prompt injection cannot bypass scope restrictions.
- **Secret Management**: Credentials are sourced through a pluggable secret provider (env/file/external). Secrets are masked in logs and API responses.
- **Audit Trail**: Every query execution is persisted in an append-only audit log. Records are immutable through normal application paths.
