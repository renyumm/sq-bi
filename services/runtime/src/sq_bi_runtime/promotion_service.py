from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sq_bi_contracts.assets import AssetKey, AssetRef
from sq_bi_contracts.enterprise_pack import (
    EnterprisePackDraft,
    PackEnterpriseField,
    PackEnterpriseMetric,
    PackReport,
    PackSkill,
    PackSkillStep,
)
from sq_bi_contracts.enums import AssetSourceType, AssetType
from sq_bi_contracts.personal_assets import (
    ConfirmPromotionRequest,
    MappingCandidateProposal,
    PromotionConflict,
    PromotionPreview,
    PromotionPreviewRequest,
    PromotionRecord,
    StandardFieldProposal,
)

from .enterprise_pack_store import EnterprisePackStore
from .personal_asset_store import PersonalAssetStore


class ProductAssetRepository(Protocol):
    def get_metric_by_ref(self, asset_ref: AssetRef): ...  # noqa: ANN201
    def get_skill_by_ref(self, asset_ref: AssetRef): ...  # noqa: ANN201
    def get_report_by_ref(self, asset_ref: AssetRef): ...  # noqa: ANN201


class PersonalAssetPromotionService:
    def __init__(
        self,
        personal_store: PersonalAssetStore,
        enterprise_store: EnterprisePackStore,
        product_repository: ProductAssetRepository,
    ) -> None:
        self._personal = personal_store
        self._enterprise = enterprise_store
        self._products = product_repository

    def preview(self, request: PromotionPreviewRequest) -> PromotionPreview:
        conflicts: list[PromotionConflict] = []
        if request.workspace_id != PersonalAssetStore.workspace_id_for(request.requested_by):
            conflicts.append(PromotionConflict(code="WORKSPACE_FORBIDDEN", message="workspace is not owned by requester"))
        pack = self._enterprise.get(request.target_pack_id)
        if pack is None:
            conflicts.append(PromotionConflict(code="PACK_NOT_FOUND", message="target enterprise pack does not exist"))
        elif pack.version_state.value != "draft":
            conflicts.append(PromotionConflict(code="PACK_NOT_DRAFT", message="target pack must be a draft"))

        records = []
        for ref in request.asset_refs:
            record = self._personal.get_asset(ref, workspace_id=request.workspace_id)
            if record is None:
                conflicts.append(
                    PromotionConflict(code="ASSET_NOT_FOUND", message="personal asset version is unavailable", asset_ref=ref)
                )
            else:
                records.append(record)
        try:
            if records:
                self._personal.effective_scope(request.asset_refs, request.workspace_id)
        except ValueError as exc:
            conflicts.append(PromotionConflict(code=str(exc), message="asset dependency scopes are incompatible"))

        fields: dict[tuple[str, str], StandardFieldProposal] = {}
        mappings: dict[tuple[str, str], MappingCandidateProposal] = {}
        for record in records:
            for physical in record.scope.physical_fields:
                table, _, column = physical.partition(".")
                if not table or not column:
                    continue
                field_id = _slug(f"{table}_{column}")
                fields[(table.upper(), column.upper())] = StandardFieldProposal(
                    field_id=field_id,
                    business_name=column.replace("_", " ").title(),
                    physical_table=table,
                    physical_column=column,
                    evidence=f"promoted from {record.asset_ref.asset.asset_id}@{record.asset_ref.version}",
                )
                mappings[(table.upper(), column.upper())] = MappingCandidateProposal(
                    standard_field_id=field_id,
                    physical_table=table,
                    physical_column=column,
                    confidence=1.0,
                    evidence="exact P4 execution provenance",
                )
        return PromotionPreview(
            eligible=not conflicts,
            workspace_id=request.workspace_id,
            target_pack_id=request.target_pack_id,
            asset_refs=request.asset_refs,
            conflicts=conflicts,
            standard_fields=list(fields.values()),
            mapping_candidates=list(mappings.values()),
        )

    def confirm(self, request: ConfirmPromotionRequest) -> PromotionRecord:
        preview = self.preview(PromotionPreviewRequest(**request.model_dump(exclude={"confirmed_standard_fields", "confirmed_mappings"})))
        if not preview.eligible:
            raise ValueError("PROMOTION_NOT_ELIGIBLE")
        pack = self._enterprise.get(request.target_pack_id)
        assert pack is not None
        draft = pack.draft.model_copy(deep=True)
        target_refs: list[AssetRef] = []

        for ref in request.asset_refs:
            target_ref = AssetRef(
                asset=AssetKey(
                    source_type=AssetSourceType.ENTERPRISE_PACK,
                    source_id=pack.pack_id,
                    asset_type=ref.asset.asset_type,
                    local_code=ref.asset.local_code,
                ),
                version=pack.version,
            )
            target_refs.append(target_ref)
            if ref.asset.asset_type == AssetType.METRIC:
                metric = self._products.get_metric_by_ref(ref)
                if metric is None:
                    raise ValueError("PROMOTION_SOURCE_MISSING")
                draft.metrics.append(
                    PackEnterpriseMetric(
                        metric_code=ref.asset.local_code,
                        name=metric.name,
                        definition=metric.definition,
                        formula=metric.formula,
                        synonyms=metric.synonyms,
                        source=f"promotion:{ref.asset.asset_id}@{ref.version}",
                    )
                )
            elif ref.asset.asset_type == AssetType.SKILL:
                skill = self._products.get_skill_by_ref(ref)
                if skill is None:
                    raise ValueError("PROMOTION_SOURCE_MISSING")
                draft.skills.append(
                    PackSkill(
                        skill_id=ref.asset.local_code,
                        name=skill.name,
                        description=skill.description,
                        steps=[
                            PackSkillStep(
                                step_id="promoted_dependencies",
                                description="Frozen promoted dependencies",
                                metric_codes=[item.asset.local_code for item in skill.dependency_refs if item.asset.asset_type == AssetType.METRIC],
                            )
                        ],
                    )
                )
            elif ref.asset.asset_type == AssetType.REPORT:
                report = self._products.get_report_by_ref(ref)
                if report is None:
                    raise ValueError("PROMOTION_SOURCE_MISSING")
                draft.reports.append(
                    PackReport(
                        report_id=ref.asset.local_code,
                        name=report.name,
                        description=report.description,
                        metric_codes=[item.asset.local_code for item in report.dependency_refs if item.asset.asset_type == AssetType.METRIC],
                        skill_ids=[item.asset.local_code for item in report.dependency_refs if item.asset.asset_type == AssetType.SKILL],
                    )
                )

        confirmed_fields = request.confirmed_standard_fields or preview.standard_fields
        known_fields = {field.field_id for field in draft.fields}
        for item in confirmed_fields:
            if item.field_id in known_fields:
                continue
            draft.fields.append(
                PackEnterpriseField(
                    field_id=item.field_id,
                    business_name=item.business_name,
                    data_type=item.data_type,
                    description=item.evidence,
                    source="promotion",
                )
            )
        record = PromotionRecord(
            promotion_id="prm_" + uuid4().hex,
            workspace_id=request.workspace_id,
            target_pack_id=pack.pack_id,
            source_refs=request.asset_refs,
            target_refs=target_refs,
            requested_by=request.requested_by,
            created_at=datetime.now(UTC),
        )
        original_draft = pack.draft.model_copy(deep=True)
        try:
            self._enterprise.update_draft(pack.pack_id, EnterprisePackDraft(**draft.model_dump()))
            return self._personal.save_promotion(record)
        except Exception:
            # The stores are separate SQLite files, so compensate explicitly
            # to preserve all-or-nothing promotion semantics.
            self._enterprise.update_draft(pack.pack_id, original_draft)
            raise


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
