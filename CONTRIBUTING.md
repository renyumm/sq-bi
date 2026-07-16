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
   - Ensure all tests pass: `./scripts/check.sh`
   - Ensure no hardcoded identities remain: `python3 scripts/check-hardcoded-identities.py`
4. Open a pull request with a clear description of the change and its motivation.

### Development Setup

```bash
# Python workspace
uv sync --all-packages --extra dev

# Frontend
cd apps/web && npm install

# Run tests
for pkg in packages/contracts services/semantic services/runtime services/export; do
  (cd "$pkg" && uv run pytest)
done

# Start runtime
cd services/runtime && uv run uvicorn sq_bi_runtime.api:app --reload
```

## Open-Core Boundaries

SQ-BI follows an Open-Core model:

- **Community Edition**: Core engine (semantic layer, ask-data, metrics, skills, reports, Oracle connector).
- **Enterprise Edition**: SSO, row-level security, advanced audit, push channels, commercial domain packs.

Contributions to the community edition are welcome. Enterprise features are developed by the core team but may accept contributions under a contributor license agreement.

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
