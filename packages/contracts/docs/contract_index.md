# Contract Index

This worktree owns the first shared contract set for SQ-BI.

## Python Package

- `sq_bi_contracts.ids`
- `sq_bi_contracts.enums`
- `sq_bi_contracts.common`
- `sq_bi_contracts.assets` — stable `AssetKey`, versioned `AssetRef`, `AssetDescriptor`, and `AssetQuery` shared by official, enterprise, and personal asset providers
- `sq_bi_contracts.catalog`
- `sq_bi_contracts.metrics`
- `sq_bi_contracts.skills`
- `sq_bi_contracts.query`
- `sq_bi_contracts.reports`
- `sq_bi_contracts.exports`
- `sq_bi_contracts.api`
- `sq_bi_contracts.semantic_profile` — database semantic profile: `SchemaSnapshot`, `SemanticSpace` (+ optional `version`/`version_state`/`created_at`/`published_at` versioning overlay), `SemanticEntity`, `SemanticField` (origin/confidence/evidence/`status`), `FieldStatus`, `SemanticSpaceVersionState`, `DataSourceDocument`, `ScanRequest`, `ScanStatus`, `ProfileView`, `SemanticSpaceAdjustment`
- `sq_bi_contracts.semantic_space` — semantic-space-management: `CreateSemanticSpaceRequest`, `SemanticSpaceDiff`, `ChangedFieldEntry`, `PublishSemanticSpaceRequest`, `SemanticGapCandidate`, `GapLookupRequest`
- `sq_bi_contracts.exploration` — Phase 3 AI exploration: `AnswerPath`, `ConfidenceTier`, `JoinEvidence` (with rank/safety gate), `FieldAssumption`, `JoinAssumption`, `QueryAssumption`, `ClarificationOption`, `ClarificationRequest`, `SaveExplorationAsMetricRequest` (with optional `target_pack_id`); `QueryResult` extended with `answer_path`, `assumptions`, `confidence_tier`, `clarification`, `is_exploratory`, `gap_candidates`
- `sq_bi_contracts.enterprise_pack` — Phase 4 enterprise domain pack: `PackCreateMode` (extend_official/clone_enterprise/ai_from_profile/blank), `PackVersionState` (draft/published), `PackEntity`, `PackEnterpriseField`, `PackEnterpriseMetric`, `PackTerm`, `PackAcceptanceQuestion`, `PackSkill`, `PackReport`, `EnterprisePackDraft`, `EnterprisePack` (identity + base_pack lineage + version state), `CreateEnterprisePackRequest`, `PackDraftRequest`, `PublishPackRequest`, `PackDraftResult`
- `sq_bi_contracts.field_mount` — `DeploymentInstance`, `CreateDeploymentRequest`, `DeploymentListItem`, `MountStatus` extended with additive `semantic_space_ids: list[str]`

## Contract Documents

- `docs/api_contract.md`
- `docs/type_model.md`

## Downstream Rule

Downstream worktrees can add implementation-specific internal models, but public request and response payloads must map to these contracts.
