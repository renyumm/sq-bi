from __future__ import annotations

from enum import StrEnum


class DatabaseType(StrEnum):
    ORACLE = "oracle"
    MYSQL = "mysql"
    POSTGRESQL = "postgresql"
    CLICKHOUSE = "clickhouse"


class AuthBackendType(StrEnum):
    LOCAL = "local"
    SSO_OIDC = "sso-oidc"
    SSO_SAML = "sso-saml"
    SSO_LDAP = "sso-ldap"


class DataType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    ENUM = "enum"
    PERCENTAGE = "percentage"
    RATIO = "ratio"


class MetricVisibility(StrEnum):
    OFFICIAL = "official"
    PRIVATE = "private"
    SHARED = "shared"


class AssetSourceType(StrEnum):
    OFFICIAL_PACK = "official_pack"
    ENTERPRISE_PACK = "enterprise_pack"
    PERSONAL_WORKSPACE = "personal_workspace"


class AssetType(StrEnum):
    METRIC = "metric"
    SKILL = "skill"
    REPORT = "report"


class RuntimeVisibilityReason(StrEnum):
    """Machine-readable reason a resolved or excluded runtime asset carries.

    ACTIVE_DEPLOYMENT and PERSONAL_WORKSPACE_BINDING mark inclusion; the
    remaining values are exclusion reasons surfaced to admin diagnostics.
    """

    ACTIVE_DEPLOYMENT = "active_deployment"
    PERSONAL_WORKSPACE_BINDING = "personal_workspace_binding"
    DEPLOYMENT_INACTIVE = "deployment_inactive"
    DEPLOYMENT_UNVALIDATED = "deployment_unvalidated"
    VERSION_NOT_DEPLOYED = "version_not_deployed"
    FOREIGN_WORKSPACE = "foreign_workspace"
    NO_WORKSPACE_BINDING = "no_workspace_binding"


class ExecutionPath(StrEnum):
    FORMAL_METRIC = "formal_metric"
    CONTROLLED_EXPLORATION = "controlled_exploration"


class ExecutionStage(StrEnum):
    PLAN_VALIDATION = "plan_validation"
    COMPILATION = "compilation"
    GUARDRAIL = "guardrail"
    EXECUTION = "execution"
    RENDERING = "rendering"


class ExecutionFailureCode(StrEnum):
    INVALID_PLAN = "invalid_plan"
    MISSING_MAPPING = "missing_mapping"
    AMBIGUOUS_MAPPING = "ambiguous_mapping"
    OUT_OF_SCOPE_MAPPING = "out_of_scope_mapping"
    UNSUPPORTED_EXPRESSION = "unsupported_expression"
    QUERY_REJECTED = "query_rejected"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_TIMEOUT = "execution_timeout"


class SkillType(StrEnum):
    METRIC = "metric"
    REPORT = "report"
    EXPORT = "export"


class SkillVisibility(StrEnum):
    OFFICIAL = "official"
    PRIVATE = "private"
    SHARED = "shared"


class ChartType(StrEnum):
    NONE = "none"
    KPI = "kpi"
    TABLE = "table"
    BAR = "bar"
    LINE = "line"
    AREA = "area"
    PIE = "pie"
    COMBO = "combo"


class ExportFormat(StrEnum):
    PDF = "pdf"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    QUERY_REJECTED = "QUERY_REJECTED"
    EXECUTION_TIMEOUT = "EXECUTION_TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
