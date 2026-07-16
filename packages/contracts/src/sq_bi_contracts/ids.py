from __future__ import annotations

from typing import NewType

UserId = NewType("UserId", str)
OrgId = NewType("OrgId", str)
RoleId = NewType("RoleId", str)
DataSourceId = NewType("DataSourceId", str)
SemanticTableId = NewType("SemanticTableId", str)
SemanticFieldId = NewType("SemanticFieldId", str)
MetricCode = NewType("MetricCode", str)
SkillId = NewType("SkillId", str)
ReportSkillId = NewType("ReportSkillId", str)
QueryId = NewType("QueryId", str)
AuditId = NewType("AuditId", str)
LineageId = NewType("LineageId", str)
ExportJobId = NewType("ExportJobId", str)
ShareId = NewType("ShareId", str)
SubscriptionId = NewType("SubscriptionId", str)
