# Contributing to SQ-BI

Thank you for your interest in contributing to SQ-BI (智慧问数)!

## Code of Conduct

This project adheres to the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating, you agree to uphold its standards.

## How to Contribute

### Reporting Issues

- Check existing issues before filing a duplicate.
- Use the issue template and include: reproduction steps, expected behavior, actual behavior, environment details.
- For security vulnerabilities, email the maintainers directly — see [SECURITY.md](SECURITY.md).

### Feature Requests

- Open a GitHub Discussion or issue describing the use case, proposed behavior, and why it fits the Open-Core model.
- Large features should be discussed before implementation.

### Pull Requests

1. Fork the repository.
2. Create a feature branch from `main`.
3. Make your changes:
   - Follow existing code style (see AGENTS.md for conventions).
   - Include tests for new functionality.
   - Ensure all tests pass: `./scripts/test-all.sh`
   - Ensure no hardcoded identities remain: `python3 scripts/check-hardcoded-identities.py`
4. Open a pull request with a clear description of the change and its motivation.

### Development Setup

```bash
# Python workspace
uv sync --all-packages --extra dev

# Frontend
cd apps/web && npm ci

# Run everything (backend tests, identity check, frontend lint/build)
./scripts/test-all.sh

# Start runtime
cd services/runtime && uv run uvicorn sq_bi_runtime.api:app --reload
```

### Code Structure

```text
packages/contracts   Pydantic 契约、枚举、统一响应信封
services/semantic    语义目录、指标/Skill/报表和领域包仓储
services/runtime     Harness 规划、确定性执行、连接池、防护、血缘
services/export      导出、分享与订阅
apps/web             React 19 + Vite + Tailwind 管理与问数界面
```

Dependency direction: `contracts → semantic → runtime → web/export`. The export
service can run standalone on port 8001; in the production container Nginx routes
export/share/subscription paths to it and the rest of `/api` to runtime.

## Open-Core Boundaries

SQ-BI follows an Open-Core model:

- **Community Edition**: Core engine (semantic layer, ask-data, metrics, skills, reports, Oracle connector).
- **Enterprise Edition**: SSO, row-level security, advanced audit, push channels, commercial domain packs.

Contributions to the community edition are welcome. Enterprise features are developed by the core team but may accept contributions under a contributor license agreement.

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
