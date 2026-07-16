export type ErrorCode =
  | 'UNKNOWN_ERROR'
  | 'INVALID_REQUEST'
  | 'UNAUTHORIZED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'METRIC_CONFLICT'
  | 'GUARDRAIL_VIOLATION'
  | 'RLS_VIOLATION'
  | 'EXECUTION_FAILED';

export interface ApiError {
  code: ErrorCode;
  message: string;
  details?: Record<string, unknown>;
}

export interface ApiResponse<T> {
  request_id: string;
  data?: T | null;
  error?: ApiError | null;
}

export type AssetSourceType = 'official_pack' | 'enterprise_pack' | 'personal_workspace';
export type AssetType = 'metric' | 'skill' | 'report';

export interface AssetKey {
  source_type: AssetSourceType;
  source_id: string;
  asset_type: AssetType;
  local_code: string;
  asset_id: string;
}

export interface AssetRef {
  asset: AssetKey;
  version: string;
}

/** An asset that is currently deployable from the ask-data runtime. */
export interface CallableAsset {
  asset_id: string;
  asset_type: AssetType;
  name: string;
  code: string;
  data_source_id: string;
  asset_ref: AssetRef;
}

export interface UserContext {
  user_id: string;
  display_name: string;
  org_id: string;
  org_name?: string;
  role_ids?: string[];
  data_scope?: Record<string, string[]>;
  locale?: string;
  timezone?: string;
}

export interface ManagedUser {
  user_id: string;
  display_name: string;
  role: 'admin' | 'user';
}

export interface CreateManagedUserRequest {
  username: string;
  password: string;
  display_name?: string;
  role: 'admin' | 'user';
}

export interface UpdateManagedUserRequest {
  new_username?: string;
  password?: string;
  display_name?: string;
  role?: 'admin' | 'user';
}

export interface LoginResponse {
  session_id: string;
  token: string;
  user_id: string;
  display_name: string;
  org_id: string;
  role_ids: string[];
  expires_at: string;
}

export interface TimeRange {
  start?: string;
  end?: string;
  grain?: string;
  label?: string;
}

export interface QueryFilter {
  field: string;
  operator: string;
  value: unknown;
}

export interface QueryIntent {
  text: string;
  metric_codes: string[];
  skill_ids: string[];
  dimensions: string[];
  filters: QueryFilter[];
  time_range: TimeRange | null;
  sort: string[];
  chart_preference: string | null;
}

export interface QueryRequest {
  user_id: string;
  intent: QueryIntent;
  execute?: boolean;
}

export interface ChartSuggestion {
  chart_type: string;
  title: string;
  x_field?: string | null;
  y_field?: string | null;
  series_field?: string | null;
  value_field?: string | null;
  description?: string | null;
}

export interface Lineage {
  lineage_id: string;
  source_system: string;
  data_source_id: string;
  metric_codes: string[];
  metric_versions: Record<string, string>;
  formula_summary?: string | null;
  physical_tables: string[];
  physical_fields: string[];
  executed_at?: string | null;
}

export interface LineageMetric {
  metric_id: string;
  metric_name: string;
  visibility: string;
  formula_expression?: string | null;
  version?: string;
}

export interface LineageSkill {
  skill_id: string;
  skill_name: string;
}

export interface LineageDataSource {
  data_source_id: string;
  name: string;
}

export interface LineageInfo {
  metrics: LineageMetric[];
  skills: LineageSkill[];
  data_sources: LineageDataSource[];
  executed_at?: string | null;
  data_watermark?: string | null;
}

// ── Phase 3: AI Exploration contracts (mirrors sq_bi_contracts.exploration) ──
export type AnswerPath = 'official' | 'enterprise' | 'personal' | 'ai_exploration';
export type ConfidenceTier = 'high' | 'medium' | 'low';
export type JoinEvidence =
  | 'foreign_key'
  | 'declared_relation'
  | 'document'
  | 'name_uniqueness_validated'
  | 'llm_guess';

export interface FieldAssumption {
  physical_table: string;
  physical_column: string;
  business_name: string;
  inferred_meaning?: string | null;
  origin: string;
}

export interface JoinAssumption {
  left_table: string;
  right_table: string;
  join_key: string;
  evidence: JoinEvidence;
  note?: string | null;
}

export interface QueryAssumption {
  fields_used: FieldAssumption[];
  aggregation?: string | null;
  time_field?: string | null;
  time_grain?: string | null;
  filters: string[];
  joins: JoinAssumption[];
  best_join_evidence?: JoinEvidence | null;
  caliber_label: string;
}

export interface ClarificationOption {
  label: string;
  description?: string | null;
  interpretation: string;
}

export interface ClarificationRequest {
  question: string;
  options: ClarificationOption[];
}

export interface SaveExplorationAsMetricRequest {
  business_name: string;
  definition: string;
  data_source_id: string;
  entity?: string | null;
  aggregation: string;
  time_field?: string | null;
  filters: string[];
  synonyms: string[];
  field_mapping: FieldAssumption[];
  sql?: string | null;
  lineage: Record<string, unknown>;
  test_result?: string | null;
  visibility: string;
  user_id: string;
  target_pack_id?: string | null;
}

// ── Phase 4: Enterprise Domain Pack (mirrors sq_bi_contracts.enterprise_pack) ──
/** Only logical package-definition modes are exposed in the first product. */
export type PackCreateMode = 'extend_official' | 'blank' | 'clone_enterprise' | 'ai_from_profile';
export type PackVersionState = 'draft' | 'published';
export type ExtensionLayerState = 'draft' | 'active' | 'inactive' | 'archived';

export interface PackEntity {
  entity_id: string;
  name: string;
  description?: string | null;
  /** Legacy review evidence only; never used as a package-definition binding. */
  physical_table?: string | null;
  tags: string[];
  source: string;
}

export interface PackEnterpriseField {
  field_id: string;
  business_name: string;
  /** Legacy review evidence only; mappings live on PackDeployment. */
  physical_table?: string | null;
  physical_column?: string | null;
  data_type: string;
  description?: string | null;
  entity_id?: string | null;
  synonyms: string[];
  source: string;
}

export interface PackEnterpriseMetric {
  metric_code: string;
  name: string;
  definition: string;
  formula: MetricFormula;
  entity_id?: string | null;
  synonyms: string[];
  source: string;
}

export interface PackTerm {
  term_id: string;
  term: string;
  definition: string;
  synonyms: string[];
  related_field_ids: string[];
}

export interface PackAcceptanceQuestion {
  question_id: string;
  question: string;
  expected_metric_code?: string | null;
  expected_answer_hint?: string | null;
}

export interface PackSkillStep {
  step_id: string;
  description: string;
  metric_codes: string[];
  dimension_field_ids: string[];
}

export interface PackSkill {
  skill_id: string;
  name: string;
  description?: string | null;
  steps: PackSkillStep[];
}

export interface PackReport {
  report_id: string;
  name: string;
  description?: string | null;
  metric_codes: string[];
  skill_ids: string[];
}

export interface EnterprisePackDraft {
  entities: PackEntity[];
  fields: PackEnterpriseField[];
  metrics: PackEnterpriseMetric[];
  skills: PackSkill[];
  reports: PackReport[];
  terms: PackTerm[];
  acceptance_questions: PackAcceptanceQuestion[];
}

export interface EnterprisePack {
  pack_id: string;
  name: string;
  description?: string | null;
  business_context?: string | null;
  /** Legacy review evidence. New portable definitions do not bind a source. */
  data_source_id?: string | null;
  version: string;
  version_state: PackVersionState;
  base_pack_id?: string | null;
  base_pack_version?: string | null;
  create_mode: PackCreateMode;
  draft: EnterprisePackDraft;
  created_by: string;
  created_at?: string | null;
  updated_at?: string | null;
  /** The single additive layer owned by this base pack, when present. */
  extension_layer?: PackExtensionLayer | null;
  /** Data-source deployments for card/detail activation state. */
  deployments?: DeploymentListItem[];
}

