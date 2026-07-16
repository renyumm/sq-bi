from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from sq_bi_contracts import API_ROUTES, ApiError, ApiResponse
from sq_bi_contracts.common import UserContext
from sq_bi_contracts.enums import ChartType, DatabaseType, ErrorCode
from sq_bi_contracts.exports import CreateExportRequest
from sq_bi_contracts.catalog import DataSource, SemanticTable
from sq_bi_contracts.metrics import MetricDefinition, MetricFormula
from sq_bi_contracts.query import ChartSuggestion, Lineage, QueryResult


def test_api_response_success_envelope() -> None:
    response = ApiResponse[dict[str, str]](request_id="req_1", data={"status": "ok"})
    assert response.model_dump()["request_id"] == "req_1"
    assert response.error is None


def test_api_response_error_envelope() -> None:
    error = ApiError(code=ErrorCode.PERMISSION_DENIED, message="denied")
    response = ApiResponse[None](request_id="req_2", error=error)
    dumped = response.model_dump(mode="json")
    assert dumped["error"]["code"] == "PERMISSION_DENIED"




def test_api_response_rejects_mixed_payload() -> None:
    error = ApiError(code=ErrorCode.INTERNAL_ERROR, message="bad")
    with pytest.raises(ValidationError):
        ApiResponse[dict[str, bool]](request_id="req_3", data={"ok": False}, error=error)


def test_api_response_rejects_empty_payload() -> None:
    with pytest.raises(ValidationError):
        ApiResponse[None](request_id="req_4")

def test_contract_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        UserContext(user_id="u1", display_name="User", org_id="o1", unknown=True)


def test_metric_definition_serializes_visibility_and_formula() -> None:
    metric = MetricDefinition(
        metric_code="OTD_RATE",
        name="准时交付率",
        definition="按计划时间内完成交付的比例。",
        formula=MetricFormula(
            expression=(
                "select round(100 * count(case when d.actual_time <= d.plan_time then 1 end) "
                "/ nullif(count(1), 0), 2) as otd_rate from fact_delivery d"
            )
        ),
        data_source_id="ds_tms",
        owner="运营部",
        synonyms=["OTD", "准时率"],
    )
    dumped = metric.model_dump(mode="json")
    assert dumped["visibility"] == "official"
    assert dumped["formula"]["expression"].startswith("select round")


def test_query_result_requires_audit_and_lineage() -> None:
    result = QueryResult(
        query_id="q1",
        audit_id="a1",
        columns=["factory", "otd_rate"],
        rows=[["天津厂", 98.2]],
        chart_suggestion=ChartSuggestion(chart_type=ChartType.BAR, title="准时交付率"),
        lineage=Lineage(
            lineage_id="l1",
            source_system="TMS_SAMPLE",
            data_source_id="ds_tms",
            metric_codes=["OTD_RATE"],
            executed_at=datetime.now(timezone.utc),
        ),
    )
    assert result.audit_id == "a1"
    assert result.lineage.metric_codes == ["OTD_RATE"]


def test_catalog_contracts_are_platform_level() -> None:
    ds = DataSource(
        data_source_id="ds1",
        name="Operations Warehouse",
        database_type=DatabaseType.POSTGRESQL,
        connection_alias="ops_ro",
    )
    table = SemanticTable(
        table_id="tbl1",
        data_source_id=ds.data_source_id,
        physical_name="fact_delivery",
        business_name="交付事实表",
        description="标准交付分析事实表。",
    )
    assert table.data_source_id == "ds1"
    assert "tms_askdata" not in repr(table).lower()


def test_api_route_registry_contains_required_routes() -> None:
    route_pairs = {(route.method, route.path) for route in API_ROUTES}
    assert ("POST", "/api/v1/query/ask") in route_pairs
    assert ("POST", "/api/v1/ai/metrics/draft") in route_pairs
    assert ("POST", "/api/v1/exports") in route_pairs
    assert ("GET", "/api/v1/exports/{export_job_id}/download") in route_pairs
    assert ("POST", "/api/v1/shares/{share_id}/verify") in route_pairs
    assert ("PATCH", "/api/v1/subscriptions/{subscription_id}") in route_pairs
    assert ("POST", "/api/v1/subscriptions/{subscription_id}/run-now") in route_pairs
    assert ("GET", "/api/v1/settings/llm") in route_pairs
    assert ("PATCH", "/api/v1/settings/llm") in route_pairs
    assert ("GET", "/api/v1/settings/db") in route_pairs
    assert ("PATCH", "/api/v1/settings/db") in route_pairs


def test_create_export_request_requires_snapshot_payload() -> None:
    with pytest.raises(ValidationError):
        CreateExportRequest(user_id="u1", export_format="pdf")


def test_auth_token_claims_serialization() -> None:
    from sq_bi_contracts.auth import TokenClaims

    claims = TokenClaims(sub="u1", org_id="o1", role_ids=["admin"])
    dumped = claims.model_dump(mode="json")
    assert dumped["sub"] == "u1"
    assert dumped["iss"] == "sq-bi"


def test_login_request_serialization() -> None:
    from sq_bi_contracts.auth import LoginRequest
    from sq_bi_contracts.enums import AuthBackendType

    req = LoginRequest(username="admin", password="secret")
    dumped = req.model_dump(mode="json")
    assert dumped["username"] == "admin"
    assert dumped["backend"] == "local"
    assert AuthBackendType.LOCAL.value == "local"


