# Shared Type Model

This document describes the platform contracts exposed by `sq_bi_contracts`.

## Core Objects

- `UserContext`: current user, organization, roles, locale, timezone, and data scope.
- `DataSource`: a read-only database connection alias.
- `SemanticTable`: a business-facing table definition.
- `SemanticField`: a business-facing field definition with optional enum explanations.
- `MetricDefinition`: official, private, or shared metric definition.
- `SkillDefinition`: callable metric/report/export Skill metadata.
- `QueryResult`: columns, rows, chart suggestion, lineage, audit id, and optional summary.
- `ReportDefinition`: persisted report Skill layout and widgets.
- `AssetKey`: stable source-scoped identity (`source_type`, `source_id`, `asset_type`, `local_code`) whose `asset_id` does not contain a version.
- `AssetRef`: exact versioned reference to an `AssetKey`; metrics, Skills, and reports expose it additively for backward compatibility.
- `ExportJob`: immutable export task based on query/report snapshots.
- `ExportArtifact`: generated PDF metadata with content hash.
- `ShareLink` and `SharePreview`: secure export sharing metadata and limited snapshot preview.
- `Subscription`: scheduled report export definition with next-run time.

## Extension Rule

Additive fields are allowed when needed. Renaming or changing the meaning of existing fields requires updating foundation contracts and tests first.