/** A non-top-level additive layer. Its draft contains additions only. */
export interface PackExtensionLayer {
  extension_id: string;
  base_pack_id: string;
  base_pack_version: string;
  base_kind: 'official' | 'enterprise';
  version: string;
  version_state: PackVersionState;
  state: ExtensionLayerState;
  draft: EnterprisePackDraft;
  created_by?: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface EffectiveDomainPackAsset {
  asset_id: string;
  name: string;
  asset_type: 'field' | 'metric' | 'skill' | 'report';
  source: 'base' | 'extension';
  definition: Record<string, unknown>;
}

export interface EffectiveDomainPack {
  base_pack_id: string;
  base_pack_version: string;
  base_kind: 'official' | 'enterprise';
  extension_layer?: PackExtensionLayer | null;
  fields: EffectiveDomainPackAsset[];
  metrics: EffectiveDomainPackAsset[];
  skills: EffectiveDomainPackAsset[];
  reports: EffectiveDomainPackAsset[];
}

// ── Phase 5: Personal Asset Enterprise Promotion contracts ──
export type PromotionLifecycle = 'draft' | 'published' | 'deployed' | 'validated' | 'activated';

export interface PersonalWorkspace {
  workspace_id: string;
  owner_user_id: string;
  org_id: string;
  name: string;
}

export interface PersonalAssetScope {
  workspace_id: string;
  data_source_id: string;
  environment: string;
  semantic_space_ids: string[];
  physical_tables: string[];
  physical_fields: string[];
}

export interface AssetDependencyGraph {
  asset_ref: AssetRef;
  dependency_refs: AssetRef[];
  effective_scope: PersonalAssetScope;
}

export interface PersonalAssetRecord {
  asset_ref: AssetRef;
  name: string;
  workspace_id: string;
  owner_user_id: string;
  scope: PersonalAssetScope;
  dependency_refs: AssetRef[];
  template_asset_ref?: AssetRef | null;
  created_at?: string | null;
}

export interface PersonalAssetTemplate {
  asset_ref: AssetRef;
  name: string;
  description?: string | null;
  asset_type: AssetType;
  source_type: Extract<AssetSourceType, 'official_pack' | 'enterprise_pack'>;
  source_id: string;
  version: string;
}

export interface PromotionConflict {
  code: string;
  message: string;
  asset_ref?: AssetRef | null;
}

export interface StandardFieldProposal {
  field_id: string;
  business_name: string;
  physical_table: string;
  physical_column: string;
  data_type: string;
  evidence: string;
}

export interface MappingCandidateProposal {
  standard_field_id: string;
  physical_table: string;
  physical_column: string;
  confidence: number;
  evidence: string;
}

export interface PromotionPreviewRequest {
  workspace_id: string;
  target_pack_id: string;
  asset_refs: AssetRef[];
  requested_by: string;
}

export interface PromotionPreview {
  eligible: boolean;
  workspace_id: string;
  target_pack_id: string;
  asset_refs: AssetRef[];
  conflicts: PromotionConflict[];
  standard_fields: StandardFieldProposal[];
  mapping_candidates: MappingCandidateProposal[];
}

export interface ConfirmPromotionRequest extends PromotionPreviewRequest {
  confirmed_standard_fields: StandardFieldProposal[];
  confirmed_mappings: MappingCandidateProposal[];
}

export interface PromotionRecord {
  promotion_id: string;
  workspace_id: string;
  target_pack_id: string;
  source_refs: AssetRef[];
  target_refs: AssetRef[];
  requested_by: string;
  lifecycle: PromotionLifecycle;
  next_action: string;
  created_at: string;
}


export interface CreateEnterprisePackRequest {
  name: string;
  description?: string | null;
  business_context?: string | null;
  mode: PackCreateMode;
  base_pack_id?: string | null;
  base_pack_version?: string | null;
  /** @deprecated compatibility-only fields for pre-migration servers. */
  data_source_id?: string | null;
  /** @deprecated enterprise editing now forks a new draft version. */
  base_enterprise_pack_id?: string | null;
  created_by: string;
}

export interface PackDraftRequest {
  data_source_id: string;
  pack_id?: string | null;
  document_ids: string[];
  user_id: string;
}

export interface PublishPackRequest {
  version?: string | null;
  published_by: string;
}

export interface PackDraftResult {
  draft: EnterprisePackDraft;
  dropped_fields: string[];
  rejected_metrics: string[];
  rejection_reasons: Record<string, string>;
}

export type DomainPackAuthoringScope = 'all' | 'fields' | 'metrics' | 'skills' | 'reports' | 'self_check';

export interface DomainPackAuthoringRequest {
  scope: DomainPackAuthoringScope;
  name: string;
  description: string;
  business_context: string;
  instruction?: string;
  draft: EnterprisePackDraft;
}

export interface DomainPackAuthoringResult {
  scope: DomainPackAuthoringScope;
  input_assessment: { reasonable: boolean; feedback: string };
  summary: string;
  suggestions: string[];
  issues: string[];
  draft: EnterprisePackDraft;
}

export interface ExecutionFailure {
  stage: 'plan_validation' | 'compilation' | 'guardrail' | 'execution' | 'rendering' | string;
  code: 'invalid_plan' | 'missing_mapping' | 'ambiguous_mapping' | 'out_of_scope_mapping' | 'unsupported_expression' | 'query_rejected' | 'execution_failed' | 'execution_timeout' | string;
  message: string;
  retryable: boolean;
}

export interface ExecutionProvenance {
  asset_ref?: AssetRef | null;
  deployment_id?: string | null;
  workspace_id?: string | null;
  data_source_id: string;
  environment: string;
  semantic_space_ids: string[];
}

export interface ExecutionStageTiming {
  stage: 'plan_validation' | 'compilation' | 'guardrail' | 'execution' | 'rendering' | string;
  duration_ms: number;
}

export interface QueryResult {
  query_id: string;
  audit_id: string;
  columns: string[];
  rows: unknown[][];
  chart_suggestion: ChartSuggestion;
  lineage: Lineage;
  lineage_info?: LineageInfo | null;
  summary?: string | null;
  // Phase 3 exploration fields (optional, backward-compatible)
  answer_path?: AnswerPath | null;
  assumptions?: QueryAssumption[];
  confidence_tier?: ConfidenceTier | null;
  clarification?: ClarificationRequest | null;
  is_exploratory?: boolean;
  gap_candidates?: SemanticGapCandidate[];
  // Phase 4: Deterministic Asset Execution metadata (reconciled with backend 11ab2b8)
  execution_path?: 'formal_metric' | 'controlled_exploration' | string | null;
  execution_provenance?: ExecutionProvenance | null;
  execution_timings?: ExecutionStageTiming[] | null;
  execution_failure?: ExecutionFailure | null;
}

export interface MetricFormula {
  expression: string;
  numerator?: string | null;
  denominator?: string | null;
  filters: string[];
  time_field?: string | null;
}

export interface MetricDefinition {
  metric_code: string;
  asset_ref?: AssetRef;
  name: string;
  definition: string;
  visibility: 'official' | 'private' | 'shared';
  formula: MetricFormula;
  data_source_id: string;
  owner: string;
  version?: string;
  lifecycle_status?: string;
  update_frequency?: string | null;
  synonyms?: string[];
  permission_tags?: string[];
  workspace_id?: string | null;
  scope?: PersonalAssetScope | null;
  dependency_refs?: AssetRef[];
  execution_contract?: ExecutableAssetContract | null;
  build_trace?: AssetBuildEvent[];
  validation_evidence?: ValidationEvidence[];
}

export interface MetricDependencyRecord {
  source_type: string;
  source_id: string;
  source_name: string;
  relation_type: string;
  blocking: boolean;
}

export interface MetricDraft {
  name: string;
  formula: MetricFormula;
  mapped_fields: string[];
  explanation: string;
  warnings: string[];
  execution_contract?: ExecutableAssetContract | null;
  build_trace?: AssetBuildEvent[];
  validation_evidence?: ValidationEvidence[];
}

export type ParameterSlotStatus = 'unresolved' | 'ambiguous' | 'resolved' | 'defaulted' | 'confirmed';

export interface ParameterSlot {
  name: string;
  data_type: string;
  required: boolean;
  description?: string | null;
  value?: unknown;
  default_value?: unknown;
  allowed_values: string[];
  candidates: Array<{ value: unknown; label?: string | null; confidence?: number | null; source?: string | null }>;
  status: ParameterSlotStatus;
  resolution_source?: string | null;
}

export interface AssetBuildEvent {
  event_id: string;
  event_type: 'user_intent' | 'plan' | 'slot_resolution' | 'dependency_resolution' | 'draft' | 'validation' | 'test' | 'revision' | 'confirmation' | 'artifact';
  title: string;
  summary?: string | null;
  created_at?: string | null;
  payload: Record<string, unknown>;
}

export interface ValidationEvidence {
  check: string;
  status: 'pending' | 'passed' | 'failed';
  message?: string | null;
  details: Record<string, unknown>;
}

export interface ExecutableAssetContract {
  asset_kind: 'metric' | 'skill' | 'report';
  parameter_slots: ParameterSlot[];
  dependency_refs: AssetRef[];
  data_source_bindings: DataSourceBinding[];
  steps: Array<Record<string, unknown>>;
  logical_sql?: string | null;
  summary_rule?: string | null;
  output_contract: Record<string, unknown>;
}

export interface SkillClarificationRequired {
  clarification_required: true;
  message: string;
  skill_id: string;
  parameter_slots: ParameterSlot[];
  build_event: AssetBuildEvent;
}

export interface MetricDraftRequest {
  name: string;
  natural_language_definition: string;
  user_id: string;
}

export interface SkillSchemaDraftResponse {
  parameters: Array<{ name: string; label: string; dataType: string; required: boolean }>;
  steps: string[];
  sql: string;
  chartType: string;
}

export interface CreateUserMetricRequest {
  draft: MetricDraft;
  confirmed_by_user: boolean;
  visibility?: 'official' | 'private' | 'shared';
  user_id: string;
  data_source_id?: string;
}

export interface DataSourceBinding {
  data_source_id: string;
  name: string;
  role: 'primary' | 'inherited' | 'step_input';
  reason?: string | null;
}

// Technical connection only — business description, semantic scope, and
// scan include/exclude rules belong to semantic-space configuration, not
// the database connection (数据库连接页面只回答"怎么连上数据库，以及这个
// 连接下大概有哪些元数据").
export interface DataSource {
  data_source_id: string;
  name: string;
  database_type: string;
  is_read_only: boolean;
  user_mask?: string | null;
  host?: string;
  port?: number;
  database?: string;
  service_name?: string | null;
  sid?: string | null;
  dsn?: string | null;
  username?: string;
  owner?: string | null;
  description?: string | null;
  tags: string[];
  connect_timeout_seconds?: number | null;
  metadata_scan_enabled?: boolean;
}

export interface CreateDataSourceRequest {
  data_source_id: string;
  name: string;
  database_type: string;
  host: string;
  port: number;
  database: string;
  service_name?: string | null;
  sid?: string | null;
  dsn?: string | null;
  username: string;
  password: string;
  is_read_only: boolean;
  description?: string;
  connect_timeout_seconds?: number | null;
  metadata_scan_enabled?: boolean;
}

export interface ConnectionTestCapabilities {
  can_read_schemas: boolean;
  can_read_tables: boolean;
  can_read_columns: boolean;
  can_read_keys: boolean;
}

export interface ConnectionTestResult {
  success: boolean;
  message?: string;
  capabilities: ConnectionTestCapabilities;
}

export interface UpdateDataSourceRequest {
  name?: string;
  database_type?: string;
  host?: string;
  port?: number;
  database?: string;
  service_name?: string | null;
  sid?: string | null;
  dsn?: string | null;
  username?: string;
  password?: string;
  is_read_only?: boolean;
  description?: string;
  connect_timeout_seconds?: number | null;
  metadata_scan_enabled?: boolean;
}

// --- Semantic Discovery DTOs (mirrors packages/contracts/src/sq_bi_contracts/semantic_profile.py) ---

export type EvidenceSource =
  | 'comment'
  | 'document'
  | 'name'
  | 'sample'
  | 'user_note'
  | 'official_pack'
  | 'ai_inference';

export type FieldOrigin = 'standard' | 'enterprise' | 'inferred';

export type TableRecommendation =
  | 'recommended_include'
  | 'possibly_relevant'
  | 'not_relevant';

export type ScanPhase =
  | 'pending'
  | 'phase_one'
  | 'phase_two'
  | 'discovering'
  | 'done'
  | 'failed';

export interface SemanticEvidenceItem {
  source: EvidenceSource;
  detail?: string | null;
}

export type SemanticSpaceVersionState = 'draft' | 'published';
export type FieldStatus = 'confirmed' | 'pending' | 'excluded' | 'sensitive' | 'invalid';

export interface SemanticProfileField {
  field_id: string;
  entity_id: string;
  physical_table: string;
  physical_column: string;
  business_name: string;
  description?: string | null;
  data_type?: string | null;
  origin: FieldOrigin;
  semantic_role?: string | null;
  default_aggregation?: string | null;
  synonyms: string[];
  confidence: number;
  evidence: SemanticEvidenceItem[];
  physical_reference?: string | null;
  is_candidate: boolean;
  status?: FieldStatus;
}

export interface SemanticEntity {
  entity_id: string;
  space_id: string;
  physical_table: string;
  business_name: string;
  description?: string | null;
  recommendation: TableRecommendation;
  fields: SemanticProfileField[];
}

export interface SemanticSpace {
  space_id: string;
  snapshot_id: string;
  name: string;
  description?: string | null;
  entities: SemanticEntity[];
  accepted: boolean;
  version?: number;
  version_state?: SemanticSpaceVersionState;
  created_at?: string | null;
  published_at?: string | null;
}

export interface SemanticSpaceDraft {
  space_id: string;
  description?: string | null;
  field_statuses: Record<string, FieldStatus>;
  updated_at?: string | null;
}

export interface CreateSemanticSpaceRequest {
  data_source_id: string;
  name: string;
  description?: string | null;
  initial_tables?: string[];
}

export interface SemanticSpaceDiff {
  space_id: string;
  new_fields: SemanticProfileField[];
  removed_fields: SemanticProfileField[];
  changed_fields: {
    field_id: string;
    before: Partial<SemanticProfileField>;
    after: Partial<SemanticProfileField>;
  }[];
  invalidated_fields: string[];
}

export interface SemanticGapCandidate {
  field_name?: string;
  table_name?: string;
  connection_id?: string;
  suggested_space_id?: string;
  field_id: string;
  physical_table: string;
  physical_column: string;
  business_name: string;
  description?: string | null;
  confidence?: number;
  suggested_reason: string;
}

export interface SchemaSnapshot {
  snapshot_id: string;
  data_source_id: string;
  version: number;
  scanned_schemas: string[];
  table_count: number;
  included_table_count: number;
  excluded_table_count: number;
  recommendation_counts: Record<string, number>;
  scan_phase: ScanPhase;
  created_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
}

export interface DataSourceDocument {
  document_id: string;
  data_source_id: string;
  filename: string;
  content_type: string;
  byte_size: number;
  upload_status: 'pending' | 'processing' | 'ready' | 'failed';
  uploaded_at?: string | null;
  error?: string | null;
}

export interface CatalogColumnRecord {
  schema_name?: string | null;
  table_name: string;
  column_name: string;
  data_type?: string | null;
  comment?: string | null;
  nullable: boolean;
  is_pk: boolean;
  is_fk: boolean;
  has_index: boolean;
}

export interface CatalogTableRecord {
  schema_name?: string | null;
  table_name: string;
  table_type: string;
  comment?: string | null;
  row_count_estimate?: number | null;
  classification: TableRecommendation;
  excluded: boolean;
  excluded_reason?: string | null;
  columns: CatalogColumnRecord[];
}

export interface CatalogOverview {
  data_source_id: string;
  snapshot_id: string;
  version: number;
  schema_count: number;
  table_count: number;
  column_count: number;
  included_table_count: number;
  excluded_table_count: number;
  excluded_tables: CatalogTableRecord[];
  suspected_business_tables: CatalogTableRecord[];
  recommendation_counts: Record<string, number>;
  scan_phase: ScanPhase;
  created_at?: string | null;
}

export interface ScanRequest {
  force_rescan?: boolean;
  authorized_schemas?: string[];
  include_rules?: string[];
  exclude_rules?: string[];
}

export interface ScanStatus {
  scan_id: string;
  data_source_id: string;
  snapshot_id?: string | null;
  phase: ScanPhase;
  progress_message?: string | null;
  table_count: number;
  included_table_count: number;
  recommendation_counts: Record<string, number>;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
}

export interface ProfileView {
  data_source_id: string;
  snapshot_id: string;
  version: number;
  spaces: SemanticSpace[];
  scan_phase: ScanPhase;
  created_at?: string | null;
}

export interface SemanticSpaceAdjustment {
  space_id: string;
  accepted: boolean;
  name?: string | null;
  description?: string | null;
  field_statuses?: Record<string, FieldStatus>;
  field_updates?: Record<string, SemanticFieldUpdate>;
}

export interface SemanticFieldUpdate {
  business_name?: string | null;
  description?: string | null;
  semantic_role?: string | null;
  default_aggregation?: string | null;
  synonyms?: string[] | null;
}

export interface SemanticTable {
  table_id: string;
  data_source_id: string;
  physical_name: string;
  business_name: string;
  description: string;
  owner?: string | null;
  tags: string[];
}

export interface SemanticField {
  field_id: string;
  table_id: string;
  physical_name: string;
  business_name: string;
  data_type: string;
  description?: string | null;
  enum_values: Record<string, string>;
  sensitivity_level: string;
  is_dimension: boolean;
  is_measure: boolean;
}

export interface SkillParameter {
  name: string;
  data_type: string;
  required: boolean;
  description?: string | null;
  allowed_values: string[];
}

export interface SkillDefinition {
  skill_id: string;
  asset_ref?: AssetRef;
  dependency_refs?: AssetRef[];
  data_source_bindings?: DataSourceBinding[];
  namespace: string;
  name: string;
  skill_type: 'metric' | 'report' | 'export';
  visibility: 'official' | 'private' | 'shared';
  owner_user_id?: string | null;
  owner_org_id?: string | null;
  description: string;
  parameters: SkillParameter[];
  output_schema?: Record<string, unknown>;
  permission_tags?: string[];
  synonyms?: string[];
  workspace_id?: string | null;
  scope?: PersonalAssetScope | null;
  version?: string;
  execution_contract?: ExecutableAssetContract | null;
  build_trace?: AssetBuildEvent[];
  validation_evidence?: ValidationEvidence[];
}

export interface ReportScheduleInfo {
  mode: 'immediate' | 'scheduled';
  status: 'draft' | 'sent' | 'scheduled' | 'stopped';
  sendAt?: string;
  note?: string;
  taskId?: string;
}

export interface ReportDefinition {
  report_id: string;
  asset_ref?: AssetRef;
  dependency_refs?: AssetRef[];
  data_source_bindings?: DataSourceBinding[];
  name: string;
  description: string;
  visibility: 'official' | 'private' | 'shared';
  owner: string;
  outputTypes: Array<'pptx' | 'docx' | 'pdf' | 'html' | 'push'>;
  channels: Array<'ec' | 'email'>;
  flow: string;
  sections: string[];
  analysis_chain?: Array<Record<string, unknown>>;
  parameters?: Array<Record<string, unknown>>;
  tags: string[];
  schedule?: ReportScheduleInfo | null;
  artifact_url?: string | null;
  publish_url?: string | null;
  version: string;
  workspace_id?: string | null;
  scope?: PersonalAssetScope | null;
  execution_contract?: ExecutableAssetContract | null;
  build_trace?: AssetBuildEvent[];
  validation_evidence?: ValidationEvidence[];
}

export interface GeneratedFileRecord {
  file_id: string;
  owner_user_id: string;
  entity_type: string;
  entity_id: string;
  filename: string;
  content_type: string;
  byte_size: number;
  download_url: string;
  view_url?: string | null;
  created_at: string;
}

export interface ScheduledJobRecord {
  job_id: string;
  owner_user_id: string;
  entity_type: string;
  entity_id: string;
  status: string;
  schedule_text: string;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ChatMessageRecord {
  message_id: string;
  session_id: string;
  user_id: string;
  sender: 'user' | 'assistant' | 'system';
  text: string;
  payload: Record<string, unknown>;
  archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface ChatSessionRecord {
  session_id: string;
  user_id: string;
  title: string;
  archived: boolean;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface SkillResolveRequest {
  user_id: string;
  text: string;
  trigger: string;
}

export interface SkillResolveResult {
  matched_skill?: SkillDefinition | null;
  candidates: SkillDefinition[];
}

export interface LlmSettings {
  base_url: string;
  model: string;
  timeout_seconds: number;
  has_api_key: boolean;
  api_key_mask?: string | null;
}

export interface LlmSettingsUpdate {
  base_url?: string;
  model?: string;
  timeout_seconds?: number;
  api_key?: string;
}

export interface DbSettings {
  data_source_id: string;
  name: string;
  database_type: string;
  connection_alias: string;
  is_read_only: boolean;
  is_configured: boolean;
  user_mask?: string | null;
  dsn_mask?: string | null;
  has_password: boolean;
}

export interface DbSettingsUpdate {
  connection_alias?: string;
  user?: string;
  password?: string;
  dsn?: string;
}

// ── Phase 6: Runtime Harness Planning Loop DTOs (mirrors sq_bi_contracts.harness) ──

export type HarnessStatus = 'completed' | 'clarification_required' | 'confirmation_required' | 'failed';

export type HarnessCommandType = 'call_tool' | 'finish' | 'clarify' | 'request_confirmation';

export type HarnessToolName =
  | 'resolve_scope'
  | 'search_assets'
  | 'inspect_asset'
  | 'execute_metric'
  | 'execute_skill'
  | 'execute_report'
  | 'explore_fields'
  | 'lookup_semantic_gap'
  | 'save_personal_asset';

export type HarnessFailureCode =
  | 'invalid_plan'
  | 'unknown_tool'
  | 'duplicate_call'
  | 'permission_denied'
  | 'step_limit'
  | 'cost_limit'
  | 'deadline_exceeded'
  | 'tool_timeout'
  | 'confirmation_invalid'
  | 'tool_failed'
  | 'asset_unavailable';

export interface RuntimeRequestContext {
  user_id: string;
  data_source_id: string;
  environment?: string;
  workspace_id?: string | null;
}

export interface HarnessBudgetLimits {
  max_steps?: number;
  max_elapsed_ms?: number;
  per_tool_timeout_ms?: number;
  max_cost_units?: number;
}

export interface HarnessBudgetUsage {
  steps: number;
  elapsed_ms: number;
  cost_units: number;
}

export interface HarnessContinuation {
  run_id: string;
  clarification?: string | null;
  confirmation_token?: string | null;
}

export interface HarnessRequest {
  question: string;
  context: RuntimeRequestContext;
  permissions?: string[];
  execute?: boolean;
  budget?: HarnessBudgetLimits;
  continuation?: HarnessContinuation | null;
  session_id?: string | null;
  conversation?: Array<{ role: 'user' | 'assistant' | 'system'; text: string }>;
  data_source_ids?: string[];
}

export interface HarnessToolCall {
  tool: HarnessToolName;
  arguments?: Record<string, unknown>;
  cost_units?: number;
}

export interface HarnessPlannerCommand {
  type: HarnessCommandType;
  call?: HarnessToolCall | null;
  message?: string | null;
  result?: Record<string, unknown> | null;
}

export interface HarnessObservation {
  ok: boolean;
  summary: string;
  data?: Record<string, unknown>;
  failure_code?: HarnessFailureCode | null;
}

export interface HarnessTraceStep {
  index: number;
  command: HarnessCommandType;
  tool?: HarnessToolName | null;
  arguments?: Record<string, unknown>;
  observation?: HarnessObservation | null;
  duration_ms: number;
  cost_units: number;
  message?: string | null;
}

export interface HarnessConfirmation {
  token: string;
  operation_digest: string;
  prompt: string;
  expires_at: string;
}

export interface HarnessFailure {
  code: HarnessFailureCode;
  message: string;
  step?: number | null;
}

export interface HarnessResult {
  run_id: string;
  status: HarnessStatus;
  answer?: string | null;
  result?: Record<string, unknown>;
  clarification?: string | null;
  confirmation?: HarnessConfirmation | null;
  trace: HarnessTraceStep[];
  budget: HarnessBudgetUsage;
  failure?: HarnessFailure | null;
  provenance?: Record<string, unknown>;
}

import { request } from './api/core';
import { authApi } from './api/auth';
import { chatApi } from './api/chat';
import { deliveryApi } from './api/delivery';
import { systemApi } from './api/system';

export const api = {
  ...authApi,
  ...chatApi,
  ...deliveryApi,
  ...systemApi,

  // Catalog
  async getDataSources() {
    try {
      return await request<DataSource[]>('/api/v1/admin/data-sources');
    } catch {
      return request<DataSource[]>('/api/v1/catalog/data-sources');
    }
  },
  async createDataSource(payload: CreateDataSourceRequest) {
    return request<DataSource & { scan_id?: string; snapshot_id?: string }>('/api/v1/admin/data-sources', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  async updateDataSource(dsId: string, payload: UpdateDataSourceRequest) {
    return request<DataSource & { connection_changed: boolean; scan_id?: string; snapshot_id?: string }>(
      `/api/v1/admin/data-sources/${dsId}`,
      { method: 'PUT', body: JSON.stringify(payload) }
    );
  },
  async deleteDataSource(dsId: string) {
    return request<{ deleted: string }>(`/api/v1/admin/data-sources/${dsId}`, {
      method: 'DELETE',
    });
  },
  async testConnection(payload: Partial<CreateDataSourceRequest>): Promise<ConnectionTestResult> {
    if (import.meta.env.VITE_MOCK_SEMANTIC === 'true') {
      await new Promise(resolve => setTimeout(resolve, 1000));
      if (payload.host && payload.host.includes('fail')) {
        return {
          success: false, message: '无法解析主机地址: Connection timed out',
          capabilities: { can_read_schemas: false, can_read_tables: false, can_read_columns: false, can_read_keys: false }
        };
      }
      return {
        success: true, message: '数据库连接测试成功！',
        capabilities: { can_read_schemas: true, can_read_tables: true, can_read_columns: true, can_read_keys: true }
      };
    }
    return request<ConnectionTestResult>('/api/v1/admin/data-sources/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  // --- Semantic Discovery ---
  async scanDataSource(dsId: string, payload: ScanRequest): Promise<ScanStatus> {
    if (import.meta.env.VITE_MOCK_SEMANTIC === 'true') {
      const store = getOrInitSemanticStore();
      const scanId = `scan_${dsId}_${Date.now()}`;
      const newScan: ScanStatus = {
        scan_id: scanId,
        data_source_id: dsId,
        snapshot_id: `snap_${dsId}_${Date.now()}`,
        phase: 'pending',
        progress_message: '开始进行扫描准备...',
        table_count: 12,
        included_table_count: 0,
        recommendation_counts: {
          recommended_include: 5,
          possibly_relevant: 4,
          not_relevant: 3
        },
        started_at: new Date().toISOString()
      };
      store.scans[dsId] = newScan;
      saveSemanticStore(store);
      return newScan;
    }
    return request<ScanStatus>(`/api/v1/datasources/${dsId}/scan`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  async getScanStatus(dsId: string, scanId: string): Promise<ScanStatus> {
    if (import.meta.env.VITE_MOCK_SEMANTIC === 'true') {
      const store = getOrInitSemanticStore();
      const scan = store.scans[dsId];
      if (!scan) {
        throw new Error(`No scan found for data source ${dsId}`);
      }
      if (scan.phase !== 'done' && scan.phase !== 'failed' && scan.started_at) {
        const elapsedSec = (Date.now() - new Date(scan.started_at).getTime()) / 1000;
        let nextPhase: ScanPhase = 'pending';
        let msg = '正在初始化连接...';

        if (elapsedSec > 8) {
          nextPhase = 'done';
          msg = '扫描完成';
          scan.completed_at = new Date().toISOString();

          if (!store.profiles[dsId]) {
            store.profiles[dsId] = {
              data_source_id: dsId,
              snapshot_id: scan.snapshot_id || 'snap_new',
              version: 1,
              scan_phase: 'done',
              created_at: new Date().toISOString(),
              spaces: [
                {
                  space_id: 'space_default',
                  snapshot_id: scan.snapshot_id || 'snap_new',
                  name: '默认业务域 (Default Domain)',
                  description: '自动发现的主业务数据表。',
                  accepted: false,
                  entities: [
                    {
                      entity_id: 'ent_orders',
                      space_id: 'space_default',
                      physical_table: 'orders',
                      business_name: '订单明细 (Orders)',
                      description: '销售订单、客户下单记录。',
                      recommendation: 'recommended_include',
                      fields: [
                        {
                          field_id: 'field_ord_id',
                          entity_id: 'ent_orders',
                          physical_table: 'orders',
                          physical_column: 'id',
                          business_name: '订单唯一 ID',
                          description: '主键 ID',
                          data_type: 'INTEGER',
                          origin: 'inferred',
                          semantic_role: 'primary_key',
                          confidence: 0.99,
                          evidence: [{ source: 'name', detail: '匹配 id' }],
                          is_candidate: true
                        },
                        {
                          field_id: 'field_ord_amt',
                          entity_id: 'ent_orders',
                          physical_table: 'orders',
                          physical_column: 'amount',
                          business_name: '订单金额',
                          description: '交易金额',
                          data_type: 'DECIMAL(10,2)',
                          origin: 'inferred',
                          semantic_role: 'measure',
                          default_aggregation: 'sum',
                          confidence: 0.95,
                          evidence: [{ source: 'name', detail: '匹配 amount' }],
                          is_candidate: true
                        }
                      ]
                    }
                  ]
                }
              ]
            };
          }
        } else if (elapsedSec > 6) {
          nextPhase = 'discovering';
          msg = '第二阶段：AI 正在对推荐表进行语义理解和分类...';
        } else if (elapsedSec > 4) {
          nextPhase = 'phase_two';
          msg = '第一阶段完成。第二阶段：正在采集数据样本与分布特征...';
        } else if (elapsedSec > 2) {
          nextPhase = 'phase_one';
          msg = '第一阶段：正在读取所有表和视图的元数据...';
        }

        scan.phase = nextPhase;
        scan.progress_message = msg;
        saveSemanticStore(store);
      }
      return scan;
    }
    return request<ScanStatus>(`/api/v1/datasources/${dsId}/scan/${scanId}`);
  },
  async getCatalogOverview(dsId: string): Promise<CatalogOverview> {
    if (import.meta.env.VITE_MOCK_SEMANTIC === 'true') {
      const store = getOrInitSemanticStore();
      const profile = store.profiles[dsId];
      if (!profile) {
        throw new Error(`No catalog snapshot for data source ${dsId}`);
      }
      return {
        data_source_id: dsId,
        snapshot_id: profile.snapshot_id,
        version: profile.version,
        schema_count: 1,
        table_count: 0,
        column_count: 0,
        included_table_count: 0,
        excluded_table_count: 0,
        excluded_tables: [],
        suspected_business_tables: [],
        recommendation_counts: {},
        scan_phase: profile.scan_phase,
        created_at: profile.created_at,
      };
    }
    return request<CatalogOverview>(`/api/v1/datasources/${dsId}/catalog/overview`);
  },
  async getCatalogLatest(dsId: string): Promise<CatalogTableRecord[]> {
    if (import.meta.env.VITE_MOCK_SEMANTIC === 'true') {
      return [];
    }
    return request<CatalogTableRecord[]>(`/api/v1/datasources/${dsId}/catalog/latest`);
  },
  async getSemanticProfile(dsId: string): Promise<ProfileView> {
    if (import.meta.env.VITE_MOCK_SEMANTIC === 'true') {
      const store = getOrInitSemanticStore();
      return store.profiles[dsId] || {
        data_source_id: dsId,
        snapshot_id: 'snap_empty',
        version: 1,
        spaces: [],
        scan_phase: 'pending'
      };
    }
    return request<ProfileView>(`/api/v1/datasources/${dsId}/profile`);
  },
  async updateSemanticSpaces(dsId: string, adjustments: SemanticSpaceAdjustment[]): Promise<ProfileView> {
    if (import.meta.env.VITE_MOCK_SEMANTIC === 'true') {
      const store = getOrInitSemanticStore();
      const profile = store.profiles[dsId];
      if (profile) {
        profile.spaces = profile.spaces.map((space: any) => {
          const adj = adjustments.find(a => a.space_id === space.space_id);
          if (adj) {
            return {
              ...space,
              accepted: adj.accepted,
              name: adj.name !== undefined && adj.name !== null ? adj.name : space.name,
              description: adj.description !== undefined && adj.description !== null ? adj.description : space.description,
              entities: (adj.field_statuses || adj.field_updates)
                ? space.entities.map((entity: any) => ({
                    ...entity,
                    fields: entity.fields.map((field: any) => ({
                      ...field,
                      status: adj.field_statuses?.[field.field_id] || field.status,
                      ...(adj.field_updates?.[field.field_id] || {})
                    }))
                  }))
                : space.entities
            };
          }
          return space;
        });
        saveSemanticStore(store);
        return profile;
      }
      throw new Error(`Profile not found for data source ${dsId}`);
    }
    return request<ProfileView>(`/api/v1/datasources/${dsId}/semantic-spaces`, {
      method: 'PUT',
      body: JSON.stringify({ adjustments }),
    });
  },

  async listSemanticSpaces(dsId: string): Promise<SemanticSpace[]> {
    if (import.meta.env.VITE_MOCK_SEMANTIC_SPACE === 'true') {
      const store = getOrInitSemanticStore();
      const profile = store.profiles[dsId];
      return profile ? profile.spaces : [];
    }
    return request<SemanticSpace[]>(`/api/v1/datasources/${dsId}/semantic-spaces`);
  },
  async getRecommendedSemanticSpaces(dsId: string): Promise<SemanticSpace[]> {
    if (import.meta.env.VITE_MOCK_SEMANTIC_SPACE === 'true') {
      return [];
    }
    return request<SemanticSpace[]>(`/api/v1/datasources/${dsId}/semantic-spaces/recommendations`);
  },

  async createSemanticSpace(dsId: string, payload: CreateSemanticSpaceRequest): Promise<SemanticSpace> {
    if (import.meta.env.VITE_MOCK_SEMANTIC_SPACE === 'true') {
      const store = getOrInitSemanticStore();
      if (!store.profiles[dsId]) {
        store.profiles[dsId] = {
          data_source_id: dsId,
          snapshot_id: 'snap_tms_1',
          version: 1,
          scan_phase: 'done',
          created_at: new Date().toISOString(),
          spaces: []
        };
      }
      const spaceId = `space_${Date.now()}`;
      const newSpace: SemanticSpace = {
        space_id: spaceId,
        snapshot_id: 'snap_tms_1',
        name: payload.name,
        description: payload.description || '',
        accepted: true,
        version: 1,
        version_state: 'draft',
        entities: [],
        created_at: new Date().toISOString()
      };
      store.profiles[dsId].spaces.push(newSpace);
      saveSemanticStore(store);
      return newSpace;
    }
    return request<SemanticSpace>(`/api/v1/datasources/${dsId}/semantic-spaces`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async deleteSemanticSpace(dsId: string, spaceId: string): Promise<{ deleted: boolean; space_id: string }> {
    if (import.meta.env.VITE_MOCK_SEMANTIC_SPACE === 'true') {
      const store = getOrInitSemanticStore();
      const profile = store.profiles[dsId];
      if (!profile) {
        throw new Error(`Profile not found for data source ${dsId}`);
      }
      profile.spaces = profile.spaces.filter((s: any) => s.space_id !== spaceId);
      saveSemanticStore(store);
      return { deleted: true, space_id: spaceId };
    }
    return request<{ deleted: boolean; space_id: string }>(
      `/api/v1/datasources/${dsId}/semantic-spaces/${spaceId}`,
      { method: 'DELETE' }
    );
  },

  async getSemanticSpace(dsId: string, spaceId: string): Promise<SemanticSpace> {
    if (import.meta.env.VITE_MOCK_SEMANTIC_SPACE === 'true') {
      const store = getOrInitSemanticStore();
      const profile = store.profiles[dsId];
      const space = profile?.spaces.find((s: any) => s.space_id === spaceId);
      if (!space) {
        throw new Error(`Space ${spaceId} not found`);
      }
      return space;
    }
    return request<SemanticSpace>(`/api/v1/datasources/${dsId}/semantic-spaces/${spaceId}`);
  },

  async refreshSemanticSpace(dsId: string, spaceId: string): Promise<SemanticSpaceDiff> {
    if (import.meta.env.VITE_MOCK_SEMANTIC_SPACE === 'true') {
      return {
        space_id: spaceId,
        new_fields: [
          {
            field_id: 'field_ord_coupon',
            entity_id: 'ent_orders',
            physical_table: 'orders',
            physical_column: 'coupon_discount',
            business_name: '优惠券抵扣金额',
            description: '订单使用优惠券抵扣的交易金额',
            data_type: 'DECIMAL(10,2)',
            origin: 'inferred',
            semantic_role: 'measure',
            default_aggregation: 'sum',
            synonyms: ['优惠券', '折扣金额'],
            confidence: 0.92,
            evidence: [{ source: 'name', detail: '物理字段 coupon_discount 匹配' }],
            is_candidate: true,
            status: 'pending'
          }
        ],
        removed_fields: [],
        changed_fields: [
          {
            field_id: 'field_status_code',
            before: { business_name: '配送状态' } as any,
            after: { business_name: '订单配送状态码' } as any
          }
        ],
        invalidated_fields: []
      };
    }
    return request<SemanticSpaceDiff>(`/api/v1/datasources/${dsId}/semantic-spaces/${spaceId}/refresh`, {
      method: 'POST',
    });
  },

  async publishSemanticSpace(dsId: string, spaceId: string, payload: { confirmed_suggestions?: string[] }): Promise<SemanticSpace> {
    if (import.meta.env.VITE_MOCK_SEMANTIC_SPACE === 'true') {
      const store = getOrInitSemanticStore();
      const profile = store.profiles[dsId];
      if (!profile) throw new Error('Profile not found');
      const space = profile.spaces.find((s: any) => s.space_id === spaceId);
      if (!space) throw new Error('Space not found');

      space.version = (space.version || 1) + 1;
      space.version_state = 'published';
      space.published_at = new Date().toISOString();

      if (payload.confirmed_suggestions && payload.confirmed_suggestions.includes('field_ord_coupon')) {
        let ent = space.entities.find((e: any) => e.entity_id === 'ent_orders');
        if (!ent) {
          ent = {
            entity_id: 'ent_orders',
            space_id: spaceId,
            physical_table: 'orders',
            business_name: '订单明细 (Orders)',
            description: '销售订单、客户下单记录。',
            recommendation: 'recommended_include',
            fields: []
          };
          space.entities.push(ent);
        }
        if (!ent.fields.some((f: any) => f.field_id === 'field_ord_coupon')) {
          ent.fields.push({
            field_id: 'field_ord_coupon',
            entity_id: 'ent_orders',
            physical_table: 'orders',
            physical_column: 'coupon_discount',
            business_name: '优惠券抵扣金额',
            description: '订单使用优惠券抵扣的交易金额',
            data_type: 'DECIMAL(10,2)',
            origin: 'inferred',
            semantic_role: 'measure',
            default_aggregation: 'sum',
            synonyms: ['优惠券', '折扣金额'],
            confidence: 0.92,
            evidence: [{ source: 'name', detail: '物理字段 coupon_discount 匹配' }],
            is_candidate: false,
            status: 'confirmed'
          });
        }
      }
      saveSemanticStore(store);
      return space;
    }
    return request<SemanticSpace>(`/api/v1/datasources/${dsId}/semantic-spaces/${spaceId}/publish`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async lookupSemanticGaps(connectionId: string, query: string): Promise<SemanticGapCandidate[]> {
    if (import.meta.env.VITE_MOCK_SEMANTIC_SPACE === 'true') {
      const candidates: SemanticGapCandidate[] = [];
      if (query.includes('coupon') || query.includes('折扣') || query.includes('优惠券')) {
        candidates.push({
          field_name: 'coupon_discount',
          table_name: 'orders',
          connection_id: connectionId,
          suggested_space_id: 'space_scheduling',
          field_id: 'field_ord_coupon',
          physical_table: 'billing_detail',
          physical_column: 'coupon_discount',
          business_name: '优惠券抵扣金额',
          suggested_reason: '用户提问提及了优惠券折扣，该物理字段与提问主题强相关，但尚未纳入本数据源的任何业务语义空间中',
          confidence: 0.92
        });
      }
      return candidates;
    }
    return request<SemanticGapCandidate[]>('/api/v1/query/gap-lookup', {
      method: 'POST',
      body: JSON.stringify({ connection_id: connectionId, query }),
    });
  },
  async uploadDataSourceDocument(dsId: string, file: File): Promise<DataSourceDocument> {
    if (import.meta.env.VITE_MOCK_SEMANTIC === 'true') {
      const store = getOrInitSemanticStore();
      const docId = `doc_${dsId}_${Date.now()}`;
      const newDoc: DataSourceDocument = {
        document_id: docId,
        data_source_id: dsId,
        filename: file.name,
        content_type: file.type || 'application/octet-stream',
        byte_size: file.size,
        upload_status: 'ready',
        uploaded_at: new Date().toISOString()
      };
      if (!store.documents[dsId]) {
        store.documents[dsId] = [];
      }
      store.documents[dsId].push(newDoc);
      saveSemanticStore(store);
      return newDoc;
    }
    const form = new FormData();
    form.append('file', file);
    return request<DataSourceDocument>(`/api/v1/datasources/${dsId}/documents`, {
      method: 'POST',
      body: form,
    });
  },
  async listDataSourceDocuments(dsId: string): Promise<DataSourceDocument[]> {
    if (import.meta.env.VITE_MOCK_SEMANTIC === 'true') {
      const store = getOrInitSemanticStore();
      return store.documents[dsId] || [];
    }
    return request<DataSourceDocument[]>(`/api/v1/datasources/${dsId}/documents`);
  },
  async deleteDataSourceDocument(dsId: string, documentId: string): Promise<void> {
    if (import.meta.env.VITE_MOCK_SEMANTIC === 'true') {
      const store = getOrInitSemanticStore();
      store.documents[dsId] = (store.documents[dsId] || []).filter(
        (d: DataSourceDocument) => d.document_id !== documentId
      );
      saveSemanticStore(store);
      return;
    }
    await request(`/api/v1/datasources/${dsId}/documents/${documentId}`, { method: 'DELETE' });
  },

  async getTables() {
    return request<SemanticTable[]>('/api/v1/catalog/tables');
  },
  async getFields() {
    return request<SemanticField[]>('/api/v1/catalog/fields');
  },

  // Metrics
  async getMetrics() {
    return request<MetricDefinition[]>('/api/v1/metrics');
  },
  async draftMetric(payload: MetricDraftRequest) {
    return request<MetricDraft>('/api/v1/ai/metrics/draft', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  async createUserMetric(payload: CreateUserMetricRequest) {
    return request<MetricDefinition>('/api/v1/metrics/user-defined', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  async updateMetric(metricCode: string, payload: {
    user_id: string;
    role_ids?: string[];
    name?: string;
    definition?: string;
    formula?: Partial<MetricFormula>;
    update_frequency?: string | null;
    synonyms?: string[];
    permission_tags?: string[];
    execution_contract?: ExecutableAssetContract | null;
    build_trace?: AssetBuildEvent[];
    validation_evidence?: ValidationEvidence[];
  }) {
    return request<MetricDefinition>(`/api/v1/metrics/${encodeURIComponent(metricCode)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },
  async draftSkillSchema(payload: {
    user_id: string;
    name: string;
    description: string;
    prompt: string;
    adjustment?: string | null;
  }) {
    return request<SkillSchemaDraftResponse>('/api/v1/ai/skills/draft', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  async executeSkill(payload: {
    user_id: string;
    question: string;
    skill: SkillDefinition;
    execute?: boolean;
  }) {
    return request<QueryResult | SkillClarificationRequired>('/api/v1/ai/skills/execute', {
      method: 'POST',
      body: JSON.stringify({
        ...payload,
        execute: payload.execute ?? true,
      }),
    });
  },
  async testAssetDraft(payload: {
    user_id: string;
    asset_type: 'metric' | 'skill' | 'report';
    name: string;
    description: string;
    logical_sql?: string | null;
    data_source_id?: string;
    conversation_context?: string;
    default_time_range?: '本月' | '本周';
    execute?: boolean;
  }) {
    return request<QueryResult>('/api/v1/ai/assets/test', {
      method: 'POST',
      body: JSON.stringify({ ...payload, default_time_range: payload.default_time_range || '本月', execute: payload.execute ?? true }),
    });
  },
  async draftReportPlan(payload: {
    user_id: string;
    output_type: string;
    title: string;
    background?: string;
    prompt?: string;
    bound_metric_codes?: string[];
    bound_skill_ids?: string[];
  }) {
    return request<Record<string, unknown>>('/api/v1/ai/reports/draft', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  async updateMetricVisibility(metricCode: string, payload: { visibility: 'private' | 'shared'; user_id: string; role_ids?: string[] }) {
    return request<MetricDefinition>(`/api/v1/metrics/${encodeURIComponent(metricCode)}/visibility`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },
  async getMetricDependencies(metricCode: string) {
    return request<MetricDependencyRecord[]>(`/api/v1/metrics/${encodeURIComponent(metricCode)}/dependencies`);
  },
  async deleteMetric(metricCode: string, payload: { user_id: string; role_ids?: string[] }) {
    return request<MetricDefinition>(`/api/v1/metrics/${encodeURIComponent(metricCode)}`, {
      method: 'DELETE',
      body: JSON.stringify(payload),
    });
  },
  async copyMetric(metricCode: string, payload: { user_id: string }) {
    return request<MetricDefinition>(`/api/v1/metrics/${encodeURIComponent(metricCode)}/copy`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  // Skills
  async getSkills() {
    return request<SkillDefinition[]>('/api/v1/skills');
  },
  async createSkill(payload: SkillDefinition, userId = 'admin') {
    return request<SkillDefinition>(`/api/v1/skills?user_id=${encodeURIComponent(userId)}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  async updateSkill(skillId: string, payload: {
    user_id: string;
    name?: string;
    description?: string;
    parameters?: SkillParameter[];
    output_schema?: Record<string, unknown>;
    permission_tags?: string[];
    synonyms?: string[];
    execution_contract?: ExecutableAssetContract | null;
    build_trace?: AssetBuildEvent[];
    validation_evidence?: ValidationEvidence[];
    data_source_bindings?: DataSourceBinding[];
  }) {
    return request<SkillDefinition>(`/api/v1/skills/${skillId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },
  async updateSkillVisibility(skillId: string, payload: { visibility: 'private' | 'shared'; user_id: string }) {
    return request<SkillDefinition>(`/api/v1/skills/${skillId}/visibility`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },
  async copySkill(skillId: string, payload: { user_id: string }) {
    return request<SkillDefinition>(`/api/v1/skills/${skillId}/copy`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  async deleteSkill(skillId: string, payload: { user_id: string; role_ids?: string[] }) {
    return request<{ status: string; skill_id: string }>(`/api/v1/skills/${skillId}`, {
      method: 'DELETE',
      body: JSON.stringify(payload),
    });
  },
  async resolveSkill(payload: SkillResolveRequest) {
    return request<SkillResolveResult>('/api/v1/skills/resolve', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  // Query Runtime
  async askQuery(payload: { user_id: string; text: string; execute?: boolean; data_source_id?: string; data_source_ids?: string[] }) {
    if (import.meta.env.VITE_MOCK_EXPLORATION === 'true') {
      await new Promise(resolve => setTimeout(resolve, 800));
      const store = getOrInitExplorationStore();
      const queryText = payload.text.trim();

      // Check if it's already saved as a metric (or if query text matches any saved metrics)
      const isSaved = store.savedMetrics.some(m =>
        queryText.includes(m) || m.includes(queryText)
      );

      if (isSaved) {
        return {
          query_id: `qry_${Math.random().toString(36).substr(2, 9)}`,
          audit_id: `aud_${Math.random().toString(36).substr(2, 9)}`,
          columns: ['factory', 'shipments'],
          rows: queryText.includes('上海')
            ? [['上海厂区', 1200]]
            : queryText.includes('北京')
              ? [['北京厂区', 800]]
              : [['上海厂区', 1200], ['北京厂区', 800], ['广州厂区', 1500]],
          chart_suggestion: {
            chart_type: 'BAR',
            title: queryText.includes('上海') ? '上海厂区发货量 (企业正式)' : '各厂区发货量 (企业正式)',
            x_field: 'factory',
            y_field: 'shipments'
          },
          lineage: {
            lineage_id: `lin_${Math.random().toString(36).substr(2, 9)}`,
            source_system: 'TMS',
            data_source_id: payload.data_source_id || 'oracle_tms',
            metric_codes: ['shipment_volume'],
            metric_versions: { 'shipment_volume': '1.0.0' },
            physical_tables: ['delivery_order'],
            physical_fields: ['factory_name', 'qty'],
            executed_at: new Date().toISOString()
          },
          lineage_info: {
            metrics: [
              {
                metric_id: 'shipment_volume',
                metric_name: '发货量',
                visibility: 'enterprise',
                version: '1.0.0'
              }
            ],
            skills: [],
            data_sources: [
              {
                data_source_id: payload.data_source_id || 'oracle_tms',
                name: 'TMS 生产数据库'
              }
            ],
            executed_at: new Date().toISOString(),
            data_watermark: new Date().toLocaleString()
          },
          summary: `该查询已匹配已沉淀的企业正式口径“发货量”。结果源自经过治理的标准化指标。`,
          answer_path: 'enterprise',
          confidence_tier: 'high',
          is_exploratory: false
        } as QueryResult;
      }

      if (queryText.includes('探索') || queryText.includes('优惠券')) {
        return {
          query_id: `qry_${Math.random().toString(36).substr(2, 9)}`,
          audit_id: `aud_${Math.random().toString(36).substr(2, 9)}`,
          columns: ['factory', 'shipments'],
          rows: [['上海厂区', 1200], ['北京厂区', 800], ['广州厂区', 1500]],
          chart_suggestion: {
            chart_type: 'BAR',
            title: '各厂区发货量 (AI 探索分析)',
            x_field: 'factory',
            y_field: 'shipments'
          },
          lineage: {
            lineage_id: `lin_${Math.random().toString(36).substr(2, 9)}`,
            source_system: 'TMS',
            data_source_id: payload.data_source_id || 'oracle_tms',
            metric_codes: [],
            metric_versions: {},
            physical_tables: ['delivery_order'],
            physical_fields: ['factory_name', 'qty'],
            executed_at: new Date().toISOString()
          },
          summary: `已根据探索口径“${queryText}”为您生成分析结果。本查询为基于数据库表字段的探索性分析，非官方口径。`,
          answer_path: 'ai_exploration',
          confidence_tier: 'medium',
          is_exploratory: true,
          assumptions: [
            {
              fields_used: [
                {
                  physical_table: 'delivery_order',
                  physical_column: 'qty',
                  business_name: '发货数量',
                  inferred_meaning: '发运明细表中的物理件数',
                  origin: 'inferred'
                },
                {
                  physical_table: 'delivery_order',
                  physical_column: 'factory_name',
                  business_name: '厂区名称',
                  inferred_meaning: '运单起点的厂区名称',
                  origin: 'inferred'
                }
              ],
              aggregation: 'SUM(qty)',
              time_field: 'create_time',
              time_grain: 'month',
              filters: [],
              joins: [
                {
                  left_table: 'delivery_order',
                  right_table: 'factory_dim',
                  join_key: 'factory_id',
                  evidence: 'foreign_key',
                  note: '关联厂区维度表以解析厂区名称'
                }
              ],
              best_join_evidence: 'foreign_key',
              caliber_label: 'AI 探索 / 企业数据库字段，非官方标准口径'
            }
          ],
          gap_candidates: [
            {
              field_id: 'field_ord_coupon',
              physical_table: 'billing_detail',
              physical_column: 'coupon_discount',
              business_name: '优惠券抵扣金额',
              confidence: 0.92,
              suggested_reason: '用户提问提及了优惠券折扣，该物理字段与提问主题强相关，但尚未纳入本数据源的任何业务语义空间中'
            }
          ]
        } as QueryResult;
      }

      // If it contains clarification keywords (interpretation choice or correction options)
      const isClarifiedOrCorrected =
        queryText.includes('申请') ||
        queryText.includes('出库') ||
        queryText.includes('过滤') ||
        queryText.includes('上海') ||
        queryText.includes('北京') ||
        queryText.includes('按月') ||
        queryText.includes('SUM');

      if (isClarifiedOrCorrected) {
        return {
          query_id: `qry_${Math.random().toString(36).substr(2, 9)}`,
          audit_id: `aud_${Math.random().toString(36).substr(2, 9)}`,
          columns: ['factory', 'shipments'],
          rows: queryText.includes('上海')
            ? [['上海厂区', 1200]]
            : queryText.includes('北京')
              ? [['北京厂区', 800]]
              : [['上海厂区', 1200], ['北京厂区', 800], ['广州厂区', 1500]],
          chart_suggestion: {
            chart_type: 'BAR',
            title: queryText.includes('上海') ? '上海厂区发货量' : '各厂区发货量',
            x_field: 'factory',
            y_field: 'shipments'
          },
          lineage: {
            lineage_id: `lin_${Math.random().toString(36).substr(2, 9)}`,
            source_system: 'TMS',
            data_source_id: payload.data_source_id || 'oracle_tms',
            metric_codes: [],
            metric_versions: {},
            physical_tables: ['delivery_order'],
            physical_fields: ['factory_name', 'qty'],
            executed_at: new Date().toISOString()
          },
          summary: `已根据探索口径“${queryText}”为您生成分析结果。本查询为基于数据库表字段的探索性分析，非官方口径。`,
          answer_path: 'ai_exploration',
          confidence_tier: queryText.includes('过滤') || queryText.includes('上海') ? 'high' : 'medium',
          is_exploratory: true,
          assumptions: [
            {
              fields_used: [
                {
                  physical_table: 'delivery_order',
                  physical_column: 'qty',
                  business_name: '发货数量',
                  inferred_meaning: '发运明细表中的物理件数',
                  origin: 'inferred'
                },
                {
                  physical_table: 'delivery_order',
                  physical_column: 'factory_name',
                  business_name: '厂区名称',
                  inferred_meaning: '运单起点的厂区名称',
                  origin: 'inferred'
                }
              ],
              aggregation: 'SUM(qty)',
              time_field: 'create_time',
              time_grain: 'month',
              filters: queryText.includes('上海') ? ["factory_name = '上海厂区'"] : [],
              joins: [
                {
                  left_table: 'delivery_order',
                  right_table: 'factory_dim',
                  join_key: 'factory_id',
                  evidence: 'foreign_key',
                  note: '关联厂区维度表以解析厂区名称'
                }
              ],
              best_join_evidence: 'foreign_key',
              caliber_label: 'AI 探索 / 企业数据库字段，非官方标准口径'
            }
          ]
        } as QueryResult;
      }

      // Default low confidence result with clarification request
      return {
        query_id: `qry_${Math.random().toString(36).substr(2, 9)}`,
        audit_id: `aud_${Math.random().toString(36).substr(2, 9)}`,
        columns: ['factory', 'shipments'],
        rows: [['上海厂区', 1000], ['北京厂区', 750], ['广州厂区', 1200]],
        chart_suggestion: {
          chart_type: 'BAR',
          title: '各厂区发货量 (低置信度估算)',
          x_field: 'factory',
          y_field: 'shipments'
        },
        lineage: {
          lineage_id: `lin_${Math.random().toString(36).substr(2, 9)}`,
          source_system: 'TMS',
          data_source_id: payload.data_source_id || 'oracle_tms',
          metric_codes: [],
          metric_versions: {},
          physical_tables: ['delivery_order'],
          physical_fields: ['factory_name', 'qty'],
          executed_at: new Date().toISOString()
        },
        summary: `您提问的“${payload.text}”涉及的指标“发货量”口径尚不明确。系统已自动生成低置信度的临时探索，请在下方选择精确的业务口径以重新计算。`,
        answer_path: 'ai_exploration',
        confidence_tier: 'low',
        is_exploratory: true,
        clarification: {
          question: '在 TMS 系统中，“发货量”可能有不同的统计口径，请选择您想查询的口径：',
          options: [
            {
              label: '按发货申请单统计 (发货申请量)',
              description: '基于用户提交的发货申请单数量进行统计，包含未审核的订单。',
              interpretation: `${queryText} (发货申请量)`
            },
            {
              label: '按实际出库发货量统计 (实际出库量)',
              description: '基于仓库实际出库发货的物理数量统计，仅包含已出库完成的订单。',
              interpretation: `${queryText} (实际出库量)`
            }
          ]
        }
      } as QueryResult;
    }

    return request<QueryResult>('/api/v1/query/ask', {
      method: 'POST',
      body: JSON.stringify({
        question: payload.text,
        user_id: payload.user_id,
        execute: payload.execute ?? true,
        ...(payload.data_source_id ? { data_source_id: payload.data_source_id } : {}),
        ...(payload.data_source_ids?.length ? { data_source_ids: payload.data_source_ids } : {}),
      }),
    });
  },
  async queryHarness(payload: HarnessRequest): Promise<HarnessResult> {
    if (import.meta.env.VITE_MOCK_EXPLORATION === 'true') {
      await new Promise(resolve => setTimeout(resolve, 1200));
      const question = payload.question.trim();
      const runId = payload.continuation?.run_id || `hrun_${Math.random().toString(36).substring(2, 8)}`;

      // 1. Failure Scenario
      if (question.includes('失败') || question.includes('error')) {
        return {
          run_id: runId,
          status: 'failed',
          trace: [
            {
              index: 1,
              command: 'call_tool',
              tool: 'resolve_scope',
              arguments: { user_id: payload.context.user_id, data_source_id: payload.context.data_source_id },
              observation: { ok: true, summary: 'Successfully resolved scope.' },
              duration_ms: 80,
              cost_units: 1,
            },
            {
              index: 2,
              command: 'call_tool',
              tool: 'search_assets',
              arguments: { query: question },
              observation: { ok: false, summary: 'Step execution failed due to database connection timeout.', failure_code: 'tool_timeout' },
              duration_ms: 1000,
              cost_units: 1,
            }
          ],
          budget: { steps: 2, elapsed_ms: 1080, cost_units: 2 },
          failure: {
            code: 'tool_timeout',
            message: 'Controlled tool search_assets exceeded allowed execution duration.',
            step: 2,
          },
          provenance: { data_source_id: payload.context.data_source_id, environment: 'default' },
        };
      }

      // 2. Personal Asset Save Confirmation / Save Flow
      if (question.includes('保存') || question.includes('save') || payload.continuation?.confirmation_token) {
        if (payload.continuation?.confirmation_token === 'conf_token_123') {
          return {
            run_id: runId,
            status: 'completed',
            answer: `已成功保存个人资产 '实付运费'，并在您的个人工作区中建立依赖关联。该资产已绑定物理列 billing_detail.freight_charge。`,
            result: {
              columns: ['status', 'message', 'asset_id'],
              rows: [['success', 'Personal asset saved successfully', 'usr_freight_total']],
              chart_suggestion: { chart_type: 'TABLE', title: '保存结果' },
              lineage: {
                lineage_id: `lin_${Math.random().toString(36).substring(2, 8)}`,
                source_system: 'TMS',
                data_source_id: payload.context.data_source_id,
                metric_codes: [],
                metric_versions: {},
                physical_tables: ['billing_detail'],
                physical_fields: ['freight_charge'],
                executed_at: new Date().toISOString(),
              },
            },
            trace: [
              {
                index: 1,
                command: 'call_tool',
                tool: 'resolve_scope',
                arguments: { user_id: payload.context.user_id, data_source_id: payload.context.data_source_id },
                observation: { ok: true, summary: 'Successfully resolved scope.' },
                duration_ms: 50,
                cost_units: 1,
              },
              {
                index: 2,
                command: 'call_tool',
                tool: 'save_personal_asset',
                arguments: {
                  business_name: '实付运费',
                  physical_table: 'billing_detail',
                  physical_column: 'freight_charge',
                  confirmation_token: 'conf_token_123',
                },
                observation: { ok: true, summary: 'Saved personal asset successfully. Asset ID: usr_freight_total.' },
                duration_ms: 400,
                cost_units: 2,
              },
              {
                index: 3,
                command: 'finish',
                duration_ms: 20,
                cost_units: 0,
              }
            ],
            budget: { steps: 3, elapsed_ms: 470, cost_units: 3 },
            provenance: {
              data_source_id: payload.context.data_source_id,
              environment: 'default',
              workspace_id: payload.context.workspace_id || 'personal_ws_admin',
            },
          };
        }

        return {
          run_id: runId,
          status: 'confirmation_required',
          confirmation: {
            token: 'conf_token_123',
            operation_digest: 'digest_freight_charge_save',
            prompt: '您确定要将物理字段 billing_detail.freight_charge 保存为个人资产 "实付运费" 吗？此操作将写入您的个人工作区。',
            expires_at: new Date(Date.now() + 600 * 1000).toISOString(),
          },
          trace: [
            {
              index: 1,
              command: 'call_tool',
              tool: 'resolve_scope',
              arguments: { user_id: payload.context.user_id, data_source_id: payload.context.data_source_id },
              observation: { ok: true, summary: 'Successfully resolved scope.' },
              duration_ms: 70,
              cost_units: 1,
            },
            {
              index: 2,
              command: 'request_confirmation',
              message: 'Saving personal asset requires user confirmation.',
              duration_ms: 10,
              cost_units: 0,
            }
          ],
          budget: { steps: 2, elapsed_ms: 80, cost_units: 1 },
          provenance: { data_source_id: payload.context.data_source_id, environment: 'default' },
        };
      }

      // 3. Clarification Flow
      if (question.includes('澄清') || question === '发货量' || payload.continuation?.clarification) {
        if (payload.continuation?.clarification) {
          const selectedOption = payload.continuation.clarification;
          return {
            run_id: runId,
            status: 'completed',
            answer: `已根据澄清口径“${selectedOption}”进行规划计算：上海厂区总发货量为 1,200 件，北京厂区为 800 件，广州厂区为 1,500 件。`,
            result: {
              columns: ['factory', 'shipments'],
              rows: [['上海厂区', 1200], ['北京厂区', 800], ['广州厂区', 1500]],
              chart_suggestion: { chart_type: 'BAR', title: `${selectedOption} 统计结果`, x_field: 'factory', y_field: 'shipments' },
              lineage: {
                lineage_id: `lin_${Math.random().toString(36).substring(2, 8)}`,
                source_system: 'TMS',
                data_source_id: payload.context.data_source_id,
                metric_codes: [],
                metric_versions: {},
                physical_tables: ['delivery_order'],
                physical_fields: ['factory_name', 'qty'],
                executed_at: new Date().toISOString(),
              },
            },
            trace: [
              {
                index: 1,
                command: 'call_tool',
                tool: 'resolve_scope',
                arguments: { user_id: payload.context.user_id, data_source_id: payload.context.data_source_id },
                observation: { ok: true, summary: 'Successfully resolved scope.' },
                duration_ms: 60,
                cost_units: 1,
              },
              {
                index: 2,
                command: 'call_tool',
                tool: 'execute_metric',
                arguments: { metric_code: 'shipment_volume', clarification: selectedOption },
                observation: { ok: true, summary: `Successfully executed metric with clarified parameter: ${selectedOption}.` },
                duration_ms: 380,
                cost_units: 2,
              },
              {
                index: 3,
                command: 'finish',
                duration_ms: 15,
                cost_units: 0,
              }
            ],
            budget: { steps: 3, elapsed_ms: 455, cost_units: 3 },
            provenance: { data_source_id: payload.context.data_source_id, environment: 'default' },
          };
        }

        return {
          run_id: runId,
          status: 'clarification_required',
          clarification: '在 TMS 系统中，"发货量"可能按以下两个口径统计，请问您想查询哪一个？\n1. 按发货申请单统计 (仅包含已生成申请的订单)\n2. 按实际出库发货量统计 (仅包含已完成仓库发货的订单)',
          trace: [
            {
              index: 1,
              command: 'call_tool',
              tool: 'resolve_scope',
              arguments: { user_id: payload.context.user_id, data_source_id: payload.context.data_source_id },
              observation: { ok: true, summary: 'Successfully resolved scope.' },
              duration_ms: 70,
              cost_units: 1,
            },
            {
              index: 2,
              command: 'clarify',
              message: 'Ambiguity detected for term "发货量".',
              duration_ms: 10,
              cost_units: 0,
            }
          ],
          budget: { steps: 2, elapsed_ms: 80, cost_units: 1 },
          provenance: { data_source_id: payload.context.data_source_id, environment: 'default' },
        };
      }

      // 4. Default Completed Flow
      return {
        run_id: runId,
        status: 'completed',
        answer: `基于数据源 ${payload.context.data_source_id}，Harness 执行规划器完成 5 步检索计算。上海厂区总发货量为 1,200 件，北京厂区为 800 件，广州厂区为 1,500 件。`,
        result: {
          columns: ['factory', 'shipments'],
          rows: [['上海厂区', 1200], ['北京厂区', 800], ['广州厂区', 1500]],
          chart_suggestion: { chart_type: 'BAR', title: '各厂区发货量分析', x_field: 'factory', y_field: 'shipments' },
          lineage: {
            lineage_id: `lin_${Math.random().toString(36).substring(2, 8)}`,
            source_system: 'TMS',
            data_source_id: payload.context.data_source_id,
            metric_codes: ['shipment_volume'],
            metric_versions: { 'shipment_volume': '1.0.0' },
            physical_tables: ['delivery_order'],
            physical_fields: ['factory_name', 'qty'],
            executed_at: new Date().toISOString(),
          },
        },
        trace: [
          {
            index: 1,
            command: 'call_tool',
            tool: 'resolve_scope',
            arguments: { user_id: payload.context.user_id, data_source_id: payload.context.data_source_id },
            observation: { ok: true, summary: 'Successfully resolved scope.' },
            duration_ms: 80,
            cost_units: 1,
          },
          {
            index: 2,
            command: 'call_tool',
            tool: 'search_assets',
            arguments: { query: question },
            observation: { ok: true, summary: 'Found matching metric: shipment_volume.' },
            duration_ms: 120,
            cost_units: 1,
          },
          {
            index: 3,
            command: 'call_tool',
            tool: 'inspect_asset',
            arguments: { asset_ref: { asset: { source_type: 'official_pack', source_id: 'tms', asset_type: 'metric', local_code: 'shipment_volume', asset_id: 'shipment_volume' }, version: '1.0.0' } },
            observation: { ok: true, summary: 'Confirmed metric formula: SUM(qty). Dimensions: factory_name.' },
            duration_ms: 100,
            cost_units: 1,
          },
          {
            index: 4,
            command: 'call_tool',
            tool: 'execute_metric',
            arguments: { metric_code: 'shipment_volume' },
            observation: { ok: true, summary: 'Executed metric calculation. Returned 3 rows.' },
            duration_ms: 450,
            cost_units: 2,
          },
          {
            index: 5,
            command: 'finish',
            duration_ms: 30,
            cost_units: 0,
          }
        ],
        budget: { steps: 5, elapsed_ms: 780, cost_units: 5 },
        provenance: { data_source_id: payload.context.data_source_id, environment: 'default' },
      };
    }

    return request<HarnessResult>('/api/v1/query/harness', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  async getCallableAssets(userId: string, dataSourceId?: string | null) {
    const params = new URLSearchParams({ user_id: userId });
    if (dataSourceId) params.set('data_source_id', dataSourceId);
    return request<CallableAsset[]>(`/api/v1/query/callable-assets?${params.toString()}`);
  },
  async saveExplorationAsMetric(payload: SaveExplorationAsMetricRequest) {
    if (import.meta.env.VITE_MOCK_EXPLORATION === 'true') {
      await new Promise(resolve => setTimeout(resolve, 800));
      const store = getOrInitExplorationStore();
      const metricName = payload.business_name || '发货量';

      // Save it
      if (!store.savedMetrics.includes(metricName)) {
        store.savedMetrics.push(metricName);
        // Also save the generic terms to trigger it
        store.savedMetrics.push('各厂区发货量');
        store.savedMetrics.push('发货量');
        saveExplorationStore(store);
      }

      return {
        metric_code: `usr_${Math.random().toString(36).substr(2, 6)}`,
        name: metricName
      };
    }

    return request<{ metric_code: string; name: string }>('/api/v1/query/exploration/save-metric', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  // ── Phase 4: Enterprise Domain Pack endpoints ──────────────────────────────
  async listEnterprisePacks(dataSourceId?: string) {
    if (import.meta.env.VITE_MOCK_ENTERPRISE_PACK === 'true') {
      await new Promise(resolve => setTimeout(resolve, 300));
      return _mockEnterprisePacks(dataSourceId);
    }
    const qs = dataSourceId ? `?data_source_id=${encodeURIComponent(dataSourceId)}` : '';
    return request<EnterprisePack[]>(`/api/v1/admin/enterprise-packs${qs}`);
  },

  async getEnterprisePack(packId: string) {
    if (import.meta.env.VITE_MOCK_ENTERPRISE_PACK === 'true') {
      await new Promise(resolve => setTimeout(resolve, 200));
      const packs = _mockEnterprisePacks();
      return packs.find(p => p.pack_id === packId) ?? packs[0];
    }
    return request<EnterprisePack>(`/api/v1/admin/enterprise-packs/${packId}`);
  },

  async createEnterprisePack(payload: CreateEnterprisePackRequest) {
    if (import.meta.env.VITE_MOCK_ENTERPRISE_PACK === 'true') {
      await new Promise(resolve => setTimeout(resolve, 600));
      return _mockNewEnterprisePack(payload);
    }
    return request<EnterprisePack>('/api/v1/admin/enterprise-packs', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async updateEnterprisePack(packId: string, payload: Partial<EnterprisePack> & { updated_by?: string }) {
    if (import.meta.env.VITE_MOCK_ENTERPRISE_PACK === 'true') {
      await new Promise(resolve => setTimeout(resolve, 400));
      const base = _mockEnterprisePacks().find(p => p.pack_id === packId) ?? _mockEnterprisePacks()[0];
      return { ...base, ...payload, updated_at: new Date().toISOString() } as EnterprisePack;
    }
    return request<EnterprisePack>(`/api/v1/admin/enterprise-packs/${packId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  },

  async deleteEnterprisePack(packId: string) {
    return request<{ pack_id: string; deleted: boolean }>(`/api/v1/admin/enterprise-packs/${packId}`, {
      method: 'DELETE',
    });
  },

  async draftEnterprisePack(payload: PackDraftRequest) {
    if (import.meta.env.VITE_MOCK_ENTERPRISE_PACK === 'true') {
      await new Promise(resolve => setTimeout(resolve, 1200));
      return _mockPackDraftResult(payload.data_source_id);
    }
    return request<PackDraftResult>('/api/v1/admin/enterprise-packs/draft', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async suggestDomainPackAuthoring(payload: DomainPackAuthoringRequest) {
    return request<DomainPackAuthoringResult>('/api/v1/admin/domain-pack-authoring/suggest', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async publishEnterprisePack(packId: string, payload: PublishPackRequest) {
    if (import.meta.env.VITE_MOCK_ENTERPRISE_PACK === 'true') {
      await new Promise(resolve => setTimeout(resolve, 500));
      const base = _mockEnterprisePacks().find(p => p.pack_id === packId) ?? _mockEnterprisePacks()[0];
      return { ...base, version_state: 'published' as PackVersionState, version: payload.version ?? '1.0.0' } as EnterprisePack;
    }
    return request<EnterprisePack>(`/api/v1/admin/enterprise-packs/${packId}/publish`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /**
   * Open the one additive extension layer owned by a first-class base pack.
   * The server creates it only when absent; it is deliberately never returned
   * by listEnterprisePacks as another top-level card.
   */
  async openPackExtensionLayer(basePackId: string, payload: { base_kind: 'official' | 'enterprise'; created_by: string }) {
    if (import.meta.env.VITE_MOCK_ENTERPRISE_PACK === 'true') {
      await new Promise(resolve => setTimeout(resolve, 250));
      return _mockOpenPackExtensionLayer(basePackId, payload);
    }
    return request<PackExtensionLayer>(`/api/v1/admin/domain-packs/${encodeURIComponent(basePackId)}/extension-layer`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /** Read-only base-plus-extension content used by the pack browser dialog. */
  async getEffectivePackContent(basePackId: string, baseKind: 'official' | 'enterprise'): Promise<EffectiveDomainPack> {
    return request<EffectiveDomainPack>(`/api/v1/admin/domain-packs/${encodeURIComponent(basePackId)}/effective-content?base_kind=${baseKind}`);
  },

  async updatePackExtensionLayer(extensionId: string, payload: { draft: EnterprisePackDraft }) {
    return request<PackExtensionLayer>(`/api/v1/admin/extension-layers/${encodeURIComponent(extensionId)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  },

  async transitionPackExtensionLayer(extensionId: string, action: 'publish' | 'deactivate' | 'archive' | 'restore') {
    return request<PackExtensionLayer>(`/api/v1/admin/extension-layers/${encodeURIComponent(extensionId)}/${action}`, { method: 'POST' });
  },

  async deletePackExtensionLayer(extensionId: string) {
    return request<void>(`/api/v1/admin/extension-layers/${encodeURIComponent(extensionId)}`, { method: 'DELETE' });
  },

  async previewPromotion(payload: PromotionPreviewRequest): Promise<PromotionPreview> {
    if (import.meta.env.VITE_MOCK_ENTERPRISE_PACK === 'true') {
      await new Promise(resolve => setTimeout(resolve, 500));
      return _mockPromotionPreview(payload);
    }
    return request<PromotionPreview>('/api/v1/personal-assets/promotions/preview', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async getPersonalAssets(workspaceId: string): Promise<PersonalAssetRecord[]> {
    return request<PersonalAssetRecord[]>(
      `/api/v1/personal-assets?workspace_id=${encodeURIComponent(workspaceId)}`
    );
  },

  async getPersonalAssetTemplates(dataSourceId: string, environment = 'default'): Promise<PersonalAssetTemplate[]> {
    return request<PersonalAssetTemplate[]>(
      `/api/v1/personal-assets/templates?data_source_id=${encodeURIComponent(dataSourceId)}&environment=${encodeURIComponent(environment)}`
    );
  },

  async recordPersonalAssetProvenance(payload: {
    asset_type: AssetType;
    local_code: string;
    name: string;
    data_source_id?: string;
    template_asset_ref?: AssetRef | null;
    dependency_refs?: AssetRef[];
  }): Promise<PersonalAssetRecord> {
    return request<PersonalAssetRecord>('/api/v1/personal-assets/provenance', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async confirmPromotion(payload: ConfirmPromotionRequest): Promise<PromotionRecord> {
    if (import.meta.env.VITE_MOCK_ENTERPRISE_PACK === 'true') {
      await new Promise(resolve => setTimeout(resolve, 800));
      return _mockConfirmPromotion(payload);
    }
    return request<PromotionRecord>('/api/v1/personal-assets/promotions/confirm', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async getPromotionStatus(promotionId: string): Promise<PromotionRecord> {
    if (import.meta.env.VITE_MOCK_ENTERPRISE_PACK === 'true') {
      await new Promise(resolve => setTimeout(resolve, 300));
      return _mockGetPromotionStatus(promotionId);
    }
    return request<PromotionRecord>(`/api/v1/personal-assets/promotions/${promotionId}`);
  },

  async parseQuery(payload: { user_id: string; text: string }) {
    return request<QueryIntent>('/api/v1/query/parse', {
      method: 'POST',
      body: JSON.stringify({
        question: payload.text,
        actor: { user_id: payload.user_id },
      }),
    });
  },
  async executeQuery(payload: QueryRequest) {
    return request<QueryResult>('/api/v1/query/execute', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  async getQuery(queryId: string) {
    return request<QueryResult>(`/api/v1/query/${queryId}`);
  },
  async getLineage(queryId: string) {
    return request<Lineage>(`/api/v1/query/${queryId}/lineage`);
  },

  // Reports
  async getReports() {
    return request<ReportDefinition[]>('/api/v1/reports');
  },
  async createReport(payload: ReportDefinition, userId = 'admin') {
    return request<ReportDefinition>(`/api/v1/reports?user_id=${encodeURIComponent(userId)}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  async updateReport(reportId: string, payload: Partial<ReportDefinition> & { user_id: string; role_ids?: string[] }) {
    return request<ReportDefinition>(`/api/v1/reports/${reportId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },
  async updateReportVisibility(reportId: string, payload: { visibility: 'private' | 'shared'; user_id: string }) {
    return request<ReportDefinition>(`/api/v1/reports/${reportId}/visibility`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },
  async copyReport(reportId: string, payload: { user_id: string }) {
    return request<ReportDefinition>(`/api/v1/reports/${reportId}/copy`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  async deleteReport(reportId: string, payload: { user_id: string; role_ids?: string[] }) {
    return request<{ status: string; report_id: string }>(`/api/v1/reports/${reportId}`, {
      method: 'DELETE',
      body: JSON.stringify(payload),
    });
  },
  async generateReport(reportId: string, payload: {
    user_id: string;
    output_type: 'pptx' | 'docx' | 'pdf' | 'html';
    title?: string;
    content?: string;
    bound_metric_codes?: string[];
    bound_skill_ids?: string[];
  }) {
    return request<GeneratedFileRecord>(`/api/v1/reports/${reportId}/generate`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  async executeReport(reportSkillId: string, payload: Record<string, unknown>) {
    return request<QueryResult>(`/api/v1/reports/${reportSkillId}/execute`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async createScheduledJob(payload: {
    user_id: string;
    entity_type: string;
    entity_id: string;
    schedule_text: string;
    payload?: Record<string, unknown>;
  }) {
    return request<ScheduledJobRecord>('/api/v1/jobs', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  async stopScheduledJob(jobId: string, payload: { user_id: string }) {
    return request<ScheduledJobRecord>(`/api/v1/jobs/${jobId}/stop`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  // --- Domain Pack Deployment & Mounting API ---
  async getAdminPacks(): Promise<PackWithDeployments[]> {
    if (import.meta.env.VITE_MOCK_MOUNTING === 'true') {
      const store = loadMockStore() || getOrInitMockStore();
      return store.packs;
    }
    return request<PackWithDeployments[]>('/api/v1/admin/packs');
  },

  async previewPackImport(file: File): Promise<PackImportPreview> {
    const body = new FormData();
    body.append('file', file);
    return request<PackImportPreview>('/api/v1/admin/packs/import/preview', {
      method: 'POST',
      body,
    });
  },

  async importPack(file: File): Promise<PackImportPreview> {
    const body = new FormData();
    body.append('file', file);
    return request<PackImportPreview>('/api/v1/admin/packs/import', {
      method: 'POST',
      body,
    });
  },

  async getPackContent(packId: string): Promise<OfficialPackContent> {
    return request<OfficialPackContent>(`/api/v1/admin/packs/${encodeURIComponent(packId)}/content`);
  },

  // Pack-aware candidate scope for a data source that currently has zero
  // semantic spaces — used to let the admin preview/confirm the table set
  // before an implicit space is auto-created by createDeployment().
  async recommendScope(packId: string, dataSourceId: string): Promise<ScopeCandidateTable[]> {
    if (import.meta.env.VITE_MOCK_MOUNTING === 'true') {
      return [
        {
          table_name: 'shipment_order',
          tier: 'recommended',
          matched_field_ids: [`${packId}.shipment.order_id`, `${packId}.shipment.carrier_id`],
          reason: '表结构与字段命名与领域包中的「运单」标准字段高度匹配，存在强证据。'
        },
        {
          table_name: 'warehouse_inventory_snapshot',
          tier: 'ambiguous',
          matched_field_ids: [],
          reason: '通用表扫描认为该表可能与业务相关，但当前领域包未在其中找到匹配证据，建议人工确认。'
        },
        {
          table_name: 'audit_log',
          tier: 'excluded',
          matched_field_ids: [],
          reason: '系统日志表，与业务领域包无关，已自动排除。'
        }
      ];
    }
    const params = new URLSearchParams({ pack_id: packId, data_source_id: dataSourceId });
    return request<ScopeCandidateTable[]>(`/api/v1/admin/deployments/recommend-scope?${params.toString()}`);
  },

  async createDeployment(payload: CreateDeploymentRequest): Promise<CreateDeploymentResponse> {
    if (import.meta.env.VITE_MOCK_MOUNTING === 'true') {
      const store = loadMockStore() || getOrInitMockStore();
      const env = payload.environment || 'production';
      const spacesKey = (payload.semantic_space_ids || []).sort().join('_');
      const depId = `dep_${payload.pack_id}_${payload.data_source_id}_${env}_${spacesKey || 'all'}`.toLowerCase();

      let deployment = store.deployments[depId];
      if (!deployment) {
        deployment = {
          deployment_id: depId,
          pack_id: payload.pack_id,
          pack_version: '1.0.0',
          data_source_id: payload.data_source_id,
          environment: env,
          license_ref: `LIC-${payload.pack_id.toUpperCase()}-2026-MOCK`,
          validation_status: 'unvalidated',
          coverage: 0.60,
          blocking_reasons: ['待确认字段映射未确认', '未执行冒烟测试或测试失败'],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          semantic_space_ids: payload.semantic_space_ids || [],
          is_active: false,
          runtime_asset_count: 0,
          exclusion_reasons: ['未激活']
        };
        store.deployments[depId] = deployment;

        // Add to pack listing
        const pack = store.packs.find((p: PackWithDeployments) => p.pack_id === payload.pack_id);
        if (pack) {
          if (!pack.deployments.some((d: DeploymentListItem) => d.deployment_id === depId)) {
            pack.deployments.push({
              deployment_id: depId,
              data_source_id: payload.data_source_id,
              validation_status: 'unvalidated',
              coverage: 0.60,
              semantic_space_ids: payload.semantic_space_ids || [],
              pack_version: '1.0.0',
              environment: env,
              is_active: false,
              runtime_asset_count: 0,
              exclusion_reasons: ['未激活']
            });
          }
        }

        // Initialize pending mappings if they don't exist
        if (!store.pendingMappings[depId]) {
          store.pendingMappings[depId] = [
            {
              mapping_request_id: 'req_carrier_id',
              standard_field_id: `${payload.pack_id}.shipment.carrier_id`,
              business_name: '承运商 ID',
              candidates: [
                {
                  physical_table: 'carrier_info',
                  physical_column: 'carrier_code',
                  confidence: 0.95,
                  reason: '字段名称完全匹配，物理主键类型相似，语义高相似度。',
                  evidence: {
                    name_similarity: 0.95,
                    business_name_similarity: 0.92,
                    type_compatible: true,
                    comment_evidence: '承运商系统唯一代码，通常为大写英文字母。',
                    sample_values: ['SF_EXPRESS', 'JD_LOGISTICS', 'YTO_EXPRESS'],
                    conflicting_candidates: ['carrier_info.carrier_name'],
                    affected_metric_count: 5,
                    data_quality_flags: ['无空值', '已建主键索引']
                  }
                },
                {
                  physical_table: 'carrier_info',
                  physical_column: 'carrier_name',
                  confidence: 0.45,
                  reason: '字段名称部分匹配，可能为承运商名称文本。',
                  evidence: {
                    name_similarity: 0.45,
                    business_name_similarity: 0.50,
                    type_compatible: true,
                    comment_evidence: '承运商中文简称，如顺丰、京东等。',
                    sample_values: ['顺丰速运', '京东物流', '圆通速递'],
                    conflicting_candidates: ['carrier_info.carrier_code'],
                    affected_metric_count: 0,
                    data_quality_flags: ['包含中文文本']
                  }
                }
              ]
            },
            {
              mapping_request_id: 'req_delivery_status',
              standard_field_id: `${payload.pack_id}.shipment.delivery_status`,
              business_name: '配送状态',
              candidates: [
                {
                  physical_table: 'delivery_order',
                  physical_column: 'status_code',
                  confidence: 0.88,
                  reason: '字段注释包含状态枚举映射信息，语义相似。',
                  evidence: {
                    name_similarity: 0.35,
                    business_name_similarity: 0.88,
                    type_compatible: true,
                    comment_evidence: '运单配送状态(10:待发货, 20:在途, 30:已签收)',
                    sample_values: ['10', '20', '30'],
                    conflicting_candidates: ['delivery_order.ref_status'],
                    affected_metric_count: 3,
                    data_quality_flags: ['已建索引']
                  }
                },
                {
                  physical_table: 'delivery_order',
                  physical_column: 'ref_status',
                  confidence: 0.60,
                  reason: '字段带有 status 后缀，表示某种参考状态。',
                  evidence: {
                    name_similarity: 0.40,
                    business_name_similarity: 0.50,
                    type_compatible: true,
                    comment_evidence: '财务或业务外部系统的参考状态',
                    sample_values: ['A', 'B', 'C'],
                    conflicting_candidates: ['delivery_order.status_code'],
                    affected_metric_count: 1,
                    data_quality_flags: []
                  }
                }
              ]
            },
            {
              mapping_request_id: 'req_cost_amount',
              standard_field_id: `${payload.pack_id}.shipment.cost_amount`,
              business_name: '运费金额',
              candidates: [
                {
                  physical_table: 'billing_detail',
                  physical_column: 'freight_charge',
                  confidence: 0.92,
                  reason: '词义高相似度，且字段数据类型完全兼容。',
                  evidence: {
                    name_similarity: 0.85,
                    business_name_similarity: 0.90,
                    type_compatible: true,
                    comment_evidence: '该运单实际支付给承运商的运费金额（单位：元）',
                    sample_values: ['1200.50', '340.00', '0.00'],
                    conflicting_candidates: [],
                    affected_metric_count: 4,
                    data_quality_flags: []
                  }
                }
              ]
            }
          ];
        }

        if (!store.smokeTests[depId]) {
          store.smokeTests[depId] = {
            pack_id: payload.pack_id,
            data_source_id: payload.data_source_id,
            deployment_id: depId,
            metrics: [
              { metric_code: `${payload.pack_id}.metrics.total_shipments`, name: '总发货单数', compiled: true, executed: true, elapsed_ms: 120, error: null },
              { metric_code: `${payload.pack_id}.metrics.on_time_delivery_rate`, name: '准时送达率', compiled: true, executed: true, elapsed_ms: 240, error: null },
              { metric_code: `${payload.pack_id}.metrics.total_freight_cost`, name: '总运费', compiled: true, executed: true, elapsed_ms: 180, error: null },
              { metric_code: `${payload.pack_id}.metrics.carrier_fulfillment_rate`, name: '承运商履约率', compiled: false, executed: false, elapsed_ms: 0, error: 'SQL 编译错误: 物理字段 carrier_id 未映射或类型不匹配' }
            ],
            all_passed: false,
            tested_at: null
          };
        }

        saveMockStore(store);
      }

      return {
        deployment,
        auto_mapped_count: 12,
        pending: store.pendingMappings[depId],
        errors: [],
        auto_created_semantic_space_id: null
      };
    }
    return request<CreateDeploymentResponse>('/api/v1/admin/deployments', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
  },

  async getPendingMappings(deploymentId: string): Promise<PendingMapping[]> {
    if (import.meta.env.VITE_MOCK_MOUNTING === 'true') {
      const store = loadMockStore() || getOrInitMockStore();
      return store.pendingMappings[deploymentId] || [];
    }
    return request<PendingMapping[]>(`/api/v1/admin/deployments/${deploymentId}/pending`);
  },

  async prepareMappingChange(deploymentId: string, standardFieldId: string): Promise<PendingMapping> {
    return request<PendingMapping>(
      `/api/v1/admin/deployments/${deploymentId}/mappings/${standardFieldId}/remap`,
      { method: 'POST' },
    );
  },

  async confirmMapping(deploymentId: string, payload: ConfirmationRequest): Promise<{ success: boolean }> {
    if (import.meta.env.VITE_MOCK_MOUNTING === 'true') {
      const store = loadMockStore() || getOrInitMockStore();
      const pendings = store.pendingMappings[deploymentId] || [];
      const updatedPendings = pendings.filter((p: any) => p.standard_field_id !== payload.standard_field_id);
      store.pendingMappings[deploymentId] = updatedPendings;

      // Update deployment coverage & status
      const deployment = store.deployments[deploymentId];
      if (deployment) {
        const totalPending = 3; // Initial mock pending count
        const completedCount = totalPending - updatedPendings.length;
        const baseCoverage = 0.60;
        deployment.coverage = Number((baseCoverage + (0.40 * (completedCount / totalPending))).toFixed(2));

        // Remove 'req_carrier_id' check from smoke test errors if confirmed
        if (payload.standard_field_id.endsWith('carrier_id')) {
          const test = store.smokeTests[deploymentId];
          if (test) {
            const metric = test.metrics.find((m: any) => m.metric_code.endsWith('carrier_fulfillment_rate'));
            if (metric) {
              metric.compiled = true;
              metric.executed = true;
              metric.error = null;
              metric.elapsed_ms = 190;
            }
          }
        }

        // Check if all are mapped
        const requiredRemaining = updatedPendings.filter((p: PendingMapping) => p.standard_field_id.includes('carrier_id') || p.standard_field_id.includes('delivery_status')).length;
        if (requiredRemaining === 0) {
          deployment.blocking_reasons = deployment.blocking_reasons.filter((r: string) => !r.includes('字段未映射'));
        }

        // Recalculate exclusion reasons
        if (!deployment.is_active) {
          deployment.exclusion_reasons = ['未激活'];
          deployment.runtime_asset_count = 0;
        } else if (deployment.validation_status !== 'ready') {
          deployment.exclusion_reasons = ['冒烟测试未通过'];
          deployment.runtime_asset_count = 0;
        } else {
          deployment.exclusion_reasons = [];
          deployment.runtime_asset_count = 8;
        }

        deployment.updated_at = new Date().toISOString();

        // Update pack deployments list
        const pack = store.packs.find((p: PackWithDeployments) => p.pack_id === deployment.pack_id);
        if (pack) {
          const dItem = pack.deployments.find((d: DeploymentListItem) => d.deployment_id === deploymentId);
          if (dItem) {
            dItem.coverage = deployment.coverage;
            dItem.validation_status = deployment.validation_status;
            dItem.is_active = deployment.is_active;
            dItem.runtime_asset_count = deployment.runtime_asset_count;
            dItem.exclusion_reasons = deployment.exclusion_reasons;
          }
        }
      }

      saveMockStore(store);
      return { success: true };
    }
    return request<{ success: boolean }>(`/api/v1/admin/deployments/${deploymentId}/confirm`, {
      method: 'POST',
      body: JSON.stringify(payload)
    });
  },

  async runSmokeTest(deploymentId: string): Promise<SmokeTestResult> {
    if (import.meta.env.VITE_MOCK_MOUNTING === 'true') {
      const store = loadMockStore() || getOrInitMockStore();
      const test = store.smokeTests[deploymentId];
      const deployment = store.deployments[deploymentId];
      const pendings = store.pendingMappings[deploymentId] || [];

      if (test) {
        test.tested_at = new Date().toISOString();

        // Check if carrier_id is still pending
        const carrierPending = pendings.some((p: any) => p.standard_field_id.endsWith('carrier_id'));

        if (carrierPending) {
          const metric = test.metrics.find((m: any) => m.metric_code.endsWith('carrier_fulfillment_rate'));
          if (metric) {
            metric.compiled = false;
            metric.executed = false;
            metric.error = 'SQL 编译错误: 物理字段 carrier_id 未映射或类型不匹配';
            metric.elapsed_ms = 0;
          }
          test.all_passed = false;
        } else {
          const metric = test.metrics.find((m: any) => m.metric_code.endsWith('carrier_fulfillment_rate'));
          if (metric) {
            metric.compiled = true;
            metric.executed = true;
            metric.error = null;
            metric.elapsed_ms = 195;
          }
          test.all_passed = true;
        }

        if (deployment) {
          if (test.all_passed && pendings.length === 0) {
            deployment.validation_status = 'ready';
            deployment.blocking_reasons = [];
          } else {
            deployment.validation_status = 'failed';
            const reasons = [];
            if (pendings.length > 0) reasons.push(`${pendings.length} 个字段未确认映射`);
            if (!test.all_passed) reasons.push('冒烟测试有指标执行失败');
            deployment.blocking_reasons = reasons;
          }

          // Recalculate exclusion reasons
          if (!deployment.is_active) {
            deployment.exclusion_reasons = ['未激活'];
            deployment.runtime_asset_count = 0;
          } else if (deployment.validation_status !== 'ready') {
            deployment.exclusion_reasons = ['冒烟测试未通过'];
            deployment.runtime_asset_count = 0;
          } else {
            deployment.exclusion_reasons = [];
            deployment.runtime_asset_count = 8;
          }

          const pack = store.packs.find((p: PackWithDeployments) => p.pack_id === deployment.pack_id);
          if (pack) {
            const dItem = pack.deployments.find((d: DeploymentListItem) => d.deployment_id === deploymentId);
            if (dItem) {
              dItem.validation_status = deployment.validation_status;
              dItem.is_active = deployment.is_active;
              dItem.runtime_asset_count = deployment.runtime_asset_count;
              dItem.exclusion_reasons = deployment.exclusion_reasons;
            }
          }
        }

        saveMockStore(store);
        return test;
      }
    }
    return request<SmokeTestResult>(`/api/v1/admin/deployments/${deploymentId}/smoke-test`, {
      method: 'POST'
    });
  },

  async getMountStatus(deploymentId: string): Promise<MountStatus> {
    if (import.meta.env.VITE_MOCK_MOUNTING === 'true') {
      const store = loadMockStore() || getOrInitMockStore();
      const deployment = store.deployments[deploymentId];
      const pendings = store.pendingMappings[deploymentId] || [];
      const test = store.smokeTests[deploymentId];

      if (deployment) {
        return {
          pack_id: deployment.pack_id,
          data_source_id: deployment.data_source_id,
          deployment_id: deploymentId,
          total_standard_fields: 15,
          mapped_fields: 15 - pendings.length,
          pending_fields: pendings.length,
          is_ready: deployment.validation_status === 'ready',
          validation_status: deployment.validation_status,
          coverage: deployment.coverage,
          blocking_reasons: deployment.blocking_reasons,
          is_active: !!deployment.is_active,
          activated_at: deployment.activated_at || null,
          activated_by: deployment.activated_by || null,
          smoke_test: test,
          semantic_space_ids: deployment.semantic_space_ids || [],
          environment: deployment.environment || 'production',
          runtime_asset_count: deployment.runtime_asset_count || 0,
          exclusion_reasons: deployment.exclusion_reasons || []
        };
      }
    }
    return request<MountStatus>(`/api/v1/admin/deployments/${deploymentId}/status`);
  },

  async activateDeployment(deploymentId: string): Promise<DeploymentInstance> {
    if (import.meta.env.VITE_MOCK_MOUNTING === 'true') {
      const store = loadMockStore() || getOrInitMockStore();
      const deployment = store.deployments[deploymentId];
      if (!deployment) {
        throw { code: 'NOT_FOUND', message: `Deployment '${deploymentId}' not found.` } as ApiError;
      }
      if (deployment.validation_status !== 'ready') {
        throw {
          code: 'INVALID_REQUEST',
          message: 'Deployment is not ready for activation.'
        } as ApiError;
      }
      deployment.is_active = true;
      deployment.activated_at = new Date().toISOString();
      deployment.activated_by = 'mock-admin';
      deployment.runtime_asset_count = 8;
      deployment.exclusion_reasons = [];

      // Update pack deployments list
      const pack = store.packs.find((p: PackWithDeployments) => p.pack_id === deployment.pack_id);
      if (pack) {
        const dItem = pack.deployments.find((d: DeploymentListItem) => d.deployment_id === deploymentId);
        if (dItem) {
          dItem.is_active = true;
          dItem.runtime_asset_count = 8;
          dItem.exclusion_reasons = [];
        }
      }

      saveMockStore(store);
      return deployment;
    }
    return request<DeploymentInstance>(`/api/v1/admin/deployments/${deploymentId}/activate`, {
      method: 'POST'
    });
  },

  async deactivateDeployment(deploymentId: string): Promise<DeploymentInstance> {
    if (import.meta.env.VITE_MOCK_MOUNTING === 'true') {
      const store = loadMockStore() || getOrInitMockStore();
      const deployment = store.deployments[deploymentId];
      if (!deployment) {
        throw { code: 'NOT_FOUND', message: `Deployment '${deploymentId}' not found.` } as ApiError;
      }
      deployment.is_active = false;
      deployment.activated_at = null;
      deployment.activated_by = null;
      deployment.runtime_asset_count = 0;
      deployment.exclusion_reasons = ['未激活'];

      // Update pack deployments list
      const pack = store.packs.find((p: PackWithDeployments) => p.pack_id === deployment.pack_id);
      if (pack) {
        const dItem = pack.deployments.find((d: DeploymentListItem) => d.deployment_id === deploymentId);
        if (dItem) {
          dItem.is_active = false;
          dItem.runtime_asset_count = 0;
          dItem.exclusion_reasons = ['未激活'];
        }
      }

      saveMockStore(store);
      return deployment;
    }
    return request<DeploymentInstance>(`/api/v1/admin/deployments/${deploymentId}/deactivate`, {
      method: 'POST'
    });
  },

  async getRuntimeAssetProjection(params: {
    data_source_id: string;
    environment?: string;
    workspace_id?: string;
  }): Promise<RuntimeAssetProjection> {
    if (import.meta.env.VITE_MOCK_MOUNTING === 'true') {
      const store = loadMockStore() || getOrInitMockStore();
      const resolved: ResolvedRuntimeAsset[] = [];
      const excluded: ExcludedRuntimeBinding[] = [];
      const filterEnv = params.environment || 'default';
      const deploymentsProj: Array<{
        deployment_id: string;
        source_type: AssetSourceType;
        source_id: string;
        effective_asset_count: number;
        excluded: boolean;
        exclusion_reason: RuntimeVisibilityReason | null;
      }> = [];

      (Object.entries(store.deployments || {}) as Array<[string, DeploymentInstance]>).forEach(([depId, dep]) => {
        if (dep.data_source_id !== params.data_source_id) return;
        if ((dep.environment || 'default') !== filterEnv) return;

        const isReady = dep.validation_status === 'ready';
        const isActive = !!dep.is_active;
        const isVisible = isActive && isReady;

        const assetCount = isVisible ? (dep.pack_id === 'tms' ? 8 : 4) : 0;
        const exclusionReason: RuntimeVisibilityReason | null = !isReady
          ? 'deployment_unvalidated'
          : !isActive
          ? 'deployment_inactive'
          : null;

        deploymentsProj.push({
          deployment_id: depId,
          source_type: 'official_pack',
          source_id: dep.pack_id || 'tms',
          effective_asset_count: assetCount,
          excluded: !isVisible,
          exclusion_reason: exclusionReason
        });

        if (isVisible) {
          for (let i = 0; i < assetCount; i++) {
            resolved.push({
              asset_ref: {
                asset: {
                  source_type: 'official_pack',
                  source_id: dep.pack_id || 'tms',
                  asset_type: 'metric',
                  local_code: `mock_asset_${i}`,
                  asset_id: `asset:v1:official_pack:${dep.pack_id || 'tms'}:metric:mock_asset_${i}`
                },
                version: dep.pack_version || '1.0.0'
              },
              definition: {
                metric_code: `mock_asset_${i}`,
                name: `Mock asset ${i + 1}`,
                definition: 'Mock runtime projection metric',
                visibility: 'official',
                formula: { expression: 'select 1 from dual', filters: [] },
                data_source_id: params.data_source_id,
                owner: 'official',
                version: dep.pack_version || '1.0.0',
                asset_ref: {
                  asset: {
                    source_type: 'official_pack',
                    source_id: dep.pack_id || 'tms',
                    asset_type: 'metric',
                    local_code: `mock_asset_${i}`,
                    asset_id: `asset:v1:official_pack:${dep.pack_id || 'tms'}:metric:mock_asset_${i}`
                  },
                  version: dep.pack_version || '1.0.0'
                }
              },
              data_source_id: params.data_source_id,
              environment: filterEnv,
              semantic_space_ids: dep.semantic_space_ids || [],
              deployment_id: depId,
              visibility_reason: 'active_deployment'
            });
          }
        } else if (exclusionReason) {
          excluded.push({
            source_type: 'official_pack',
            source_id: dep.pack_id || 'tms',
            reason: exclusionReason,
            deployment_id: depId,
            detail: !isReady ? '待确认字段映射未确认' : '未激活'
          });
        }
      });

      return {
        resolved,
        excluded,
        context: {
          user_id: 'mock-user',
          data_source_id: params.data_source_id,
          environment: filterEnv,
          workspace_id: params.workspace_id || null
        },
        effective_asset_count: resolved.length,
        deployments: deploymentsProj
      };
    }

    const queryParams: Record<string, string> = { data_source_id: params.data_source_id };
    if (params.environment) {
      queryParams.environment = params.environment;
    }
    if (params.workspace_id) {
      queryParams.workspace_id = params.workspace_id;
    }
    return request<RuntimeAssetProjection>(
      `/api/v1/admin/deployments/runtime-projection?${new URLSearchParams(queryParams).toString()}`
    );
  }
};

// --- Type Exports and Helpers for Mounting API ---
export interface MappingEvidence {
  name_similarity?: number | null;
  business_name_similarity?: number | null;
  type_compatible?: boolean | null;
  comment_evidence?: string | null;
  sample_values?: string[];
  conflicting_candidates?: string[];
  affected_metric_count?: number | null;
  data_quality_flags?: string[];
}

export interface CandidateMapping {
  physical_table: string;
  physical_column: string;
  confidence: number;
  reason: string;
  evidence: MappingEvidence;
}

export interface PendingMapping {
  mapping_request_id: string;
  standard_field_id: string;
  business_name: string;
  candidates: CandidateMapping[];
  outside_scope_candidates: CandidateMapping[];
}

export interface FieldMapping {
  mapping_id: string;
  pack_id: string;
  standard_field_id: string;
  data_source_id: string;
  physical_table: string;
  physical_column: string;
  transform?: string | null;
  confidence: number;
  source: 'deterministic' | 'auto' | 'llm' | 'manual';
  status: 'active' | 'inactive';
  version: string;
  deployment_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  created_by?: string | null;
  confirmed_by?: string | null;
  confirmed_at?: string | null;
}

export type ValidationStatus = 'unvalidated' | 'incomplete' | 'failed' | 'ready';

export interface DeploymentInstance {
  deployment_id: string;
  pack_id: string;
  pack_version: string;
  data_source_id: string;
  license_ref?: string | null;
  validation_status: ValidationStatus;
  coverage: number;
  blocking_reasons: string[];
  // Activation is an independent dimension from validation_status: a
  // deployment can be 'ready' without being live. An admin must explicitly
  // activate it before it goes live (split publish/deploy/validate/activate
  // per .design/asset_semantic_space_harness_operating_model.md §9/§11).
  is_active: boolean;
  activated_at?: string | null;
  activated_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  semantic_space_ids?: string[];
  // Additive contract fields for runtime-asset-projection
  environment?: string; // 'test' | 'production'
  runtime_asset_count?: number;
  exclusion_reasons?: string[];
}

export interface CreateDeploymentRequest {
  pack_id: string;
  data_source_id: string;
  confirmed_by?: string | null;
  semantic_space_ids?: string[];
  // Only consulted when semantic_space_ids is empty AND the data source has
  // zero existing semantic spaces (i.e. an implicit space is about to be
  // auto-created). When provided, the backend uses exactly this table list
  // (filtered to valid catalog tables) instead of computing the pack-aware
  // recommendation itself. Lets the admin confirm/adjust the "ambiguous"
  // tier from GET .../recommend-scope before the space is created.
  implicit_space_tables?: string[] | null;
  environment?: string; // 'test' | 'production'
}

// Response item for GET /api/v1/admin/deployments/recommend-scope — the
// pack-aware candidate scope shown to the admin before an implicit semantic
// space is auto-created for a data source with zero existing spaces.
export interface ScopeCandidateTable {
  table_name: string;
  tier: 'recommended' | 'ambiguous' | 'excluded';
  matched_field_ids: string[];
  reason: string;
}

export interface CreateDeploymentResponse {
  deployment: DeploymentInstance;
  auto_mapped_count: number;
  pending: PendingMapping[];
  errors: string[];
  // Set when the request omitted semantic_space_ids and the backend had to
  // resolve/create one implicitly (P1: pack-first mounting shouldn't require
  // a manual semantic-space-creation step first). Null when the caller
  // explicitly chose spaces or exactly one existing space was reused.
  auto_created_semantic_space_id: string | null;
}

export interface DeploymentListItem {
  deployment_id: string;
  data_source_id: string;
  validation_status: ValidationStatus;
  coverage: number;
  is_active: boolean;
  semantic_space_ids?: string[];
  semantic_space_names?: string[];
  unavailable_semantic_space_ids?: string[];
  binding_status?: 'available' | 'unavailable';
  pack_version?: string;
  environment?: string;
  runtime_asset_count?: number;
  exclusion_reasons?: string[];
}

export interface PackWithDeployments {
  pack_id: string;
  pack_version: string;
  name: string;
  description: string;
  author: string;
  tags: string[];
  distribution_source: 'built_in' | 'imported';
  standard_field_count: number;
  metric_count: number;
  skill_count: number;
  report_count: number;
  deployments: DeploymentListItem[];
}

export interface PackImportPreview {
  filename: string;
  pack_id: string;
  name: string;
  version: string;
  description: string;
  author: string;
  tags: string[];
  standard_field_count: number;
  metric_count: number;
  skill_count: number;
  report_count: number;
  can_import: boolean;
  conflict: string | null;
  warnings: string[];
}

export interface PackStandardFieldView {
  field_id: string;
  business_name: string;
  data_type: string;
  description?: string | null;
  enum_values?: string[];
  required: boolean;
}

export interface OfficialPackContent {
  pack_id: string;
  name: string;
  version: string;
  description: string;
  standard_fields: PackStandardFieldView[];
  fields: Array<Record<string, unknown>>;
  metrics: Array<Record<string, unknown>>;
  skills: Array<Record<string, unknown>>;
  reports: Array<Record<string, unknown>>;
}

export interface ConfirmationRequest {
  pack_id: string;
  data_source_id: string;
  standard_field_id: string;
  mapping_request_id: string;
  chosen_candidate_index?: number;
  candidate_scope?: 'bound_space' | 'scanned_catalog';
  physical_table?: string;
  physical_column?: string;
  confirmed_by?: string | null;
}

export interface SmokeTestMetric {
  metric_code: string;
  name: string;
  compiled: boolean;
  executed: boolean;
  elapsed_ms?: number | null;
  row_count?: number | null;
  error?: string | null;
}

export interface SmokeTestResult {
  pack_id: string;
  data_source_id: string;
  deployment_id?: string | null;
  metrics: SmokeTestMetric[];
  all_passed: boolean;
  tested_at?: string | null;
}

export interface MountStatus {
  pack_id: string;
  pack_version?: string;
  data_source_id: string;
  deployment_id?: string | null;
  total_standard_fields: number;
  mapped_fields: number;
  pending_fields: number;
  is_ready: boolean;
  validation_status: ValidationStatus;
  coverage: number;
  blocking_reasons: string[];
  is_active: boolean;
  activated_at?: string | null;
  activated_by?: string | null;
  smoke_test?: SmokeTestResult | null;
  semantic_space_ids?: string[];
  semantic_space_names?: string[];
  unavailable_semantic_space_ids?: string[];
  binding_status?: 'available' | 'unavailable';
  environment?: string;
  runtime_asset_count?: number;
  exclusion_reasons?: string[];
  standard_fields?: PackStandardFieldView[];
  mappings?: FieldMapping[];
}

export type RuntimeVisibilityReason =
  | 'active_deployment'
  | 'personal_workspace_binding'
  | 'deployment_inactive'
  | 'deployment_unvalidated'
  | 'version_not_deployed'
  | 'foreign_workspace'
  | 'no_workspace_binding';

export interface ResolvedRuntimeAsset {
  asset_ref: AssetRef;
  definition: MetricDefinition | SkillDefinition | ReportDefinition;
  data_source_id: string;
  environment: string;
  semantic_space_ids: string[];
  deployment_id?: string | null;
  workspace_id?: string | null;
  visibility_reason: RuntimeVisibilityReason;
}

export interface ExcludedRuntimeBinding {
  source_type: AssetSourceType;
  source_id: string;
  reason: RuntimeVisibilityReason;
  deployment_id?: string | null;
  detail?: string | null;
}

export interface RuntimeAssetProjection {
  resolved: ResolvedRuntimeAsset[];
  excluded: ExcludedRuntimeBinding[];
  context?: {
    user_id: string;
    data_source_id: string;
    environment: string;
    workspace_id?: string | null;
  };
  effective_asset_count?: number;
  deployments?: Array<{
    deployment_id: string;
    source_type: AssetSourceType;
    source_id: string;
    effective_asset_count: number;
    excluded: boolean;
    exclusion_reason: RuntimeVisibilityReason | null;
  }>;
}

const MOCK_STORAGE_KEY = 'sqbi.mock_mounting_store';

function loadMockStore(): any {
  if (typeof window === 'undefined') return null;
  const stored = window.localStorage.getItem(MOCK_STORAGE_KEY);
  if (stored) {
    try {
      return JSON.parse(stored);
    } catch {
      return null;
    }
  }
  return null;
}

function saveMockStore(state: any): void {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(MOCK_STORAGE_KEY, JSON.stringify(state));
  }
}

function getOrInitMockStore(): any {
  if (typeof window === 'undefined') {
    return { packs: [], deployments: {}, pendingMappings: {}, smokeTests: {} };
  }

  let store = loadMockStore();
  if (!store) {
    store = {
      packs: [
        {
          pack_id: 'tms',
          pack_version: '1.0.0',
          name: 'TMS 运输管理系统领域包',
          standard_field_count: 15,
          metric_count: 8,
          deployments: [
            {
              deployment_id: 'dep_tms_prod',
              data_source_id: 'oracle_tms',
              pack_version: '1.0.0',
              environment: 'production',
              validation_status: 'unvalidated',
              coverage: 0.60,
              semantic_space_ids: ['space_finance'],
              is_active: false,
              runtime_asset_count: 0,
              exclusion_reasons: ['未激活']
            },
            {
              deployment_id: 'dep_tms_test',
              data_source_id: 'oracle_tms',
              pack_version: '1.0.0',
              environment: 'test',
              validation_status: 'ready',
              coverage: 1.00,
              semantic_space_ids: ['space_scheduling'],
              is_active: true,
              runtime_asset_count: 8,
              exclusion_reasons: []
            }
          ]
        },
        {
          pack_id: 'wms',
          pack_version: '1.2.0',
          name: 'WMS 智能仓储系统领域包',
          standard_field_count: 20,
          metric_count: 12,
          deployments: []
        }
      ],
      deployments: {
        'dep_tms_prod': {
          deployment_id: 'dep_tms_prod',
          pack_id: 'tms',
          pack_version: '1.0.0',
          data_source_id: 'oracle_tms',
          environment: 'production',
          license_ref: 'LIC-TMS-2026-009A',
          validation_status: 'unvalidated',
          coverage: 0.60,
          blocking_reasons: ['待确认字段映射未确认', '未执行冒烟测试或测试失败'],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          semantic_space_ids: ['space_finance'],
          is_active: false,
          runtime_asset_count: 0,
          exclusion_reasons: ['未激活']
        },
        'dep_tms_test': {
          deployment_id: 'dep_tms_test',
          pack_id: 'tms',
          pack_version: '1.0.0',
          data_source_id: 'oracle_tms',
          environment: 'test',
          license_ref: 'LIC-TMS-2026-TEST',
          validation_status: 'ready',
          coverage: 1.00,
          blocking_reasons: [],
          created_at: new Date(Date.now() - 86400000).toISOString(),
          updated_at: new Date().toISOString(),
          semantic_space_ids: ['space_scheduling'],
          is_active: true,
          runtime_asset_count: 8,
          exclusion_reasons: []
        }
      },
      pendingMappings: {
        'dep_tms_prod': [
          {
            mapping_request_id: 'req_carrier_id',
            standard_field_id: 'tms.shipment.carrier_id',
            business_name: '承运商 ID',
            candidates: [
              {
                physical_table: 'carrier_info',
                physical_column: 'carrier_code',
                confidence: 0.95,
                reason: '字段名称完全匹配，物理主键类型相似，语义高相似度。',
                evidence: {
                  name_similarity: 0.95,
                  business_name_similarity: 0.92,
                  type_compatible: true,
                  comment_evidence: '承运商系统唯一代码，通常为大写英文字母。',
                  sample_values: ['SF_EXPRESS', 'JD_LOGISTICS', 'YTO_EXPRESS'],
                  conflicting_candidates: ['carrier_info.carrier_name'],
                  affected_metric_count: 5,
                  data_quality_flags: ['无空值', '已建主键索引']
                }
              },
              {
                physical_table: 'carrier_info',
                physical_column: 'carrier_name',
                confidence: 0.45,
                reason: '字段名称部分匹配，可能为承运商名称文本。',
                evidence: {
                  name_similarity: 0.45,
                  business_name_similarity: 0.50,
                  type_compatible: true,
                  comment_evidence: '承运商中文简称，如顺丰、京东等。',
                  sample_values: ['顺丰速运', '京东物流', '圆通速递'],
                  conflicting_candidates: ['carrier_info.carrier_code'],
                  affected_metric_count: 0,
                  data_quality_flags: ['包含中文文本']
                }
              }
            ]
          },
          {
            mapping_request_id: 'req_delivery_status',
            standard_field_id: 'tms.shipment.delivery_status',
            business_name: '配送状态',
            candidates: [
              {
                physical_table: 'delivery_order',
                physical_column: 'status_code',
                confidence: 0.88,
                reason: '字段注释包含状态枚举映射信息，语义相似。',
                evidence: {
                  name_similarity: 0.35,
                  business_name_similarity: 0.88,
                  type_compatible: true,
                  comment_evidence: '运单配送状态(10:待发货, 20:在途, 30:已签收)',
                  sample_values: ['10', '20', '30'],
                  conflicting_candidates: ['delivery_order.ref_status'],
                  affected_metric_count: 3,
                  data_quality_flags: ['已建索引']
                }
              },
              {
                physical_table: 'delivery_order',
                physical_column: 'ref_status',
                confidence: 0.60,
                reason: '字段带有 status 后缀，表示某种参考状态。',
                evidence: {
                  name_similarity: 0.40,
                  business_name_similarity: 0.50,
                  type_compatible: true,
                  comment_evidence: '财务或业务外部系统的参考状态',
                  sample_values: ['A', 'B', 'C'],
                  conflicting_candidates: ['delivery_order.status_code'],
                  affected_metric_count: 1,
                  data_quality_flags: []
                }
              }
            ]
          },
          {
            mapping_request_id: 'req_cost_amount',
            standard_field_id: 'tms.shipment.cost_amount',
            business_name: '运费金额',
            candidates: [
              {
                physical_table: 'billing_detail',
                physical_column: 'freight_charge',
                confidence: 0.92,
                reason: '词义高相似度，且字段数据类型完全兼容。',
                evidence: {
                  name_similarity: 0.85,
                  business_name_similarity: 0.90,
                  type_compatible: true,
                  comment_evidence: '该运单实际支付给承运商的运费金额（单位：元）',
                  sample_values: ['1200.50', '340.00', '0.00'],
                  conflicting_candidates: [],
                  affected_metric_count: 4,
                  data_quality_flags: []
                }
              }
            ]
          }
        ],
        'dep_tms_test': []
      },
      smokeTests: {
        'dep_tms_prod': {
          pack_id: 'tms',
          data_source_id: 'oracle_tms',
          deployment_id: 'dep_tms_prod',
          metrics: [
            { metric_code: 'tms.metrics.total_shipments', name: '总发货单数', compiled: true, executed: true, elapsed_ms: 120, error: null },
            { metric_code: 'tms.metrics.on_time_delivery_rate', name: '准时送达率', compiled: true, executed: true, elapsed_ms: 240, error: null },
            { metric_code: 'tms.metrics.total_freight_cost', name: '总运费', compiled: true, executed: true, elapsed_ms: 180, error: null },
            { metric_code: 'tms.metrics.carrier_fulfillment_rate', name: '承运商履约率', compiled: false, executed: false, elapsed_ms: 0, error: 'SQL 编译错误: 物理字段 carrier_id 未映射或类型不匹配' }
          ],
          all_passed: false,
          tested_at: null
        },
        'dep_tms_test': {
          pack_id: 'tms',
          data_source_id: 'oracle_tms',
          deployment_id: 'dep_tms_test',
          metrics: [
            { metric_code: 'tms.metrics.total_shipments', name: '总发货单数', compiled: true, executed: true, elapsed_ms: 105, error: null },
            { metric_code: 'tms.metrics.on_time_delivery_rate', name: '准时送达率', compiled: true, executed: true, elapsed_ms: 210, error: null },
            { metric_code: 'tms.metrics.total_freight_cost', name: '总运费', compiled: true, executed: true, elapsed_ms: 160, error: null },
            { metric_code: 'tms.metrics.carrier_fulfillment_rate', name: '承运商履约率', compiled: true, executed: true, elapsed_ms: 175, error: null }
          ],
          all_passed: true,
          tested_at: new Date(Date.now() - 3600000).toISOString()
        }
      }
    };
    saveMockStore(store);
  }
  return store;
}

const SEMANTIC_MOCK_KEY = 'sqbi.mock_semantic_store';

function loadSemanticStore(): any {
  if (typeof window === 'undefined') return null;
  const stored = window.localStorage.getItem(SEMANTIC_MOCK_KEY);
  if (stored) {
    try {
      return JSON.parse(stored);
    } catch {
      return null;
    }
  }
  return null;
}

function saveSemanticStore(store: any) {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(SEMANTIC_MOCK_KEY, JSON.stringify(store));
  }
}

function getOrInitSemanticStore(): any {
  let store = loadSemanticStore();
  if (!store) {
    const dsId = 'oracle_tms';
    store = {
      scans: {
        [dsId]: {
          scan_id: 'scan_tms_init',
          data_source_id: dsId,
          snapshot_id: 'snap_tms_1',
          phase: 'done',
          progress_message: '扫描完成',
          table_count: 12,
          included_table_count: 5,
          recommendation_counts: {
            recommended_include: 5,
            possibly_relevant: 4,
            not_relevant: 3
          },
          started_at: new Date(Date.now() - 3600000).toISOString(),
          completed_at: new Date(Date.now() - 3590000).toISOString()
        }
      },
      profiles: {
        [dsId]: {
          data_source_id: dsId,
          snapshot_id: 'snap_tms_1',
          version: 1,
          scan_phase: 'done',
          created_at: new Date(Date.now() - 3600000).toISOString(),
          spaces: [
            {
              space_id: 'space_scheduling',
              snapshot_id: 'snap_tms_1',
              name: '运输规划与调度 (Transport Planning & Scheduling)',
              description: '包含车辆运输调度、配载规划、发车确认以及与配送运单管理相关的实体。',
              accepted: true,
              entities: [
                {
                  entity_id: 'ent_delivery_order',
                  space_id: 'space_scheduling',
                  physical_table: 'delivery_order',
                  business_name: '运单 (Delivery Order)',
                  description: '记录发运单据的生命周期状态、配送终点、对应包裹与客户信息。',
                  recommendation: 'recommended_include',
                  fields: [
                    {
                      field_id: 'field_order_id',
                      entity_id: 'ent_delivery_order',
                      physical_table: 'delivery_order',
                      physical_column: 'order_id',
                      business_name: '运单 ID',
                      description: '运单的全局唯一主键',
                      data_type: 'VARCHAR(64)',
                      origin: 'standard',
                      semantic_role: 'primary_key',
                      synonyms: ['运单号', '发运单号'],
                      confidence: 1.0,
                      evidence: [
                        { source: 'name', detail: '列名精确匹配 order_id' },
                        { source: 'official_pack', detail: '匹配 TMS 领域标准包中的 tms.shipment.carrier_id 映射主键规范' }
                      ],
                      is_candidate: false
                    },
                    {
                      field_id: 'field_status_code',
                      entity_id: 'ent_delivery_order',
                      physical_table: 'delivery_order',
                      physical_column: 'status_code',
                      business_name: '配送状态',
                      description: '运单当前所处的物流配送阶段',
                      data_type: 'INTEGER',
                      origin: 'inferred',
                      semantic_role: 'dimension',
                      synonyms: ['状态码', '配送状态'],
                      confidence: 0.88,
                      evidence: [
                        { source: 'comment', detail: '字段注释: "运单配送状态(10:待发货, 20:在途, 30:已签收)"' },
                        { source: 'sample', detail: '枚举样本值符合 [10, 20, 30] 分布特征' }
                      ],
                      is_candidate: true
                    },
                    {
                      field_id: 'field_ref_status',
                      entity_id: 'ent_delivery_order',
                      physical_table: 'delivery_order',
                      physical_column: 'ref_status',
                      business_name: '参考外部状态',
                      description: '对接第三方财务系统或外部运单系统的非标准参考状态',
                      data_type: 'VARCHAR(32)',
                      origin: 'inferred',
                      semantic_role: 'dimension',
                      synonyms: ['外部状态', '关联状态'],
                      confidence: 0.60,
                      evidence: [
                        { source: 'comment', detail: '财务或业务外部系统的参考状态' }
                      ],
                      is_candidate: true
                    }
                  ]
                },
                {
                  entity_id: 'ent_carrier_info',
                  space_id: 'space_scheduling',
                  physical_table: 'carrier_info',
                  business_name: '承运商信息 (Carrier Info)',
                  description: '记录承运商的基础资质、合作代码、合同编号与简称。',
                  recommendation: 'recommended_include',
                  fields: [
                    {
                      field_id: 'field_carrier_code',
                      entity_id: 'ent_carrier_info',
                      physical_table: 'carrier_info',
                      physical_column: 'carrier_code',
                      business_name: '承运商代码',
                      description: '承运商在物流系统中的唯一英文识别码',
                      data_type: 'VARCHAR(32)',
                      origin: 'inferred',
                      semantic_role: 'dimension',
                      synonyms: ['承运商 Code', '承运商编码'],
                      confidence: 0.95,
                      evidence: [
                        { source: 'name', detail: '列名部分匹配 carrier_code' },
                        { source: 'comment', detail: '承运商系统唯一代码，通常为大写英文字母。' },
                        { source: 'sample', detail: '样本数据分布如: ["SF_EXPRESS", "JD_LOGISTICS", "YTO_EXPRESS"]' }
                      ],
                      is_candidate: true
                    },
                    {
                      field_id: 'field_carrier_name',
                      entity_id: 'ent_carrier_info',
                      physical_table: 'carrier_info',
                      physical_column: 'carrier_name',
                      business_name: '承运商名称',
                      description: '承运商的工商登记名称或简称',
                      data_type: 'VARCHAR(128)',
                      origin: 'inferred',
                      semantic_role: 'dimension',
                      synonyms: ['承运商名字', '承运公司'],
                      confidence: 0.90,
                      evidence: [
                        { source: 'comment', detail: '承运商中文简称，如顺丰、京东等。' },
                        { source: 'sample', detail: '中文文本样本包含: ["顺丰速运", "京东物流", "圆通速递"]' }
                      ],
                      is_candidate: true
                    }
                  ]
                }
              ]
            },
            {
              space_id: 'space_finance',
              snapshot_id: 'snap_tms_1',
              name: '财务结算 (Financial Settlement)',
              description: '涵盖运费计算明细、对账单据、承运商应付款项等实体。',
              accepted: true,
              entities: [
                {
                  entity_id: 'ent_billing_detail',
                  space_id: 'space_finance',
                  physical_table: 'billing_detail',
                  business_name: '费用明细 (Billing Detail)',
                  description: '运单费用拆分明细，包含首重、续重费、保价费及应付账款。',
                  recommendation: 'recommended_include',
                  fields: [
                    {
                      field_id: 'field_freight_charge',
                      entity_id: 'ent_billing_detail',
                      physical_table: 'billing_detail',
                      physical_column: 'freight_charge',
                      business_name: '运费金额',
                      description: '实际需要结算的运输费用',
                      data_type: 'DECIMAL(12,2)',
                      origin: 'inferred',
                      semantic_role: 'measure',
                      default_aggregation: 'sum',
                      synonyms: ['费用', '实付运费'],
                      confidence: 0.92,
                      evidence: [
                        { source: 'comment', detail: '该运单实际支付给承运商的运费金额（单位：元）' },
                        { source: 'sample', detail: '浮点金额样本符合计费特征: [1200.50, 340.00, 0.00]' }
                      ],
                      is_candidate: true
                    }
                  ]
                }
              ]
            }
          ]
        }
      },
      documents: {
        [dsId]: [
          {
            document_id: 'doc_tms_dict',
            data_source_id: dsId,
            filename: 'tms_data_dictionary_v2.xlsx',
            content_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            byte_size: 145200,
            upload_status: 'ready',
            uploaded_at: new Date(Date.now() - 7200000).toISOString()
          },
          {
            document_id: 'doc_tms_design',
            data_source_id: dsId,
            filename: 'tms_dispatch_module_spec.pdf',
            content_type: 'application/pdf',
            byte_size: 2450000,
            upload_status: 'ready',
            uploaded_at: new Date(Date.now() - 7100000).toISOString()
          }
        ]
      }
    };
    saveSemanticStore(store);
  }
  return store;
}

const EXPLORATION_MOCK_KEY = 'sqbi.mock_exploration_store';

function loadExplorationStore(): ExplorationMockStore | null {
  if (typeof window === 'undefined') return null;
  const stored = window.localStorage.getItem(EXPLORATION_MOCK_KEY);
  if (stored) {
    try {
      return JSON.parse(stored);
    } catch {
      return null;
    }
  }
  return null;
}

function saveExplorationStore(store: ExplorationMockStore) {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(EXPLORATION_MOCK_KEY, JSON.stringify(store));
  }
}

interface ExplorationMockStore {
  savedMetrics: string[];
}

function getOrInitExplorationStore(): ExplorationMockStore {
  let store = loadExplorationStore();
  if (!store) {
    store = {
      savedMetrics: []
    };
    saveExplorationStore(store);
  }
  return store;
}

// ── Phase 4: Enterprise Domain Pack mock factory (VITE_MOCK_ENTERPRISE_PACK) ──

const _mockExtensionLayers = new Map<string, PackExtensionLayer>();

function _mockOpenPackExtensionLayer(
  basePackId: string,
  payload: { base_kind: 'official' | 'enterprise'; created_by: string },
): PackExtensionLayer {
  const existing = _mockExtensionLayers.get(basePackId);
  if (existing) return existing;
  const layer: PackExtensionLayer = {
    extension_id: `ext_${basePackId}`,
    base_pack_id: basePackId,
    base_pack_version: '1.0.0',
    base_kind: payload.base_kind,
    version: '0.1.0',
    version_state: 'draft',
    state: 'draft',
    draft: { entities: [], fields: [], metrics: [], skills: [], reports: [], terms: [], acceptance_questions: [] },
    created_by: payload.created_by,
    created_at: new Date().toISOString(),
  };
  _mockExtensionLayers.set(basePackId, layer);
  return layer;
}

function _mockEnterprisePacks(dataSourceId?: string): EnterprisePack[] {
  const packs: EnterprisePack[] = [
    {
      pack_id: 'ep_logistics_001',
      name: '物流域企业包',
      description: '基于官方物流包扩展，涵盖企业特有的运费和履约指标。',
      data_source_id: 'ds_logistics',
      version: '0.3.0',
      version_state: 'draft',
      base_pack_id: 'logistics',
      base_pack_version: '1.0.0',
      create_mode: 'extend_official',
      draft: {
        entities: [
          { entity_id: 'ent_shipment', name: '运单', physical_table: 'shipment', tags: ['core'], source: 'enterprise' }
        ],
        fields: [
          {
            field_id: 'ef_freight_charge',
            business_name: '实付运费',
            physical_table: 'billing_detail',
            physical_column: 'freight_charge',
            data_type: 'DECIMAL(12,2)',
            entity_id: 'ent_shipment',
            synonyms: ['运费', '实际运费'],
            source: 'enterprise',
          }
        ],
        metrics: [
          {
            metric_code: 'usr_freight_total',
            name: '总运费',
            definition: '统计期内所有运单的实付运费之和。',
            formula: { expression: 'SUM(billing_detail.freight_charge)', filters: [] },
            entity_id: 'ent_shipment',
            synonyms: ['运费汇总'],
            source: 'enterprise',
          }
        ],
        skills: [],
        reports: [],
        terms: [
          { term_id: 'term_otd', term: '准时交付', definition: '按承诺时间完成配送的运单比例。', synonyms: ['OTD'], related_field_ids: [] }
        ],
        acceptance_questions: [
          { question_id: 'aq_1', question: '上周总运费是多少？', expected_metric_code: 'usr_freight_total' }
        ],
      },
      created_by: 'admin',
      created_at: '2026-06-01T08:00:00Z',
      updated_at: '2026-06-20T14:30:00Z',
    }
  ];
  if (dataSourceId) return packs.filter(p => p.data_source_id === dataSourceId);
  return packs;
}

function _mockNewEnterprisePack(req: CreateEnterprisePackRequest): EnterprisePack {
  return {
    pack_id: `ep_${Math.random().toString(36).substring(2, 8)}`,
    name: req.name,
    description: req.description ?? null,
    data_source_id: null,
    version: '0.1.0',
    version_state: 'draft',
    base_pack_id: req.base_pack_id ?? null,
    base_pack_version: req.base_pack_version ?? (req.base_pack_id ? '1.0.0' : null),
    create_mode: req.mode,
    draft: {
      entities: [],
      fields: [],
      metrics: [],
      skills: [],
      reports: [],
      terms: [],
      acceptance_questions: [],
    },
    created_by: req.created_by,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

function _mockPackDraftResult(dataSourceId: string): PackDraftResult {
  return {
    draft: {
      entities: [
        { entity_id: 'ent_draft_1', name: 'AI建议实体', physical_table: 'orders', tags: ['ai_draft'], source: 'enterprise' }
      ],
      fields: [
        {
          field_id: 'ef_draft_1',
          business_name: 'AI建议字段',
          physical_table: 'orders',
          physical_column: 'total_amount',
          data_type: 'DECIMAL',
          entity_id: 'ent_draft_1',
          synonyms: ['总金额'],
          source: 'enterprise',
        }
      ],
      metrics: [
        {
          metric_code: 'draft_metric_1',
          name: 'AI建议指标',
          definition: `基于 ${dataSourceId} 语义档案自动生成。`,
          formula: { expression: 'SUM(orders.total_amount)', filters: [] },
          entity_id: 'ent_draft_1',
          synonyms: [],
          source: 'enterprise',
        }
      ],
      skills: [],
      reports: [],
      terms: [
        { term_id: 'term_draft_1', term: 'AI建议术语', definition: '从上传文档提取的业务术语。', synonyms: [], related_field_ids: [] }
      ],
      acceptance_questions: [
        { question_id: 'aq_draft_1', question: '本月总金额是多少？', expected_metric_code: 'draft_metric_1' }
      ],
    },
    dropped_fields: [],
    rejected_metrics: [],
    rejection_reasons: {},
  };
}

const mockPromotionsStore: Record<string, PromotionRecord> = {};

function _mockPromotionPreview(payload: PromotionPreviewRequest): PromotionPreview {
  const hasConflict = payload.asset_refs.some(ref => ref.asset.local_code.includes('conflict'));
  const conflicts: PromotionConflict[] = [];
  if (hasConflict) {
    conflicts.push({
      code: 'scope_mismatch',
      message: '数据源/环境范围不兼容：资产引用的数据源与目标企业包不匹配。',
      asset_ref: payload.asset_refs[0]
    });
  }

  const standard_fields: StandardFieldProposal[] = [];
  const mapping_candidates: MappingCandidateProposal[] = [];

  payload.asset_refs.forEach((ref, index) => {
    const code = ref.asset.local_code;
    standard_fields.push({
      field_id: `sf_${code}_${index}`,
      business_name: `标准字段_${code}`,
      physical_table: 'billing_detail',
      physical_column: 'freight_charge',
      data_type: 'decimal',
      evidence: `根据资产 ${code} 及其底层 SQL 的物理字段解析生成`
    });

    mapping_candidates.push({
      standard_field_id: `sf_${code}_${index}`,
      physical_table: 'billing_detail',
      physical_column: 'freight_charge',
      confidence: 0.95,
      evidence: '字段物理名称 freight_charge 与模型字段高度一致'
    });
  });

  return {
    eligible: !hasConflict,
    workspace_id: payload.workspace_id,
    target_pack_id: payload.target_pack_id,
    asset_refs: payload.asset_refs,
    conflicts,
    standard_fields,
    mapping_candidates
  };
}

function _mockConfirmPromotion(payload: ConfirmPromotionRequest): PromotionRecord {
  const promoId = `promo_${Math.random().toString(36).substring(2, 8)}`;
  const record: PromotionRecord = {
    promotion_id: promoId,
    workspace_id: payload.workspace_id,
    target_pack_id: payload.target_pack_id,
    source_refs: payload.asset_refs,
    target_refs: payload.asset_refs.map(ref => ({
      ...ref,
      asset: {
        ...ref.asset,
        source_type: 'enterprise_pack',
        source_id: payload.target_pack_id
      }
    })),
    requested_by: payload.requested_by,
    lifecycle: 'draft',
    next_action: 'publish_pack',
    created_at: new Date().toISOString()
  };
  mockPromotionsStore[promoId] = record;
  return record;
}

function _mockGetPromotionStatus(promotionId: string): PromotionRecord {
  if (mockPromotionsStore[promotionId]) {
    return mockPromotionsStore[promotionId];
  }
  return {
    promotion_id: promotionId,
    workspace_id: 'personal_ws_admin',
    target_pack_id: 'ep_logistics_001',
    source_refs: [],
    target_refs: [],
    requested_by: 'admin',
    lifecycle: 'draft',
    next_action: 'publish_pack',
    created_at: new Date().toISOString()
  };
}
