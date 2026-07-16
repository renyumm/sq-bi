from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApiRoute:
    method: str
    path: str
    owner: str
    description: str


API_ROUTES: tuple[ApiRoute, ...] = (
    # Foundation
    ApiRoute("GET", "/api/v1/health", "foundation-contracts", "Service health."),
    ApiRoute("GET", "/api/v1/version", "foundation-contracts", "Service and contract version."),
    ApiRoute("GET", "/api/v1/contracts", "foundation-contracts", "Machine-readable contract index."),
    # Catalog
    ApiRoute("GET", "/api/v1/catalog/data-sources", "semantic-layer", "List authorized data sources."),
    ApiRoute("GET", "/api/v1/catalog/tables", "semantic-layer", "List semantic tables."),
    ApiRoute("GET", "/api/v1/catalog/fields", "semantic-layer", "List semantic fields."),
    # Metrics
    ApiRoute("GET", "/api/v1/metrics", "semantic-layer", "List authorized metrics."),
    ApiRoute("POST", "/api/v1/ai/metrics/draft", "query-runtime-security", "Draft a user metric with LLM."),
    ApiRoute("POST", "/api/v1/metrics/user-defined", "semantic-layer", "Persist a confirmed user metric."),
    # Skills
    ApiRoute("GET", "/api/v1/skills", "semantic-layer", "List authorized Skills."),
    ApiRoute("POST", "/api/v1/skills/resolve", "semantic-layer", "Resolve typed Skill trigger text."),
    # AI / Query
    ApiRoute("POST", "/api/v1/ai/conversation/interpret", "query-runtime-security", "Use LLM to judge whether a message continues a pending asset invocation."),
    ApiRoute("POST", "/api/v1/query/ask", "query-runtime-security", "Execute AI-native AskData Skill with guarded LLM SQL."),
    ApiRoute("POST", "/api/v1/query/harness", "query-runtime-security", "Execute a bounded controlled-tool planning loop."),
    # Reports
    ApiRoute("GET", "/api/v1/reports", "ui-workflows", "List report Skills."),
    ApiRoute("POST", "/api/v1/reports", "ui-workflows", "Create report Skill."),
    ApiRoute("POST", "/api/v1/reports/{report_skill_id}/execute", "query-runtime-security", "Execute report Skill."),
    # Exports / Sharing
    ApiRoute("POST", "/api/v1/exports", "export-sharing", "Create export job."),
    ApiRoute("GET", "/api/v1/exports/{export_job_id}", "export-sharing", "Fetch export job."),
    ApiRoute("GET", "/api/v1/exports/{export_job_id}/download", "export-sharing", "Download export artifact."),
    ApiRoute("POST", "/api/v1/shares", "export-sharing", "Create secure share link."),
    ApiRoute("GET", "/api/v1/shares/{share_id}", "export-sharing", "Fetch share preview."),
    ApiRoute("POST", "/api/v1/shares/{share_id}/verify", "export-sharing", "Verify secure share access."),
    ApiRoute("POST", "/api/v1/subscriptions", "export-sharing", "Create report subscription."),
    ApiRoute("GET", "/api/v1/subscriptions", "export-sharing", "List report subscriptions."),
    ApiRoute("PATCH", "/api/v1/subscriptions/{subscription_id}", "export-sharing", "Update report subscription."),
    ApiRoute("POST", "/api/v1/subscriptions/{subscription_id}/run-now", "export-sharing", "Run report subscription now."),
    # Settings
    ApiRoute("GET", "/api/v1/settings/llm", "query-runtime-security", "Fetch local LLM settings."),
    ApiRoute("PATCH", "/api/v1/settings/llm", "query-runtime-security", "Update local LLM settings."),
    ApiRoute("GET", "/api/v1/settings/db", "query-runtime-security", "Fetch local DB settings."),
    ApiRoute("PATCH", "/api/v1/settings/db", "query-runtime-security", "Update local DB settings."),
    # Auth (Capability: identity-access-control)
    ApiRoute("POST", "/api/v1/auth/login", "identity-access-control", "Authenticate with local credentials."),
    ApiRoute("POST", "/api/v1/auth/logout", "identity-access-control", "Destroy active session."),
    ApiRoute("GET", "/api/v1/auth/session", "identity-access-control", "Fetch current session info."),
    # Data Source Management (Capability: datasource-abstraction)
    ApiRoute("GET", "/api/v1/admin/data-sources", "datasource-abstraction", "List configured data sources."),
    ApiRoute("POST", "/api/v1/admin/data-sources", "datasource-abstraction", "Register a new data source."),
    ApiRoute("PATCH", "/api/v1/admin/data-sources/{data_source_id}", "datasource-abstraction", "Update data source configuration."),
    ApiRoute("DELETE", "/api/v1/admin/data-sources/{data_source_id}", "datasource-abstraction", "Remove a data source."),
    # Domain Pack Management (Capability: domain-pack-framework)
    ApiRoute("GET", "/api/v1/admin/packs", "domain-pack-framework", "List enabled packs with deployment summaries."),
    ApiRoute("POST", "/api/v1/admin/packs/install", "domain-pack-framework", "Install a domain pack."),
    ApiRoute("POST", "/api/v1/admin/packs/{pack_id}/enable", "domain-pack-framework", "Enable a domain pack."),
    ApiRoute("POST", "/api/v1/admin/packs/{pack_id}/disable", "domain-pack-framework", "Disable a domain pack."),
    # Deployment / Mounting (Capability: pack-deployment-mounting)
    ApiRoute("POST", "/api/v1/admin/deployments", "pack-deployment-mounting", "Create or reuse deployment instance and trigger mounting."),
    ApiRoute("GET", "/api/v1/admin/deployments/{deployment_id}/pending", "pack-deployment-mounting", "List pending mappings requiring confirmation."),
    ApiRoute("POST", "/api/v1/admin/deployments/{deployment_id}/mappings/{standard_field_id}/remap", "pack-deployment-mounting", "Prepare replacement candidates for a confirmed mapping."),
    ApiRoute("POST", "/api/v1/admin/deployments/{deployment_id}/confirm", "pack-deployment-mounting", "Confirm a pending field mapping."),
    ApiRoute("POST", "/api/v1/admin/deployments/{deployment_id}/smoke-test", "pack-deployment-mounting", "Run smoke test for a deployment instance."),
    ApiRoute("GET", "/api/v1/admin/deployments/{deployment_id}/status", "pack-deployment-mounting", "Query deployment readiness and coverage."),
    # Audit (Capability: observability-and-audit)
    ApiRoute("GET", "/api/v1/admin/audit", "observability-and-audit", "Query audit log."),
    ApiRoute("GET", "/api/v1/admin/audit/{audit_id}", "observability-and-audit", "Fetch single audit record."),
    # Observability (Capability: observability-and-audit)
    ApiRoute("GET", "/api/v1/admin/metrics", "observability-and-audit", "Prometheus-style operational metrics."),
)