def test_session_info_contains_required_fields() -> None:
    from datetime import datetime, timezone
    from sq_bi_contracts.auth import SessionInfo

    expires = datetime(2026, 12, 31, tzinfo=timezone.utc)
    created = datetime(2026, 6, 1, tzinfo=timezone.utc)
    session = SessionInfo(
        session_id="sess_abc",
        user_id="u1",
        org_id="o1",
        display_name="Admin",
        role_ids=["admin"],
        expires_at=expires,
        created_at=created,
    )
    dumped = session.model_dump(mode="json")
    assert dumped["session_id"] == "sess_abc"
    assert dumped["role_ids"] == ["admin"]


def test_rls_scope_mapping_serialization() -> None:
    from sq_bi_contracts.rls import RlsScopeMapping, RlsScopePolicy

    mapping = RlsScopeMapping(
        target_type="role",
        target_id="base_user",
        table_physical="fact_delivery",
        column_physical="factory_code",
        value="'天津厂'",
    )
    policy = RlsScopePolicy(
        policy_id="rls_1",
        data_source_id="ds_tms",
        mappings=[mapping],
    )
    dumped = policy.model_dump(mode="json")
    assert dumped["policy_id"] == "rls_1"
    assert dumped["mappings"][0]["target_type"] == "role"


def test_rls_scope_resolved_serialization() -> None:
    from sq_bi_contracts.rls import RlsScopeResolved

    resolved = RlsScopeResolved(
        user_id="u1",
        data_source_id="ds_tms",
        table_physical="fact_delivery",
        predicates=["factory_code = '天津厂'"],
        is_full_access=False,
    )
    dumped = resolved.model_dump(mode="json")
    assert dumped["predicates"] == ["factory_code = '天津厂'"]
    assert dumped["is_full_access"] is False


def test_datasource_connection_config_serialization() -> None:
    from sq_bi_contracts.datasource import DataSourceConnectionConfig
    from sq_bi_contracts.enums import DatabaseType

    cfg = DataSourceConnectionConfig(
        data_source_id="ds1",
        name="TMS Prod",
        engine=DatabaseType.ORACLE,
        host="db.example.com",
        port=1521,
        database="tms",
        username="reader",
        password="s3cret",
    )
    dumped = cfg.model_dump(mode="json")
    assert dumped["engine"] == "oracle"
    assert dumped["port"] == 1521
    assert dumped["password"] == "s3cret"


def test_domain_pack_manifest_serialization() -> None:
    from sq_bi_contracts.domain_pack import (
        DomainPackManifest,
        PackAsset,
        PackDependency,
    )

    manifest = DomainPackManifest(
        pack_id="tms",
        namespace="tms",
        name="TMS Domain Pack",
        version="1.0.0",
        dependencies=[PackDependency(pack_id="core", version_spec=">=0.1.0")],
        assets=[PackAsset(path="semantic.yaml", asset_type="semantic")],
    )
    dumped = manifest.model_dump(mode="json")
    assert dumped["pack_id"] == "tms"
    assert dumped["dependencies"][0]["pack_id"] == "core"


