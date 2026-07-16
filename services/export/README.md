# SQ-BI Export Service

Owns `/api/v1/exports`, `/api/v1/shares`, and `/api/v1/subscriptions`.

The service accepts immutable `QueryResult` or `ReportSnapshot` payloads from the public contracts. It does not query the database or call query runtime directly.

Current implementation:

- Generates deterministic PDF artifacts from captured snapshots.
- Includes source query ids and lineage in exported content.
- Creates password- or user-scoped share links and preview payloads.
- Stores subscription definitions and records an integration gap when `run-now` is requested without a report snapshot provider.