def test_audit_record_serialization() -> None:
    from datetime import datetime, timezone
    from sq_bi_contracts.audit import AuditRecord

    record = AuditRecord(
        audit_id="aud_001",
        request_id="req_abc",
        user_id="u1",
        org_id="o1",
        data_source_id="ds_tms",
        question="全厂OTD",
        executed_sql="SELECT * FROM fact_delivery",
        resolved_metrics=["OTD_RATE"],
        status="success",
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    dumped = record.model_dump(mode="json")
    assert dumped["audit_id"] == "aud_001"
    assert dumped["status"] == "success"


def test_error_code_includes_new_values() -> None:
    assert ErrorCode.UNAUTHORIZED.value == "UNAUTHORIZED"
    assert ErrorCode.FORBIDDEN.value == "FORBIDDEN"


def test_auth_backend_type_values() -> None:
    from sq_bi_contracts.enums import AuthBackendType

    assert AuthBackendType.LOCAL.value == "local"
    assert AuthBackendType.SSO_OIDC.value == "sso-oidc"
    assert AuthBackendType.SSO_SAML.value == "sso-saml"
    assert AuthBackendType.SSO_LDAP.value == "sso-ldap"


def test_api_route_registry_includes_new_routes() -> None:
    route_pairs = {(route.method, route.path) for route in API_ROUTES}
    # Auth routes
    assert ("POST", "/api/v1/auth/login") in route_pairs
    assert ("POST", "/api/v1/auth/logout") in route_pairs
    assert ("GET", "/api/v1/auth/session") in route_pairs
    # Data source admin routes
    assert ("GET", "/api/v1/admin/data-sources") in route_pairs
    assert ("POST", "/api/v1/admin/data-sources") in route_pairs
    assert ("DELETE", "/api/v1/admin/data-sources/{data_source_id}") in route_pairs
    # Domain pack routes
    assert ("GET", "/api/v1/admin/packs") in route_pairs
    assert ("POST", "/api/v1/admin/packs/install") in route_pairs
    assert ("POST", "/api/v1/admin/packs/{pack_id}/enable") in route_pairs
    # Audit routes
    assert ("GET", "/api/v1/admin/audit") in route_pairs
    assert ("GET", "/api/v1/admin/audit/{audit_id}") in route_pairs
    # Observability
    assert ("GET", "/api/v1/admin/metrics") in route_pairs


# ── Standard field / Logical metric / Field mounting tests ──


def test_standard_field_definition_serialization() -> None:
    from sq_bi_contracts.field_mount import StandardFieldDefinition
    from sq_bi_contracts.enums import DataType

    field = StandardFieldDefinition(
        field_id="deliver_no",
        business_name="运单号",
        data_type=DataType.TEXT,
        description="唯一运单编号",
    )
    dumped = field.model_dump(mode="json")
    assert dumped["field_id"] == "deliver_no"
    assert dumped["data_type"] == "text"


def test_logical_metric_formula_serialization() -> None:
    from sq_bi_contracts.field_mount import LogicalMetricFormula

    formula = LogicalMetricFormula(
        expression="count_distinct(deliver_no)",
        referenced_standard_fields=["deliver_no"],
        time_field="plan_time",
    )
    dumped = formula.model_dump(mode="json")
    assert dumped["expression"] == "count_distinct(deliver_no)"
    assert "deliver_no" in dumped["referenced_standard_fields"]


def test_logical_metric_definition_serialization() -> None:
    from sq_bi_contracts.field_mount import LogicalMetricDefinition, LogicalMetricFormula

    metric = LogicalMetricDefinition(
        metric_code="SHIPMENT_CNT",
        name="执行单量",
        definition="统计运单数量",
        logical_formula=LogicalMetricFormula(
            expression="count_distinct(deliver_no)",
            referenced_standard_fields=["deliver_no"],
        ),
        data_source_id="ds_tms",
        owner="运营部",
    )
    dumped = metric.model_dump(mode="json")
    assert dumped["metric_code"] == "SHIPMENT_CNT"
    assert dumped["logical_formula"]["expression"] == "count_distinct(deliver_no)"


def test_field_mapping_serialization() -> None:
    from datetime import datetime, timezone
    from sq_bi_contracts.field_mount import FieldMapping

    mapping = FieldMapping(
        mapping_id="map_001",
        pack_id="tms",
        standard_field_id="deliver_no",
        data_source_id="ds_tms",
        physical_table="HR_DELIVER_FORM",
        physical_column="DELIVER_NO",
        confidence=0.95,
        source="auto",
        created_at=datetime.now(timezone.utc),
    )
    dumped = mapping.model_dump(mode="json")
    assert dumped["pack_id"] == "tms"
    assert dumped["physical_column"] == "DELIVER_NO"


def test_pending_mapping_serialization() -> None:
    from sq_bi_contracts.field_mount import CandidateMapping, PendingMapping

    pending = PendingMapping(
        standard_field_id="factory_code",
        business_name="工厂代码",
        candidates=[
            CandidateMapping(
                physical_table="HR_DELIVER_CARRY",
                physical_column="FACTORY_CODE",
                confidence=0.85,
                reason="名称和类型匹配",
            ),
        ],
        outside_scope_candidates=[
            CandidateMapping(
                physical_table="HR_PROJECT_BASE",
                physical_column="PROJECT_NAME",
                confidence=1.0,
                reason="领域包验证映射",
            ),
        ],
    )
    dumped = pending.model_dump(mode="json")
    assert dumped["standard_field_id"] == "factory_code"
    assert dumped["candidates"][0]["confidence"] == 0.85
    assert dumped["outside_scope_candidates"][0]["physical_column"] == "PROJECT_NAME"


def test_mount_trigger_request_response() -> None:
    from sq_bi_contracts.field_mount import MountTriggerRequest, MountTriggerResponse

    req = MountTriggerRequest(pack_id="tms", data_source_id="ds_tms")
    assert req.pack_id == "tms"

    resp = MountTriggerResponse(status="completed")
    assert resp.status == "completed"


def test_smoke_test_result_serialization() -> None:
    from sq_bi_contracts.field_mount import SmokeTestMetric, SmokeTestResult

    result = SmokeTestResult(
        pack_id="tms",
        data_source_id="ds_tms",
        metrics=[
            SmokeTestMetric(metric_code="SHIPMENT_CNT", name="执行单量", compiled=True, executed=True, row_count=100),
        ],
        all_passed=True,
    )
    dumped = result.model_dump(mode="json")
    assert dumped["all_passed"] is True
    assert dumped["metrics"][0]["row_count"] == 100


def test_mount_status_serialization() -> None:
    from sq_bi_contracts.field_mount import MountStatus

    status = MountStatus(
        pack_id="tms",
        data_source_id="ds_tms",
        total_standard_fields=10,
        mapped_fields=7,
        pending_fields=3,
        is_ready=False,
    )
    dumped = status.model_dump(mode="json")
    assert dumped["total_standard_fields"] == 10
    assert dumped["is_ready"] is False


def test_pack_standard_field_in_manifest() -> None:
    from sq_bi_contracts.domain_pack import DomainPackManifest, PackStandardField

    manifest = DomainPackManifest(
        pack_id="tms",
        namespace="tms",
        name="TMS Domain Pack",
        version="1.0.0",
        standard_fields=[
            PackStandardField(field_id="deliver_no", business_name="运单号", data_type="text"),
        ],
    )
    dumped = manifest.model_dump(mode="json")
    assert len(dumped["standard_fields"]) == 1
    assert dumped["standard_fields"][0]["field_id"] == "deliver_no"


def test_backward_compat_metric_with_physical_sql() -> None:
    """Old MetricFormula with physical SQL should still parse (task 1.5)."""
    from sq_bi_contracts.metrics import MetricDefinition, MetricFormula

    metric = MetricDefinition(
        metric_code="OTD_RATE",
        name="准时交付率",
        definition="按计划时间内完成交付的比例。",
        formula=MetricFormula(
            expression=(
                "select round(100 * count(case when d.actual_time <= d.plan_time then 1 end) "
                "/ nullif(count(1), 0), 2) as otd_rate from fact_delivery d"
            )
        ),
        data_source_id="ds_tms",
        owner="运营部",
    )
    dumped = metric.model_dump(mode="json")
    assert dumped["formula"]["expression"].startswith("select round")
    # optional logical_formula should be None
    assert dumped.get("logical_formula") is None


def test_metric_with_both_formulas() -> None:
    """Metric can carry both physical SQL (backward compat) and logical formula."""
    from sq_bi_contracts.metrics import MetricDefinition, MetricFormula, LogicalMetricFormula

    metric = MetricDefinition(
        metric_code="SHIPMENT_CNT",
        name="执行单量",
        definition="统计运单数量",
        formula=MetricFormula(expression="select count(distinct deliver_no) from hr_deliver_form"),
        logical_formula=LogicalMetricFormula(
            expression="count_distinct(deliver_no)",
            referenced_standard_fields=["deliver_no"],
        ),
        data_source_id="ds_tms",
        owner="运营部",
    )
    dumped = metric.model_dump(mode="json")
    assert dumped["formula"]["expression"].startswith("select")
    assert dumped["logical_formula"]["expression"] == "count_distinct(deliver_no)"

# ── Phase 0 gate: Evidence, DeploymentInstance, DSL transform, routes ──


def test_mapping_evidence_serialization() -> None:
    """MappingEvidence carries multi-signal fields correctly."""
    from sq_bi_contracts.field_mount import MappingEvidence

    ev = MappingEvidence(
        name_similarity=0.92,
        business_name_similarity=0.85,
        type_compatible=True,
        comment_evidence="column comment mentions 运单",
        sample_values=["DELIVER_001", "DELIVER_002"],
        conflicting_candidates=["ALT_TABLE.DELIVER_ID"],
        affected_metric_count=3,
        data_quality_flags=["null_rate_high"],
    )
    dumped = ev.model_dump(mode="json")
    assert dumped["name_similarity"] == 0.92
    assert dumped["affected_metric_count"] == 3
    assert "null_rate_high" in dumped["data_quality_flags"]


def test_candidate_mapping_carries_evidence() -> None:
    """CandidateMapping now includes evidence sub-object."""
    from sq_bi_contracts.field_mount import CandidateMapping, MappingEvidence

    c = CandidateMapping(
        physical_table="HR_DELIVER_FORM",
        physical_column="DELIVER_NO",
        confidence=0.9,
        reason="name_similarity=0.92",
        evidence=MappingEvidence(name_similarity=0.92, type_compatible=True),
    )
    dumped = c.model_dump(mode="json")
    assert dumped["evidence"]["name_similarity"] == 0.92
    assert dumped["evidence"]["type_compatible"] is True


def test_deployment_instance_serialization() -> None:
    """DeploymentInstance is a valid first-class contract model."""
    from sq_bi_contracts.field_mount import DeploymentInstance

    di = DeploymentInstance(
        deployment_id="dep_abc123",
        pack_id="tms",
        pack_version="1.0.0",
        data_source_id="ds_tms",
        validation_status="unvalidated",
        coverage=0.0,
    )
    dumped = di.model_dump(mode="json")
    assert dumped["deployment_id"] == "dep_abc123"
    assert dumped["validation_status"] == "unvalidated"


def test_deployment_instance_environment_defaults_to_default() -> None:
    """`environment` is additive (P3 task 2.1): omitting it must not break
    existing construction sites, and it defaults to 'default'."""
    from sq_bi_contracts.field_mount import DeploymentInstance

    di = DeploymentInstance(
        deployment_id="dep_env1", pack_id="tms", pack_version="1.0.0", data_source_id="ds_tms",
    )
    assert di.environment == "default"

    staged = DeploymentInstance(
        deployment_id="dep_env2", pack_id="tms", pack_version="1.0.0", data_source_id="ds_tms",
        environment="staging",
    )
    assert staged.environment == "staging"


def test_create_deployment_request_response() -> None:
    """CreateDeploymentRequest and Response round-trip correctly."""
    from sq_bi_contracts.field_mount import (
        CreateDeploymentRequest,
        CreateDeploymentResponse,
        DeploymentInstance,
    )

    req = CreateDeploymentRequest(pack_id="tms", data_source_id="ds_tms")
    assert req.data_source_id == "ds_tms"

    dep = DeploymentInstance(
        deployment_id="dep_001",
        pack_id="tms",
        pack_version="1.0.0",
        data_source_id="ds_tms",
        validation_status="unvalidated",
        coverage=0.0,
    )
    resp = CreateDeploymentResponse(deployment=dep, auto_mapped_count=5, errors=[])
    dumped = resp.model_dump(mode="json")
    assert dumped["auto_mapped_count"] == 5
    assert dumped["deployment"]["deployment_id"] == "dep_001"


def test_field_mapping_transform_rejects_raw_sql() -> None:
    """FieldMapping.transform must not accept raw SQL — DSL only."""
    import pytest
    from pydantic import ValidationError
    from sq_bi_contracts.field_mount import FieldMapping

    with pytest.raises(ValidationError, match="restricted DSL"):
        FieldMapping(
            mapping_id="map_001",
            pack_id="tms",
            standard_field_id="status",
            data_source_id="ds_tms",
            physical_table="HR_DELIVER_FORM",
            physical_column="STATUS",
            transform="SELECT CASE WHEN STATUS='1' THEN 'active' END",
        )


def test_field_mapping_transform_accepts_valid_dsl() -> None:
    """FieldMapping.transform accepts a DSL JSON string."""
    from sq_bi_contracts.field_mount import FieldMapping
    import json

    dsl = json.dumps({"type": "enum_map", "mapping": {"1": "active", "0": "inactive"}})
    mapping = FieldMapping(
        mapping_id="map_002",
        pack_id="tms",
        standard_field_id="status",
        data_source_id="ds_tms",
        physical_table="HR_DELIVER_FORM",
        physical_column="STATUS",
        transform=dsl,
    )
    assert mapping.transform is not None
    assert "enum_map" in mapping.transform


def test_field_mapping_confirmation_metadata() -> None:
    """FieldMapping records confirmed_by and confirmed_at when set."""
    from datetime import datetime, timezone
    from sq_bi_contracts.field_mount import FieldMapping

    now = datetime.now(timezone.utc)
    mapping = FieldMapping(
        mapping_id="map_003",
        pack_id="tms",
        standard_field_id="deliver_no",
        data_source_id="ds_tms",
        physical_table="HR_DELIVER_FORM",
        physical_column="DELIVER_NO",
        source="manual",
        confirmed_by="admin_u1",
        confirmed_at=now,
    )
    dumped = mapping.model_dump(mode="json")
    assert dumped["confirmed_by"] == "admin_u1"
    assert dumped["confirmed_at"] is not None


def test_api_route_registry_includes_deployment_routes() -> None:
    """Deployment / mounting routes must appear in the API route registry."""
    from sq_bi_contracts import API_ROUTES

    route_pairs = {(route.method, route.path) for route in API_ROUTES}
    assert ("POST", "/api/v1/admin/deployments") in route_pairs
    assert ("GET", "/api/v1/admin/deployments/{deployment_id}/pending") in route_pairs
    assert ("POST", "/api/v1/admin/deployments/{deployment_id}/confirm") in route_pairs
    assert ("POST", "/api/v1/admin/deployments/{deployment_id}/smoke-test") in route_pairs
    assert ("GET", "/api/v1/admin/deployments/{deployment_id}/status") in route_pairs


# ── Phase 0 gate: semantic_profile contracts ──

def test_evidence_item_source_enum_values() -> None:
    from sq_bi_contracts.semantic_profile import EvidenceItem, EvidenceSource

    for source in EvidenceSource:
        item = EvidenceItem(source=source, detail="test detail")
        dumped = item.model_dump(mode="json")
        assert dumped["source"] == source.value


def test_field_origin_enum_values() -> None:
    from sq_bi_contracts.semantic_profile import FieldOrigin

    assert FieldOrigin.standard.value == "standard"
    assert FieldOrigin.enterprise.value == "enterprise"
    assert FieldOrigin.inferred.value == "inferred"


def test_table_recommendation_enum_values() -> None:
    from sq_bi_contracts.semantic_profile import TableRecommendation

    assert TableRecommendation.recommended_include.value == "recommended_include"
    assert TableRecommendation.possibly_relevant.value == "possibly_relevant"
    assert TableRecommendation.not_relevant.value == "not_relevant"


def test_scan_phase_enum_values() -> None:
    from sq_bi_contracts.semantic_profile import ScanPhase

    assert ScanPhase.pending.value == "pending"
    assert ScanPhase.phase_one.value == "phase_one"
    assert ScanPhase.phase_two.value == "phase_two"
    assert ScanPhase.discovering.value == "discovering"
    assert ScanPhase.done.value == "done"
    assert ScanPhase.failed.value == "failed"


def test_semantic_field_carries_origin_confidence_evidence() -> None:
    from sq_bi_contracts.semantic_profile import (
        EvidenceItem, EvidenceSource, FieldOrigin, SemanticField,
    )

    field = SemanticField(
        field_id="fld_001",
        entity_id="ent_001",
        physical_table="HR_DELIVER_FORM",
        physical_column="DELIVER_NO",
        business_name="运单号",
        origin=FieldOrigin.inferred,
        confidence=0.87,
        evidence=[
            EvidenceItem(source=EvidenceSource.name, detail="column name contains 运单"),
            EvidenceItem(source=EvidenceSource.comment, detail="column comment: 唯一运单编号"),
        ],
        semantic_role="identifier",
        synonyms=["运单编号", "shipment_no"],
        physical_reference="HR_DELIVER_FORM.DELIVER_NO",
    )
    dumped = field.model_dump(mode="json")
    assert dumped["origin"] == "inferred"
    assert dumped["confidence"] == 0.87
    assert len(dumped["evidence"]) == 2
    assert dumped["evidence"][0]["source"] == "name"
    assert dumped["semantic_role"] == "identifier"
    assert "运单编号" in dumped["synonyms"]


def test_semantic_entity_contains_fields() -> None:
    from sq_bi_contracts.semantic_profile import (
        FieldOrigin, SemanticEntity, SemanticField, TableRecommendation,
    )

    entity = SemanticEntity(
        entity_id="ent_001",
        space_id="sp_001",
        physical_table="HR_DELIVER_FORM",
        business_name="运单实体",
        recommendation=TableRecommendation.recommended_include,
        fields=[
            SemanticField(
                field_id="fld_001",
                entity_id="ent_001",
                physical_table="HR_DELIVER_FORM",
                physical_column="DELIVER_NO",
                business_name="运单号",
                origin=FieldOrigin.inferred,
            )
        ],
    )
    dumped = entity.model_dump(mode="json")
    assert dumped["recommendation"] == "recommended_include"
    assert len(dumped["fields"]) == 1


def test_semantic_space_contains_entities() -> None:
    from sq_bi_contracts.semantic_profile import SemanticSpace, SemanticEntity

    space = SemanticSpace(
        space_id="sp_001",
        snapshot_id="snap_001",
        name="运输管理",
        entities=[
            SemanticEntity(
                entity_id="ent_001",
                space_id="sp_001",
                physical_table="HR_DELIVER_FORM",
                business_name="运单实体",
            )
        ],
        accepted=False,
    )
    dumped = space.model_dump(mode="json")
    assert dumped["name"] == "运输管理"
    assert dumped["accepted"] is False
    assert len(dumped["entities"]) == 1


def test_schema_snapshot_versioning_fields() -> None:
    from sq_bi_contracts.semantic_profile import SchemaSnapshot, ScanPhase

    snapshot = SchemaSnapshot(
        snapshot_id="snap_001",
        data_source_id="ds_tms",
        version=2,
        scanned_schemas=["TMS_SCHEMA"],
        table_count=120,
        included_table_count=80,
        excluded_table_count=40,
        recommendation_counts={"recommended_include": 60, "possibly_relevant": 15, "not_relevant": 5},
        scan_phase=ScanPhase.done,
    )
    dumped = snapshot.model_dump(mode="json")
    assert dumped["version"] == 2
    assert dumped["scan_phase"] == "done"
    assert dumped["recommendation_counts"]["recommended_include"] == 60


def test_data_source_document_upload_status() -> None:
    from sq_bi_contracts.semantic_profile import DataSourceDocument

    doc = DataSourceDocument(
        document_id="doc_001",
        data_source_id="ds_tms",
        filename="数据字典.xlsx",
        content_type="application/vnd.ms-excel",
        byte_size=204800,
        upload_status="ready",
    )
    dumped = doc.model_dump(mode="json")
    assert dumped["upload_status"] == "ready"
    assert dumped["byte_size"] == 204800


def test_scan_request_defaults() -> None:
    from sq_bi_contracts.semantic_profile import ScanRequest

    req = ScanRequest()
    assert req.force_rescan is False
    assert req.authorized_schemas == []
    assert req.include_rules == []
    assert req.exclude_rules == []


def test_scan_status_serialization() -> None:
    from sq_bi_contracts.semantic_profile import ScanStatus, ScanPhase

    status = ScanStatus(
        scan_id="scan_abc",
        data_source_id="ds_tms",
        snapshot_id="snap_001",
        phase=ScanPhase.phase_two,
        table_count=80,
        included_table_count=60,
        recommendation_counts={"recommended_include": 50},
    )
    dumped = status.model_dump(mode="json")
    assert dumped["scan_id"] == "scan_abc"
    assert dumped["phase"] == "phase_two"


def test_profile_view_contains_spaces() -> None:
    from sq_bi_contracts.semantic_profile import ProfileView, ScanPhase, SemanticSpace

    view = ProfileView(
        data_source_id="ds_tms",
        snapshot_id="snap_001",
        version=1,
        spaces=[
            SemanticSpace(
                space_id="sp_001",
                snapshot_id="snap_001",
                name="运输管理",
            )
        ],
        scan_phase=ScanPhase.done,
    )
    dumped = view.model_dump(mode="json")
    assert dumped["version"] == 1
    assert len(dumped["spaces"]) == 1


def test_semantic_space_adjustment_serialization() -> None:
    from sq_bi_contracts.semantic_profile import SemanticSpaceAdjustment

    adj = SemanticSpaceAdjustment(
        space_id="sp_001",
        accepted=True,
        name="运输管理（已确认）",
    )
    dumped = adj.model_dump(mode="json")
    assert dumped["accepted"] is True
    assert dumped["name"] == "运输管理（已确认）"


def test_datasource_config_technical_connection_fields_only() -> None:
    """DataSourceConnectionConfig is technical-connection-only: business scope
    (authorized schemas, business description, include/exclude rules) belongs
    to semantic-space configuration, not the connection."""
    from sq_bi_contracts.datasource import DataSourceConnectionConfig
    from sq_bi_contracts.enums import DatabaseType

    cfg = DataSourceConnectionConfig(
        data_source_id="ds_tms",
        name="TMS Prod",
        engine=DatabaseType.ORACLE,
        host="db.internal",
        port=1521,
        database="tms",
        username="ro_user",
        password="secret",
        service_name="ORCLPDB1",
        connect_timeout_seconds=10.0,
    )
    dumped = cfg.model_dump(mode="json")
    assert dumped["service_name"] == "ORCLPDB1"
    assert dumped["connect_timeout_seconds"] == 10.0
    assert dumped["sid"] is None
    assert dumped["dsn"] is None
    assert "authorized_schemas" not in dumped
    assert "business_description" not in dumped


# ── Phase 3: AI Exploration contract tests ────────────────────────────────────

def test_answer_path_enum_values() -> None:
    from sq_bi_contracts.exploration import AnswerPath
    assert AnswerPath.official.value == "official"
    assert AnswerPath.enterprise.value == "enterprise"
    assert AnswerPath.ai_exploration.value == "ai_exploration"


def test_confidence_tier_enum_values() -> None:
    from sq_bi_contracts.exploration import ConfidenceTier
    assert ConfidenceTier.high.value == "high"
    assert ConfidenceTier.medium.value == "medium"
    assert ConfidenceTier.low.value == "low"


def test_join_evidence_ordering() -> None:
    from sq_bi_contracts.exploration import JoinEvidence
    # foreign_key is the strongest (lowest rank)
    assert JoinEvidence.foreign_key.rank() < JoinEvidence.declared_relation.rank()
    assert JoinEvidence.declared_relation.rank() < JoinEvidence.document.rank()
    assert JoinEvidence.document.rank() < JoinEvidence.name_uniqueness_validated.rank()
    assert JoinEvidence.name_uniqueness_validated.rank() < JoinEvidence.llm_guess.rank()


def test_join_evidence_safe_for_aggregation() -> None:
    from sq_bi_contracts.exploration import JoinEvidence
    assert JoinEvidence.foreign_key.is_safe_for_aggregation() is True
    assert JoinEvidence.declared_relation.is_safe_for_aggregation() is True
    assert JoinEvidence.document.is_safe_for_aggregation() is True
    assert JoinEvidence.name_uniqueness_validated.is_safe_for_aggregation() is True
    assert JoinEvidence.llm_guess.is_safe_for_aggregation() is False


def test_field_assumption_serialization() -> None:
    from sq_bi_contracts.exploration import FieldAssumption
    fa = FieldAssumption(
        physical_table="TMS_ORDER",
        physical_column="INSURANCE_AMT",
        business_name="保险费用",
        inferred_meaning="每单保险金额",
        origin="inferred",
    )
    dumped = fa.model_dump(mode="json")
    assert dumped["physical_column"] == "INSURANCE_AMT"
    assert dumped["business_name"] == "保险费用"
    assert dumped["origin"] == "inferred"


def test_query_assumption_join_safety_gate() -> None:
    from sq_bi_contracts.exploration import (
        JoinAssumption, JoinEvidence, QueryAssumption,
    )
    safe_join = JoinAssumption(
        left_table="TMS_ORDER",
        right_table="TMS_CARRIER",
        join_key="CARRIER_ID",
        evidence=JoinEvidence.foreign_key,
    )
    unsafe_join = JoinAssumption(
        left_table="TMS_ORDER",
        right_table="TMS_COST",
        join_key="ORDER_ID",
        evidence=JoinEvidence.llm_guess,
    )
    assumption_safe = QueryAssumption(joins=[safe_join])
    assert assumption_safe.join_safe_for_aggregation() is True

    assumption_unsafe = QueryAssumption(joins=[safe_join, unsafe_join])
    assert assumption_unsafe.join_safe_for_aggregation() is False


def test_clarification_request_serialization() -> None:
    from sq_bi_contracts.exploration import ClarificationOption, ClarificationRequest
    cr = ClarificationRequest(
        question="保险费用指哪个字段？",
        options=[
            ClarificationOption(label="INSURANCE_AMT", description="单票保险金额", interpretation="INSURANCE_AMT"),
            ClarificationOption(label="INSURANCE_FEE", description="合同保险费", interpretation="INSURANCE_FEE"),
        ],
    )
    dumped = cr.model_dump(mode="json")
    assert len(dumped["options"]) == 2
    assert dumped["options"][0]["label"] == "INSURANCE_AMT"


def test_save_exploration_as_metric_request() -> None:
    from sq_bi_contracts.exploration import FieldAssumption, SaveExplorationAsMetricRequest
    req = SaveExplorationAsMetricRequest(
        business_name="保险费用",
        definition="各单保险费合计",
        data_source_id="ds_tms",
        aggregation="SUM",
        time_field="SHIP_DATE",
        synonyms=["保险金", "投保费"],
        field_mapping=[FieldAssumption(
            physical_table="TMS_ORDER",
            physical_column="INSURANCE_AMT",
            business_name="保险费用",
            origin="inferred",
        )],
        sql="SELECT SUM(INSURANCE_AMT) FROM TMS_ORDER",
        visibility="enterprise",
        user_id="u1",
    )
    dumped = req.model_dump(mode="json")
    assert dumped["business_name"] == "保险费用"
    assert dumped["aggregation"] == "SUM"
    assert dumped["visibility"] == "enterprise"
    assert len(dumped["synonyms"]) == 2


def test_query_result_backward_compatible_defaults() -> None:
    from datetime import datetime, timezone
    from sq_bi_contracts.query import (
        ChartSuggestion, Lineage, QueryResult,
    )
    from sq_bi_contracts.enums import ChartType
    result = QueryResult(
        query_id="q1",
        audit_id="a1",
        columns=["col1"],
        rows=[[1]],
        chart_suggestion=ChartSuggestion(chart_type=ChartType.BAR, title="Test"),
        lineage=Lineage(
            lineage_id="l1",
            source_system="test",
            data_source_id="ds1",
        ),
    )
    # Phase 3 fields should all be absent/default without being required
    assert result.answer_path is None
    assert result.assumptions == []
    assert result.confidence_tier is None
    assert result.clarification is None
    assert result.is_exploratory is False


def test_query_result_with_exploration_fields() -> None:
    from datetime import datetime, timezone
    from sq_bi_contracts.query import (
        ChartSuggestion, Lineage, QueryResult,
    )
    from sq_bi_contracts.exploration import (
        AnswerPath, ConfidenceTier, FieldAssumption, QueryAssumption,
    )
    from sq_bi_contracts.enums import ChartType
    assumption = QueryAssumption(
        fields_used=[FieldAssumption(
            physical_table="T", physical_column="C", business_name="B", origin="inferred",
        )],
        aggregation="SUM",
        caliber_label="企业数据库字段，非官方标准口径",
    )
    result = QueryResult(
        query_id="q2",
        audit_id="a2",
        columns=["val"],
        rows=[[100]],
        chart_suggestion=ChartSuggestion(chart_type=ChartType.BAR, title="T"),
        lineage=Lineage(lineage_id="l2", source_system="s", data_source_id="ds1"),
        answer_path=AnswerPath.ai_exploration,
        assumptions=[assumption],
        confidence_tier=ConfidenceTier.high,
        is_exploratory=True,
    )
    dumped = result.model_dump(mode="json")
    assert dumped["answer_path"] == "ai_exploration"
    assert dumped["is_exploratory"] is True
    assert dumped["confidence_tier"] == "high"
    assert len(dumped["assumptions"]) == 1


# ── Phase 4: Enterprise Domain Pack contract tests ────────────────────────────

from sq_bi_contracts.enterprise_pack import (
    CreateEnterprisePackRequest,
    EnterprisePack,
    EnterprisePackDraft,
    PackAcceptanceQuestion,
    PackCreateMode,
    PackDraftRequest,
    PackDraftResult,
    PackEnterpriseField,
    PackEnterpriseMetric,
    PackEntity,
    PackSkill,
    PackSkillStep,
    PackTerm,
    PackVersionState,
    PublishPackRequest,
)
from sq_bi_contracts.metrics import MetricFormula


def test_pack_create_mode_enum_values() -> None:
    assert PackCreateMode.extend_official.value == "extend_official"
    assert PackCreateMode.blank.value == "blank"
    assert {m.value for m in PackCreateMode} == {"extend_official", "blank"}


def test_pack_version_state_enum_values() -> None:
    assert PackVersionState.draft.value == "draft"
    assert PackVersionState.published.value == "published"


def test_enterprise_pack_draft_serialization_round_trip() -> None:
    draft = EnterprisePackDraft(
        entities=[PackEntity(entity_id="e1", name="运单", tags=["core"], source="enterprise")],
        fields=[
            PackEnterpriseField(
                field_id="f1",
                business_name="实付运费",
                data_type="DECIMAL(12,2)",
                entity_id="e1",
                synonyms=["运费"],
                source="enterprise",
            )
        ],
        metrics=[
            PackEnterpriseMetric(
                metric_code="usr_freight_total",
                name="总运费",
                definition="统计期内运费之和",
                formula=MetricFormula(expression="SUM(billing_detail.freight_charge)"),
                entity_id="e1",
                synonyms=["运费汇总"],
                source="enterprise",
            )
        ],
        terms=[PackTerm(term_id="t1", term="准时交付", definition="按时完成的比例", synonyms=["OTD"])],
        acceptance_questions=[PackAcceptanceQuestion(question_id="aq1", question="本月总运费？")],
    )
    dumped = draft.model_dump(mode="json")
    assert dumped["entities"][0]["entity_id"] == "e1"
    assert dumped["fields"][0]["field_id"] == "f1"
    assert "physical_table" not in dumped["fields"][0]
    assert dumped["metrics"][0]["metric_code"] == "usr_freight_total"
    assert dumped["terms"][0]["term"] == "准时交付"
    assert dumped["acceptance_questions"][0]["question_id"] == "aq1"


def test_enterprise_pack_base_pack_lineage_fields() -> None:
    pack = EnterprisePack(
        pack_id="ep_001",
        name="物流域企业包",
        base_pack_id="logistics",
        base_pack_version="1.0.0",
        create_mode=PackCreateMode.extend_official,
    )
    dumped = pack.model_dump(mode="json")
    assert dumped["base_pack_id"] == "logistics"
    assert dumped["base_pack_version"] == "1.0.0"
    assert dumped["create_mode"] == "extend_official"
    assert dumped["version_state"] == "draft"
    assert "data_source_id" not in dumped


def test_enterprise_pack_blank_has_no_base() -> None:
    pack = EnterprisePack(
        pack_id="ep_002",
        name="空白包",
        create_mode=PackCreateMode.blank,
    )
    assert pack.base_pack_id is None
    assert pack.base_pack_version is None


def test_enterprise_pack_legacy_review_evidence_defaults() -> None:
    pack = EnterprisePack(pack_id="ep_003", name="迁移包")
    assert pack.legacy_review_required is False
    assert pack.legacy_authoring_evidence == {}

    migrated = EnterprisePack(
        pack_id="ep_004",
        name="旧连接绑定包",
        legacy_review_required=True,
        legacy_authoring_evidence={"data_source_id": "ds_tms", "physical_fields": ["orders.id"]},
    )
    assert migrated.legacy_review_required is True
    assert migrated.legacy_authoring_evidence["data_source_id"] == "ds_tms"


def test_save_exploration_target_pack_id_optional_and_backward_compat() -> None:
    from sq_bi_contracts.exploration import SaveExplorationAsMetricRequest

    req_without = SaveExplorationAsMetricRequest(
        business_name="总运费",
        definition="运费之和",
        data_source_id="ds_tms",
        aggregation="sum",
        visibility="enterprise",
    )
    assert req_without.target_pack_id is None

    req_with = SaveExplorationAsMetricRequest(
        business_name="总运费",
        definition="运费之和",
        data_source_id="ds_tms",
        aggregation="sum",
        visibility="enterprise",
        target_pack_id="ep_001",
    )
    assert req_with.target_pack_id == "ep_001"


def test_create_enterprise_pack_request_serialization() -> None:
    req = CreateEnterprisePackRequest(
        name="物流域企业包",
        mode=PackCreateMode.extend_official,
        base_pack_id="logistics",
        base_pack_version="1.0.0",
        created_by="analyst",
    )
    dumped = req.model_dump(mode="json")
    assert dumped["mode"] == "extend_official"
    assert dumped["base_pack_id"] == "logistics"
    assert dumped["base_pack_version"] == "1.0.0"
    assert "data_source_id" not in dumped


def test_pack_draft_result_tracks_dropped_and_rejected() -> None:
    result = PackDraftResult(
        draft=EnterprisePackDraft(),
        dropped_fields=["unknown_col"],
        rejected_metrics=["bad_formula"],
        rejection_reasons={"bad_formula": "SQL编译失败"},
    )
    assert "unknown_col" in result.dropped_fields
    assert result.rejection_reasons["bad_formula"] == "SQL编译失败"
