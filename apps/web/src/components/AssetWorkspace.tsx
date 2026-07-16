import React, { useState } from 'react';
import { 
  BookOpen, 
  Cpu, 
  FileText, 
  Plus, 
  Search, 
  Wand2, 
  Share2, 
  Trash2, 
  Save, 
  Send,
  X, 
  RefreshCw, 
  AlertTriangle,
  LayoutGrid,
  List,
  ArrowUpCircle,
  CheckCircle2,
  Lock,
  Boxes
} from 'lucide-react';
import { api } from '../api';
import { getAssetIdentity } from '../assetIdentity';
import { confirmAction } from '../systemDialog';
import type { 
  MetricDefinition, 
  SkillDefinition, 
  ReportDefinition,
  SemanticField,
  DataSource,
  QueryResult,
  SkillClarificationRequired,
  EnterprisePack,
  PersonalAssetScope,
  PersonalAssetRecord,
  AssetRef,
  PromotionPreview,
  PromotionRecord,
  PromotionPreviewRequest,
  ConfirmPromotionRequest,
  PersonalAssetTemplate,
  GeneratedFileRecord,
  DataSourceBinding
} from '../api';
import { QueryResultView } from './QueryResultView';

interface AssetWorkspaceProps {
  metrics: MetricDefinition[];
  skills: SkillDefinition[];
  reports: ReportDefinition[];
  fields: SemanticField[];
  dataSources: DataSource[];
  userContext: any;
  darkMode: boolean;
  onRefreshAll: () => Promise<void>;
  onPreviewMetric?: (metric: MetricDefinition) => void;
  onPreviewSkill?: (skill: SkillDefinition) => void;
  onPreviewReport?: (report: ReportDefinition) => void;
}

type ConversationCandidate = {
  assetType: 'metric' | 'skill' | 'report';
  name: string;
  description: string;
  expression: string;
  logicSql?: string;
  artifactTitle: string;
  artifactContent: string;
  parameters?: Array<{ name: string; data_type: string; required: boolean; description?: string; allowed_values: string[] }>;
  workflow?: string[];
  dependencies?: string[];
  dependencyNodes?: HarnessDependencyNode[];
  caliber?: string;
  outputSchema?: Record<string, unknown>;
  dataSourceId?: string;
  dataSourceName?: string;
  dataSourceReason?: string;
  dataSourceBindings?: DataSourceBinding[];
  analysisChain?: Array<{ order: number; kind: 'semantic' | 'metric' | 'skill' | 'report' | 'delivery'; label: string; input: string; output: string; data_source_ids: string[] }>;
  supplementary?: Array<{ title: string; content: string }>;
  flow?: string;
  sections?: string[];
};

type HarnessDependencyNode = {
  id: string;
  label: string;
  kind: 'template' | 'field' | 'metric' | 'skill' | 'report' | 'parameter' | 'delivery';
  resolved: boolean;
  assetRef?: AssetRef;
};

type CreationConversationMessage = {
  id: string;
  role: 'assistant' | 'user';
  content: string;
  candidate?: ConversationCandidate;
  testResult?: QueryResult;
  slotResolution?: Array<{ name: string; description?: string | null; status: string; candidates?: Array<{ value: unknown }> }>;
  error?: boolean;
};

type SkillSchemaDraft = {
  parameters: Array<{ name: string; label: string; dataType: string; required: boolean }>;
  steps: string[];
  sql: string;
  chartType: string;
};

type ReportAiPlan = {
  title?: string;
  flow?: string;
  sections?: string[];
  outline?: string[];
  warnings?: string[];
};

const isSkillClarification = (value: QueryResult | SkillClarificationRequired): value is SkillClarificationRequired => (
  'clarification_required' in value && value.clarification_required === true
);

const describeApiError = (error: unknown, fallback: string) => {
  if (error instanceof Error && error.message) return error.message;
  if (error && typeof error === 'object' && 'message' in error && typeof error.message === 'string') return error.message;
  return fallback;
};

const asText = (value: unknown): string => typeof value === 'string' ? value : '';
const withoutStepPrefix = (value: string): string => value.replace(/^\s*(?:第\s*)?\d+\s*[.、)、]\s*/, '');
const candidateConclusion = (candidate: ConversationCandidate | null): string => (
  asText(candidate?.outputSchema?.conclusion).trim()
  || candidate?.analysisChain?.at(-1)?.output
  || ''
);

const candidateSupplementary = (candidate: ConversationCandidate): Array<{ title: string; content: string }> => {
  const items = [{ title: candidate.artifactTitle, content: candidate.artifactContent }];
  if (candidate.flow && candidate.flow !== candidate.artifactContent) items.push({ title: '生成的执行说明', content: candidate.flow });
  if (candidate.sections?.length) items.push({ title: '章节与结构', content: candidate.sections.map((section, index) => `${index + 1}. ${section}`).join('\n') });
  return items.filter(item => item.content.trim());
};

const mergeCandidateDraft = (current: ConversationCandidate | null, patch: ConversationCandidate): ConversationCandidate => {
  const patchWithSupplementary = { ...patch, supplementary: candidateSupplementary(patch) };
  if (!current || current.assetType !== patch.assetType) return patchWithSupplementary;
  const mergedSupplementary = [...(current.supplementary || []), ...(patchWithSupplementary.supplementary || [])]
    .filter((item, index, items) => items.findIndex(candidate => candidate.title === item.title && candidate.content === item.content) === index)
    .slice(-6);
  return {
    ...current,
    ...patchWithSupplementary,
    description: patch.description || current.description,
    expression: patch.expression || current.expression,
    logicSql: patch.logicSql || current.logicSql,
    parameters: patch.parameters?.length ? patch.parameters : current.parameters,
    workflow: patch.workflow?.length ? patch.workflow : current.workflow,
    dependencyNodes: patch.dependencyNodes?.length ? patch.dependencyNodes : current.dependencyNodes,
    dataSourceBindings: patch.dataSourceBindings?.length ? patch.dataSourceBindings : current.dataSourceBindings,
    analysisChain: patch.analysisChain?.length ? patch.analysisChain : current.analysisChain,
    outputSchema: { ...(current.outputSchema || {}), ...(patch.outputSchema || {}) },
    flow: patch.flow || current.flow,
    sections: patch.sections?.length ? patch.sections : current.sections,
    supplementary: mergedSupplementary,
  };
};

const formatCandidateDefinition = (candidate: ConversationCandidate): string => {
  const sources = candidate.dataSourceBindings?.map(binding => `${binding.name}（${binding.role === 'primary' ? '直接读取' : '依赖继承'}）`).join('、') || '待确认';
  const dependencies = candidate.dependencyNodes?.filter(node => node.kind === 'metric' || node.kind === 'skill').map(node => `${node.kind === 'metric' ? '指标' : '技能'}·${node.label}`).join('、') || '无';
  const chain = candidate.analysisChain?.map(step => `${step.order}. ${step.label}`).join(' → ') || '待确认';
  if (candidate.assetType === 'metric') return [`数据源：${sources}`, `业务口径：${candidate.caliber || candidate.description}`, `逻辑 SQL：${candidate.logicSql || candidate.expression || '待确认'}`].join('\n');
  if (candidate.assetType === 'skill') return [`数据源：${sources}`, `依赖：${dependencies}`, `参数：${candidate.parameters?.map(parameter => `${parameter.description || parameter.name}${parameter.required ? '（必填）' : ''}`).join('、') || '无'}`, `分析链路：${chain}`, `输出结论：${asText(candidate.outputSchema?.conclusion) || '可追溯分析结论、查询证据与可复用结果。'}`].join('\n');
  return [`数据源：${sources}`, `依赖：${dependencies}`, `报告链路：${chain}`, `交付产物：HTML 主产物 → ${((candidate.outputSchema?.derived_output_types as string[] | undefined) || ['PDF', 'PPTX', 'DOCX']).map(item => item.toUpperCase()).join(' / ')}`].join('\n');
};

type TemplateCatalogEntry =
  | { key: string; assetType: 'metric'; name: string; description: string; sourceType: 'official_pack' | 'enterprise_pack'; sourceId: string; version: string; asset: MetricDefinition }
  | { key: string; assetType: 'skill'; name: string; description: string; sourceType: 'official_pack' | 'enterprise_pack'; sourceId: string; version: string; asset: SkillDefinition }
  | { key: string; assetType: 'report'; name: string; description: string; sourceType: 'official_pack' | 'enterprise_pack'; sourceId: string; version: string; asset: ReportDefinition };

const reportOutputLabels = { pptx: 'PPTX', docx: 'DOCX', pdf: 'PDF', html: 'HTML', push: '消息推送' } as const;
const reportTemplates: Record<'pptx' | 'docx' | 'html', Array<[string, string]>> = {
  pptx: [['management_review', '管理层经营复盘'], ['business_review', '业务专题汇报'], ['risk_alert', '异常风险专题']],
  docx: [['formal_report', '正式分析报告'], ['audit_report', '审计留档报告'], ['briefing', '分析简报']],
  html: [['interactive_dashboard', '交互分析看板'], ['executive_portal', '管理驾驶舱'], ['public_page', '发布型报告页']],
};
const runtimeAssetUrl = (url: string) => /^https?:\/\//.test(url) ? url : `${import.meta.env.VITE_API_BASE_URL || ''}${url}`;

export const AssetWorkspace: React.FC<AssetWorkspaceProps> = ({
  metrics,
  skills,
  reports,
  fields,
  dataSources,
  userContext,
  darkMode,
  onRefreshAll,
  onPreviewMetric,
  onPreviewSkill,
  onPreviewReport
}) => {

  const [activeSubTab, setActiveSubTab] = useState<'metrics' | 'skills' | 'reports'>('metrics');
  const primaryTab: 'marketplace' | 'workbench' = 'workbench';
  const showMarketplace = false;
  const [templatePickerOpen, setTemplatePickerOpen] = useState(false);
  const [templateSearch, setTemplateSearch] = useState('');
  const [templateSourceFilter, setTemplateSourceFilter] = useState<'all' | 'official_pack' | 'enterprise_pack'>('all');
  const [assetCreationChoiceOpen, setAssetCreationChoiceOpen] = useState(false);
  const [newAssetModalOpen, setNewAssetModalOpen] = useState(false);
  const [newAssetType, setNewAssetType] = useState<'metric' | 'skill' | 'report'>('metric');
  const [newAssetDraft, setNewAssetDraft] = useState({ name: '', description: '', expression: '', dataSourceId: '' });
  const [assetIntent, setAssetIntent] = useState('');
  const [creationError, setCreationError] = useState<string | null>(null);
  const [isGeneratingCandidate, setIsGeneratingCandidate] = useState(false);
  const [conversationCandidate, setConversationCandidate] = useState<ConversationCandidate | null>(null);
  const [creationConversation, setCreationConversation] = useState<CreationConversationMessage[]>([]);
  const [isTestingConversationDraft, setIsTestingConversationDraft] = useState(false);
  const [conversationPreviewResult, setConversationPreviewResult] = useState<QueryResult | null>(null);
  const [conversationPreviewError, setConversationPreviewError] = useState<string | null>(null);
  const [isEditingAssetStructure, setIsEditingAssetStructure] = useState(false);
  const [assetDefinitionText, setAssetDefinitionText] = useState('');
  const [draggedChainStep, setDraggedChainStep] = useState<number | null>(null);
  const conversationScrollRef = React.useRef<HTMLDivElement>(null);
  const [isCreatingAsset, setIsCreatingAsset] = useState(false);
  const [editingAssetRow, setEditingAssetRow] = useState<PersonalAssetRow | null>(null);
  const [hubView, setHubView] = useState(true);
  const [assetTypeFilter, setAssetTypeFilter] = useState<'all' | 'metrics' | 'skills' | 'reports'>('all');
  const [assetSearch, setAssetSearch] = useState('');
  const [runtimeTemplates, setRuntimeTemplates] = useState<PersonalAssetTemplate[]>([]);
  const [templateSourceRef, setTemplateSourceRef] = useState<AssetRef | null>(null);
  const [viewLayout, setViewLayout] = useState<'card' | 'table'>('card');
  const [isCloning, setIsCloning] = useState(false);

  // --- Promotion Wizard state ---
  const [showPromotionModal, setShowPromotionModal] = useState(false);
  const [selectedAssetForPromotion, setSelectedAssetForPromotion] = useState<{
    asset_type: 'metric' | 'skill' | 'report';
    local_code: string;
    name: string;
    version?: string;
    workspace_id?: string | null;
    asset_ref?: AssetRef;
  } | null>(null);
  const [enterprisePacksList, setEnterprisePacksList] = useState<EnterprisePack[]>([]);
  const [selectedTargetPackId, setSelectedTargetPackId] = useState('');
  const [promotionPreviewResult, setPromotionPreviewResult] = useState<PromotionPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [promotionRecord, setPromotionRecord] = useState<PromotionRecord | null>(null);
  const [promoting, setPromoting] = useState(false);
  const [simulateConflicts, setSimulateConflicts] = useState(false);
  const [wizardStage, setWizardStage] = useState<'preview' | 'status'>('preview');
  const [statusLoading, setStatusLoading] = useState(false);

  // --- Advanced metadata state ---
  const [expandedCards, setExpandedCards] = useState<Record<string, boolean>>({});
  const [personalAssetRecords, setPersonalAssetRecords] = useState<PersonalAssetRecord[]>([]);

  React.useEffect(() => {
    const workspaceId = userContext?.user_id;
    if (!workspaceId) return;
    api.getPersonalAssets(workspaceId)
      .then(setPersonalAssetRecords)
      .catch(error => console.error('Failed to load personal asset metadata:', error));
  }, [userContext?.user_id]);

  React.useEffect(() => {
    const dataSourceId = dataSources[0]?.data_source_id;
    if (!dataSourceId) return;
    api.getPersonalAssetTemplates(dataSourceId)
      .then(setRuntimeTemplates)
      .catch(() => setRuntimeTemplates([]));
  }, [dataSources]);

  React.useEffect(() => {
    const panel = conversationScrollRef.current;
    if (panel) panel.scrollTop = panel.scrollHeight;
  }, [creationConversation, isGeneratingCandidate]);

  const prepareNewAssetDialog = () => {
    setNewAssetType('metric');
    setNewAssetDraft({ name: '', description: '', expression: '', dataSourceId: '' });
    setTemplateSourceRef(null);
    setEditingAssetRow(null);
    setAssetIntent('');
    setCreationError(null);
    setConversationCandidate(null);
    setIsEditingAssetStructure(false);
    setAssetDefinitionText('');
    setCreationConversation([{ id: `welcome_${Date.now()}`, role: 'assistant', content: '你好，我是资产创建助手。请用业务语言告诉我你想沉淀什么分析能力；我会生成草稿，你可以持续补充和调整，满意后再填充到左侧测试并保存。' }]);
    setConversationPreviewResult(null);
    setConversationPreviewError(null);
  };

  const openConversationCreation = (
    type: 'metric' | 'skill' | 'report',
    initialDraft?: Partial<typeof newAssetDraft>,
    sourceRef: AssetRef | null = null,
    sourceName?: string,
  ) => {
    const label = type === 'metric' ? '指标' : type === 'skill' ? '技能' : '报表';
    setNewAssetType(type);
    setNewAssetDraft({ name: '', description: '', expression: '', dataSourceId: '', ...initialDraft });
    setTemplateSourceRef(sourceRef);
    setEditingAssetRow(null);
    setAssetIntent('');
    setCreationError(null);
    setConversationCandidate(null);
    setIsEditingAssetStructure(false);
    setAssetDefinitionText('');
    setCreationConversation([{
      id: `welcome_${Date.now()}`,
      role: 'assistant',
      content: sourceName
        ? `已载入领域包模板「${sourceName}」。请告诉我你想在这个模板基础上做哪些调整，我会持续生成新的${label}草案。`
        : `请描述你想创建的${label}。我会在右侧持续生成和调整候选；运行受控测试后，由你决定是否同步到左侧并保存。`,
    }]);
    setConversationPreviewResult(null);
    setConversationPreviewError(null);
    setTemplatePickerOpen(false);
    setNewAssetModalOpen(true);
  };

  const openNewAssetModal = () => {
    setAssetCreationChoiceOpen(true);
  };

  const handleCancelAssetWorkspace = () => {
    setNewAssetModalOpen(false);
  };

  const startBlankAsset = () => {
    setAssetCreationChoiceOpen(false);
    openConversationCreation('metric');
  };

  const startFromPackAsset = () => {
    prepareNewAssetDialog();
    setAssetCreationChoiceOpen(false);
    setActiveSubTab('metrics');
    setTemplateSearch('');
    setTemplateSourceFilter('all');
    setTemplatePickerOpen(true);
  };

  const personalMetadataFor = (asset: { asset_ref?: AssetRef | null }) => {
    const assetId = asset.asset_ref?.asset.asset_id;
    const version = asset.asset_ref?.version;
    return personalAssetRecords.find(record =>
      record.asset_ref.asset.asset_id === assetId && record.asset_ref.version === version
    );
  };

  const toggleCardExpanded = (id: string) => {
    setExpandedCards(prev => ({
      ...prev,
      [id]: !prev[id]
    }));
  };

  const handleOpenPromotion = async (asset: any, type: 'metric' | 'skill' | 'report') => {
    const metadata = personalMetadataFor(asset);
    setSelectedAssetForPromotion({
      asset_type: type,
      local_code: type === 'metric' ? asset.metric_code : (type === 'skill' ? asset.skill_id : asset.report_id),
      name: asset.name,
      version: asset.asset_ref?.version || asset.version || '1.0.0',
      workspace_id: metadata?.workspace_id || asset.workspace_id || asset.asset_ref?.asset?.source_id || userContext?.user_id || 'anonymous',
      asset_ref: asset.asset_ref
    });
    setPromotionPreviewResult(null);
    setPromotionRecord(null);
    setWizardStage('preview');
    setSelectedTargetPackId('');
    setSimulateConflicts(false);
    setShowPromotionModal(true);

    try {
      const list = await api.listEnterprisePacks();
      setEnterprisePacksList(list);
      if (list.length > 0) {
        setSelectedTargetPackId(list[0].pack_id);
      }
    } catch (e) {
      console.error('Failed to load enterprise packs:', e);
    }
  };

  const handleLoadPreview = async () => {
    if (!selectedAssetForPromotion || !selectedTargetPackId) return;
    setPreviewLoading(true);
    try {
      const localCode = selectedAssetForPromotion.local_code;
      const finalCode = simulateConflicts ? `${localCode}_conflict` : localCode;
      
      const payload: PromotionPreviewRequest = {
        workspace_id: selectedAssetForPromotion.workspace_id || userContext?.user_id || 'anonymous',
        target_pack_id: selectedTargetPackId,
        asset_refs: selectedAssetForPromotion.asset_ref ? [selectedAssetForPromotion.asset_ref] : [{
          asset: {
            source_type: 'personal_workspace',
            source_id: selectedAssetForPromotion.workspace_id || userContext?.user_id || 'anonymous',
            asset_type: selectedAssetForPromotion.asset_type,
            local_code: finalCode,
            asset_id: ''
          },
          version: selectedAssetForPromotion.version || '1.0.0'
        }],
        requested_by: userContext?.user_id || 'admin'
      };

      const result = await api.previewPromotion(payload);
      setPromotionPreviewResult(result);
    } catch (e) {
      console.error('Failed to preview promotion:', e);
    } finally {
      setPreviewLoading(false);
    }
  };

  React.useEffect(() => {
    if (showPromotionModal && selectedAssetForPromotion && selectedTargetPackId) {
      void handleLoadPreview();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTargetPackId, simulateConflicts, showPromotionModal]);

  const handleConfirmPromotion = async () => {
    if (!selectedAssetForPromotion || !selectedTargetPackId || !promotionPreviewResult) return;
    setPromoting(true);
    try {
      const payload: ConfirmPromotionRequest = {
        workspace_id: selectedAssetForPromotion.workspace_id || userContext?.user_id || 'anonymous',
        target_pack_id: selectedTargetPackId,
        asset_refs: promotionPreviewResult.asset_refs,
        requested_by: userContext?.user_id || 'admin',
        confirmed_standard_fields: promotionPreviewResult.standard_fields,
        confirmed_mappings: promotionPreviewResult.mapping_candidates
      };
      const record = await api.confirmPromotion(payload);
      setPromotionRecord(record);
      setWizardStage('status');
      if (onRefreshAll) {
        void onRefreshAll();
      }
    } catch (e) {
      console.error('Failed to confirm promotion:', e);
      alert('确认晋升失败：' + (e instanceof Error ? e.message : '未知错误'));
    } finally {
      setPromoting(false);
    }
  };

  const handleAdvanceLifecycle = async () => {
    if (!promotionRecord) return;
    setStatusLoading(true);
    try {
      const updated = await api.getPromotionStatus(promotionRecord.promotion_id);
      setPromotionRecord(updated);
    } catch (e) {
      console.error('Failed to advance promotion lifecycle:', e);
      alert('推进生命周期失败：' + (e instanceof Error ? e.message : '未知错误'));
    } finally {
      setStatusLoading(false);
    }
  };

  const renderAdvancedMetadata = (asset: any, activeId: string) => {
    const metadata = personalMetadataFor(asset);
    const isExpanded = !!expandedCards[activeId];
    const workspaceId = metadata?.workspace_id || asset.workspace_id || asset.asset_ref?.asset?.source_id;
    const version = metadata?.asset_ref.version || asset.asset_ref?.version || asset.version;
    const scope = (metadata?.scope || asset.scope) as PersonalAssetScope | undefined;
    const deps = (metadata?.dependency_refs || asset.dependency_refs) as AssetRef[] | undefined;

    const hasDsConflict = scope && !dataSources.some(ds => ds.data_source_id === scope.data_source_id);
    const hasAuthConflict = workspaceId === 'foreign_workspace';

    return (
      <div className="mt-2 pt-2 border-t border-slate-100 dark:border-slate-800 text-[10px] text-slate-500 dark:text-slate-400">
        <div className="flex justify-between items-center cursor-pointer select-none" onClick={() => toggleCardExpanded(activeId)}>
          <span className="font-semibold text-slate-700 dark:text-slate-300">高级元数据 & 范围</span>
          <span className="text-slate-455">{isExpanded ? '▲ 收起' : '▼ 展开'}</span>
        </div>
        
        {isExpanded && (
          <div className="mt-2 space-y-2.5 bg-slate-50 dark:bg-slate-950 p-2.5 rounded-lg border border-slate-100 dark:border-slate-900/60">
            {hasAuthConflict && (
              <div className="flex items-center gap-1 bg-rose-50 dark:bg-rose-950/20 text-rose-600 dark:text-rose-400 p-1.5 rounded text-[9px] font-medium border border-rose-100 dark:border-rose-900/40">
                <Lock className="w-3.5 h-3.5 shrink-0" />
                <span>授权冲突：工作区权限不足，当前用户无此个人空间访问权限</span>
              </div>
            )}

            {hasDsConflict && (
              <div className="flex items-center gap-1 bg-amber-50 dark:bg-amber-950/20 text-amber-600 dark:text-amber-400 p-1.5 rounded text-[9px] font-medium border border-amber-100 dark:border-amber-900/40">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                <span>范围冲突：绑定了未注册数据源 ({scope?.data_source_id})</span>
              </div>
            )}

            <div className="grid grid-cols-2 gap-2 text-[9px]">
              <div>
                <span className="text-slate-400">工作区归属:</span>{' '}
                <span className="font-mono font-bold text-slate-700 dark:text-slate-300">{workspaceId || '未分配'}</span>
              </div>
              <div>
                <span className="text-slate-450">精确版本:</span>{' '}
                <span className="font-mono font-bold text-slate-700 dark:text-slate-300">{version || 'v1.0.0'}</span>
              </div>
            </div>

            {scope && (
              <div className="space-y-1 text-[9px] border-t border-slate-200/40 dark:border-slate-800/40 pt-1.5 font-mono">
                <div>
                  <span className="text-slate-400 font-sans">有效环境:</span>{' '}
                  <span className="text-slate-700 dark:text-slate-300">{scope.environment || 'default'}</span>
                </div>
                {scope.semantic_space_ids && scope.semantic_space_ids.length > 0 && (
                  <div>
                    <span className="text-slate-400 font-sans">语义空间:</span>{' '}
                    <span className="text-slate-700 dark:text-slate-300">{scope.semantic_space_ids.join(', ')}</span>
                  </div>
                )}
                {scope.physical_tables && scope.physical_tables.length > 0 && (
                  <div>
                    <span className="text-slate-400 font-sans">物理表:</span>{' '}
                    <span className="text-slate-700 dark:text-slate-300">{scope.physical_tables.join(', ')}</span>
                  </div>
                )}
              </div>
            )}

            <div className="border-t border-slate-200/40 dark:border-slate-800/40 pt-1.5">
              <div className="font-semibold mb-1 text-[9px] text-slate-600 dark:text-slate-400">依赖图谱 (Dependency Graph):</div>
              {deps && deps.length > 0 ? (
                <div className="space-y-1">
                  {deps.map((ref, idx) => (
                    <div key={idx} className="flex justify-between items-center bg-slate-100 dark:bg-slate-900 px-1.5 py-0.5 rounded font-mono text-[8px]">
                      <span>{ref.asset.asset_type === 'metric' ? '指标' : ref.asset.asset_type === 'skill' ? '技能' : '报表'}: {ref.asset.local_code}</span>
                      <span className="text-slate-450 font-bold">{ref.version}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <span className="text-slate-400 text-[8px] italic">无依赖</span>
              )}
            </div>
          </div>
        )}
      </div>
    );
  };


  // Search filter states
  const [metricSearch, setMetricSearch] = useState('');
  const [skillSearch, setSkillSearch] = useState('');
  const [reportSearch, setReportSearch] = useState('');

  // --- Metrics workspace states ---
  const [metricMode, setMetricMode] = useState<'list' | 'create' | 'edit'>('list');
  const [selectedMetric, setSelectedMetric] = useState<MetricDefinition | null>(null);
  const [metricDraft, setMetricDraft] = useState({
    name: '',
    definition: '',
    expression: '',
    numerator: '',
    denominator: '',
    filters: [] as string[],
    time_field: '',
    data_source_id: '',
    update_frequency: '',
    synonyms: '',
    visibility: 'private' as 'private' | 'shared'
  });
  const [isSavingMetric, setIsSavingMetric] = useState(false);
  const [isRunningMetricPreview, setIsRunningMetricPreview] = useState(false);
  const [metricPreviewResult, setMetricPreviewResult] = useState<QueryResult | null>(null);
  const [metricPreviewError, setMetricPreviewError] = useState<string | null>(null);
  const [metricPreviewTimeRange, setMetricPreviewTimeRange] = useState('最近30天');
  const [metricPreviewFactory, setMetricPreviewFactory] = useState('全部厂区');
  const [metricAdjustPrompt, setMetricAdjustPrompt] = useState('');
  const [isAdjustingMetric, setIsAdjustingMetric] = useState(false);
  const [metricDependencies, setMetricDependencies] = useState<Array<{ source_name: string; relation_type: string; blocking: boolean }>>([]);

  // --- Skills workspace states ---
  const [skillMode, setSkillMode] = useState<'list' | 'create' | 'edit'>('list');
  const [selectedSkill, setSelectedSkill] = useState<SkillDefinition | null>(null);
  const [skillDraft, setSkillDraft] = useState({
    skill_id: '',
    name: '',
    description: '',
    visibility: 'private' as 'private' | 'shared',
    parameters: [] as Array<{ name: string; data_type: string; required: boolean; description?: string; allowed_values: string[] }>
  });
  const [isSavingSkill, setIsSavingSkill] = useState(false);
  const [isRunningSkillPreview, setIsRunningSkillPreview] = useState(false);
  const [skillPreviewResult, setSkillPreviewResult] = useState<QueryResult | null>(null);
  const [skillPreviewError, setSkillPreviewError] = useState<string | null>(null);
  const [skillPreviewFactory, setSkillPreviewFactory] = useState('全部厂区');
  const [skillPreviewCarrier] = useState('全部承运商');
  const [skillPrompt, setSkillPrompt] = useState('');
  const [skillAdjustPrompt, setSkillAdjustPrompt] = useState('');
  const [skillSchemaDraft, setSkillSchemaDraft] = useState<SkillSchemaDraft | null>(null);
  const [isBuildingSkillSchema, setIsBuildingSkillSchema] = useState(false);

  // --- Reports workspace states ---
  const [reportMode, setReportMode] = useState<'list' | 'create' | 'edit'>('list');
  const [selectedReport, setSelectedReport] = useState<ReportDefinition | null>(null);
  const [reportDraft, setReportDraft] = useState({
    name: '',
    description: '',
    visibility: 'private' as 'private' | 'shared',
    outputTypes: ['html'] as Array<'pptx' | 'docx' | 'pdf' | 'html' | 'push'>,
    channels: ['email'] as Array<'ec' | 'email'>,
    flow: '',
    sections: [] as string[],
    tags: [] as string[],
    schedule: {
      mode: 'immediate' as 'immediate' | 'scheduled',
      status: 'draft' as 'draft' | 'sent' | 'scheduled' | 'stopped',
      sendAt: '',
      note: ''
    }
  });
  const [isSavingReport, setIsSavingReport] = useState(false);
  const [reportTemplateMode, setReportTemplateMode] = useState<'built_in' | 'upload'>('built_in');
  const [reportTemplate, setReportTemplate] = useState('management_review');
  const [reportTimeGrain, setReportTimeGrain] = useState('月度');
  const [reportPresenter, setReportPresenter] = useState('');
  const [reportAudience, setReportAudience] = useState('');
  const [reportContent, setReportContent] = useState('');
  const [reportBoundMetrics, setReportBoundMetrics] = useState<string[]>([]);
  const [reportBoundSkills, setReportBoundSkills] = useState<string[]>([]);
  const [reportAiPlan, setReportAiPlan] = useState<ReportAiPlan | null>(null);
  const [reportAdjustment, setReportAdjustment] = useState('');
  const [reportPreviewVersion, setReportPreviewVersion] = useState(0);
  const [isBuildingReportPlan, setIsBuildingReportPlan] = useState(false);
  const [reportArtifact, setReportArtifact] = useState<GeneratedFileRecord | null>(null);

  React.useEffect(() => {
    if (metricMode === 'list' && skillMode === 'list' && reportMode === 'list') {
      setHubView(true);
    }
  }, [metricMode, reportMode, skillMode]);

  // --- Asset Filters (PRIVATE or SHARED, exclude OFFICIAL) ---
  const isOwner = (asset: any) => asset.owner === userContext.user_id || asset.owner === userContext.display_name;

  const customMetrics = metrics.filter(m => m.visibility === 'private' && isOwner(m));
  const sharedMetrics = metrics.filter(m => m.visibility === 'shared' && !isOwner(m));
  const officialMetrics = metrics.filter(m => m.visibility === 'official');

  const customSkills = skills.filter(s => s.visibility === 'private' && s.owner_user_id === userContext.user_id);
  const sharedSkills = skills.filter(s => s.visibility === 'shared' && s.owner_user_id !== userContext.user_id);
  const officialSkills = skills.filter(s => s.visibility === 'official');

  const customReports = reports.filter(r => r.visibility === 'private' && (r.owner === userContext.user_id || r.owner === userContext.display_name));
  const sharedReports = reports.filter(r => r.visibility === 'shared' && r.owner !== userContext.user_id && r.owner !== userContext.display_name);
  const officialReports = reports.filter(r => r.visibility === 'official');

  const templateCatalog: TemplateCatalogEntry[] = [];
  const catalogKeys = new Set<string>();
  runtimeTemplates.forEach(template => {
    const localCode = template.asset_ref.asset.local_code;
    if (template.asset_type === 'metric') {
      const asset = metrics.find(item => item.metric_code === localCode || item.asset_ref?.asset.asset_id === template.asset_ref.asset.asset_id);
      if (asset) templateCatalog.push({ key: `metric:${template.asset_ref.asset.asset_id}`, assetType: 'metric', name: template.name, description: template.description || asset.definition, sourceType: template.source_type, sourceId: template.source_id, version: template.version, asset });
    } else if (template.asset_type === 'skill') {
      const asset = skills.find(item => item.skill_id === localCode || item.asset_ref?.asset.asset_id === template.asset_ref.asset.asset_id);
      if (asset) templateCatalog.push({ key: `skill:${template.asset_ref.asset.asset_id}`, assetType: 'skill', name: template.name, description: template.description || asset.description, sourceType: template.source_type, sourceId: template.source_id, version: template.version, asset });
    } else if (template.asset_type === 'report') {
      const asset = reports.find(item => item.report_id === localCode || item.asset_ref?.asset.asset_id === template.asset_ref.asset.asset_id);
      if (asset) templateCatalog.push({ key: `report:${template.asset_ref.asset.asset_id}`, assetType: 'report', name: template.name, description: template.description || asset.description, sourceType: template.source_type, sourceId: template.source_id, version: template.version, asset });
    }
  });
  templateCatalog.forEach(entry => catalogKeys.add(`${entry.assetType}:${entry.assetType === 'metric' ? entry.asset.metric_code : entry.assetType === 'skill' ? entry.asset.skill_id : entry.asset.report_id}`));
  officialMetrics.forEach(asset => { if (!catalogKeys.has(`metric:${asset.metric_code}`)) templateCatalog.push({ key: `metric:${asset.metric_code}`, assetType: 'metric', name: asset.name, description: asset.definition, sourceType: 'official_pack', sourceId: asset.asset_ref?.asset.source_id || 'official', version: asset.version || '1.0.0', asset }); });
  officialSkills.forEach(asset => { if (!catalogKeys.has(`skill:${asset.skill_id}`)) templateCatalog.push({ key: `skill:${asset.skill_id}`, assetType: 'skill', name: asset.name, description: asset.description, sourceType: 'official_pack', sourceId: asset.asset_ref?.asset.source_id || 'official', version: asset.version || '1.0.0', asset }); });
  officialReports.forEach(asset => { if (!catalogKeys.has(`report:${asset.report_id}`)) templateCatalog.push({ key: `report:${asset.report_id}`, assetType: 'report', name: asset.name, description: asset.description, sourceType: 'official_pack', sourceId: asset.asset_ref?.asset.source_id || 'official', version: asset.version || '1.0.0', asset }); });
  const activeTemplateType = activeSubTab === 'metrics' ? 'metric' : activeSubTab === 'skills' ? 'skill' : 'report';
  const normalizedTemplateSearch = templateSearch.trim().toLowerCase();
  const filteredTemplateCatalog = templateCatalog.filter(entry => entry.assetType === activeTemplateType && (templateSourceFilter === 'all' || entry.sourceType === templateSourceFilter) && (!normalizedTemplateSearch || `${entry.name} ${entry.description} ${entry.sourceId}`.toLowerCase().includes(normalizedTemplateSearch)));

  // Search logic
  const visibleCustomMetrics = customMetrics.filter(m => 
    m.name.toLowerCase().includes(metricSearch.toLowerCase()) || 
    m.metric_code.toLowerCase().includes(metricSearch.toLowerCase())
  );
  const visibleSharedMetrics = sharedMetrics.filter(m => 
    m.name.toLowerCase().includes(metricSearch.toLowerCase()) || 
    m.metric_code.toLowerCase().includes(metricSearch.toLowerCase())
  );
  const visibleOfficialMetrics = officialMetrics.filter(m => 
    m.name.toLowerCase().includes(metricSearch.toLowerCase()) || 
    m.metric_code.toLowerCase().includes(metricSearch.toLowerCase())
  );

  const visibleCustomSkills = customSkills.filter(s => 
    s.name.toLowerCase().includes(skillSearch.toLowerCase()) || 
    s.skill_id.toLowerCase().includes(skillSearch.toLowerCase())
  );
  const visibleSharedSkills = sharedSkills.filter(s => 
    s.name.toLowerCase().includes(skillSearch.toLowerCase()) || 
    s.skill_id.toLowerCase().includes(skillSearch.toLowerCase())
  );
  const visibleOfficialSkills = officialSkills.filter(s => 
    s.name.toLowerCase().includes(skillSearch.toLowerCase()) || 
    s.skill_id.toLowerCase().includes(skillSearch.toLowerCase())
  );

  const visibleCustomReports = customReports.filter(r => 
    r.name.toLowerCase().includes(reportSearch.toLowerCase()) || 
    r.report_id.toLowerCase().includes(reportSearch.toLowerCase())
  );
  const visibleSharedReports = sharedReports.filter(r => 
    r.name.toLowerCase().includes(reportSearch.toLowerCase()) || 
    r.report_id.toLowerCase().includes(reportSearch.toLowerCase())
  );
  const visibleOfficialReports = officialReports.filter(r => 
    r.name.toLowerCase().includes(reportSearch.toLowerCase()) || 
    r.report_id.toLowerCase().includes(reportSearch.toLowerCase())
  );

  type PersonalAssetRow = {
    id: string;
    type: 'metrics' | 'skills' | 'reports';
    label: string;
    name: string;
    description: string;
    updatedAt: string;
    source: string;
    asset: MetricDefinition | SkillDefinition | ReportDefinition;
  };

  const sourceFor = (asset: { asset_ref?: AssetRef | null }) => {
    const record = personalMetadataFor(asset);
    const template = record?.template_asset_ref;
    if (!template) return '空白新建';
    const pack = template.asset.source_id || '领域包';
    const templateName = runtimeTemplates.find(item => (
      item.asset_ref.asset.asset_id === template.asset.asset_id
      && item.asset_ref.version === template.version
    ))?.name || template.asset.local_code;
    return `${pack} · ${templateName}`;
  };

  const formatAssetTime = (value?: string | null) => {
    if (!value) return '—';
    const timestamp = new Date(value);
    if (Number.isNaN(timestamp.getTime())) return value;
    const twoDigits = (part: number) => String(part).padStart(2, '0');
    return `${timestamp.getFullYear()}-${twoDigits(timestamp.getMonth() + 1)}-${twoDigits(timestamp.getDate())} ${twoDigits(timestamp.getHours())}:${twoDigits(timestamp.getMinutes())}:${twoDigits(timestamp.getSeconds())}`;
  };

  const personalAssetRows: PersonalAssetRow[] = [
    ...customMetrics.map(metric => ({
      id: `metric_${metric.metric_code}`,
      type: 'metrics' as const,
      label: '指标',
      name: metric.name,
      description: metric.definition,
      updatedAt: formatAssetTime(personalMetadataFor(metric)?.created_at),
      source: sourceFor(metric),
      asset: metric,
    })),
    ...customSkills.map(skill => ({
      id: `skill_${skill.skill_id}`,
      type: 'skills' as const,
      label: '技能',
      name: skill.name,
      description: skill.description,
      updatedAt: formatAssetTime(personalMetadataFor(skill)?.created_at),
      source: sourceFor(skill),
      asset: skill,
    })),
    ...customReports.map(report => ({
      id: `report_${report.report_id}`,
      type: 'reports' as const,
      label: '报表',
      name: report.name,
      description: report.description,
      updatedAt: formatAssetTime(personalMetadataFor(report)?.created_at),
      source: sourceFor(report),
      asset: report,
    })),
  ].filter(row => (
    assetTypeFilter === 'all' || row.type === assetTypeFilter
  ) && `${row.name} ${row.description} ${row.source}`.toLowerCase().includes(assetSearch.toLowerCase()));

  const handleDeriveToCustom = async (assetType: 'metric' | 'skill' | 'report', assetId: string, name: string) => {
    setIsCloning(true);
    try {
      if (assetType === 'metric') {
        await api.copyMetric(assetId, { user_id: userContext.user_id });
        alert(`🎉 已成功复制 "${name}" 到您的个人自定义指标中！`);
      } else if (assetType === 'skill') {
        await api.copySkill(assetId, { user_id: userContext.user_id });
        alert(`🎉 已成功复制 "${name}" 到您的个人自定义技能中！`);
      } else if (assetType === 'report') {
        await api.copyReport(assetId, { user_id: userContext.user_id });
        alert(`🎉 已成功复制 "${name}" 到您的个人自定义报表中！`);
      }
      await onRefreshAll();
    } catch {
      alert('复制失败，请重试');
    } finally {
      setIsCloning(false);
    }
  };

  // --- Metric Handlers ---
  const handleOpenCreateMetric = () => {
    setTemplateSourceRef(null);
    setMetricDraft({
      name: '',
      definition: '',
      expression: '',
      numerator: '',
      denominator: '',
      filters: [],
      time_field: '',
      data_source_id: dataSources[0]?.data_source_id || 'oracle_tms',
      update_frequency: '',
      synonyms: '',
      visibility: 'private'
    });
    setMetricAdjustPrompt('');
    setMetricDependencies([]);
    setMetricPreviewResult(null);
    setMetricPreviewError(null);
    setMetricMode('create');
  };

  const applyMetricTemplate = (template: MetricDefinition) => {
    const sourceRef = runtimeTemplates.find(item => item.asset_type === 'metric' && item.asset_ref.asset.local_code === template.metric_code)?.asset_ref || template.asset_ref || null;
    openConversationCreation('metric', {
      name: `${template.name}（个人版）`,
      description: template.definition,
      expression: template.formula.expression,
      dataSourceId: template.data_source_id,
    }, sourceRef, template.name);
  };

  const handleOpenEditMetric = (metric: MetricDefinition) => {
    setSelectedMetric(metric);
    setMetricDraft({
      name: metric.name,
      definition: metric.definition,
      expression: metric.formula.expression,
      numerator: metric.formula.numerator || '',
      denominator: metric.formula.denominator || '',
      filters: metric.formula.filters || [],
      time_field: metric.formula.time_field || '',
      data_source_id: metric.data_source_id,
      update_frequency: metric.update_frequency || '',
      synonyms: (metric.synonyms || []).join('、'),
      visibility: metric.visibility === 'official' ? 'private' : metric.visibility
    });
    setMetricAdjustPrompt('');
    api.getMetricDependencies(metric.metric_code).then(setMetricDependencies).catch(() => setMetricDependencies([]));
    setMetricPreviewResult(null);
    setMetricPreviewError(null);
    setMetricMode('edit');
  };

  const handleAdjustMetricWithAi = async () => {
    if (!metricAdjustPrompt.trim()) return;
    setIsAdjustingMetric(true);
    try {
      const draft = await api.draftMetric({
        name: metricDraft.name || '新指标',
        natural_language_definition: [metricDraft.definition, metricAdjustPrompt].filter(Boolean).join('\n补充调整：'),
        user_id: userContext.user_id,
      });
      setMetricDraft(current => ({
        ...current,
        name: draft.name || current.name,
        definition: draft.explanation || current.definition,
        expression: draft.formula.expression || current.expression,
        numerator: draft.formula.numerator || '',
        denominator: draft.formula.denominator || '',
        filters: draft.formula.filters || [],
        time_field: draft.formula.time_field || '',
      }));
      setMetricAdjustPrompt('');
    } catch (error) {
      alert(`AI 调整失败：${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setIsAdjustingMetric(false);
    }
  };

  const handleRunMetricPreview = async () => {
    setIsRunningMetricPreview(true);
    setMetricPreviewResult(null);
    setMetricPreviewError(null);
    try {
      const question = [
        metricDraft.name || '预览指标',
        metricDraft.definition,
        metricPreviewTimeRange,
        metricPreviewFactory !== '全部厂区' ? metricPreviewFactory : '',
        '生成数据预览',
      ].filter(Boolean).join('，');
      
      const result = await api.askQuery({ 
        user_id: userContext.user_id, 
        text: question, 
        execute: true 
      });
      setMetricPreviewResult(result);
    } catch (err: unknown) {
      setMetricPreviewError(err instanceof Error ? err.message : '预览执行失败');
    } finally {
      setIsRunningMetricPreview(false);
    }
  };

  const handleSaveMetric = async () => {
    if (!metricDraft.name.trim() || !metricDraft.expression.trim()) {
      alert('请填写完整的指标名称和表达式');
      return;
    }
    setIsSavingMetric(true);
    try {
      if (metricMode === 'create') {
        const NLDef = `${metricDraft.name}: ${metricDraft.definition}`;
        const draftRes = await api.draftMetric({
          name: metricDraft.name.trim(),
          natural_language_definition: NLDef,
          user_id: userContext.user_id
        });
        
        const created = await api.createUserMetric({
          draft: {
            name: metricDraft.name.trim(),
            formula: {
              expression: metricDraft.expression.trim(),
              numerator: metricDraft.numerator.trim() || null,
              denominator: metricDraft.denominator.trim() || null,
              filters: metricDraft.filters,
              time_field: metricDraft.time_field.trim() || null
            },
            mapped_fields: draftRes.mapped_fields,
            explanation: metricDraft.definition,
            warnings: []
          },
          confirmed_by_user: true,
          visibility: metricDraft.visibility,
          user_id: userContext.user_id
        });
        await api.recordPersonalAssetProvenance({
          asset_type: 'metric', local_code: created.metric_code, name: created.name,
          data_source_id: metricDraft.data_source_id, template_asset_ref: templateSourceRef,
        });
        if (metricDraft.update_frequency || metricDraft.synonyms.trim()) {
          await api.updateMetric(created.metric_code, {
            user_id: userContext.user_id,
            update_frequency: metricDraft.update_frequency || null,
            synonyms: metricDraft.synonyms.split(/[、,，]/).map(item => item.trim()).filter(Boolean),
          });
        }
        alert('新建指标保存成功！');
      } else if (metricMode === 'edit' && selectedMetric) {
        await api.updateMetric(selectedMetric.metric_code, {
          user_id: userContext.user_id,
          name: metricDraft.name.trim(),
          definition: metricDraft.definition.trim(),
          formula: {
            expression: metricDraft.expression.trim(),
            numerator: metricDraft.numerator.trim() || null,
            denominator: metricDraft.denominator.trim() || null,
            filters: metricDraft.filters,
            time_field: metricDraft.time_field.trim() || null
          },
          update_frequency: metricDraft.update_frequency || null,
          synonyms: metricDraft.synonyms.split(/[、,，]/).map(item => item.trim()).filter(Boolean),
        });
        
        if (selectedMetric.visibility !== metricDraft.visibility) {
          await api.updateMetricVisibility(selectedMetric.metric_code, {
            visibility: metricDraft.visibility,
            user_id: userContext.user_id
          });
        }
        alert('指标更新成功！');
      }
      await onRefreshAll();
      setMetricMode('list');
    } catch (e) {
      alert('保存失败: ' + (e instanceof Error ? e.message : '未知错误'));
    } finally {
      setIsSavingMetric(false);
    }
  };

  const handleDeleteMetric = async (code: string) => {
    if (!await confirmAction('您确定要删除此指标吗？')) return;
    try {
      await api.deleteMetric(code, { user_id: userContext.user_id });
      alert('已成功删除指标！');
      await onRefreshAll();
    } catch {
      alert('删除失败');
    }
  };

  const handlePublishMetric = async (code: string, toPublish: boolean) => {
    try {
      await api.updateMetricVisibility(code, {
        visibility: toPublish ? 'shared' : 'private',
        user_id: userContext.user_id
      });
      alert(toPublish ? '指标已发布分享！' : '指标已取消分享！');
      await onRefreshAll();
    } catch {
      alert('操作失败');
    }
  };

  // --- Skill Handlers ---
  const handleOpenCreateSkill = () => {
    setTemplateSourceRef(null);
    setSkillDraft({
      skill_id: `skill_${Math.random().toString(36).substr(2, 6)}`,
      name: '',
      description: '',
      visibility: 'private',
      parameters: [
        { name: 'factory_name', data_type: 'VARCHAR', required: false, description: '厂区名称过滤', allowed_values: ['全部厂区', '厂区A', '厂区B'] },
        { name: 'carrier_name', data_type: 'VARCHAR', required: false, description: '承运商名称过滤', allowed_values: ['全部承运商', '顺丰速运', '京东物流'] }
      ]
    });
    setSkillPreviewResult(null);
    setSkillPreviewError(null);
    setSkillPrompt('');
    setSkillAdjustPrompt('');
    setSkillSchemaDraft(null);
    setSkillMode('create');
  };

  const applySkillTemplate = (template: SkillDefinition) => {
    const sourceRef = runtimeTemplates.find(item => item.asset_type === 'skill' && item.asset_ref.asset.local_code === template.skill_id)?.asset_ref || template.asset_ref || null;
    openConversationCreation('skill', { name: `${template.name}（个人版）`, description: template.description }, sourceRef, template.name);
  };

  const handleOpenEditSkill = (skill: SkillDefinition) => {
    setSelectedSkill(skill);
    setSkillDraft({
      skill_id: skill.skill_id,
      name: skill.name,
      description: skill.description,
      visibility: skill.visibility === 'official' ? 'private' : skill.visibility,
      parameters: skill.parameters.map(p => ({
        name: p.name,
        data_type: p.data_type,
        required: p.required,
        description: p.description || '',
        allowed_values: p.allowed_values || []
      }))
    });
    setSkillPreviewResult(null);
    setSkillPreviewError(null);
    setSkillPrompt(skill.description);
    const rawSchema = skill.output_schema?.schema as Partial<SkillSchemaDraft> | undefined;
    setSkillSchemaDraft(rawSchema?.sql ? { parameters: rawSchema.parameters || [], steps: rawSchema.steps || [], sql: rawSchema.sql, chartType: rawSchema.chartType || '表格' } : null);
    setSkillMode('edit');
  };

  const buildSkillSchema = async (adjustment?: string) => {
    const source = [skillDraft.name, skillDraft.description, skillPrompt].filter(Boolean).join(' ');
    if (!source.trim()) { alert('请先描述要创建的技能。'); return; }
    setIsBuildingSkillSchema(true);
    try {
      const schema = await api.draftSkillSchema({ user_id: userContext.user_id, name: skillDraft.name || '新技能', description: skillDraft.description || skillPrompt, prompt: skillPrompt || skillDraft.description, adjustment: adjustment || null });
      setSkillSchemaDraft(schema);
      setSkillDraft(current => ({ ...current, parameters: schema.parameters.map(p => ({ name: p.name, data_type: p.dataType, required: p.required, description: p.label, allowed_values: [] })) }));
      if (adjustment) setSkillAdjustPrompt('');
    } catch (error) {
      alert(`Skill Schema 生成失败：${error instanceof Error ? error.message : '未知错误'}`);
    } finally { setIsBuildingSkillSchema(false); }
  };

  const handleRunSkillPreview = async () => {
    setIsRunningSkillPreview(true);
    setSkillPreviewResult(null);
    setSkillPreviewError(null);
    try {
      if (!skillSchemaDraft) throw new Error('请先生成 Skill Schema');
      const result = await api.executeSkill({ user_id: userContext.user_id, question: `${skillDraft.name} ${skillPreviewFactory} ${skillPreviewCarrier}`, execute: true, skill: {
        skill_id: skillDraft.skill_id, namespace: 'custom', name: skillDraft.name || '待测试技能', skill_type: 'report', visibility: 'private', owner_user_id: userContext.user_id, description: skillDraft.description, parameters: skillDraft.parameters,
        output_schema: { chart: skillSchemaDraft.chartType, steps: skillSchemaDraft.steps, schema: skillSchemaDraft },
      } });
      if (isSkillClarification(result)) throw new Error(result.message);
      setSkillPreviewResult(result);
    } catch (e) {
      setSkillPreviewError(e instanceof Error ? e.message : '运行预览失败');
    } finally {
      setIsRunningSkillPreview(false);
    }
  };

  const handleSaveSkill = async () => {
    if (!skillDraft.name.trim() || !skillDraft.description.trim()) {
      alert('请填写技能名称和描述');
      return;
    }
    if (!skillSchemaDraft) {
      alert('请先生成并确认 Skill Schema');
      return;
    }
    setIsSavingSkill(true);
    try {
      const payload: SkillDefinition = {
        skill_id: skillDraft.skill_id,
        namespace: 'custom',
        name: skillDraft.name.trim(),
        skill_type: 'report',
        visibility: skillDraft.visibility,
        owner_user_id: userContext.user_id,
        description: skillDraft.description.trim(),
        parameters: skillDraft.parameters.map(p => ({
          name: p.name,
          data_type: p.data_type,
          required: p.required,
          description: p.description,
          allowed_values: p.allowed_values
        })),
        output_schema: skillSchemaDraft ? { chart: skillSchemaDraft.chartType, steps: skillSchemaDraft.steps, schema: skillSchemaDraft, lifecycle: 'solidified', creator: userContext.display_name, version: '1.0.0' } : undefined,
        synonyms: [skillDraft.name.trim()],
      };

      if (skillMode === 'create') {
        const created = await api.createSkill(payload, userContext.user_id);
        await api.recordPersonalAssetProvenance({
          asset_type: 'skill', local_code: created.skill_id, name: created.name,
          template_asset_ref: templateSourceRef,
        });
        alert('新建技能保存成功！');
      } else if (skillMode === 'edit' && selectedSkill) {
        await api.updateSkill(selectedSkill.skill_id, {
          user_id: userContext.user_id,
          name: skillDraft.name.trim(),
          description: skillDraft.description.trim(),
          parameters: payload.parameters,
          output_schema: payload.output_schema,
        });
        
        if (selectedSkill.visibility !== skillDraft.visibility) {
          await api.updateSkillVisibility(selectedSkill.skill_id, {
            visibility: skillDraft.visibility,
            user_id: userContext.user_id
          });
        }
        alert('技能更新成功！');
      }
      await onRefreshAll();
      setSkillMode('list');
    } catch {
      alert('保存失败');
    } finally {
      setIsSavingSkill(false);
    }
  };

  // --- Report Handlers ---
  const handleOpenCreateReport = () => {
    setTemplateSourceRef(null);
    setReportDraft({
      name: '',
      description: '',
      visibility: 'private',
      outputTypes: ['pptx'],
      channels: ['email'],
      flow: '',
      sections: [],
      tags: [],
      schedule: {
        mode: 'immediate',
        status: 'draft',
        sendAt: '',
        note: ''
      }
    });
    setReportTemplateMode('built_in');
    setReportTemplate('management_review');
    setReportTimeGrain('月度');
    setReportPresenter(userContext.display_name || '');
    setReportAudience('');
    setReportContent('');
    setReportBoundMetrics([]);
    setReportBoundSkills([]);
    setReportAiPlan(null);
    setReportAdjustment('');
    setReportPreviewVersion(0);
    setReportArtifact(null);
    setReportMode('create');
  };

  const applyReportTemplate = (template: ReportDefinition) => {
    const sourceRef = runtimeTemplates.find(item => item.asset_type === 'report' && item.asset_ref.asset.local_code === template.report_id)?.asset_ref || template.asset_ref || null;
    openConversationCreation('report', { name: `${template.name}（个人版）`, description: template.description }, sourceRef, template.name);
  };

  const handleOpenEditReport = (report: ReportDefinition) => {
    setSelectedReport(report);
    setReportDraft({
      name: report.name,
      description: report.description,
      visibility: report.visibility === 'official' ? 'private' : report.visibility,
      outputTypes: report.outputTypes || ['pptx'],
      channels: report.channels || ['email'],
      flow: report.flow || '',
      sections: report.sections || [],
      tags: report.tags || [],
      schedule: {
        mode: report.schedule?.mode || 'immediate',
        status: report.schedule?.status || 'draft',
        sendAt: report.schedule?.sendAt || '',
        note: report.schedule?.note || ''
      }
    });
    setReportPresenter(userContext.display_name || '');
    setReportContent(report.description);
    setReportAiPlan({ title: report.name, flow: report.flow, sections: report.sections, outline: report.sections });
    setReportPreviewVersion(report.outputTypes?.[0] === 'push' ? 0 : 1);
    setReportArtifact(null);
    setReportMode('edit');
  };

  const handleBuildReportPlan = async (adjustment = '') => {
    const outputType = reportDraft.outputTypes[0] || 'pptx';
    setIsBuildingReportPlan(true);
    try {
      const plan = await api.draftReportPlan({
        user_id: userContext.user_id,
        output_type: outputType,
        title: reportDraft.name || `${reportOutputLabels[outputType]} 报表`,
        background: [reportPresenter, reportAudience, reportContent].filter(Boolean).join('；'),
        prompt: [reportDraft.description, adjustment].filter(Boolean).join('\n补充调整：'),
        bound_metric_codes: reportBoundMetrics,
        bound_skill_ids: reportBoundSkills,
      });
      const next: ReportAiPlan = {
        title: typeof plan.title === 'string' ? plan.title : undefined,
        flow: typeof plan.flow === 'string' ? plan.flow : undefined,
        sections: Array.isArray(plan.sections) ? plan.sections.map(String) : undefined,
        outline: Array.isArray(plan.outline) ? plan.outline.map(String) : undefined,
        warnings: Array.isArray(plan.warnings) ? plan.warnings.map(String) : undefined,
      };
      setReportAiPlan(next);
      setReportDraft(current => ({ ...current, name: next.title || current.name, flow: next.flow || current.flow, sections: next.sections || current.sections }));
      setReportPreviewVersion(version => version + 1);
      setReportAdjustment('');
    } catch (error) {
      alert(`报表预览生成失败：${error instanceof Error ? error.message : '未知错误'}`);
    } finally { setIsBuildingReportPlan(false); }
  };

  const handleSaveReport = async () => {
    if (!reportDraft.name.trim() || !reportDraft.description.trim()) {
      alert('请填写报表名称和描述');
      return;
    }
    setIsSavingReport(true);
    try {
      const payload: ReportDefinition = {
        report_id: reportMode === 'create' ? `rep_${Math.random().toString(36).substr(2, 6)}` : selectedReport!.report_id,
        name: reportDraft.name.trim(),
        description: reportDraft.description.trim(),
        visibility: reportDraft.visibility,
        owner: userContext.user_id,
        outputTypes: reportDraft.outputTypes,
        channels: reportDraft.channels,
        flow: reportDraft.flow,
        sections: reportDraft.sections,
        tags: reportDraft.tags,
        version: '1.0.0',
        schedule: reportDraft.schedule
        ,analysis_chain: [
          ...reportBoundMetrics.map(code => ({ asset_type: 'metric', asset_id: code })),
          ...reportBoundSkills.map(id => ({ asset_type: 'skill', asset_id: id })),
        ],
        parameters: [{ name: 'time_grain', value: reportTimeGrain }, { name: 'presenter', value: reportPresenter }, { name: 'audience', value: reportAudience }, { name: 'template', value: reportTemplateMode === 'upload' ? 'uploaded' : reportTemplate }]
      };

      if (reportMode === 'create') {
        const created = await api.createReport(payload, userContext.user_id);
        await api.recordPersonalAssetProvenance({
          asset_type: 'report', local_code: created.report_id, name: created.name,
          template_asset_ref: templateSourceRef,
        });
        const outputType = reportDraft.outputTypes[0] || 'pptx';
        if (outputType === 'push' && reportDraft.schedule.mode === 'scheduled' && reportDraft.schedule.sendAt.trim()) {
          const job = await api.createScheduledJob({ user_id: userContext.user_id, entity_type: 'report_push', entity_id: created.report_id, schedule_text: reportDraft.schedule.sendAt, payload: { channels: reportDraft.channels, bound_metric_codes: reportBoundMetrics, bound_skill_ids: reportBoundSkills } });
          await api.updateReport(created.report_id, { user_id: userContext.user_id, schedule: { ...reportDraft.schedule, status: 'scheduled', taskId: job.job_id } });
          alert('报表与定时推送任务已创建！');
        } else if (outputType !== 'push') {
          const artifact = await api.generateReport(created.report_id, { user_id: userContext.user_id, output_type: outputType, title: payload.name, content: [reportContent, payload.flow, ...payload.sections].filter(Boolean).join('\n'), bound_metric_codes: reportBoundMetrics, bound_skill_ids: reportBoundSkills });
          setReportArtifact(artifact);
          alert(`${reportOutputLabels[outputType]} 报表已生成并保存！`);
        } else {
          alert('报表推送定义已保存！');
        }
      } else if (reportMode === 'edit' && selectedReport) {
        await api.updateReport(selectedReport.report_id, {
          user_id: userContext.user_id,
          name: reportDraft.name.trim(),
          description: reportDraft.description.trim(),
          flow: reportDraft.flow,
          outputTypes: reportDraft.outputTypes,
          channels: reportDraft.channels,
          schedule: reportDraft.schedule,
          sections: reportDraft.sections,
          tags: reportDraft.tags,
          analysis_chain: payload.analysis_chain,
          parameters: payload.parameters,
        });
        
        if (selectedReport.visibility !== reportDraft.visibility) {
          await api.updateReportVisibility(selectedReport.report_id, {
            visibility: reportDraft.visibility,
            user_id: userContext.user_id
          });
        }
        alert('报表修改成功！');
      }
      await onRefreshAll();
      if (reportDraft.outputTypes[0] === 'push' || reportMode === 'edit') setReportMode('list');
    } catch {
      alert('保存失败');
    } finally {
      setIsSavingReport(false);
    }
  };

  const handleDeleteReport = async (id: string) => {
    if (!await confirmAction('您确定要删除此报表模版吗？')) return;
    try {
      await api.deleteReport(id, { user_id: userContext.user_id });
      alert('删除报表成功！');
      await onRefreshAll();
    } catch {
      alert('删除失败');
    }
  };

  const handleCreateAssetFromModal = async () => {
    const name = newAssetDraft.name.trim();
    const description = newAssetDraft.description.trim();
    if (!name || (newAssetType !== 'metric' && !description) || (newAssetType === 'metric' && !newAssetDraft.expression.trim())) {
      alert(newAssetType === 'metric' ? '请填写指标名称和逻辑表达式' : '请填写名称和说明');
      return;
    }
    if (!editingAssetRow && newAssetType === 'metric' && !newAssetDraft.dataSourceId) {
      alert('请先在右侧对话中描述指标需求，让系统判断并说明使用的数据源。');
      return;
    }

    setIsCreatingAsset(true);
    try {
      const dependencyRefs = dependencyRefsFor(conversationCandidate);
      const testStatus = conversationPreviewResult ? 'passed' : conversationPreviewError ? 'failed' : 'not_run';
      const now = new Date().toISOString();
      const buildTrace = [
        ...creationConversation.map((message, index) => ({
          event_id: `evt_${Date.now()}_${index}`,
          event_type: message.role === 'user' ? 'user_intent' as const : message.testResult ? 'test' as const : message.slotResolution ? 'slot_resolution' as const : message.candidate ? 'draft' as const : 'plan' as const,
          title: message.role === 'user' ? '用户补充需求' : message.testResult ? '受控测试完成' : message.slotResolution ? '参数解析与澄清' : message.candidate ? '生成资产草案' : 'AI 规划',
          summary: message.content,
          created_at: now,
          payload: message.candidate ? { asset_type: message.candidate.assetType, name: message.candidate.name } : message.slotResolution ? { parameter_slots: message.slotResolution } : {},
        })),
        { event_id: `evt_confirm_${Date.now()}`, event_type: 'confirmation' as const, title: '用户人工确认保存', summary: '用户确认当前定义、依赖和测试状态后保存资产。', created_at: now, payload: { test_status: testStatus } },
      ];
      const validationEvidence = [{
        check: 'controlled_execution',
        status: conversationPreviewResult ? 'passed' as const : conversationPreviewError ? 'failed' as const : 'pending' as const,
        message: conversationPreviewResult ? '受控测试通过' : conversationPreviewError || '尚未运行受控测试',
        details: { tested_at: conversationPreviewResult || conversationPreviewError ? now : null },
      }];
      const parameterSlots = (conversationCandidate?.parameters || []).map(parameter => ({
        ...parameter,
        value: null,
        default_value: null,
        candidates: [],
        status: 'unresolved' as const,
        resolution_source: null,
      }));
      const dataSourceBindings = conversationCandidate?.dataSourceBindings || [];
      const executionContract = {
        asset_kind: newAssetType,
        parameter_slots: parameterSlots,
        dependency_refs: dependencyRefs,
        data_source_bindings: dataSourceBindings,
        steps: (conversationCandidate?.analysisChain || (conversationCandidate?.workflow || []).map((step, index) => ({ order: index + 1, kind: 'skill', label: step, input: '上一步分析证据', output: '分析证据', data_source_ids: dataSourceBindings.map(binding => binding.data_source_id) }))),
        logical_sql: conversationCandidate?.logicSql || conversationCandidate?.expression || null,
        summary_rule: newAssetType === 'skill' ? '基于每一步执行证据输出分析结论，并保留指标与查询引用。' : null,
        output_contract: {
          ...(conversationCandidate?.outputSchema || (newAssetType === 'report' ? { primary_output_type: 'html', derived_output_types: [] } : {})),
          definition_text: assetDefinitionText.trim(),
        },
      };
      if (editingAssetRow?.type === 'metrics') {
        const metric = editingAssetRow.asset as MetricDefinition;
        await api.updateMetric(metric.metric_code, {
          user_id: userContext.user_id,
          name,
          definition: description,
          formula: { ...metric.formula, expression: newAssetDraft.expression.trim() },
          execution_contract: executionContract,
          build_trace: buildTrace,
          validation_evidence: validationEvidence,
        });
      } else if (editingAssetRow?.type === 'skills') {
        const skill = editingAssetRow.asset as SkillDefinition;
        await api.updateSkill(skill.skill_id, {
          user_id: userContext.user_id,
          name,
          description,
          parameters: conversationCandidate?.parameters || skill.parameters,
          output_schema: conversationCandidate?.outputSchema || skill.output_schema,
          data_source_bindings: dataSourceBindings,
          execution_contract: executionContract,
          build_trace: buildTrace,
          validation_evidence: validationEvidence,
        });
      } else if (editingAssetRow?.type === 'reports') {
        const report = editingAssetRow.asset as ReportDefinition;
        await api.updateReport(report.report_id, {
          user_id: userContext.user_id,
          name,
          description,
          flow: conversationCandidate?.flow || report.flow,
          sections: conversationCandidate?.sections || report.sections,
          analysis_chain: conversationCandidate?.analysisChain || report.analysis_chain,
          parameters: conversationCandidate?.parameters || report.parameters,
          data_source_bindings: dataSourceBindings,
          execution_contract: executionContract,
          build_trace: buildTrace,
          validation_evidence: validationEvidence,
        });
      } else if (newAssetType === 'metric') {
        const draft = await api.draftMetric({
          name,
          natural_language_definition: `${name}: ${description}`,
          user_id: userContext.user_id,
        });
        const created = await api.createUserMetric({
          draft: {
            name,
            formula: { expression: newAssetDraft.expression.trim(), numerator: null, denominator: null, filters: [], time_field: null },
            mapped_fields: draft.mapped_fields,
            explanation: description,
            warnings: [],
            execution_contract: executionContract,
            build_trace: buildTrace,
            validation_evidence: validationEvidence,
          },
          confirmed_by_user: true,
          visibility: 'private',
          user_id: userContext.user_id,
          data_source_id: newAssetDraft.dataSourceId,
        });
        await api.recordPersonalAssetProvenance({
          asset_type: 'metric', local_code: created.metric_code, name: created.name,
          data_source_id: newAssetDraft.dataSourceId, template_asset_ref: templateSourceRef, dependency_refs: dependencyRefs,
        });
      } else if (newAssetType === 'skill') {
        const skillId = `skill_${Math.random().toString(36).slice(2, 8)}`;
        const created = await api.createSkill({
          skill_id: skillId,
          namespace: 'custom',
          name,
          skill_type: 'report',
          visibility: 'private',
          owner_user_id: userContext.user_id,
          description,
          parameters: conversationCandidate?.parameters || [],
          dependency_refs: dependencyRefs,
          data_source_bindings: dataSourceBindings,
          output_schema: {
            harness: {
              version: '1.0',
              asset_type: 'skill',
              input_schema: { parameters: conversationCandidate?.parameters || [] },
              workflow: conversationCandidate?.workflow || [],
              logic_sql: conversationCandidate?.logicSql || conversationCandidate?.expression || '',
              dependencies: conversationCandidate?.dependencyNodes || [],
              dependency_refs: dependencyRefs,
              data_source_bindings: dataSourceBindings,
              analysis_chain: conversationCandidate?.analysisChain || [],
              caliber: conversationCandidate?.caliber || description,
              output_schema: conversationCandidate?.outputSchema || {},
              execution_policy: { mode: 'controlled', timeout_seconds: 30, retries: 0 },
              test_status: testStatus,
            },
          },
          execution_contract: executionContract,
          build_trace: buildTrace,
          validation_evidence: validationEvidence,
        }, userContext.user_id);
        await api.recordPersonalAssetProvenance({ asset_type: 'skill', local_code: created.skill_id, name: created.name, data_source_id: dataSourceBindings[0]?.data_source_id, template_asset_ref: templateSourceRef, dependency_refs: dependencyRefs });
      } else {
        const created = await api.createReport({
          report_id: `rep_${Math.random().toString(36).slice(2, 8)}`,
          name,
          description,
          visibility: 'private',
          owner: userContext.user_id,
          outputTypes: ['html'],
          channels: ['email'],
          flow: conversationCandidate?.flow || '',
          sections: conversationCandidate?.sections || [],
          analysis_chain: conversationCandidate?.analysisChain || [],
          dependency_refs: dependencyRefs,
          data_source_bindings: dataSourceBindings,
          tags: [],
          version: '1.0.0',
          schedule: { mode: 'immediate', status: 'draft', sendAt: '', note: '' },
          execution_contract: executionContract,
          build_trace: buildTrace,
          validation_evidence: validationEvidence,
        }, userContext.user_id);
        await api.recordPersonalAssetProvenance({ asset_type: 'report', local_code: created.report_id, name: created.name, data_source_id: dataSourceBindings[0]?.data_source_id, template_asset_ref: templateSourceRef, dependency_refs: dependencyRefs });
      }
      await onRefreshAll();
      const workspaceId = userContext?.user_id;
      if (workspaceId) setPersonalAssetRecords(await api.getPersonalAssets(workspaceId));
      setNewAssetModalOpen(false);
      setEditingAssetRow(null);
    } catch (error) {
      alert(`创建失败：${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setIsCreatingAsset(false);
    }
  };

  const selectedTemplate = runtimeTemplates.find(template => (
    template.asset_ref.asset.asset_id === templateSourceRef?.asset.asset_id
    && template.asset_ref.version === templateSourceRef?.version
  ));

  const suggestedName = (intent: string, fallback: string) => {
    const plainText = asText(intent).replace(/\s+/g, ' ').trim();
    return plainText.length > 24 ? `${plainText.slice(0, 24)}…` : plainText || fallback;
  };

  const compactAssetName = (rawName: string | undefined | null, assetType: 'metric' | 'skill' | 'report') => {
    const fallback = assetType === 'metric' ? '新指标' : assetType === 'skill' ? '新分析技能' : '新分析报表';
    const withoutRequestPrefix = asText(rawName)
      .replace(/[“”"']/g, '')
      .replace(/^(?:请(?:帮我)?|帮我|我想要|我需要|需要|创建|新建|生成|设计|制作)(?:一个|一份|一套|一下)?/u, '')
      .replace(/^(?:用于|关于|针对)/u, '')
      .replace(/[。！？!?].*$/u, '')
      .replace(/\s+/g, '')
      .replace(/[…]+$/u, '')
      .trim();
    const corePhrase = withoutRequestPrefix
      .split(/[，,；;：:]/u)
      .map(part => part.trim())
      .find(Boolean) || withoutRequestPrefix;
    if (!corePhrase) return fallback;
    return Array.from(corePhrase).slice(0, 18).join('');
  };

  const inferConversationDataSource = (intent: string) => {
    if (dataSources.length === 0) return null;
    const normalized = intent.toLowerCase();
    const mentioned = dataSources.find(source => (
      normalized.includes(source.data_source_id.toLowerCase())
      || normalized.includes(source.name.toLowerCase())
      || (source.database_type && normalized.includes(source.database_type.toLowerCase()))
    ));
    if (mentioned) return { source: mentioned, reason: `对话或模型草案明确提到了「${mentioned.name}」或其数据库类型` };
    if (newAssetDraft.dataSourceId) {
      const inherited = dataSources.find(source => source.data_source_id === newAssetDraft.dataSourceId);
      if (inherited) return { source: inherited, reason: selectedTemplate ? '该领域包模板当前从此数据源解析' : '沿用当前资产上下文' };
    }
    if (dataSources.length === 1) return { source: dataSources[0], reason: '当前只有一个可用数据源' };
    return null;
  };

  const resolveHarnessDependencies = (text: string, extraNodes: HarnessDependencyNode[] = []) => {
    const normalized = text.toLowerCase();
    const nodes: HarnessDependencyNode[] = [];
    if (selectedTemplate) {
      nodes.push({
        id: selectedTemplate.asset_ref.asset.asset_id,
        label: selectedTemplate.name,
        kind: 'template',
        resolved: true,
        assetRef: selectedTemplate.asset_ref,
      });
    }
    const addReferencedAssets = <T extends { name: string; asset_ref?: AssetRef }>(
      assets: T[], kind: 'metric' | 'skill' | 'report', getCode: (asset: T) => string,
    ) => {
      assets.forEach(asset => {
        if (!asset.asset_ref) return;
        const name = asText(asset.name).trim().toLowerCase();
        const code = asText(getCode(asset)).trim().toLowerCase();
        if ((name && normalized.includes(name)) || (code && normalized.includes(code))) {
          nodes.push({ id: asset.asset_ref.asset.asset_id, label: asset.name, kind, resolved: true, assetRef: asset.asset_ref });
        }
      });
    };
    addReferencedAssets(metrics, 'metric', asset => (asset as MetricDefinition).metric_code);
    addReferencedAssets(skills, 'skill', asset => (asset as SkillDefinition).skill_id);
    addReferencedAssets(reports, 'report', asset => (asset as ReportDefinition).report_id);
    const deduplicated = new Map<string, HarnessDependencyNode>();
    [...nodes, ...extraNodes].forEach(node => deduplicated.set(`${node.kind}:${node.id}`, node));
    return [...deduplicated.values()];
  };

  const dependencyRefsFor = (candidate: ConversationCandidate | null) => {
    const references = candidate?.dependencyNodes?.flatMap(node => node.assetRef ? [node.assetRef] : []) || [];
    return [...new Map(references.map(reference => [reference.asset.asset_id, reference])).values()];
  };

  const resolveDataSourceBindings = (
    text: string,
    nodes: HarnessDependencyNode[] = [],
    primaryDataSourceId?: string,
    assetType: ConversationCandidate['assetType'] = 'metric',
    allowInference = true,
  ): DataSourceBinding[] => {
    const bindings: DataSourceBinding[] = [];
    const addBinding = (dataSourceId: string | undefined, role: DataSourceBinding['role'], reason: string) => {
      if (!dataSourceId) return;
      const source = dataSources.find(item => item.data_source_id === dataSourceId);
      bindings.push({
        data_source_id: dataSourceId,
        name: source?.name || dataSourceId,
        role,
        reason,
      });
    };
    addBinding(primaryDataSourceId, 'primary', '当前草案直接读取的数据源');
    const inferred = allowInference && assetType !== 'report' ? inferConversationDataSource(text) : null;
    if (!primaryDataSourceId && inferred) addBinding(inferred.source.data_source_id, 'primary', inferred.reason);
    nodes.forEach(node => {
      if (!node.assetRef) return;
      if (node.kind === 'metric') {
        const metric = metrics.find(item => item.asset_ref?.asset.asset_id === node.assetRef?.asset.asset_id);
        addBinding(metric?.data_source_id, 'inherited', `继承指标「${node.label}」的数据源`);
      }
      if (node.kind === 'skill') {
        const skill = skills.find(item => item.asset_ref?.asset.asset_id === node.assetRef?.asset.asset_id);
        (skill?.data_source_bindings || []).forEach(binding => addBinding(binding.data_source_id, 'inherited', `继承技能「${node.label}」的数据源`));
      }
      if (node.kind === 'report') {
        const report = reports.find(item => item.asset_ref?.asset.asset_id === node.assetRef?.asset.asset_id);
        (report?.data_source_bindings || []).forEach(binding => addBinding(binding.data_source_id, 'inherited', `继承报表「${node.label}」的数据源`));
      }
    });
    return [...new Map(bindings.map(binding => [binding.data_source_id, binding])).values()];
  };

  const inheritedBindingsFor = (nodes: HarnessDependencyNode[]): DataSourceBinding[] => {
    const bindings: DataSourceBinding[] = [];
    const add = (dataSourceId: string | undefined, name: string | undefined, reason: string) => {
      if (!dataSourceId) return;
      bindings.push({ data_source_id: dataSourceId, name: name || dataSources.find(source => source.data_source_id === dataSourceId)?.name || dataSourceId, role: 'inherited', reason });
    };
    nodes.forEach(node => {
      if (!node.assetRef) return;
      if (node.kind === 'metric') {
        const metric = metrics.find(item => item.asset_ref?.asset.asset_id === node.assetRef?.asset.asset_id);
        add(metric?.data_source_id, undefined, `继承指标「${node.label}」的数据源`);
      }
      if (node.kind === 'skill') {
        const skill = skills.find(item => item.asset_ref?.asset.asset_id === node.assetRef?.asset.asset_id);
        skill?.data_source_bindings?.forEach(binding => add(binding.data_source_id, binding.name, `继承技能「${node.label}」的数据源`));
      }
    });
    return [...new Map(bindings.map(binding => [binding.data_source_id, binding])).values()];
  };

  const buildAnalysisChain = (candidate: ConversationCandidate, bindings: DataSourceBinding[]) => {
    const sourceIds = bindings.map(binding => binding.data_source_id);
    if (candidate.assetType === 'metric') {
      return [{ order: 1, kind: 'semantic' as const, label: '语义字段与 SQL 验证', input: '标准字段、指标口径与默认时间范围', output: '受控 SQL 与指标值', data_source_ids: sourceIds }];
    }
    if (candidate.assetType === 'skill') {
      const workflow = candidate.workflow?.length ? candidate.workflow : ['读取依赖资产并输出分析结论'];
      return workflow.map((step, index) => ({
        order: index + 1,
        kind: 'skill' as const,
        label: step,
        input: index === 0 ? '指标/技能依赖、参数插槽与语义字段' : '上一步分析证据',
        output: index === workflow.length - 1 ? '可追溯分析结论' : '中间分析证据',
        data_source_ids: sourceIds,
      }));
    }
    return [
      { order: 1, kind: 'report' as const, label: '汇集指标与技能结果', input: '已绑定指标、技能及其执行证据', output: '报告数据模型', data_source_ids: sourceIds },
      { order: 2, kind: 'report' as const, label: '编排报告章节', input: (candidate.sections || []).join('、') || '报告章节定义', output: '完整 HTML 报告', data_source_ids: sourceIds },
      { order: 3, kind: 'delivery' as const, label: '发布 HTML 报告', input: 'HTML 主产物', output: '可预览、可分享的 HTML 报告', data_source_ids: [] },
    ];
  };

  const updateConversationCandidate = (updater: (candidate: ConversationCandidate) => ConversationCandidate) => {
    setConversationCandidate(current => current ? updater(current) : current);
  };

  const addCandidateDataSource = (dataSourceId: string) => {
    const source = dataSources.find(item => item.data_source_id === dataSourceId);
    if (!source) return;
    updateConversationCandidate(candidate => {
      if (candidate.dataSourceBindings?.some(binding => binding.data_source_id === dataSourceId)) return candidate;
      return {
        ...candidate,
        dataSourceBindings: [...(candidate.dataSourceBindings || []), {
          data_source_id: source.data_source_id,
          name: source.name,
          role: 'primary',
          reason: '由用户在资产定义中补充',
        }],
      };
    });
  };

  const toggleCandidateDependency = (kind: 'metric' | 'skill', assetId: string) => {
    const asset = kind === 'metric'
      ? metrics.find(item => item.asset_ref?.asset.asset_id === assetId)
      : skills.find(item => item.asset_ref?.asset.asset_id === assetId);
    if (!asset?.asset_ref) return;
    updateConversationCandidate(candidate => {
      const nodes = candidate.dependencyNodes || [];
      const exists = nodes.some(node => node.kind === kind && node.id === assetId);
      const dependencyNodes = exists
        ? nodes.filter(node => !(node.kind === kind && node.id === assetId))
        : [...nodes, { id: assetId, label: asset.name, kind, resolved: true, assetRef: asset.asset_ref }];
      const inheritedBindings = inheritedBindingsFor(dependencyNodes);
      return {
        ...candidate,
        dependencyNodes,
        dataSourceBindings: candidate.assetType === 'report'
          ? inheritedBindings
          : [...(candidate.dataSourceBindings || []).filter(binding => binding.role !== 'inherited'), ...inheritedBindings],
      };
    });
  };

  const updateCandidateChainStep = (index: number, patch: Partial<NonNullable<ConversationCandidate['analysisChain']>[number]>) => {
    updateConversationCandidate(candidate => ({
      ...candidate,
      analysisChain: (candidate.analysisChain || []).map((step, stepIndex) => stepIndex === index ? { ...step, ...patch } : step),
    }));
  };

  const addCandidateChainStep = () => {
    updateConversationCandidate(candidate => ({
      ...candidate,
      analysisChain: [...(candidate.analysisChain || []), {
        order: (candidate.analysisChain?.length || 0) + 1,
        kind: candidate.assetType === 'report' ? 'report' : 'skill',
        label: '新增分析步骤',
        input: '待补充输入',
        output: '待补充输出',
        data_source_ids: (candidate.dataSourceBindings || []).map(binding => binding.data_source_id),
      }],
    }));
  };

  const moveCandidateChainStep = (from: number, to: number) => {
    if (from === to) return;
    updateConversationCandidate(candidate => {
      const steps = [...(candidate.analysisChain || [])];
      const [moved] = steps.splice(from, 1);
      steps.splice(to, 0, moved);
      return { ...candidate, analysisChain: steps.map((step, index) => ({ ...step, order: index + 1 })) };
    });
  };

  const renderHarnessCandidate = (candidate: ConversationCandidate) => (
    <div className="mt-4 space-y-3 border-t border-slate-200 pt-3 dark:border-slate-700">
      <p className="text-[10px] font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-300">本轮 {candidate.assetType === 'skill' ? '分析 Skill' : candidate.assetType === 'metric' ? '可追溯指标' : 'HTML 报表'}草案</p>
      <p className="font-semibold">{candidate.name}</p>
      <div className="text-[11px]"><p className="mb-1 font-semibold text-slate-500">业务口径</p><p>{candidate.caliber || candidate.description}</p></div>
      {candidate.dataSourceBindings && candidate.dataSourceBindings.length > 0 && <div className="text-[11px]"><p className="mb-1 font-semibold text-slate-500">数据源绑定</p><p>{candidate.dataSourceBindings.map(binding => `${binding.name}（${binding.role === 'primary' ? '直接读取' : '依赖继承'}）`).join(' · ')}</p></div>}
      <div><p className="mb-1 font-semibold text-slate-500">{candidate.artifactTitle}</p><pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 text-[10px] leading-relaxed text-slate-100">{candidate.artifactContent}</pre></div>
      {candidate.parameters && candidate.parameters.length > 0 && <div className="text-[11px]"><p className="mb-1 font-semibold text-slate-500">运行参数插槽</p><p>{candidate.parameters.map(parameter => `${parameter.description || parameter.name}${parameter.required ? '（必填，缺失时对话澄清）' : '（可选）'}`).join(' · ')}</p></div>}
      <div className="space-y-3">
        <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">依赖关系与执行链路</p>
        <div className="flex flex-wrap items-center gap-1.5">
          {(candidate.dependencyNodes || []).map((node, index) => <React.Fragment key={`${node.kind}:${node.id}`}><span className={`rounded-md border px-2 py-1 text-[10px] font-semibold ${node.resolved ? 'border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900 dark:bg-indigo-950/30 dark:text-indigo-300' : 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300'}`}>{node.label}<span className="ml-1 opacity-60">{node.resolved ? '资产引用' : '结构节点'}</span></span>{index < (candidate.dependencyNodes?.length || 0) - 1 && <span className="text-slate-300">→</span>}</React.Fragment>)}
          {(candidate.dependencyNodes || []).length > 0 && <span className="text-slate-300">→</span>}
          <span className="rounded-md bg-indigo-600 px-2 py-1 text-[10px] font-bold text-white">{candidate.name}</span>
        </div>
        <p className="text-[10px] text-slate-400">已解析资产使用版本化 AssetRef；结构节点与参数插槽随资产一并保存。</p>
        {candidate.analysisChain && candidate.analysisChain.length > 0 && <ol className="space-y-1 text-[10px] text-slate-500 dark:text-slate-400">{candidate.analysisChain.map(step => <li key={`${step.order}_${step.label}`}>{step.order}. {step.label}：{step.input} → {step.output}{step.data_source_ids.length ? `（${step.data_source_ids.join('、')}）` : ''}</li>)}</ol>}
      </div>
      <div className="flex flex-wrap justify-end gap-2 border-t border-slate-200 pt-3 dark:border-slate-700">
        <button type="button" onClick={() => void handleTestConversationDraft(candidate)} disabled={isTestingConversationDraft} className="rounded-lg border border-slate-200 px-3 py-1.5 text-[10px] font-bold text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800">{isTestingConversationDraft && conversationCandidate === candidate ? '测试中…' : '运行受控测试'}</button>
        <button type="button" onClick={() => applyConversationCandidate(candidate)} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-[10px] font-bold text-white hover:bg-indigo-700">同步到左侧</button>
      </div>
    </div>
  );

  const handleGenerateConversationCandidate = async () => {
    const intent = assetIntent.trim();
    if (!intent) {
      setCreationError('请先用一句话说明想解决的分析问题。');
      return;
    }
    setCreationError(null);
    setConversationPreviewResult(null);
    setConversationPreviewError(null);
    setIsGeneratingCandidate(true);
    const templateHint = selectedTemplate ? `；参考领域包模板「${selectedTemplate.name}」` : '';
    const historyContext = creationConversation
      .slice(-10)
      .map(message => `${message.role === 'user' ? '用户' : '助手'}：${message.content}${message.candidate ? `\n${message.candidate.artifactTitle}：${message.candidate.artifactContent}` : ''}`)
      .join('\n');
    setCreationConversation(messages => [...messages, { id: `user_${Date.now()}`, role: 'user', content: intent }]);
    setAssetIntent('');
    try {
      let candidate: ConversationCandidate;
      if (newAssetType === 'metric') {
        if (dataSources.length === 0) throw new Error('当前没有可用数据源，请先由管理员配置数据源后再创建指标。');
        const availableDataSources = dataSources.map(source => `${source.data_source_id}=${source.name}(${source.database_type})`).join('；');
        const draft = await api.draftMetric({
          name: selectedTemplate ? `${selectedTemplate.name}（个人版）` : suggestedName(intent, '新指标'),
          natural_language_definition: `${historyContext}\n本轮补充：${intent}${templateHint}\n若用户没有指定时间范围，默认使用本月并将时间筛选写入 SQL；若明确要求周粒度，则默认使用本周。\n可用数据源：${availableDataSources}。请根据业务描述选择最合适的数据源，并在解释中明确说明。`,
          user_id: userContext.user_id,
        });
        const inferredDataSource = inferConversationDataSource(`${intent}\n${draft.explanation || ''}`);
        if (!inferredDataSource) throw new Error('模型未能判断可用数据源，请在对话中明确指定数据源名称。');
        if (!draft.formula.expression) {
          throw new Error('未生成可确认的指标表达式，请补充统计口径或选择模板。');
        }
        candidate = {
          assetType: 'metric',
          name: draft.name || suggestedName(intent, '新指标'),
          description: draft.explanation || intent,
          expression: draft.formula.expression,
          logicSql: draft.formula.expression,
          artifactTitle: '逻辑 SQL 片段',
          artifactContent: draft.formula.expression,
          dependencyNodes: resolveHarnessDependencies(
            `${intent}\n${draft.formula.expression}`,
            draft.mapped_fields.map(fieldId => ({ id: fieldId, label: fieldId, kind: 'field', resolved: false })),
          ),
          caliber: draft.explanation || intent,
          outputSchema: { value_type: 'number', mapped_fields: draft.mapped_fields },
          dataSourceId: inferredDataSource.source.data_source_id,
          dataSourceName: inferredDataSource.source.name,
          dataSourceReason: inferredDataSource.reason,
        };
      } else if (newAssetType === 'skill') {
        const draft = await api.draftSkillSchema({
          user_id: userContext.user_id,
          name: selectedTemplate ? `${selectedTemplate.name}（个人版）` : suggestedName(intent, '新分析技能'),
          description: intent,
          prompt: `${historyContext}\n本轮补充：${intent}${templateHint}`,
        });
        const parameters = draft.parameters.map(parameter => ({
          name: parameter.name,
          data_type: parameter.dataType,
          required: parameter.required,
          description: parameter.label,
          allowed_values: [],
        }));
        candidate = {
          assetType: 'skill',
          name: selectedTemplate ? `${selectedTemplate.name}（个人版）` : suggestedName(intent, '新分析技能'),
          description: intent,
          expression: '',
          logicSql: draft.sql,
          artifactTitle: 'Skill 执行链路',
          artifactContent: [
            draft.sql ? `SQL 逻辑：\n${draft.sql}` : '',
            draft.steps.length ? `执行步骤：\n${draft.steps.map((step, index) => `${index + 1}. ${step}`).join('\n')}` : '',
          ].filter(Boolean).join('\n\n') || '已生成 Skill Schema。',
          parameters,
          workflow: draft.steps,
          dependencies: [
            ...(selectedTemplate ? [`领域包模板：${selectedTemplate.name}`] : []),
            ...parameters.map(parameter => `运行参数：${parameter.name}`),
          ],
          dependencyNodes: resolveHarnessDependencies(
            `${intent}\n${draft.sql}\n${draft.steps.join('\n')}`,
            parameters.map(parameter => ({ id: parameter.name, label: parameter.description || parameter.name, kind: 'parameter', resolved: false })),
          ),
          caliber: intent,
          outputSchema: { chart_type: draft.chartType, result_type: 'query_result' },
        };
      } else {
        const plan = await api.draftReportPlan({
          user_id: userContext.user_id,
          output_type: 'html',
          title: selectedTemplate ? `${selectedTemplate.name}（个人版）` : suggestedName(intent, '新分析报表'),
          background: intent,
          prompt: `${historyContext}\n本轮补充：${intent}${templateHint}`,
        });
        const name = typeof plan.title === 'string' ? plan.title : (selectedTemplate ? `${selectedTemplate.name}（个人版）` : suggestedName(intent, '新分析报表'));
        const sections = Array.isArray(plan.sections) ? plan.sections.map(String) : [];
        const flow = typeof plan.flow === 'string' ? plan.flow : '';
        candidate = {
          assetType: 'report',
          name,
          description: intent,
          expression: '',
          artifactTitle: '报表计划',
          artifactContent: [flow ? `执行流程：${flow}` : '', sections.length ? `章节结构：\n${sections.map((section, index) => `${index + 1}. ${section}`).join('\n')}` : '已生成报表计划。'].filter(Boolean).join('\n\n'),
          flow,
          sections,
          workflow: sections,
          dependencyNodes: resolveHarnessDependencies(
            `${intent}\n${flow}\n${sections.join('\n')}`,
            [
              { id: 'html', label: 'HTML 主产物', kind: 'delivery', resolved: true },
            ],
          ),
          caliber: intent,
          outputSchema: { primary_output_type: 'html', derived_output_types: [], report_style: 'management', sections },
        };
      }
      const dataSourceBindings = resolveDataSourceBindings(
        `${intent}\n${candidate.logicSql || ''}\n${candidate.workflow?.join('\n') || ''}`,
        candidate.dependencyNodes || [],
        candidate.dataSourceId,
        candidate.assetType,
        candidate.assetType === 'metric' || (candidate.assetType === 'skill' && Boolean(candidate.logicSql?.trim())),
      );
      candidate = {
        ...candidate,
        dataSourceBindings,
        analysisChain: buildAnalysisChain(candidate, dataSourceBindings),
      };
      const latestCandidate = [...creationConversation].reverse().find(message => message.candidate)?.candidate || conversationCandidate;
      candidate = mergeCandidateDraft(latestCandidate, candidate);
      setCreationConversation(messages => [...messages, {
        id: `assistant_${Date.now()}`,
        role: 'assistant',
        content: `我已根据本轮需求生成「${candidate.name}」的${candidate.artifactTitle}。${candidate.dataSourceBindings?.length ? `\n数据源：${candidate.dataSourceBindings.map(binding => binding.name).join('、')}。` : ''}${candidate.dataSourceName ? `\n数据源判断：${candidate.dataSourceName}。${candidate.dataSourceReason}。` : ''}\n当前仅为候选，尚未修改左侧；请先审阅或运行受控测试，再决定是否同步。`,
        candidate,
      }]);
    } catch (error) {
      const message = error instanceof Error ? error.message : '生成候选失败，请补充描述后重试。';
      setCreationError(message);
      setCreationConversation(messages => [...messages, { id: `error_${Date.now()}`, role: 'assistant', content: message, error: true }]);
    } finally {
      setIsGeneratingCandidate(false);
    }
  };

  const applyConversationCandidate = (candidate = conversationCandidate) => {
    if (!candidate) return;
    setConversationCandidate(candidate);
    setAssetDefinitionText(formatCandidateDefinition(candidate));
    setNewAssetDraft(current => ({
      ...current,
      name: compactAssetName(candidate.name, candidate.assetType),
      description: asText(candidate.description),
      expression: asText(candidate.expression),
      dataSourceId: candidate.dataSourceId || current.dataSourceId,
    }));
  };

  const handleTestConversationDraft = async (candidate = conversationCandidate) => {
    const targetType = candidate?.assetType || newAssetType;
    const targetName = asText(candidate?.name || newAssetDraft.name);
    const targetDescription = asText(candidate?.description || newAssetDraft.description);
    const targetExpression = asText(candidate?.expression || newAssetDraft.expression);
    if (!targetName.trim() || !targetDescription.trim() || (targetType === 'metric' && !targetExpression.trim())) {
      setConversationPreviewError(targetType === 'metric' ? '请先生成完整的指标名称、说明和逻辑表达式。' : '请先生成完整的名称和业务说明。');
      return;
    }
    setConversationPreviewError(null);
    setConversationPreviewResult(null);
    setIsTestingConversationDraft(true);
    try {
      const conversationContext = creationConversation
        .filter(message => message.role === 'user')
        .map(message => message.content)
        .join('；');
      const defaultTimeRange = /周|weekly/i.test(`${targetName} ${targetDescription} ${candidate?.workflow?.join(' ') || ''}`) ? '本周' : '本月';
      const result = targetType === 'skill' && candidate
        ? await api.executeSkill({
          user_id: userContext.user_id,
          question: `${targetName}：${targetDescription}。对话上下文：${conversationContext}。请基于此 Skill 的执行链路进行受控测试执行。`,
          skill: {
            skill_id: 'skill_draft_preview',
            namespace: 'draft',
            name: targetName,
            skill_type: 'report',
            visibility: 'private',
            owner_user_id: userContext.user_id,
            description: targetDescription,
            parameters: candidate.parameters || [],
            output_schema: {
              harness: {
                workflow: candidate.workflow || [],
                logic_sql: candidate.logicSql || candidate.expression || '',
                dependencies: candidate.dependencyNodes || [],
                caliber: candidate.caliber || targetDescription,
                output_schema: candidate.outputSchema || {},
                execution_policy: { mode: 'controlled', timeout_seconds: 30, retries: 0 },
              },
            },
          },
          execute: true,
        })
        : await api.testAssetDraft({
          user_id: userContext.user_id,
          asset_type: targetType,
          name: targetName,
          description: targetDescription,
          logical_sql: candidate?.logicSql || targetExpression || null,
          execute: true,
          data_source_id: candidate?.dataSourceId,
          conversation_context: conversationContext,
          default_time_range: defaultTimeRange,
        });
      if (isSkillClarification(result)) {
        setConversationPreviewError(result.message);
        setCreationConversation(messages => [...messages, {
          id: `slot_${Date.now()}`,
          role: 'assistant',
          content: `${result.message}\n请直接在下方对话中补充参数；确认后我会重新解析并继续测试。`,
          slotResolution: result.parameter_slots,
        }]);
      } else {
        setConversationPreviewResult(result);
        setCreationConversation(messages => [...messages, {
          id: `test_${Date.now()}`,
          role: 'assistant',
          content: `受控测试已完成。默认时间规则为${defaultTimeRange}；是否已写入当前 SQL 请以下方执行说明为准。真实查询结果和执行证据会随资产构建记录保存。`,
          testResult: result,
        }]);
      }
    } catch (error) {
      const message = describeApiError(error, '测试执行失败。');
      setConversationPreviewError(message);
      setCreationConversation(messages => [...messages, { id: `test_error_${Date.now()}`, role: 'assistant', content: `受控测试失败：${message}`, error: true }]);
    } finally {
      setIsTestingConversationDraft(false);
    }
  };

  const openAssetEditor = (row: PersonalAssetRow) => {
    setEditingAssetRow(row);
    setTemplateSourceRef(null);
    setAssetIntent('');
    setCreationError(null);
    setConversationPreviewResult(null);
    setConversationPreviewError(null);
    setIsEditingAssetStructure(false);
    const asset = row.asset as MetricDefinition | SkillDefinition | ReportDefinition;
    const contract = asset.execution_contract;
    const dependencyRefs = asset.dependency_refs || [];
    const dependencyNodes: HarnessDependencyNode[] = dependencyRefs.map(reference => {
      const kind = reference.asset.asset_type;
      const matched = kind === 'metric'
        ? metrics.find(item => item.asset_ref?.asset.asset_id === reference.asset.asset_id)
        : kind === 'skill'
          ? skills.find(item => item.asset_ref?.asset.asset_id === reference.asset.asset_id)
          : reports.find(item => item.asset_ref?.asset.asset_id === reference.asset.asset_id);
      return { id: reference.asset.asset_id, label: matched?.name || reference.asset.local_code, kind, resolved: true, assetRef: reference };
    });
    const analysisChain = (contract?.steps || []).map((step, index) => ({
      order: Number(step.order) || index + 1,
      kind: (['semantic', 'metric', 'skill', 'report', 'delivery'].includes(asText(step.kind)) ? step.kind : row.type === 'metrics' ? 'semantic' : row.type === 'skills' ? 'skill' : 'report') as 'semantic' | 'metric' | 'skill' | 'report' | 'delivery',
      label: asText(step.label) || `步骤 ${index + 1}`,
      input: asText(step.input) || '上一步执行证据',
      output: asText(step.output) || '可追溯结果',
      data_source_ids: Array.isArray(step.data_source_ids) ? step.data_source_ids.map(String) : [],
    }));
    let candidate: ConversationCandidate;
    if (row.type === 'metrics') {
      const metric = row.asset as MetricDefinition;
      setNewAssetType('metric');
      setNewAssetDraft({ name: metric.name, description: metric.definition, expression: metric.formula.expression, dataSourceId: metric.data_source_id });
      candidate = {
        assetType: 'metric', name: metric.name, description: metric.definition, expression: metric.formula.expression,
        logicSql: contract?.logical_sql || metric.formula.expression, artifactTitle: '逻辑 SQL 片段', artifactContent: contract?.logical_sql || metric.formula.expression,
        caliber: metric.definition, dependencyNodes, dataSourceId: metric.data_source_id,
        dataSourceBindings: contract?.data_source_bindings?.length ? contract.data_source_bindings : [{ data_source_id: metric.data_source_id, name: dataSources.find(source => source.data_source_id === metric.data_source_id)?.name || metric.data_source_id, role: 'primary', reason: '指标直接读取的数据源' }],
        analysisChain, outputSchema: contract?.output_contract || {},
      };
    } else if (row.type === 'skills') {
      const skill = row.asset as SkillDefinition;
      setNewAssetType('skill');
      setNewAssetDraft({ name: skill.name, description: skill.description, expression: '', dataSourceId: '' });
      candidate = {
        assetType: 'skill', name: skill.name, description: skill.description, expression: '', logicSql: contract?.logical_sql || '',
        artifactTitle: 'Skill 执行链路', artifactContent: contract?.logical_sql || analysisChain.map(step => `${step.order}. ${step.label}`).join('\n') || skill.description,
        parameters: skill.parameters.map(parameter => ({ ...parameter, description: parameter.description || undefined })), workflow: analysisChain.map(step => step.label), caliber: skill.description, dependencyNodes,
        dataSourceBindings: skill.data_source_bindings || contract?.data_source_bindings || [], analysisChain,
        outputSchema: { ...(skill.output_schema || {}), ...(contract?.output_contract || {}) },
      };
    } else {
      const report = row.asset as ReportDefinition;
      setNewAssetType('report');
      setNewAssetDraft({ name: report.name, description: report.description, expression: '', dataSourceId: '' });
      candidate = {
        assetType: 'report', name: report.name, description: report.description, expression: '',
        artifactTitle: '报表计划', artifactContent: [report.flow, ...report.sections].filter(Boolean).join('\n'),
        flow: report.flow, sections: report.sections, workflow: report.sections, caliber: report.description, dependencyNodes,
        dataSourceBindings: report.data_source_bindings || contract?.data_source_bindings || [],
        analysisChain: analysisChain.length ? analysisChain : (report.analysis_chain || []).map((step, index) => ({ order: index + 1, kind: 'report' as const, label: asText(step.label) || `步骤 ${index + 1}`, input: asText(step.input), output: asText(step.output), data_source_ids: Array.isArray(step.data_source_ids) ? step.data_source_ids.map(String) : [] })),
        parameters: (report.parameters || []).map(parameter => ({ name: asText(parameter.name), data_type: asText(parameter.data_type) || 'string', required: Boolean(parameter.required), description: asText(parameter.description), allowed_values: Array.isArray(parameter.allowed_values) ? parameter.allowed_values.map(String) : [] })),
        outputSchema: { primary_output_type: 'html', derived_output_types: report.outputTypes.filter(type => type !== 'html' && type !== 'push'), ...(contract?.output_contract || {}) },
      };
    }
    setConversationCandidate(candidate);
    setAssetDefinitionText(formatCandidateDefinition(candidate));
    setCreationConversation([{ id: `edit_${Date.now()}`, role: 'assistant', content: `已载入当前保存的「${candidate.name}」完整定义。你可以继续在下方对话中提出修改；生成候选后，请人工同步到左侧。`, candidate }]);
    setNewAssetModalOpen(true);
  };

  const handleDeleteAsset = async (row: PersonalAssetRow) => {
    if (!await confirmAction(`确定删除“${row.name}”吗？此操作不可恢复。`)) return;
    try {
      if (row.type === 'metrics') await api.deleteMetric((row.asset as MetricDefinition).metric_code, { user_id: userContext.user_id });
      if (row.type === 'skills') await api.deleteSkill((row.asset as SkillDefinition).skill_id, { user_id: userContext.user_id });
      if (row.type === 'reports') await api.deleteReport((row.asset as ReportDefinition).report_id, { user_id: userContext.user_id });
      await onRefreshAll();
    } catch (error) {
      alert(`删除失败：${error instanceof Error ? error.message : '未知错误'}`);
    }
  };

  return (
    <div className="management-page flex min-h-0 flex-col bg-slate-50 dark:bg-slate-950">
      {/* Private personal workspace header */}
      <div className="management-header shrink-0">
        <div>
          <h2 className="management-title"><Boxes className="h-5 w-5 text-indigo-500" /> 我的资产</h2>
          <p className="management-description">管理您私有的指标、技能和报表；领域包资产可作为创建模板。</p>
        </div>
        <button type="button" onClick={openNewAssetModal} className="management-primary-action cursor-pointer"><Plus className="h-4 w-4" /> 新建资产</button>
      </div>

      {assetCreationChoiceOpen && (
        <div className="fixed inset-0 z-[76] flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" onMouseDown={() => setAssetCreationChoiceOpen(false)}>
          <div className="w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-800 dark:bg-slate-900" onMouseDown={event => event.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-slate-100 pb-4 dark:border-slate-800">
              <div>
                <h3 className="flex items-center gap-2 text-base font-bold text-slate-900 dark:text-white"><Boxes className="h-5 w-5 text-indigo-500" /> 选择创建方式</h3>
                <p className="mt-1 text-[11px] text-slate-500">选择领域包资产作为起点，或从空白对话开始创建。</p>
              </div>
              <button type="button" onClick={() => setAssetCreationChoiceOpen(false)} className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200" aria-label="关闭创建方式"><X className="h-5 w-5" /></button>
            </div>
            <div className="grid grid-cols-1 gap-4 py-6 sm:grid-cols-2">
              <button type="button" onClick={startFromPackAsset} className="flex gap-3 rounded-xl border border-slate-200 p-4 text-left transition-all hover:border-indigo-500 hover:bg-indigo-50/30 active:scale-[0.99] dark:border-slate-800 dark:hover:border-indigo-400 dark:hover:bg-indigo-950/20">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-indigo-50 dark:bg-indigo-950/30"><Boxes className="h-5 w-5 text-indigo-500" /></span>
                <span className="space-y-1"><span className="block text-xs font-bold text-slate-800 dark:text-white">从领域包创建</span><span className="block text-[10px] leading-relaxed text-slate-400">选择官方或企业领域包中的指标、技能、报表作为模板，生成个人副本后再调整。</span></span>
              </button>
              <button type="button" onClick={startBlankAsset} className="flex gap-3 rounded-xl border border-slate-200 p-4 text-left transition-all hover:border-indigo-500 hover:bg-indigo-50/30 active:scale-[0.99] dark:border-slate-800 dark:hover:border-indigo-400 dark:hover:bg-indigo-950/20">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-indigo-50 dark:bg-indigo-950/30"><Plus className="h-5 w-5 text-indigo-500" /></span>
                <span className="space-y-1"><span className="block text-xs font-bold text-slate-800 dark:text-white">空白创建</span><span className="block text-[10px] leading-relaxed text-slate-400">从业务描述开始，通过对话生成指标、Skill 或报表草案，再人工确认保存。</span></span>
              </button>
            </div>
          </div>
        </div>
      )}

      {newAssetModalOpen && (
        <div className="fixed inset-0 z-[75] flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" onMouseDown={() => setNewAssetModalOpen(false)}>
          <div className="flex h-[min(780px,calc(100vh-2rem))] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900" onMouseDown={event => event.stopPropagation()}>
            <div className="flex shrink-0 items-start justify-between border-b border-slate-100 px-5 py-4 dark:border-slate-800">
              <div>
                <h3 className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white"><Boxes className="h-4 w-4 text-indigo-500" /> {editingAssetRow ? `编辑${newAssetType === 'metric' ? '指标' : newAssetType === 'skill' ? '技能' : '报表'}` : '新建资产'}</h3>
                <p className="mt-1 text-[11px] text-slate-500">{editingAssetRow ? '修改仅影响您个人空间中的资产。' : '创建后仅保存在您的个人空间。'}</p>
              </div>
              <button type="button" onClick={() => setNewAssetModalOpen(false)} className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200" aria-label="关闭新建资产"><X className="h-5 w-5" /></button>
            </div>
            <div className="min-h-0 flex-1 overflow-hidden p-5">
              <div className="grid h-full min-h-0 gap-5 lg:grid-cols-2">
                <section className="h-full min-h-0 space-y-4 overflow-y-auto rounded-xl border border-slate-200 p-4 dark:border-slate-800">
                  <div className="flex rounded-lg bg-slate-100 p-1 dark:bg-slate-800">{([['metric', '指标'], ['skill', '技能'], ['report', '报表']] as const).map(([type, label]) => <button type="button" key={type} disabled={Boolean(editingAssetRow)} onClick={() => openConversationCreation(type)} className={`flex-1 rounded-md px-3 py-2 text-xs font-semibold transition-colors disabled:cursor-default ${newAssetType === type ? 'bg-white text-indigo-700 shadow-sm dark:bg-slate-900 dark:text-indigo-300' : 'text-slate-500 hover:text-slate-800 disabled:opacity-50 dark:text-slate-400 dark:hover:text-slate-200'}`}>{label}</button>)}</div>
                  <div><label className="mb-1 block text-[11px] font-semibold text-slate-600 dark:text-slate-300">{newAssetType === 'metric' ? '指标名称' : newAssetType === 'skill' ? '技能名称' : '报表名称'}</label><input readOnly value={newAssetDraft.name} placeholder="等待右侧对话生成" className="w-full cursor-default rounded-lg border border-slate-200 bg-slate-100 px-3 py-2 text-xs text-slate-700 outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200" /></div>
                  <div><label className="mb-1 block text-[11px] font-semibold text-slate-600 dark:text-slate-300">{newAssetType === 'metric' ? '业务说明与口径' : '业务说明'}</label><textarea readOnly value={newAssetDraft.description} rows={2} placeholder="等待右侧对话生成" className="w-full resize-none rounded-lg border border-slate-200 bg-slate-100 px-3 py-2 text-xs text-slate-700 outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200" /></div>
                  {newAssetType === 'metric' && <>
                    <div><label className="mb-1 block text-[11px] font-semibold text-slate-600 dark:text-slate-300">数据源</label><input readOnly value={dataSources.find(source => source.data_source_id === newAssetDraft.dataSourceId)?.name || '等待右侧对话判断'} className="w-full cursor-default rounded-lg border border-slate-200 bg-slate-100 px-3 py-2 text-xs text-slate-700 outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200" /></div>
                    <div><label className="mb-1 block text-[11px] font-semibold text-slate-600 dark:text-slate-300">逻辑表达式</label><textarea readOnly value={newAssetDraft.expression} rows={4} placeholder="等待右侧对话生成 SQL" className="w-full resize-none rounded-lg border border-slate-200 bg-slate-100 px-3 py-2 font-mono text-xs text-slate-700 outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200" /></div>
                  </>}
                  {newAssetType === 'skill' && <><p className="text-[11px] font-semibold text-slate-700 dark:text-slate-200">执行定义</p><div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-[11px] leading-relaxed text-slate-600 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-300"><p><span className="font-semibold text-slate-500">数据源：</span>{conversationCandidate?.dataSourceBindings?.map(binding => `${binding.name}（${binding.role === 'primary' ? '直接读取' : '依赖继承'}）`).join('、') || '等待对话判断'}</p><p><span className="font-semibold text-slate-500">依赖：</span>{conversationCandidate?.dependencyNodes?.filter(node => node.kind === 'metric' || node.kind === 'skill').map(node => `${node.kind === 'metric' ? '指标' : '技能'}·${node.label}`).join('、') || '无'}</p><p><span className="font-semibold text-slate-500">参数：</span>{conversationCandidate?.parameters?.map(parameter => `${parameter.description || parameter.name}${parameter.required ? '（必填）' : ''}`).join('、') || '无'}</p><div><p className="font-semibold text-slate-500">分析链路：</p>{conversationCandidate?.analysisChain?.length ? <ol className="mt-1 space-y-1">{conversationCandidate.analysisChain.map(step => <li key={`${step.order}_${step.label}`}>{step.order}. {withoutStepPrefix(step.label)}：{step.input} → {step.output}</li>)}</ol> : <p>等待对话生成</p>}</div>{candidateConclusion(conversationCandidate) && <p><span className="font-semibold text-slate-500">输出结论：</span>{candidateConclusion(conversationCandidate)}</p>}</div></>}
                  {isEditingAssetStructure && newAssetType === 'skill' && <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-[11px] dark:border-slate-700 dark:bg-slate-950/40">
                    <p className="font-semibold text-slate-700 dark:text-slate-200">执行定义</p>
                    <div><p className="mb-1 font-semibold text-slate-500">直接数据源</p><div className="flex flex-wrap gap-1">{conversationCandidate?.dataSourceBindings?.filter(binding => binding.role === 'primary').map(binding => <button key={binding.data_source_id} type="button" onClick={() => updateConversationCandidate(candidate => ({ ...candidate, dataSourceBindings: (candidate.dataSourceBindings || []).filter(item => item.data_source_id !== binding.data_source_id) }))} className="rounded border border-indigo-200 bg-indigo-50 px-2 py-1 text-[10px] text-indigo-700">{binding.name} ×</button>)}</div><select value="" disabled={!conversationCandidate} onChange={event => addCandidateDataSource(event.target.value)} className="mt-1 w-full rounded-md border border-dashed border-slate-300 bg-transparent px-2 py-1 text-[10px]"><option value="">+ 仅当 Skill 自身读库时绑定数据源</option>{dataSources.map(source => <option key={source.data_source_id} value={source.data_source_id}>{source.name}</option>)}</select></div>
                    <div><p className="mb-1 font-semibold text-slate-500">指标 / 技能依赖</p><div className="flex flex-wrap gap-1">{conversationCandidate?.dependencyNodes?.filter(node => node.kind === 'metric' || node.kind === 'skill').map(node => <button type="button" key={`${node.kind}_${node.id}`} onClick={() => toggleCandidateDependency(node.kind as 'metric' | 'skill', node.id)} className="rounded border border-slate-200 bg-white px-2 py-1 text-[10px] text-slate-600 dark:border-slate-700 dark:bg-slate-900">{node.kind === 'metric' ? '指标' : '技能'}·{node.label} ×</button>)}</div><select value="" disabled={!conversationCandidate} onChange={event => { const [kind, id] = event.target.value.split(':'); if ((kind === 'metric' || kind === 'skill') && id) toggleCandidateDependency(kind, id); }} className="mt-1 w-full rounded-md border border-dashed border-slate-300 bg-transparent px-2 py-1 text-[10px]"><option value="">+ 添加依赖</option>{metrics.filter(metric => metric.asset_ref).map(metric => <option key={metric.metric_code} value={`metric:${metric.asset_ref!.asset.asset_id}`}>指标·{metric.name}</option>)}{skills.filter(skill => skill.asset_ref).map(skill => <option key={skill.skill_id} value={`skill:${skill.asset_ref!.asset.asset_id}`}>技能·{skill.name}</option>)}</select></div>
                    <div><p className="mb-1 font-semibold text-slate-500">参数插槽</p><div className="space-y-1">{conversationCandidate?.parameters?.map((parameter, index) => <div key={`${parameter.name}_${index}`} className="flex gap-1"><input value={parameter.name} onChange={event => updateConversationCandidate(candidate => ({ ...candidate, parameters: (candidate.parameters || []).map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item) }))} className="min-w-0 flex-1 rounded border border-slate-200 bg-white px-2 py-1 text-[10px] dark:border-slate-700 dark:bg-slate-900" /><label className="flex items-center gap-1 text-[10px]"><input type="checkbox" checked={parameter.required} onChange={event => updateConversationCandidate(candidate => ({ ...candidate, parameters: (candidate.parameters || []).map((item, itemIndex) => itemIndex === index ? { ...item, required: event.target.checked } : item) }))} />必填</label></div>)}</div><button type="button" disabled={!conversationCandidate} onClick={() => updateConversationCandidate(candidate => ({ ...candidate, parameters: [...(candidate.parameters || []), { name: 'new_parameter', data_type: 'string', required: false, description: '', allowed_values: [] }] }))} className="mt-1 text-[10px] font-semibold text-indigo-600">+ 添加参数</button></div>
                    <div><p className="mb-1 font-semibold text-slate-500">逐步分析链路 <span className="font-normal text-slate-400">可拖拽排序</span></p><ol className="space-y-1">{conversationCandidate?.analysisChain?.map((step, index) => <li key={`${step.order}_${index}`} draggable onDragStart={() => setDraggedChainStep(index)} onDragOver={event => event.preventDefault()} onDrop={() => { if (draggedChainStep !== null) moveCandidateChainStep(draggedChainStep, index); setDraggedChainStep(null); }} className="cursor-grab rounded border border-slate-200 bg-white px-2 py-1.5 text-[10px] dark:border-slate-700 dark:bg-slate-900">⠿ <input value={step.label} onChange={event => updateCandidateChainStep(index, { label: event.target.value })} className="w-[calc(100%-1.5rem)] bg-transparent outline-none" /></li>)}</ol><button type="button" disabled={!conversationCandidate} onClick={addCandidateChainStep} className="mt-1 text-[10px] font-semibold text-indigo-600">+ 添加步骤</button></div>
                    <div><p className="mb-1 font-semibold text-slate-500">输出结论提示</p><textarea value={asText(conversationCandidate?.outputSchema?.conclusion)} disabled={!conversationCandidate} onChange={event => updateConversationCandidate(candidate => ({ ...candidate, outputSchema: { ...(candidate.outputSchema || {}), conclusion: event.target.value } }))} rows={2} placeholder="例如：输出根因、影响范围、建议动作及查询证据" className="w-full resize-none rounded border border-slate-200 bg-white px-2 py-1 text-[10px] dark:border-slate-700 dark:bg-slate-900" /></div>
                  </div>}
                  {newAssetType === 'report' && <><p className="text-[11px] font-semibold text-slate-700 dark:text-slate-200">报表定义</p><div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-[11px] leading-relaxed text-slate-600 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-300"><p><span className="font-semibold text-slate-500">继承数据源：</span>{conversationCandidate?.dataSourceBindings?.map(binding => binding.name).join('、') || '等待指标或 Skill 依赖'}</p><p><span className="font-semibold text-slate-500">依赖：</span>{conversationCandidate?.dependencyNodes?.filter(node => node.kind === 'metric' || node.kind === 'skill').map(node => `${node.kind === 'metric' ? '指标' : '技能'}·${node.label}`).join('、') || '无'}</p><div><p className="font-semibold text-slate-500">报告链路：</p>{conversationCandidate?.analysisChain?.length ? <ol className="mt-1 space-y-1">{conversationCandidate.analysisChain.map(step => <li key={`${step.order}_${step.label}`}>{step.order}. {withoutStepPrefix(step.label)}：{step.input} → {step.output}</li>)}</ol> : <p>等待对话生成</p>}</div><p><span className="font-semibold text-slate-500">交付产物：</span>HTML 报告（{asText(conversationCandidate?.outputSchema?.report_style) || '管理驾驶舱'}）</p></div></>}
                  {isEditingAssetStructure && newAssetType === 'report' && <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-[11px] dark:border-slate-700 dark:bg-slate-950/40">
                    <p className="font-semibold text-slate-700 dark:text-slate-200">报表定义</p>
                    <div><p className="mb-1 font-semibold text-slate-500">继承数据源</p><p className="text-slate-600 dark:text-slate-300">{conversationCandidate?.dataSourceBindings?.map(binding => `${binding.name}（来自依赖）`).join('、') || '添加指标或 Skill 依赖后自动汇集'}</p></div>
                    <div><p className="mb-1 font-semibold text-slate-500">指标 / 技能依赖</p><div className="flex flex-wrap gap-1">{conversationCandidate?.dependencyNodes?.filter(node => node.kind === 'metric' || node.kind === 'skill').map(node => <button type="button" key={`${node.kind}_${node.id}`} onClick={() => toggleCandidateDependency(node.kind as 'metric' | 'skill', node.id)} className="rounded border border-slate-200 bg-white px-2 py-1 text-[10px] text-slate-600 dark:border-slate-700 dark:bg-slate-900">{node.kind === 'metric' ? '指标' : '技能'}·{node.label} ×</button>)}</div><select value="" disabled={!conversationCandidate} onChange={event => { const [kind, id] = event.target.value.split(':'); if ((kind === 'metric' || kind === 'skill') && id) toggleCandidateDependency(kind, id); }} className="mt-1 w-full rounded-md border border-dashed border-slate-300 bg-transparent px-2 py-1 text-[10px]"><option value="">+ 添加依赖</option>{metrics.filter(metric => metric.asset_ref).map(metric => <option key={metric.metric_code} value={`metric:${metric.asset_ref!.asset.asset_id}`}>指标·{metric.name}</option>)}{skills.filter(skill => skill.asset_ref).map(skill => <option key={skill.skill_id} value={`skill:${skill.asset_ref!.asset.asset_id}`}>技能·{skill.name}</option>)}</select></div>
                    <div><p className="mb-1 font-semibold text-slate-500">报告链路 <span className="font-normal text-slate-400">可拖拽排序</span></p><ol className="space-y-1">{conversationCandidate?.analysisChain?.map((step, index) => <li key={`${step.order}_${index}`} draggable onDragStart={() => setDraggedChainStep(index)} onDragOver={event => event.preventDefault()} onDrop={() => { if (draggedChainStep !== null) moveCandidateChainStep(draggedChainStep, index); setDraggedChainStep(null); }} className="cursor-grab rounded border border-slate-200 bg-white px-2 py-1.5 text-[10px] dark:border-slate-700 dark:bg-slate-900">⠿ <input value={step.label} onChange={event => updateCandidateChainStep(index, { label: event.target.value })} className="w-[calc(100%-1.5rem)] bg-transparent outline-none" /></li>)}</ol><button type="button" disabled={!conversationCandidate} onClick={addCandidateChainStep} className="mt-1 text-[10px] font-semibold text-indigo-600">+ 添加步骤</button></div>
                    <div><p className="mb-1 font-semibold text-slate-500">交付产物</p><p className="text-slate-600 dark:text-slate-300">HTML 报告（本期仅支持 HTML）</p><select value={asText(conversationCandidate?.outputSchema?.report_style) || 'management'} disabled={!conversationCandidate} onChange={event => updateConversationCandidate(candidate => ({ ...candidate, outputSchema: { ...(candidate.outputSchema || {}), primary_output_type: 'html', derived_output_types: [], report_style: event.target.value } }))} className="mt-1 w-full rounded border border-slate-200 bg-white px-2 py-1 text-[10px] dark:border-slate-700 dark:bg-slate-900"><option value="management">管理驾驶舱</option><option value="review">经营复盘</option><option value="formal">正式分析报告</option><option value="brief">数据简报</option></select></div>
                  </div>}
                  {conversationCandidate?.supplementary?.length ? <div className="space-y-2"><p className="text-[11px] font-semibold text-slate-700 dark:text-slate-200">AI 补充内容</p><div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-[11px] text-slate-600 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-300">{conversationCandidate.supplementary.map((item, index) => <div key={`${item.title}_${index}`}><p className="font-semibold text-slate-500">{item.title}</p><pre className="mt-1 whitespace-pre-wrap break-words font-sans leading-relaxed">{item.content}</pre></div>)}</div></div> : null}
                  {(conversationPreviewResult || conversationPreviewError) && <div className={`rounded-lg px-3 py-2 text-[11px] ${conversationPreviewResult ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300' : 'bg-rose-50 text-rose-700 dark:bg-rose-950/30 dark:text-rose-300'}`}>{conversationPreviewResult ? '受控测试已通过' : `受控测试失败：${conversationPreviewError}`}</div>}
                  {isEditingAssetStructure && conversationCandidate && newAssetType === 'skill' && !isEditingAssetStructure && <div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-[11px] leading-relaxed text-slate-600 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-300">
                    <div className="flex items-center justify-between gap-3"><p className="font-bold text-slate-700 dark:text-slate-200">Skill 执行定义</p><button type="button" onClick={() => setIsEditingAssetStructure(true)} disabled={!conversationCandidate} className="shrink-0 text-[10px] font-semibold text-indigo-600 hover:text-indigo-700 disabled:cursor-not-allowed disabled:text-slate-400">微调定义</button></div>
                    <p><span className="font-semibold text-slate-500">数据源：</span>{conversationCandidate?.dataSourceBindings?.map(binding => `${binding.name}（${binding.role === 'primary' ? '直接读取' : '依赖继承'}）`).join('、') || '等待对话判断'}</p>
                    <p><span className="font-semibold text-slate-500">依赖：</span>{conversationCandidate?.dependencyNodes?.filter(node => node.kind === 'metric' || node.kind === 'skill').map(node => `${node.kind === 'metric' ? '指标' : '技能'}·${node.label}`).join('、') || '未引用已登记资产'}</p>
                    <p><span className="font-semibold text-slate-500">参数：</span>{conversationCandidate?.parameters?.map(parameter => `${parameter.description || parameter.name}${parameter.required ? '（必填）' : ''}`).join('、') || '无额外参数'}</p>
                    <p><span className="font-semibold text-slate-500">链路：</span>{conversationCandidate?.analysisChain?.map(step => `${step.order}. ${step.label}`).join(' → ') || '等待对话生成'}</p>
                    <p><span className="font-semibold text-slate-500">输出：</span>{asText(conversationCandidate?.outputSchema?.conclusion) || '可追溯分析结论、查询证据与可复用结果。'}</p>
                  </div>}
                  {isEditingAssetStructure && newAssetType === 'skill' && <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-700 dark:bg-slate-950/40">
                    <div><p className="text-[11px] font-bold text-slate-700 dark:text-slate-200">Skill 执行定义</p><p className="mt-0.5 text-[10px] text-slate-400">数据源、依赖、参数、执行链路和输出结论会随 Skill 保存。</p></div>
                    <div className="border-t border-slate-200 pt-3 dark:border-slate-700"><p className="text-[10px] font-bold text-slate-500">数据源绑定</p>{conversationCandidate ? <><div className="mt-1.5 space-y-1.5">{(conversationCandidate.dataSourceBindings || []).map((binding, index) => <div key={`${binding.data_source_id}_${index}`} className="flex items-center gap-1"><select value={binding.data_source_id} onChange={event => updateConversationCandidate(candidate => ({ ...candidate, dataSourceBindings: (candidate.dataSourceBindings || []).map((item, itemIndex) => itemIndex === index ? { ...item, data_source_id: event.target.value, name: dataSources.find(source => source.data_source_id === event.target.value)?.name || event.target.value, reason: '由用户在资产定义中调整' } : item) }))} className="min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] dark:border-slate-700 dark:bg-slate-900">{dataSources.map(source => <option key={source.data_source_id} value={source.data_source_id}>{source.name}</option>)}</select><select value={binding.role} onChange={event => updateConversationCandidate(candidate => ({ ...candidate, dataSourceBindings: (candidate.dataSourceBindings || []).map((item, itemIndex) => itemIndex === index ? { ...item, role: event.target.value as DataSourceBinding['role'] } : item) }))} className="rounded-md border border-slate-200 bg-white px-1.5 py-1 text-[10px] dark:border-slate-700 dark:bg-slate-900"><option value="primary">直接读取</option><option value="inherited">依赖继承</option><option value="step_input">步骤输入</option></select><button type="button" onClick={() => updateConversationCandidate(candidate => ({ ...candidate, dataSourceBindings: (candidate.dataSourceBindings || []).filter((_, itemIndex) => itemIndex !== index) }))} className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600" aria-label="移除数据源"><X className="h-3 w-3" /></button></div>)}</div><select value="" onChange={event => addCandidateDataSource(event.target.value)} className="mt-1.5 w-full rounded-md border border-dashed border-slate-300 bg-transparent px-2 py-1 text-[10px] text-slate-500 dark:border-slate-700"><option value="">+ 绑定数据源</option>{dataSources.filter(source => !conversationCandidate.dataSourceBindings?.some(binding => binding.data_source_id === source.data_source_id)).map(source => <option key={source.data_source_id} value={source.data_source_id}>{source.name}</option>)}</select></> : <p className="mt-1 text-[11px] text-slate-400">等待对话根据依赖和业务描述判断。</p>}</div>
                    <div className="border-t border-slate-200 pt-3 dark:border-slate-700"><p className="text-[10px] font-bold text-slate-500">指标 / 技能依赖</p>{conversationCandidate ? <><div className="mt-1.5 flex flex-wrap gap-1.5">{conversationCandidate.dependencyNodes?.filter(node => node.kind === 'metric' || node.kind === 'skill').map(node => <button type="button" key={`${node.kind}_${node.id}`} onClick={() => toggleCandidateDependency(node.kind as 'metric' | 'skill', node.id)} className="rounded-md border border-indigo-200 bg-indigo-50 px-2 py-1 text-[10px] font-semibold text-indigo-700 hover:bg-rose-50 hover:text-rose-700 dark:border-indigo-900 dark:bg-indigo-950/30 dark:text-indigo-300">{node.kind === 'metric' ? '指标' : '技能'} · {node.label} <span className="ml-1 opacity-60">×</span></button>)}</div><select value="" onChange={event => { const [kind, id] = event.target.value.split(':'); if ((kind === 'metric' || kind === 'skill') && id) toggleCandidateDependency(kind, id); }} className="mt-1.5 w-full rounded-md border border-dashed border-slate-300 bg-transparent px-2 py-1 text-[10px] text-slate-500 dark:border-slate-700"><option value="">+ 添加指标或技能依赖</option>{metrics.filter(metric => metric.asset_ref).map(metric => <option key={metric.metric_code} value={`metric:${metric.asset_ref!.asset.asset_id}`}>指标 · {metric.name}</option>)}{skills.filter(skill => skill.asset_ref).map(skill => <option key={skill.skill_id} value={`skill:${skill.asset_ref!.asset.asset_id}`}>技能 · {skill.name}</option>)}</select></> : <p className="mt-1 text-[11px] text-slate-400">尚未生成草案。</p>}</div>
                    <div className="border-t border-slate-200 pt-3 dark:border-slate-700"><p className="text-[10px] font-bold text-slate-500">参数插槽</p>{conversationCandidate ? <><div className="mt-1.5 space-y-1.5">{(conversationCandidate.parameters || []).map((parameter, index) => <div key={`${parameter.name}_${index}`} className="grid grid-cols-[1fr_72px_44px_20px] items-center gap-1"><input value={parameter.name} onChange={event => updateConversationCandidate(candidate => ({ ...candidate, parameters: (candidate.parameters || []).map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item) }))} placeholder="参数名" className="min-w-0 rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] dark:border-slate-700 dark:bg-slate-900" /><select value={parameter.data_type} onChange={event => updateConversationCandidate(candidate => ({ ...candidate, parameters: (candidate.parameters || []).map((item, itemIndex) => itemIndex === index ? { ...item, data_type: event.target.value } : item) }))} className="rounded-md border border-slate-200 bg-white px-1 py-1 text-[10px] dark:border-slate-700 dark:bg-slate-900"><option value="string">文本</option><option value="number">数字</option><option value="date">日期</option><option value="enum">枚举</option></select><label className="flex items-center gap-1 text-[9px] text-slate-500"><input type="checkbox" checked={parameter.required} onChange={event => updateConversationCandidate(candidate => ({ ...candidate, parameters: (candidate.parameters || []).map((item, itemIndex) => itemIndex === index ? { ...item, required: event.target.checked } : item) }))} />必填</label><button type="button" onClick={() => updateConversationCandidate(candidate => ({ ...candidate, parameters: (candidate.parameters || []).filter((_, itemIndex) => itemIndex !== index) }))} className="text-slate-400 hover:text-rose-600" aria-label="移除参数"><X className="h-3 w-3" /></button><input value={parameter.description || ''} onChange={event => updateConversationCandidate(candidate => ({ ...candidate, parameters: (candidate.parameters || []).map((item, itemIndex) => itemIndex === index ? { ...item, description: event.target.value } : item) }))} placeholder="参数说明" className="col-span-3 min-w-0 rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] dark:border-slate-700 dark:bg-slate-900" /></div>)}</div><button type="button" onClick={() => updateConversationCandidate(candidate => ({ ...candidate, parameters: [...(candidate.parameters || []), { name: 'new_parameter', data_type: 'string', required: false, description: '新增参数', allowed_values: [] }] }))} className="mt-1.5 text-[10px] font-semibold text-indigo-600 hover:text-indigo-700">+ 添加参数插槽</button></> : <p className="mt-1 text-[11px] text-slate-400">尚未生成草案。</p>}</div>
                    <div className="border-t border-slate-200 pt-3 dark:border-slate-700"><p className="text-[10px] font-bold text-slate-500">逐步分析链路</p>{conversationCandidate ? <><ol className="mt-1.5 space-y-1.5">{(conversationCandidate.analysisChain || []).map((step, index) => <li key={`${step.order}_${index}`} className="grid grid-cols-[20px_1fr_20px] items-start gap-1"><span className="mt-1 inline-flex h-4 w-4 items-center justify-center rounded-full bg-indigo-100 text-[9px] font-bold text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300">{step.order}</span><div className="space-y-1"><input value={step.label} onChange={event => updateCandidateChainStep(index, { label: event.target.value })} className="w-full rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] font-semibold dark:border-slate-700 dark:bg-slate-900" /><div className="grid grid-cols-2 gap-1"><input value={step.input} onChange={event => updateCandidateChainStep(index, { input: event.target.value })} placeholder="输入" className="min-w-0 rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] dark:border-slate-700 dark:bg-slate-900" /><input value={step.output} onChange={event => updateCandidateChainStep(index, { output: event.target.value })} placeholder="输出" className="min-w-0 rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] dark:border-slate-700 dark:bg-slate-900" /></div></div><button type="button" onClick={() => updateConversationCandidate(candidate => ({ ...candidate, analysisChain: (candidate.analysisChain || []).filter((_, stepIndex) => stepIndex !== index).map((item, itemIndex) => ({ ...item, order: itemIndex + 1 })) }))} className="mt-1 text-slate-400 hover:text-rose-600" aria-label="移除分析步骤"><X className="h-3 w-3" /></button></li>)}</ol><button type="button" onClick={addCandidateChainStep} className="mt-1.5 text-[10px] font-semibold text-indigo-600 hover:text-indigo-700">+ 添加分析步骤</button></> : <p className="mt-1 text-[11px] text-slate-400">尚未生成草案。</p>}</div>
                    <div className="border-t border-slate-200 pt-3 dark:border-slate-700"><p className="text-[10px] font-bold text-slate-500">输出结论</p><textarea value={asText(conversationCandidate?.outputSchema?.conclusion) || '可追溯分析结论、查询证据与可复用结果。'} onChange={event => updateConversationCandidate(candidate => ({ ...candidate, outputSchema: { ...(candidate.outputSchema || {}), conclusion: event.target.value } }))} disabled={!conversationCandidate} rows={2} className="mt-1 w-full resize-none rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 outline-none focus:border-indigo-400 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300" /></div>
                  </div>}
                  {isEditingAssetStructure && conversationCandidate && newAssetType === 'report' && !isEditingAssetStructure && <div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-[11px] leading-relaxed text-slate-600 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-300">
                    <div className="flex items-center justify-between gap-3"><p className="font-bold text-slate-700 dark:text-slate-200">报表分析与交付链路</p><button type="button" onClick={() => setIsEditingAssetStructure(true)} disabled={!conversationCandidate} className="shrink-0 text-[10px] font-semibold text-indigo-600 hover:text-indigo-700 disabled:cursor-not-allowed disabled:text-slate-400">微调定义</button></div>
                    <p><span className="font-semibold text-slate-500">数据源：</span>{conversationCandidate?.dataSourceBindings?.map(binding => `${binding.name}（${binding.role === 'primary' ? '直接读取' : '继承'}）`).join('、') || '等待从指标和 Skill 继承'}</p>
                    <p><span className="font-semibold text-slate-500">依赖：</span>{conversationCandidate?.dependencyNodes?.filter(node => node.kind === 'metric' || node.kind === 'skill').map(node => `${node.kind === 'metric' ? '指标' : '技能'}·${node.label}`).join('、') || '未引用已登记资产'}</p>
                    <p><span className="font-semibold text-slate-500">链路：</span>{conversationCandidate?.analysisChain?.map(step => `${step.order}. ${step.label}`).join(' → ') || '汇集数据 → 编排章节 → HTML 主产物 → 派生交付'}</p>
                    <p><span className="font-semibold text-slate-500">交付：</span>HTML 主产物 → {((conversationCandidate?.outputSchema?.derived_output_types as string[] | undefined) || ['PDF', 'PPTX', 'DOCX']).map(item => item.toUpperCase()).join(' / ')}</p>
                  </div>}
                  {isEditingAssetStructure && newAssetType === 'report' && <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-700 dark:bg-slate-950/40">
                    <div><p className="text-[11px] font-bold text-slate-700 dark:text-slate-200">报表执行定义</p><p className="mt-0.5 text-[10px] text-slate-400">数据源仅从指标和 Skill 依赖继承；本期交付固定为 HTML。</p></div>
                    <div className="border-t border-slate-200 pt-3 dark:border-slate-700"><p className="text-[10px] font-bold text-slate-500">继承的数据源</p>{conversationCandidate ? <><div className="mt-1.5 space-y-1.5">{(conversationCandidate.dataSourceBindings || []).map((binding, index) => <div key={`${binding.data_source_id}_${index}`} className="flex items-center gap-1"><select value={binding.data_source_id} onChange={event => updateConversationCandidate(candidate => ({ ...candidate, dataSourceBindings: (candidate.dataSourceBindings || []).map((item, itemIndex) => itemIndex === index ? { ...item, data_source_id: event.target.value, name: dataSources.find(source => source.data_source_id === event.target.value)?.name || event.target.value, reason: '由用户在资产定义中调整' } : item) }))} className="min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] dark:border-slate-700 dark:bg-slate-900">{dataSources.map(source => <option key={source.data_source_id} value={source.data_source_id}>{source.name}</option>)}</select><select value={binding.role} onChange={event => updateConversationCandidate(candidate => ({ ...candidate, dataSourceBindings: (candidate.dataSourceBindings || []).map((item, itemIndex) => itemIndex === index ? { ...item, role: event.target.value as DataSourceBinding['role'] } : item) }))} className="rounded-md border border-slate-200 bg-white px-1.5 py-1 text-[10px] dark:border-slate-700 dark:bg-slate-900"><option value="inherited">继承</option><option value="primary">直接读取</option><option value="step_input">步骤输入</option></select><button type="button" onClick={() => updateConversationCandidate(candidate => ({ ...candidate, dataSourceBindings: (candidate.dataSourceBindings || []).filter((_, itemIndex) => itemIndex !== index) }))} className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600" aria-label="移除数据源"><X className="h-3 w-3" /></button></div>)}</div><select value="" onChange={event => addCandidateDataSource(event.target.value)} className="mt-1.5 w-full rounded-md border border-dashed border-slate-300 bg-transparent px-2 py-1 text-[10px] text-slate-500 dark:border-slate-700"><option value="">+ 绑定或继承数据源</option>{dataSources.filter(source => !conversationCandidate.dataSourceBindings?.some(binding => binding.data_source_id === source.data_source_id)).map(source => <option key={source.data_source_id} value={source.data_source_id}>{source.name}</option>)}</select></> : <p className="mt-1 text-[11px] text-slate-400">等待识别所引用指标和 Skill 的数据源。</p>}</div>
                    <div className="border-t border-slate-200 pt-3 dark:border-slate-700"><p className="text-[10px] font-bold text-slate-500">指标 / 技能依赖</p>{conversationCandidate ? <><div className="mt-1.5 flex flex-wrap gap-1.5">{conversationCandidate.dependencyNodes?.filter(node => node.kind === 'metric' || node.kind === 'skill').map(node => <button type="button" key={`${node.kind}_${node.id}`} onClick={() => toggleCandidateDependency(node.kind as 'metric' | 'skill', node.id)} className="rounded-md border border-indigo-200 bg-indigo-50 px-2 py-1 text-[10px] font-semibold text-indigo-700 hover:bg-rose-50 hover:text-rose-700 dark:border-indigo-900 dark:bg-indigo-950/30 dark:text-indigo-300">{node.kind === 'metric' ? '指标' : '技能'} · {node.label} <span className="ml-1 opacity-60">×</span></button>)}</div><select value="" onChange={event => { const [kind, id] = event.target.value.split(':'); if ((kind === 'metric' || kind === 'skill') && id) toggleCandidateDependency(kind, id); }} className="mt-1.5 w-full rounded-md border border-dashed border-slate-300 bg-transparent px-2 py-1 text-[10px] text-slate-500 dark:border-slate-700"><option value="">+ 添加指标或技能依赖</option>{metrics.filter(metric => metric.asset_ref).map(metric => <option key={metric.metric_code} value={`metric:${metric.asset_ref!.asset.asset_id}`}>指标 · {metric.name}</option>)}{skills.filter(skill => skill.asset_ref).map(skill => <option key={skill.skill_id} value={`skill:${skill.asset_ref!.asset.asset_id}`}>技能 · {skill.name}</option>)}</select></> : <p className="mt-1 text-[11px] text-slate-400">尚未生成草案。</p>}</div>
                    <div className="border-t border-slate-200 pt-3 dark:border-slate-700"><p className="text-[10px] font-bold text-slate-500">报告执行链路</p>{conversationCandidate ? <><ol className="mt-1.5 space-y-1.5">{(conversationCandidate.analysisChain || []).map((step, index) => <li key={`${step.order}_${index}`} className="grid grid-cols-[20px_1fr_20px] items-start gap-1"><span className="mt-1 inline-flex h-4 w-4 items-center justify-center rounded-full bg-indigo-100 text-[9px] font-bold text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300">{step.order}</span><div className="space-y-1"><input value={step.label} onChange={event => updateCandidateChainStep(index, { label: event.target.value })} className="w-full rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] font-semibold dark:border-slate-700 dark:bg-slate-900" /><div className="grid grid-cols-2 gap-1"><input value={step.input} onChange={event => updateCandidateChainStep(index, { input: event.target.value })} className="min-w-0 rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] dark:border-slate-700 dark:bg-slate-900" /><input value={step.output} onChange={event => updateCandidateChainStep(index, { output: event.target.value })} className="min-w-0 rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] dark:border-slate-700 dark:bg-slate-900" /></div></div><button type="button" onClick={() => updateConversationCandidate(candidate => ({ ...candidate, analysisChain: (candidate.analysisChain || []).filter((_, stepIndex) => stepIndex !== index).map((item, itemIndex) => ({ ...item, order: itemIndex + 1 })) }))} className="mt-1 text-slate-400 hover:text-rose-600" aria-label="移除报告步骤"><X className="h-3 w-3" /></button></li>)}</ol><button type="button" onClick={addCandidateChainStep} className="mt-1.5 text-[10px] font-semibold text-indigo-600 hover:text-indigo-700">+ 添加报告步骤</button></> : <p className="mt-1 text-[11px] text-slate-400">等待右侧对话生成报告链路。</p>}</div>
                    <div className="border-t border-slate-200 pt-3 dark:border-slate-700"><p className="text-[10px] font-bold text-slate-500">交付产物</p><div className="mt-1.5 flex flex-wrap gap-2"><span className="rounded-md bg-indigo-600 px-2 py-1 text-[10px] font-bold text-white">HTML 主产物</span>{(['pdf', 'pptx', 'docx'] as const).map(format => <label key={format} className="rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"><input type="checkbox" className="mr-1" disabled={!conversationCandidate} checked={(conversationCandidate?.outputSchema?.derived_output_types as string[] | undefined)?.includes(format) ?? true} onChange={event => updateConversationCandidate(candidate => { const outputs = (candidate.outputSchema?.derived_output_types as string[] | undefined) || ['pdf', 'pptx', 'docx']; return { ...candidate, outputSchema: { ...(candidate.outputSchema || {}), primary_output_type: 'html', derived_output_types: event.target.checked ? [...new Set([...outputs, format])] : outputs.filter(item => item !== format) } }; })} />{format.toUpperCase()} 派生</label>)}</div></div>
                  </div>}
                  {selectedTemplate && <p className="text-[11px] text-slate-500">来源模板：{selectedTemplate.name}</p>}
                </section>
                <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-indigo-200 bg-indigo-50/30 dark:border-indigo-900/70 dark:bg-indigo-950/10">
                  <div className="border-b border-indigo-100 px-4 py-3 dark:border-indigo-900/70"><h4 className="flex items-center gap-1.5 text-xs font-bold text-slate-800 dark:text-slate-100"><Wand2 className="h-4 w-4 text-indigo-500" /> 对话生成</h4><p className="mt-1 text-[11px] text-slate-500">需求、逻辑、依赖、参数澄清与测试证据按时间连续沉淀；不会自动保存。</p></div>
                  <div ref={conversationScrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
                    {creationConversation.map(message => (
                      <div key={message.id} className={message.role === 'user' ? 'ml-12 text-right' : ''}>
                        <div className={`inline-block max-w-full rounded-xl px-3 py-2 text-left text-xs leading-relaxed ${message.role === 'user' ? 'bg-indigo-600 text-white' : message.error ? 'bg-rose-50 text-rose-700 dark:bg-rose-950/30 dark:text-rose-300' : 'text-slate-700 dark:text-slate-200'}`}>
                          <p className="whitespace-pre-wrap">{message.content}</p>
                          {message.candidate && renderHarnessCandidate(message.candidate)}
                          {message.slotResolution && <div className="mt-3 space-y-1 border-t border-slate-200 pt-3 dark:border-slate-700">{message.slotResolution.filter(slot => slot.status === 'unresolved' || slot.status === 'ambiguous').map(slot => <p key={slot.name} className="text-[11px]"><span className="font-semibold">{slot.description || slot.name}：</span>{slot.status === 'ambiguous' && slot.candidates?.length ? `请选择 ${slot.candidates.map(candidate => String(candidate.value)).join(' / ')}` : '尚未提供'}</p>)}</div>}
                          {message.testResult && <div className="mt-3 border-t border-slate-200 pt-3 dark:border-slate-700"><QueryResultView result={message.testResult} fields={fields} darkMode={darkMode} hideLineage maxTableRows={5} /></div>}
                        </div>
                      </div>
                    ))}
                    {isGeneratingCandidate && <p className="text-xs text-slate-500"><RefreshCw className="mr-1 inline h-3 w-3 animate-spin text-indigo-500" />正在生成下一版 Harness 草案…</p>}
                    {isTestingConversationDraft && <p className="text-xs text-slate-500"><RefreshCw className="mr-1 inline h-3 w-3 animate-spin text-indigo-500" />正在通过受控引擎验证当前草案…</p>}
                  </div>
                  <div className="shrink-0 border-t border-indigo-100 p-4 dark:border-indigo-900/70"><div className="flex items-end gap-3"><textarea autoFocus value={assetIntent} onChange={event => setAssetIntent(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (assetIntent.trim() && !isGeneratingCandidate) void handleGenerateConversationCandidate(); } }} rows={1} placeholder={newAssetType === 'metric' ? '描述指标口径，或在这里指定数据源、字段和筛选条件…' : newAssetType === 'skill' ? '描述分析需求，或继续补充口径、字段、依赖和判断逻辑…' : '描述报表目标，或继续补充章节、指标和展示要求…'} className="max-h-24 flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-xs text-slate-800 outline-none dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200" /><button type="button" onClick={() => void handleGenerateConversationCandidate()} disabled={isGeneratingCandidate || !assetIntent.trim()} aria-label="发送描述" className="shrink-0 rounded-xl bg-indigo-600 p-2.5 text-white transition-colors hover:bg-indigo-700 disabled:opacity-50">{isGeneratingCandidate ? <RefreshCw className="h-[18px] w-[18px] animate-spin" /> : <Send className="h-[18px] w-[18px]" />}</button></div>{creationError && <p role="alert" className="mt-2 text-xs text-rose-600 dark:text-rose-300">{creationError}</p>}</div>
                </section>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap justify-end gap-2 border-t border-slate-100 px-5 py-4 dark:border-slate-800">
              <button type="button" onClick={handleCancelAssetWorkspace} className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800">取消</button>
              <button type="button" onClick={handleCreateAssetFromModal} disabled={isCreatingAsset} className="management-primary-action">{isCreatingAsset && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}{editingAssetRow ? '保存修改' : '人工确认保存'}</button>
            </div>
          </div>
        </div>
      )}

      {templatePickerOpen && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" onMouseDown={() => setTemplatePickerOpen(false)}>
          <div className="flex max-h-[min(760px,calc(100vh-2rem))] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900" onMouseDown={event => event.stopPropagation()}>
            <div className="flex items-start justify-between border-b border-slate-100 px-5 py-4 dark:border-slate-800">
              <div>
                <h3 className="text-sm font-bold text-slate-900 dark:text-white">选择领域包模板</h3>
                <p className="mt-1 text-[11px] text-slate-500">选择后进入双栏对话工作台；来源资产不会被修改。</p>
              </div>
              <button type="button" onClick={() => setTemplatePickerOpen(false)} className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200" aria-label="关闭模板选择"><X className="h-5 w-5" /></button>
            </div>
            <div className="space-y-3 border-b border-slate-100 px-5 py-4 dark:border-slate-800">
              <div className="relative"><Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" /><input value={templateSearch} onChange={event => setTemplateSearch(event.target.value)} autoFocus placeholder="搜索模板名称、说明或领域包…" className="w-full rounded-lg border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-xs outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-950" /></div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex min-w-[280px] flex-1 items-center gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
                  {([['metrics', '指标', 'metric'], ['skills', '技能', 'skill'], ['reports', '报表', 'report']] as const).map(([tab, label, type]) => <button key={tab} type="button" onClick={() => setActiveSubTab(tab)} className={`flex-1 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${activeSubTab === tab ? 'bg-white text-indigo-700 shadow-sm dark:bg-slate-900 dark:text-indigo-300' : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200'}`}>{label} ({templateCatalog.filter(template => template.assetType === type).length})</button>)}
                </div>
                <div className="flex items-center gap-1">{([['all', '全部来源'], ['official_pack', '官方'], ['enterprise_pack', '企业']] as const).map(([value, label]) => <button key={value} type="button" onClick={() => setTemplateSourceFilter(value)} className={`rounded-md border px-2.5 py-1.5 text-[10px] font-semibold ${templateSourceFilter === value ? 'border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900 dark:bg-indigo-950/30 dark:text-indigo-300' : 'border-slate-200 text-slate-500 dark:border-slate-700'}`}>{label}</button>)}</div>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-5">
              <div className="mb-3 flex items-center justify-between text-[10px] text-slate-400"><span>匹配 {filteredTemplateCatalog.length} 个模板</span><span>选择模板后仍可通过对话持续修改</span></div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {filteredTemplateCatalog.map(template => <button type="button" key={template.key} onClick={() => { if (template.assetType === 'metric') applyMetricTemplate(template.asset); else if (template.assetType === 'skill') applySkillTemplate(template.asset); else applyReportTemplate(template.asset); }} className="min-h-0 rounded-lg border border-slate-200 px-3 py-2.5 text-left transition hover:border-indigo-400 hover:bg-indigo-50/50 dark:border-slate-800 dark:hover:bg-indigo-950/20"><div className="flex items-center justify-between gap-2"><span className="truncate text-xs font-bold text-slate-800 dark:text-slate-100">{template.name}</span><span className={`shrink-0 rounded px-1.5 py-0.5 text-[8px] font-bold ${template.sourceType === 'official_pack' ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300' : 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300'}`}>{template.sourceType === 'official_pack' ? '官方' : '企业'}</span></div><p className="mt-1 line-clamp-1 text-[10px] text-slate-500">{template.description || '暂无说明'}</p><div className="mt-2 flex items-center justify-between text-[9px] text-slate-400"><span className="max-w-[65%] truncate">{template.sourceId}</span><span>v{template.version}</span></div></button>)}
              </div>
              {filteredTemplateCatalog.length === 0 && <p className="py-12 text-center text-xs text-slate-400">没有匹配的模板，请调整搜索词或分类。</p>}
            </div>
          </div>
        </div>
      )}

      {hubView && (
        <div className="min-h-0 flex-1">
          <div className="space-y-6">
            <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:flex-row sm:items-center sm:justify-between">
              <div className="relative w-full sm:max-w-sm">
                <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
                <input value={assetSearch} onChange={event => setAssetSearch(event.target.value)} placeholder="搜索我的资产..." className="w-full rounded-lg border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-xs text-slate-800 outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100" />
              </div>
              <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
                {([
                  ['all', '全部'], ['metrics', '指标'], ['skills', '技能'], ['reports', '报表']
                ] as const).map(([filter, label]) => (
                  <button key={filter} type="button" onClick={() => setAssetTypeFilter(filter)} className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${assetTypeFilter === filter ? 'bg-white text-indigo-700 shadow-sm dark:bg-slate-900 dark:text-indigo-300' : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200'}`}>{label} ({filter === 'all' ? customMetrics.length + customSkills.length + customReports.length : filter === 'metrics' ? customMetrics.length : filter === 'skills' ? customSkills.length : customReports.length})</button>
                ))}
              </div>
            </div>
            <div className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <table className="w-full table-fixed text-left text-xs">
                <thead className="border-b border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-800 dark:bg-slate-950/50 dark:text-slate-400">
                  <tr>
                    <th className="w-[36%] px-5 py-3 font-semibold">资产</th>
                    <th className="w-[12%] px-4 py-3 font-semibold">类型</th>
                    <th className="w-[23%] px-4 py-3 font-semibold">创建方式 / 来源</th>
                    <th className="w-[17%] px-4 py-3 font-semibold">更新时间</th>
                    <th className="w-[12%] px-5 py-3 text-right font-semibold">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {personalAssetRows.map(row => (
                    <tr key={row.id} className="transition-colors hover:bg-slate-50/70 dark:hover:bg-slate-800/30">
                      <td className="px-5 py-4">
                        <div className="truncate font-semibold text-slate-850 dark:text-slate-100" title={row.name}>{row.name}</div>
                        <div className="mt-1 truncate text-[11px] text-slate-500" title={row.description}>{row.description || '暂无说明'}</div>
                      </td>
                      <td className="px-4 py-4"><span className={`block truncate rounded-full px-2 py-1 text-center text-[10px] font-semibold ${row.type === 'metrics' ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-300' : row.type === 'skills' ? 'bg-violet-50 text-violet-700 dark:bg-violet-950/30 dark:text-violet-300' : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300'}`}>{row.label}</span></td>
                      <td className="max-w-xs px-4 py-4 text-slate-600 dark:text-slate-300"><span className="block truncate" title={row.source}>{row.source}</span></td>
                      <td className="truncate px-4 py-4 text-slate-500" title={row.updatedAt}>{row.updatedAt}</td>
                      <td className="px-5 py-4"><div className="flex justify-end gap-1"><button type="button" onClick={() => openAssetEditor(row)} className="shrink-0 rounded-lg border border-slate-200 px-2 py-1.5 text-[11px] font-semibold text-slate-650 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 dark:border-slate-700 dark:text-slate-300 dark:hover:border-indigo-700 dark:hover:bg-indigo-950/30 dark:hover:text-indigo-300">编辑</button><button type="button" onClick={() => void handleDeleteAsset(row)} className="shrink-0 rounded-lg px-1.5 py-1.5 text-[11px] font-semibold text-slate-400 hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-950/30 dark:hover:text-rose-300" aria-label={`删除${row.name}`}>删除</button></div></td>
                    </tr>
                  ))}
                  {personalAssetRows.length === 0 && (
                    <tr><td colSpan={5} className="px-5 py-16 text-center text-slate-400"><div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 dark:bg-slate-800"><BookOpen className="h-5 w-5" /></div>{assetSearch ? '没有匹配的个人资产。' : '还没有个人资产，点击“新建”开始创建。'}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
      <div className={hubView ? 'hidden' : ''}>
      {/* Sub tabs selector */}
      <div className="shrink-0 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800/80 px-6 flex text-xs font-bold">
        <button 
          onClick={() => setActiveSubTab('metrics')}
          className={`px-4 py-3.5 border-b-2 flex items-center gap-1.5 transition-all ${
            activeSubTab === 'metrics'
              ? 'border-indigo-650 text-indigo-650 dark:border-indigo-400 dark:text-indigo-400'
              : 'border-transparent text-slate-500 hover:text-slate-850 dark:hover:text-slate-350'
          }`}
        >
          <BookOpen className="w-4 h-4" />
          我的指标 ({customMetrics.length})
        </button>
        <button 
          onClick={() => setActiveSubTab('skills')}
          className={`px-4 py-3.5 border-b-2 flex items-center gap-1.5 transition-all ${
            activeSubTab === 'skills'
              ? 'border-indigo-650 text-indigo-650 dark:border-indigo-400 dark:text-indigo-400'
              : 'border-transparent text-slate-500 hover:text-slate-850 dark:hover:text-slate-350'
          }`}
        >
          <Cpu className="w-4 h-4" />
          我的技能 ({customSkills.length})
        </button>
        <button 
          onClick={() => setActiveSubTab('reports')}
          className={`px-4 py-3.5 border-b-2 flex items-center gap-1.5 transition-all ${
            activeSubTab === 'reports'
              ? 'border-indigo-650 text-indigo-650 dark:border-indigo-400 dark:text-indigo-400'
              : 'border-transparent text-slate-500 hover:text-slate-850 dark:hover:text-slate-350'
          }`}
        >
          <FileText className="w-4 h-4" />
          我的报表 ({customReports.length})
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* --- METRICS SUB TAB --- */}
        {activeSubTab === 'metrics' && (
          <div className="p-6 max-w-5xl mx-auto space-y-6 text-left">
            {metricMode === 'list' ? (
              <>
                <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-4">
                  <div className="flex items-center gap-2 flex-1 max-w-md">
                    <div className="relative flex-1">
                      <Search className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" />
                      <input 
                        type="text" 
                        placeholder="搜索我的自定义指标..."
                        value={metricSearch}
                        onChange={e => setMetricSearch(e.target.value)}
                        className="w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800/80 rounded-lg pl-9 pr-4 py-1.5 text-xs outline-none text-slate-800 dark:text-slate-200"
                      />
                    </div>
                    {/* Layout Switcher */}
                    <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg border border-slate-200 dark:border-slate-700/60 flex-shrink-0">
                      <button
                        onClick={() => setViewLayout('card')}
                        className={`p-1.5 rounded-md transition-colors ${viewLayout === 'card' ? 'bg-white dark:bg-slate-900 shadow-xs text-indigo-650 dark:text-indigo-400' : 'text-slate-455 hover:text-slate-655'}`}
                        title="卡片视图"
                      >
                        <LayoutGrid className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => setViewLayout('table')}
                        className={`p-1.5 rounded-md transition-colors ${viewLayout === 'table' ? 'bg-white dark:bg-slate-900 shadow-xs text-indigo-650 dark:text-indigo-400' : 'text-slate-455 hover:text-slate-655'}`}
                        title="表格视图"
                      >
                        <List className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                  {primaryTab === 'workbench' && (
                    <button 
                      onClick={handleOpenCreateMetric}
                      className="bg-indigo-655 hover:bg-indigo-700 text-white text-xs font-semibold px-4 py-2 rounded-lg flex items-center gap-1 transition-colors whitespace-nowrap"
                    >
                      <Plus className="w-4 h-4" />
                      新建自定义指标
                    </button>
                  )}
                </div>

                {showMarketplace ? (
                  <div className="space-y-6">
                    {/* Official Metrics */}
                    <div className="space-y-3">
                      <h3 className="text-xs font-bold text-slate-800 dark:text-slate-300">官方内置指标 ({visibleOfficialMetrics.length})</h3>
                      {visibleOfficialMetrics.length === 0 ? (
                        <p className="text-xs text-slate-400 italic">暂无匹配的官方指标。</p>
                      ) : viewLayout === 'card' ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {visibleOfficialMetrics.map(metric => (
                            <div key={getAssetIdentity(metric, metric.metric_code)} className="bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800/85 rounded-xl p-5 space-y-4 shadow-sm hover:border-slate-300 transition-colors">
                              <div className="flex justify-between items-start gap-2">
                                <div>
                                  <h4 className="font-bold text-slate-900 dark:text-white text-xs">{metric.name}</h4>
                                  <span className="text-[9px] font-mono text-slate-455 bg-slate-50 dark:bg-slate-950 px-1.5 py-0.5 rounded inline-block mt-1">{metric.metric_code}</span>
                                </div>
                                <span className="px-2 py-0.5 text-[9px] rounded-full font-bold bg-indigo-50 text-indigo-755 dark:bg-indigo-950/20 dark:text-indigo-400">官方</span>
                              </div>
                              <p className="text-xs text-slate-500 dark:text-slate-400 leading-normal line-clamp-2">{metric.definition}</p>
                              <div className="grid grid-cols-2 gap-2 text-[9px] text-slate-400 dark:text-gray-500 border-t border-slate-50 dark:border-slate-850 pt-2.5">
                                <div>发布商：官方团队</div>
                                <div className="text-right">数据源：{metric.data_source_id}</div>
                              </div>
                              <div className="flex justify-end gap-2 pt-1 border-t border-slate-50 dark:border-slate-850/60">
                                {onPreviewMetric && (
                                  <button 
                                    onClick={() => onPreviewMetric(metric)}
                                    className="px-2.5 py-1.5 rounded hover:bg-slate-105 dark:hover:bg-slate-800 text-[10px] text-slate-655 dark:text-slate-355 border border-slate-200 dark:border-slate-800 flex items-center gap-0.5 font-bold"
                                  >
                                    数据预览
                                  </button>
                                )}
                                <button 
                                  onClick={() => handleDeriveToCustom('metric', metric.metric_code, metric.name)}
                                  disabled={isCloning}
                                  className="px-2.5 py-1.5 rounded bg-indigo-50 hover:bg-indigo-105 dark:bg-indigo-950/30 text-[10px] text-indigo-650 dark:text-indigo-400 font-bold flex items-center gap-0.5"
                                >
                                  <Save className="w-3.5 h-3.5" />
                                  另存为我的指标
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="w-full overflow-x-auto rounded-xl border border-slate-200/80 dark:border-slate-800/85 bg-white dark:bg-slate-900 shadow-xs">
                          <table className="min-w-full text-xs text-left border-collapse">
                            <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200/80 dark:border-slate-800/85">
                              <tr>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">指标名称</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">指标代码</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">数据源</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300 text-right">操作</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/70">
                              {visibleOfficialMetrics.map(metric => (
                                <tr key={getAssetIdentity(metric, metric.metric_code)} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30 transition-colors">
                                  <td className="px-4 py-3.5 font-bold text-slate-900 dark:text-white">{metric.name}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-500 dark:text-slate-400">{metric.metric_code}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-655 dark:text-slate-350">{metric.data_source_id}</td>
                                  <td className="px-4 py-3.5 text-right space-x-2">
                                    {onPreviewMetric && (
                                      <button onClick={() => onPreviewMetric(metric)} className="text-slate-555 hover:text-slate-855 dark:text-slate-400 dark:hover:text-slate-200 hover:underline">数据预览</button>
                                    )}
                                    <button onClick={() => handleDeriveToCustom('metric', metric.metric_code, metric.name)} className="text-indigo-650 hover:text-indigo-855 dark:text-indigo-400 dark:hover:text-indigo-300 hover:underline font-semibold">另存为我的</button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>

                    {/* Shared Metrics */}
                    <div className="space-y-3">
                      <h3 className="text-xs font-bold text-slate-800 dark:text-slate-300">组织内部共享指标 ({visibleSharedMetrics.length})</h3>
                      {visibleSharedMetrics.length === 0 ? (
                        <p className="text-xs text-slate-400 italic">暂无共享指标。</p>
                      ) : viewLayout === 'card' ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {visibleSharedMetrics.map(metric => (
                            <div key={getAssetIdentity(metric, metric.metric_code)} className="bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800/85 rounded-xl p-5 space-y-4 shadow-sm hover:border-slate-300 transition-colors">
                              <div className="flex justify-between items-start gap-2">
                                <div>
                                  <h4 className="font-bold text-slate-900 dark:text-white text-xs">{metric.name}</h4>
                                  <span className="text-[9px] font-mono text-slate-455 bg-slate-50 dark:bg-slate-950 px-1.5 py-0.5 rounded inline-block mt-1">{metric.metric_code}</span>
                                </div>
                                <span className="px-2 py-0.5 text-[9px] rounded-full font-bold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/20 dark:text-emerald-400">共享</span>
                              </div>
                              <p className="text-xs text-slate-500 dark:text-slate-400 leading-normal line-clamp-2">{metric.definition}</p>
                              <div className="grid grid-cols-2 gap-2 text-[9px] text-slate-400 dark:text-gray-500 border-t border-slate-50 dark:border-slate-850 pt-2.5">
                                <div>共享人：{metric.owner}</div>
                                <div className="text-right">数据源：{metric.data_source_id}</div>
                              </div>
                              <div className="flex justify-end gap-2 pt-1 border-t border-slate-50 dark:border-slate-850/60">
                                {onPreviewMetric && (
                                  <button 
                                    onClick={() => onPreviewMetric(metric)}
                                    className="px-2.5 py-1.5 rounded hover:bg-slate-105 dark:hover:bg-slate-800 text-[10px] text-slate-655 dark:text-slate-355 border border-slate-200 dark:border-slate-800 flex items-center gap-0.5 font-bold"
                                  >
                                    数据预览
                                  </button>
                                )}
                                <button 
                                  onClick={() => handleDeriveToCustom('metric', metric.metric_code, metric.name)}
                                  disabled={isCloning}
                                  className="px-2.5 py-1.5 rounded bg-indigo-50 hover:bg-indigo-105 dark:bg-indigo-950/30 text-[10px] text-indigo-650 dark:text-indigo-400 font-bold flex items-center gap-0.5"
                                >
                                  <Save className="w-3.5 h-3.5" />
                                  另存为我的指标
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="w-full overflow-x-auto rounded-xl border border-slate-200/80 dark:border-slate-800/85 bg-white dark:bg-slate-900 shadow-xs">
                          <table className="min-w-full text-xs text-left border-collapse">
                            <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200/80 dark:border-slate-800/85">
                              <tr>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">指标名称</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">指标代码</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">共享人</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">数据源</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300 text-right">操作</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/70">
                              {visibleSharedMetrics.map(metric => (
                                <tr key={getAssetIdentity(metric, metric.metric_code)} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30 transition-colors">
                                  <td className="px-4 py-3.5 font-bold text-slate-900 dark:text-white">{metric.name}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-500 dark:text-slate-400">{metric.metric_code}</td>
                                  <td className="px-4 py-3.5 text-slate-500 dark:text-gray-400">{metric.owner}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-655 dark:text-slate-355">{metric.data_source_id}</td>
                                  <td className="px-4 py-3.5 text-right space-x-2">
                                    {onPreviewMetric && (
                                      <button onClick={() => onPreviewMetric(metric)} className="text-slate-555 hover:text-slate-855 dark:text-slate-400 dark:hover:text-slate-200 hover:underline">数据预览</button>
                                    )}
                                    <button onClick={() => handleDeriveToCustom('metric', metric.metric_code, metric.name)} className="text-indigo-650 hover:text-indigo-855 dark:text-indigo-400 dark:hover:text-indigo-300 hover:underline font-semibold">另存为我的</button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="space-y-6">
                    {/* Custom private metrics */}
                    <div className="space-y-3">
                      <h3 className="text-xs font-bold text-slate-800 dark:text-slate-300">我创建的指标 ({visibleCustomMetrics.length})</h3>
                      {visibleCustomMetrics.length === 0 ? (
                        <p className="text-xs text-slate-400 italic">暂无自定义指标。</p>
                      ) : viewLayout === 'card' ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {visibleCustomMetrics.map(metric => (
                            <div key={getAssetIdentity(metric, metric.metric_code)} className="bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800/85 rounded-xl p-5 space-y-4 shadow-sm hover:border-slate-300 transition-colors">
                              <div className="flex justify-between items-start gap-2">
                                <div>
                                  <h4 className="font-bold text-slate-900 dark:text-white text-xs">{metric.name}</h4>
                                  <span className="text-[9px] font-mono text-slate-450 bg-slate-50 dark:bg-slate-950 px-1.5 py-0.5 rounded inline-block mt-1">{metric.metric_code}</span>
                                </div>
                                <span className={`px-2 py-0.5 text-[9px] rounded-full font-bold ${
                                  metric.visibility === 'shared' 
                                    ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/20 dark:text-emerald-400' 
                                    : 'bg-amber-50 text-amber-700 dark:bg-amber-950/20 dark:text-amber-400'
                                }`}>{metric.visibility === 'shared' ? '共享' : '私有'}</span>
                              </div>
                              <p className="text-xs text-slate-500 dark:text-slate-400 leading-normal line-clamp-2">{metric.definition}</p>
                              <div className="grid grid-cols-2 gap-2 text-[9px] text-slate-400 dark:text-gray-500 border-t border-slate-50 dark:border-slate-850 pt-2.5">
                                <div>创建者：我</div>
                                <div className="text-right">数据源：{metric.data_source_id}</div>
                              </div>
                              
                              {renderAdvancedMetadata(metric, `metric_${metric.metric_code}`)}
                              
                              <div className="flex justify-end gap-2 pt-1 border-t border-slate-50 dark:border-slate-850/60">
                                <button 
                                  onClick={() => handlePublishMetric(metric.metric_code, metric.visibility !== 'shared')}
                                  className="hidden"
                                >
                                  <Share2 className="w-3.5 h-3.5" />
                                  {metric.visibility === 'shared' ? '取消分享' : '发布分享'}
                                </button>
                                <button 
                                  onClick={() => handleOpenPromotion(metric, 'metric')}
                                  className="hidden"
                                >
                                  <ArrowUpCircle className="w-3.5 h-3.5" />
                                  晋升企业包
                                </button>
                                <button 
                                  onClick={() => handleOpenEditMetric(metric)}
                                  className="px-2.5 py-1.5 rounded bg-indigo-50 hover:bg-indigo-100 dark:bg-indigo-950/30 text-[10px] text-indigo-650 dark:text-indigo-400 font-bold flex items-center gap-0.5"
                                >
                                  <Wand2 className="w-3.5 h-3.5" />
                                  编辑指标
                                </button>
                                <button 
                                  onClick={() => handleDeleteMetric(metric.metric_code)}
                                  className="px-2 py-1.5 rounded hover:bg-rose-50 hover:text-rose-600 text-[10px] text-slate-400 transition-colors"
                                  title="删除"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="w-full overflow-x-auto rounded-xl border border-slate-200/80 dark:border-slate-800/85 bg-white dark:bg-slate-900 shadow-xs">
                          <table className="min-w-full text-xs text-left border-collapse">
                            <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200/80 dark:border-slate-800/85">
                              <tr>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">指标名称</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">指标代码</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">工作区</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">版本</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">可见性</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">数据源</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">算法表达式</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300 text-right">操作</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/70">
                              {visibleCustomMetrics.map(metric => (
                                <tr key={getAssetIdentity(metric, metric.metric_code)} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30 transition-colors">
                                  <td className="px-4 py-3.5 font-bold text-slate-900 dark:text-white">{metric.name}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-500 dark:text-slate-400">{metric.metric_code}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-550 dark:text-slate-400">{metric.workspace_id || '个人空间'}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-550 dark:text-slate-400">{metric.version || 'v1.0.0'}</td>
                                  <td className="px-4 py-3.5">
                                    <span className={`px-2 py-0.5 text-[10px] rounded-full font-semibold ${
                                      metric.visibility === 'shared' 
                                        ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/20 dark:text-emerald-400' 
                                        : 'bg-amber-50 text-amber-700 dark:bg-amber-950/20 dark:text-amber-400'
                                    }`}>{metric.visibility === 'shared' ? '共享' : '私有'}</span>
                                  </td>
                                  <td className="px-4 py-3.5 font-mono text-slate-655 dark:text-slate-355">{metric.data_source_id}</td>
                                  <td className="px-4 py-3.5 max-w-xs truncate font-mono text-slate-500 dark:text-slate-400" title={metric.formula?.expression}>
                                    {metric.formula?.expression}
                                  </td>
                                  <td className="px-4 py-3.5 text-right space-x-2">
                                    <button onClick={() => handleOpenEditMetric(metric)} className="text-indigo-655 hover:text-indigo-855 dark:text-indigo-400 dark:hover:text-indigo-300 hover:underline">编辑</button>
                                    <button onClick={() => handleDeleteMetric(metric.metric_code)} className="text-rose-655 hover:text-rose-855 dark:text-rose-400 dark:hover:text-rose-350 hover:underline">删除</button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </>
            ) : (
              // Create or Edit Metric Form view
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 shadow-sm space-y-5">
                <div className="flex justify-between items-center border-b border-slate-100 dark:border-slate-800 pb-3">
                  <h2 className="text-sm font-bold text-slate-900 dark:text-white">{metricMode === 'create' ? '新建逻辑自定义指标' : `编辑指标: ${selectedMetric?.name}`}</h2>
                  <button onClick={() => setMetricMode('list')} className="text-slate-400 hover:text-slate-600"><X className="w-5 h-5" /></button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
                  {/* Left Form */}
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-[10px] text-slate-400 font-semibold mb-1">指标名称</label>
                        <input 
                          type="text" 
                          placeholder="例如: 承运商准时到货率"
                          value={metricDraft.name}
                          onChange={e => setMetricDraft({...metricDraft, name: e.target.value})}
                          className="w-full bg-slate-50 dark:bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-250 dark:border-slate-700 outline-none text-slate-800 dark:text-slate-200"
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] text-slate-400 font-semibold mb-1">物理数据源</label>
                        <select 
                          value={metricDraft.data_source_id} 
                          onChange={e => setMetricDraft({...metricDraft, data_source_id: e.target.value})}
                          className="w-full bg-slate-50 dark:bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-250 dark:border-slate-700 outline-none text-slate-800 dark:text-slate-200"
                        >
                          {dataSources.map(ds => (
                            <option key={ds.data_source_id} value={ds.data_source_id}>{ds.name}</option>
                          ))}
                        </select>
                      </div>
                    </div>

                    <div>
                      <label className="block text-[10px] text-slate-400 font-semibold mb-1">指标业务口径说明 (Definition)</label>
                      <textarea 
                        rows={2}
                        placeholder="例如: 计算准时送达的运单占总发货运单的比例，用于评价承运商时效保障能力。"
                        value={metricDraft.definition}
                        onChange={e => setMetricDraft({...metricDraft, definition: e.target.value})}
                        className="w-full bg-slate-50 dark:bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-250 dark:border-slate-700 outline-none text-slate-800 dark:text-slate-200 resize-none"
                      />
                    </div>

                    <div className="rounded-xl border border-indigo-100 bg-indigo-50/40 p-3 dark:border-indigo-900/60 dark:bg-indigo-950/20">
                      <label className="mb-2 flex items-center gap-1.5 text-[10px] font-bold text-indigo-700 dark:text-indigo-300"><Wand2 className="h-3.5 w-3.5" /> 用 AI 调整指标定义与公式</label>
                      <div className="flex gap-2"><input value={metricAdjustPrompt} onChange={e => setMetricAdjustPrompt(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') void handleAdjustMetricWithAi(); }} placeholder="例如：只统计已签收运单，按自然月计算" className="min-w-0 flex-1 rounded-lg border border-indigo-100 bg-white px-3 py-2 text-xs outline-none focus:border-indigo-400 dark:border-indigo-900 dark:bg-slate-900" /><button type="button" onClick={handleAdjustMetricWithAi} disabled={isAdjustingMetric || !metricAdjustPrompt.trim()} className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">{isAdjustingMetric ? '调整中' : '应用调整'}</button></div>
                    </div>

                    <div>
                      <label className="block text-[10px] text-slate-400 font-semibold mb-1">逻辑公式表达式 (Logical Formula Expression)</label>
                      <input 
                        type="text" 
                        placeholder="例如: COUNT(tms.shipment.id) FILTER (WHERE tms.shipment.delivery_status = 'ON_TIME') / COUNT(tms.shipment.id)"
                        value={metricDraft.expression}
                        onChange={e => setMetricDraft({...metricDraft, expression: e.target.value})}
                        className="w-full bg-slate-50 dark:bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-250 dark:border-slate-700 outline-none text-slate-800 dark:text-slate-200 font-mono"
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-[10px] text-slate-400 font-semibold mb-1">分子公式 (可选)</label>
                        <input 
                          type="text" 
                          placeholder="例如: COUNT(id) FILTER(ON_TIME)"
                          value={metricDraft.numerator}
                          onChange={e => setMetricDraft({...metricDraft, numerator: e.target.value})}
                          className="w-full bg-slate-50 dark:bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-250 dark:border-slate-700 outline-none text-slate-800 dark:text-slate-200 font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] text-slate-400 font-semibold mb-1">分母公式 (可选)</label>
                        <input 
                          type="text" 
                          placeholder="例如: COUNT(id)"
                          value={metricDraft.denominator}
                          onChange={e => setMetricDraft({...metricDraft, denominator: e.target.value})}
                          className="w-full bg-slate-50 dark:bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-250 dark:border-slate-700 outline-none text-slate-800 dark:text-slate-200 font-mono"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div><label className="mb-1 block text-[10px] font-semibold text-slate-400">更新频率</label><input value={metricDraft.update_frequency} onChange={e => setMetricDraft({...metricDraft, update_frequency: e.target.value})} placeholder="例如：每日 / 实时" className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-800" /></div>
                      <div><label className="mb-1 block text-[10px] font-semibold text-slate-400">同义词</label><input value={metricDraft.synonyms} onChange={e => setMetricDraft({...metricDraft, synonyms: e.target.value})} placeholder="顿号分隔，如：准点率、准时率" className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-800" /></div>
                    </div>

                    <div className="rounded-xl border border-slate-200 p-3 dark:border-slate-800"><div className="mb-2 flex items-center justify-between"><span className="text-[10px] font-bold text-slate-600 dark:text-slate-300">依赖检查</span><span className="text-[10px] text-emerald-600">{metricDependencies.some(item => item.blocking) ? '存在阻塞依赖' : '可安全保存'}</span></div>{metricDependencies.length ? metricDependencies.map((item, index) => <div key={`${item.source_name}_${index}`} className="flex justify-between border-t border-slate-100 py-1.5 text-[10px] dark:border-slate-800"><span>{item.source_name}</span><span className={item.blocking ? 'text-rose-500' : 'text-slate-400'}>{item.relation_type}</span></div>) : <p className="text-[10px] text-slate-400">当前草稿没有已登记的上游依赖；保存后平台会记录其字段与模板来源。</p>}</div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-[10px] text-slate-400 font-semibold mb-1">时间过滤字段</label>
                        <input 
                          type="text" 
                          placeholder="例如: tms.shipment.ship_date"
                          value={metricDraft.time_field}
                          onChange={e => setMetricDraft({...metricDraft, time_field: e.target.value})}
                          className="w-full bg-slate-50 dark:bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-250 dark:border-slate-700 outline-none text-slate-800 dark:text-slate-200 font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] text-slate-400 font-semibold mb-1">空间可见性</label>
                        <select 
                          value={metricDraft.visibility} 
                          onChange={e => setMetricDraft({...metricDraft, visibility: e.target.value as any})}
                          className="w-full bg-slate-50 dark:bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-250 dark:border-slate-700 outline-none text-slate-800 dark:text-slate-200"
                        >
                          <option value="private">仅自己可见 (Private)</option>
                        </select>
                        <select value={metricPreviewFactory} onChange={e => setMetricPreviewFactory(e.target.value)} className="bg-slate-50 dark:bg-slate-800 text-[10px] px-2 py-1 rounded border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300"><option>全部厂区</option><option>厂区A</option><option>厂区B</option></select>
                      </div>
                    </div>

                    {/* Restricted SQL Sandbox warning */}
                    <div className="bg-amber-500/5 dark:bg-amber-500/10 rounded-lg p-3 border border-amber-500/15 flex items-start gap-2.5 text-[10px] leading-relaxed text-amber-800 dark:text-amber-400">
                      <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
                      <div className="space-y-0.5">
                        <span className="font-bold">逻辑指标设计护栏：</span>
                        <p>请在此只使用平台绑定的标准逻辑字段 (如 `tms.shipment.*`) 描述逻辑规则，切勿输入任何特定物理数据库的方言 SQL。系统编译器将自动映射对齐到底层物理源。</p>
                      </div>
                    </div>
                  </div>

                  {/* Right Preview panel */}
                  <div className="space-y-4">
                    <div className="flex justify-between items-center">
                      <span className="text-xs font-bold text-slate-700 dark:text-slate-350">数据预览与验证</span>
                      <div className="flex gap-2">
                        <select 
                          value={metricPreviewTimeRange} 
                          onChange={e => setMetricPreviewTimeRange(e.target.value)}
                          className="bg-slate-50 dark:bg-slate-800 text-[10px] px-2 py-1 rounded border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300"
                        >
                          <option value="最近30天">最近30天</option>
                          <option value="最近7天">最近7天</option>
                          <option value="本季度">本季度</option>
                        </select>
                        <button 
                          onClick={handleRunMetricPreview}
                          disabled={isRunningMetricPreview}
                          className="bg-indigo-600 hover:bg-indigo-700 text-white text-[10px] px-3 py-1 rounded font-bold flex items-center gap-1"
                        >
                          {isRunningMetricPreview && <RefreshCw className="w-3 h-3 animate-spin" />}
                          运行预览
                        </button>
                      </div>
                    </div>

                    <div className="min-h-[18rem] h-auto border border-slate-100 dark:border-slate-800 rounded-xl p-4 bg-slate-50/20 dark:bg-slate-900/10 flex flex-col min-h-0 overflow-y-auto">
                      {metricPreviewResult ? (
                        <QueryResultView 
                          result={metricPreviewResult} 
                          fields={fields}
                          darkMode={darkMode}
                          hideLineage={true}
                          maxTableRows={5}
                        />
                      ) : metricPreviewError ? (
                        <div className="text-xs text-rose-500 font-mono text-center">{metricPreviewError}</div>
                      ) : isRunningMetricPreview ? (
                        <div className="text-xs text-slate-400 text-center flex flex-col items-center gap-2">
                          <RefreshCw className="w-4 h-4 animate-spin text-indigo-500" />
                          通过后端引擎编译并拉取物理数据中...
                        </div>
                      ) : (
                        <div className="text-xs text-slate-400 text-center">输入公式与分子分母后，点击「运行预览」查看编译校验与前 5 条样本数据。</div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex justify-end gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
                  <button 
                    onClick={() => setMetricMode('list')}
                    className="border border-slate-200 dark:border-slate-800 px-4 py-2 rounded-lg text-xs text-slate-650 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800"
                  >
                    取消
                  </button>
                  <button 
                    onClick={handleSaveMetric}
                    disabled={isSavingMetric}
                    className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 text-white text-xs font-semibold px-4 py-2 rounded-lg transition-colors flex items-center gap-1.5"
                  >
                    <Save className="w-4 h-4" />
                    保存指标
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* --- SKILLS SUB TAB --- */}
        {activeSubTab === 'skills' && (
          <div className="p-6 max-w-5xl mx-auto space-y-6 text-left">
            {skillMode === 'list' ? (
              <>
                <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-4">
                  <div className="flex items-center gap-2 flex-1 max-w-md">
                    <div className="relative flex-1">
                      <Search className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" />
                      <input 
                        type="text" 
                        placeholder="搜索我的自定义技能..."
                        value={skillSearch}
                        onChange={e => setSkillSearch(e.target.value)}
                        className="w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800/80 rounded-lg pl-9 pr-4 py-1.5 text-xs outline-none text-slate-800 dark:text-slate-200"
                      />
                    </div>
                    {/* Layout Switcher */}
                    <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg border border-slate-200 dark:border-slate-700/60 flex-shrink-0">
                      <button
                        onClick={() => setViewLayout('card')}
                        className={`p-1.5 rounded-md transition-colors ${viewLayout === 'card' ? 'bg-white dark:bg-slate-900 shadow-xs text-indigo-650 dark:text-indigo-400' : 'text-slate-450 hover:text-slate-655'}`}
                        title="卡片视图"
                      >
                        <LayoutGrid className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => setViewLayout('table')}
                        className={`p-1.5 rounded-md transition-colors ${viewLayout === 'table' ? 'bg-white dark:bg-slate-900 shadow-xs text-indigo-650 dark:text-indigo-400' : 'text-slate-455 hover:text-slate-655'}`}
                        title="表格视图"
                      >
                        <List className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                  {primaryTab === 'workbench' && (
                    <button 
                      onClick={handleOpenCreateSkill}
                      className="bg-indigo-655 hover:bg-indigo-700 text-white text-xs font-semibold px-4 py-2 rounded-lg flex items-center gap-1 transition-colors whitespace-nowrap"
                    >
                      <Plus className="w-4 h-4" />
                      定义自定义技能
                    </button>
                  )}
                </div>

                {showMarketplace ? (
                  <div className="space-y-6">
                    {/* Official Skills */}
                    <div className="space-y-3">
                      <h3 className="text-xs font-bold text-slate-800 dark:text-slate-300">官方内置技能 ({visibleOfficialSkills.length})</h3>
                      {visibleOfficialSkills.length === 0 ? (
                        <p className="text-xs text-slate-400 italic">暂无官方内置技能。</p>
                      ) : viewLayout === 'card' ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {visibleOfficialSkills.map(skill => (
                            <div key={getAssetIdentity(skill, skill.skill_id)} className="bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800/85 rounded-xl p-5 space-y-4 shadow-sm hover:border-slate-350 transition-colors">
                              <div className="flex justify-between items-start gap-2">
                                <div>
                                  <h4 className="font-bold text-slate-900 dark:text-white text-xs">{skill.name}</h4>
                                  <span className="text-[9px] font-mono text-slate-400 bg-slate-50 dark:bg-slate-950 px-1.5 py-0.5 rounded inline-block mt-1">{skill.skill_id}</span>
                                </div>
                                <span className="px-2 py-0.5 text-[9px] rounded-full font-bold bg-indigo-50 text-indigo-755 dark:bg-indigo-950/20 dark:text-indigo-400">官方</span>
                              </div>
                              <p className="text-xs text-slate-500 dark:text-slate-400 leading-normal line-clamp-2">{skill.description}</p>
                              <div className="grid grid-cols-2 gap-2 text-[9px] text-slate-400 dark:text-gray-500 border-t border-slate-50 dark:border-slate-850 pt-2.5">
                                <div>发布商：官方团队</div>
                                <div className="text-right">入参格式：{skill.parameters?.length || 0} 个参数</div>
                              </div>
                              <div className="flex justify-end gap-2 pt-1 border-t border-slate-50 dark:border-slate-850/60">
                                {onPreviewSkill && (
                                  <button 
                                    onClick={() => onPreviewSkill(skill)}
                                    className="px-2.5 py-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-[10px] text-slate-650 dark:text-slate-355 border border-slate-200 dark:border-slate-800 flex items-center gap-0.5 font-bold"
                                  >
                                    配置与测试
                                  </button>
                                )}
                                <button 
                                  onClick={() => handleDeriveToCustom('skill', skill.skill_id, skill.name)}
                                  disabled={isCloning}
                                  className="px-2.5 py-1.5 rounded bg-indigo-50 hover:bg-indigo-105 dark:bg-indigo-950/30 text-[10px] text-indigo-650 dark:text-indigo-400 font-bold flex items-center gap-0.5"
                                >
                                  <Save className="w-3.5 h-3.5" />
                                  另存为我的技能
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="w-full overflow-x-auto rounded-xl border border-slate-200/85 dark:border-slate-800/85 bg-white dark:bg-slate-900 shadow-xs">
                          <table className="min-w-full text-xs text-left border-collapse">
                            <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200/80 dark:border-slate-800/85">
                              <tr>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">技能名称</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">技能 ID</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">参数数量</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300 text-right">操作</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/70">
                              {visibleOfficialSkills.map(skill => (
                                <tr key={getAssetIdentity(skill, skill.skill_id)} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30 transition-colors">
                                  <td className="px-4 py-3.5 font-bold text-slate-900 dark:text-white">{skill.name}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-500 dark:text-slate-400">{skill.skill_id}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-550 dark:text-slate-455">{skill.parameters?.length || 0}</td>
                                  <td className="px-4 py-3.5 text-right space-x-2">
                                    {onPreviewSkill && (
                                      <button onClick={() => onPreviewSkill(skill)} className="text-slate-555 hover:text-slate-855 dark:text-slate-400 dark:hover:text-slate-200 hover:underline">配置</button>
                                    )}
                                    <button onClick={() => handleDeriveToCustom('skill', skill.skill_id, skill.name)} className="text-indigo-650 hover:text-indigo-855 dark:text-indigo-400 dark:hover:text-indigo-300 hover:underline font-semibold">另存为我的</button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>

                    {/* Shared Skills */}
                    <div className="space-y-3">
                      <h3 className="text-xs font-bold text-slate-800 dark:text-slate-300">组织内部共享技能 ({visibleSharedSkills.length})</h3>
                      {visibleSharedSkills.length === 0 ? (
                        <p className="text-xs text-slate-400 italic">暂无共享技能。</p>
                      ) : viewLayout === 'card' ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {visibleSharedSkills.map(skill => (
                            <div key={getAssetIdentity(skill, skill.skill_id)} className="bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800/85 rounded-xl p-5 space-y-4 shadow-sm hover:border-slate-355 transition-colors">
                              <div className="flex justify-between items-start gap-2">
                                <div>
                                  <h4 className="font-bold text-slate-900 dark:text-white text-xs">{skill.name}</h4>
                                  <span className="text-[9px] font-mono text-slate-400 bg-slate-50 dark:bg-slate-950 px-1.5 py-0.5 rounded inline-block mt-1">{skill.skill_id}</span>
                                </div>
                                <span className="px-2 py-0.5 text-[9px] rounded-full font-bold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/20 dark:text-emerald-400">共享</span>
                              </div>
                              <p className="text-xs text-slate-500 dark:text-slate-400 leading-normal line-clamp-2">{skill.description}</p>
                              <div className="grid grid-cols-2 gap-2 text-[9px] text-slate-400 dark:text-gray-500 border-t border-slate-50 dark:border-slate-850 pt-2.5">
                                <div>共享人：{skill.owner_user_id}</div>
                                <div className="text-right">入参格式：{skill.parameters?.length || 0} 个参数</div>
                              </div>
                              <div className="flex justify-end gap-2 pt-1 border-t border-slate-50 dark:border-slate-850/60">
                                {onPreviewSkill && (
                                  <button 
                                    onClick={() => onPreviewSkill(skill)}
                                    className="px-2.5 py-1.5 rounded hover:bg-slate-105 dark:hover:bg-slate-800 text-[10px] text-slate-655 dark:text-slate-355 border border-slate-200 dark:border-slate-800 flex items-center gap-0.5 font-semibold"
                                  >
                                    配置与测试
                                  </button>
                                )}
                                <button 
                                  onClick={() => handleDeriveToCustom('skill', skill.skill_id, skill.name)}
                                  disabled={isCloning}
                                  className="px-2.5 py-1.5 rounded bg-indigo-50 hover:bg-indigo-105 dark:bg-indigo-950/30 text-[10px] text-indigo-650 dark:text-indigo-400 font-bold flex items-center gap-0.5"
                                >
                                  <Save className="w-3.5 h-3.5" />
                                  另存为我的技能
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="w-full overflow-x-auto rounded-xl border border-slate-200/80 dark:border-slate-800/85 bg-white dark:bg-slate-900 shadow-xs">
                          <table className="min-w-full text-xs text-left border-collapse">
                            <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200/80 dark:border-slate-800/85">
                              <tr>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">技能名称</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">技能 ID</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">共享者</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">参数数量</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300 text-right">操作</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/70">
                              {visibleSharedSkills.map(skill => (
                                <tr key={getAssetIdentity(skill, skill.skill_id)} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30 transition-colors">
                                  <td className="px-4 py-3.5 font-bold text-slate-900 dark:text-white">{skill.name}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-500 dark:text-slate-400">{skill.skill_id}</td>
                                  <td className="px-4 py-3.5 text-slate-500 dark:text-gray-400">{skill.owner_user_id}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-555 dark:text-slate-455">{skill.parameters?.length || 0}</td>
                                  <td className="px-4 py-3.5 text-right space-x-2">
                                    {onPreviewSkill && (
                                      <button onClick={() => onPreviewSkill(skill)} className="text-slate-555 hover:text-slate-855 dark:text-slate-400 dark:hover:text-slate-200 hover:underline">配置</button>
                                    )}
                                    <button onClick={() => handleDeriveToCustom('skill', skill.skill_id, skill.name)} className="text-indigo-650 hover:text-indigo-855 dark:text-indigo-400 dark:hover:text-indigo-300 hover:underline font-semibold">另存为我的</button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="space-y-6">
                    {/* Custom workbench skills */}
                    <div className="space-y-3">
                      <h3 className="text-xs font-bold text-slate-800 dark:text-slate-300">我创建的报表技能 ({visibleCustomSkills.length})</h3>
                      {visibleCustomSkills.length === 0 ? (
                        <p className="text-xs text-slate-400 italic">暂无自定义技能。</p>
                      ) : viewLayout === 'card' ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {visibleCustomSkills.map(skill => (
                            <div key={getAssetIdentity(skill, skill.skill_id)} className="bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 rounded-xl p-5 space-y-4 shadow-sm hover:border-slate-350 transition-colors">
                              <div className="flex justify-between items-start gap-2">
                                <div>
                                  <h4 className="font-bold text-slate-900 dark:text-white text-xs">{skill.name}</h4>
                                  <span className="text-[9px] font-mono text-slate-450 bg-slate-50 dark:bg-slate-950 px-1.5 py-0.5 rounded inline-block mt-1">{skill.skill_id}</span>
                                </div>
                                <span className={`px-2 py-0.5 text-[9px] rounded-full font-bold ${
                                  skill.visibility === 'shared' 
                                    ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/20 dark:text-emerald-400' 
                                    : 'bg-amber-50 text-amber-700 dark:bg-amber-950/20 dark:text-amber-400'
                                }`}>{skill.visibility === 'shared' ? '共享' : '私有'}</span>
                              </div>
                              <p className="text-xs text-slate-500 dark:text-slate-400 leading-normal line-clamp-2">{skill.description}</p>
                              <div className="grid grid-cols-2 gap-2 text-[9px] text-slate-400 dark:text-gray-500 border-t border-slate-50 dark:border-slate-850 pt-2.5">
                                <div>创建者：我</div>
                                <div className="text-right">入参格式：{skill.parameters.length} 个参数</div>
                              </div>

                              {renderAdvancedMetadata(skill, `skill_${skill.skill_id}`)}

                              <div className="flex justify-end gap-2 pt-1 border-t border-slate-50 dark:border-slate-850/60">
                                <button 
                                  onClick={() => handleOpenPromotion(skill, 'skill')}
                                  className="hidden"
                                >
                                  <ArrowUpCircle className="w-3.5 h-3.5" />
                                  晋升企业包
                                </button>
                                <button 
                                  onClick={() => handleOpenEditSkill(skill)}
                                  className="px-2.5 py-1.5 rounded bg-indigo-50 hover:bg-indigo-100 dark:bg-indigo-950/30 text-[10px] text-indigo-655 dark:text-indigo-400 font-bold flex items-center gap-0.5"
                                >
                                  <Wand2 className="w-3.5 h-3.5" />
                                  编辑并测试
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="w-full overflow-x-auto rounded-xl border border-slate-200/80 dark:border-slate-800/85 bg-white dark:bg-slate-900 shadow-xs">
                          <table className="min-w-full text-xs text-left border-collapse">
                            <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200/80 dark:border-slate-800/85">
                              <tr>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">技能名称</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">技能 ID</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">工作区</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">版本</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">可见性</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">参数数量</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300 text-right">操作</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/70">
                              {visibleCustomSkills.map(skill => (
                                <tr key={getAssetIdentity(skill, skill.skill_id)} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30 transition-colors">
                                  <td className="px-4 py-3.5 font-bold text-slate-900 dark:text-white">{skill.name}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-500 dark:text-slate-400">{skill.skill_id}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-550 dark:text-slate-400">{skill.workspace_id || '个人空间'}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-550 dark:text-slate-400">{skill.version || 'v1.0.0'}</td>
                                  <td className="px-4 py-3.5">
                                    <span className={`px-2 py-0.5 text-[10px] rounded-full font-semibold ${
                                      skill.visibility === 'shared' 
                                        ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/20 dark:text-emerald-400' 
                                        : 'bg-amber-50 text-amber-700 dark:bg-amber-950/20 dark:text-amber-400'
                                    }`}>{skill.visibility === 'shared' ? '共享' : '私有'}</span>
                                  </td>
                                  <td className="px-4 py-3.5 font-mono text-slate-550 dark:text-slate-455">{skill.parameters?.length || 0} 个参数</td>
                                  <td className="px-4 py-3.5 text-right space-x-2">
                                    <button onClick={() => handleOpenEditSkill(skill)} className="text-indigo-655 hover:text-indigo-855 dark:text-indigo-400 dark:hover:text-indigo-300 hover:underline">编辑并测试</button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </>
            ) : (
              // Create or Edit Skill Form view
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 shadow-sm space-y-5">
                <div className="flex justify-between items-center border-b border-slate-100 dark:border-slate-800 pb-3">
                  <h2 className="text-sm font-bold text-slate-900 dark:text-white">{skillMode === 'create' ? '新建报表技能 Skill' : `编辑技能: ${selectedSkill?.name}`}</h2>
                  <button onClick={() => setSkillMode('list')} className="text-slate-400 hover:text-slate-600"><X className="w-5 h-5" /></button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
                  {/* Left Form */}
                  <div className="space-y-4">
                    <div>
                      <label className="block text-[10px] text-slate-400 font-semibold mb-1">技能名称</label>
                      <input 
                        type="text" 
                        placeholder="例如: 承运商履约分析"
                        value={skillDraft.name}
                        onChange={e => setSkillDraft({...skillDraft, name: e.target.value})}
                        className="w-full bg-slate-50 dark:bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-250 dark:border-slate-700 outline-none text-slate-800 dark:text-slate-200"
                      />
                    </div>

                    <div>
                      <label className="block text-[10px] text-slate-400 font-semibold mb-1">技能业务口径与功能描述</label>
                      <textarea 
                        rows={3}
                        placeholder="说明该技能在大模型理解问句后，将触发何种 SQL 生成和前端图表可视化形式..."
                        value={skillDraft.description}
                        onChange={e => setSkillDraft({...skillDraft, description: e.target.value})}
                        className="w-full bg-slate-50 dark:bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-250 dark:border-slate-700 outline-none text-slate-800 dark:text-slate-200 resize-none font-sans"
                      />
                    </div>

                    <div className="rounded-xl border border-indigo-100 bg-indigo-50/40 p-3 dark:border-indigo-900/60 dark:bg-indigo-950/20">
                      <label className="mb-1 block text-[10px] font-bold text-indigo-700 dark:text-indigo-300">自然语言生成 Skill Schema</label>
                      <textarea value={skillPrompt} onChange={e => setSkillPrompt(e.target.value)} rows={4} placeholder="描述输入参数、分析步骤、指标口径、期望图表和输出结果。模型只生成受控 Schema，运行时不临时生成 SQL。" className="w-full resize-none rounded-lg border border-indigo-100 bg-white px-3 py-2 text-xs outline-none focus:border-indigo-400 dark:border-indigo-900 dark:bg-slate-900" />
                      <button type="button" onClick={() => void buildSkillSchema()} disabled={isBuildingSkillSchema} className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50"><Wand2 className="h-3.5 w-3.5" />{skillSchemaDraft ? '重新生成 Schema' : '生成 Schema'}</button>
                    </div>

                    {skillSchemaDraft && <div className="space-y-3 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                      <div><span className="text-[10px] font-bold text-slate-500">确定性执行步骤</span><ol className="mt-2 space-y-1 text-[10px] text-slate-600 dark:text-slate-300">{skillSchemaDraft.steps.map((step, index) => <li key={`${step}_${index}`}>{index + 1}. {step}</li>)}</ol></div>
                      <div><span className="text-[10px] font-bold text-slate-500">受控 SQL / 工作流</span><pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 text-[10px] leading-5 text-emerald-300">{skillSchemaDraft.sql}</pre></div>
                      <div className="rounded-lg bg-slate-50 px-3 py-2 text-[10px] dark:bg-slate-800"><strong>推荐展示：</strong>{skillSchemaDraft.chartType}</div>
                      <div className="flex gap-2"><input value={skillAdjustPrompt} onChange={e => setSkillAdjustPrompt(e.target.value)} placeholder="继续调整：例如增加厂区参数，改为趋势图" className="min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-900" /><button type="button" onClick={() => void buildSkillSchema(skillAdjustPrompt)} disabled={!skillAdjustPrompt.trim() || isBuildingSkillSchema} className="rounded-lg border border-indigo-200 px-3 text-xs font-bold text-indigo-600 disabled:opacity-50">迭代</button></div>
                    </div>}

                    <div className="space-y-2">
                      <span className="text-[10px] text-slate-450 font-bold">技能输入参数配置 (Parameters)</span>
                      {skillDraft.parameters.map((p, idx) => (
                        <div key={idx} className="flex gap-2 items-center bg-slate-50/50 dark:bg-slate-800/40 p-2.5 rounded-lg border border-slate-100 dark:border-slate-800 text-[10px]">
                          <div className="font-bold text-slate-700 dark:text-slate-350 shrink-0 font-mono">{p.name}</div>
                          <div className="text-slate-400 font-mono">({p.data_type})</div>
                          <div className="text-slate-400 italic flex-1 truncate">{p.description}</div>
                          <div className="text-slate-450">{p.required ? '必填' : '选填'}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Right Preview panel */}
                  <div className="space-y-4">
                    {skillSchemaDraft && <div className="rounded-xl border border-slate-200 p-3 dark:border-slate-800"><div className="mb-2 flex items-center justify-between"><span className="text-[10px] font-bold text-slate-500">Harness 依赖与输入契约</span><span className="text-[10px] text-emerald-600">Schema 已生成</span></div><div className="flex flex-wrap gap-2">{skillSchemaDraft.parameters.map(parameter => <span key={parameter.name} className="rounded-full bg-indigo-50 px-2 py-1 text-[10px] text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300">{parameter.label} · {parameter.required ? '必填' : '选填'}</span>)}</div><p className="mt-2 text-[10px] text-slate-400">模板来源、输入参数、执行步骤和输出结构会一起固化到 Skill Harness。</p></div>}
                    <div className="flex justify-between items-center">
                      <span className="text-xs font-bold text-slate-700 dark:text-slate-350">技能测试沙盒</span>
                      <div className="flex gap-2">
                        <select 
                          value={skillPreviewFactory} 
                          onChange={e => setSkillPreviewFactory(e.target.value)}
                          className="bg-slate-50 dark:bg-slate-800 text-[10px] px-2 py-1 rounded border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300"
                        >
                          <option value="全部厂区">全部厂区</option>
                          <option value="厂区A">厂区A</option>
                          <option value="厂区B">厂区B</option>
                        </select>
                        <button 
                          onClick={handleRunSkillPreview}
                          disabled={isRunningSkillPreview}
                          className="bg-indigo-650 hover:bg-indigo-700 text-white text-[10px] px-3.5 py-1.5 rounded font-bold flex items-center gap-1"
                        >
                          {isRunningSkillPreview && <RefreshCw className="w-3 h-3 animate-spin" />}
                          测试执行
                        </button>
                      </div>
                    </div>

                    <div className="min-h-[18rem] h-auto border border-slate-100 dark:border-slate-800 rounded-xl p-4 bg-slate-50/20 dark:bg-slate-900/10 flex flex-col min-h-0 overflow-y-auto">
                      {skillPreviewResult ? (
                        <QueryResultView 
                          result={skillPreviewResult} 
                          fields={fields}
                          darkMode={darkMode}
                          hideLineage={true}
                        />
                      ) : skillPreviewError ? (
                        <div className="text-xs text-rose-500 font-mono text-center">{skillPreviewError}</div>
                      ) : isRunningSkillPreview ? (
                        <div className="text-xs text-slate-400 text-center flex flex-col items-center gap-2">
                          <RefreshCw className="w-4 h-4 animate-spin text-indigo-500" />
                          沙盒编译器映射转换执行中...
                        </div>
                      ) : (
                        <div className="text-xs text-slate-400 text-center">点击「测试执行」将调用大模型映射输入参数，执行所对应的数据视图获取。</div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex justify-end gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
                  <button 
                    onClick={() => setSkillMode('list')}
                    className="border border-slate-200 dark:border-slate-800 px-4 py-2 rounded-lg text-xs text-slate-650 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800"
                  >
                    取消
                  </button>
                  <button 
                    onClick={handleSaveSkill}
                    disabled={isSavingSkill}
                    className="bg-indigo-650 hover:bg-indigo-700 disabled:opacity-60 text-white text-xs font-semibold px-4 py-2 rounded-lg transition-colors flex items-center gap-1.5"
                  >
                    <Save className="w-4 h-4" />
                    保存技能
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* --- REPORTS SUB TAB --- */}
        {activeSubTab === 'reports' && (
          <div className="p-6 max-w-5xl mx-auto space-y-6 text-left">
            {reportMode === 'list' ? (
              <>
                <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-4">
                  <div className="flex items-center gap-2 flex-1 max-w-md">
                    <div className="relative flex-1">
                      <Search className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" />
                      <input 
                        type="text" 
                        placeholder="搜索我的自定义报表..."
                        value={reportSearch}
                        onChange={e => setReportSearch(e.target.value)}
                        className="w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800/80 rounded-lg pl-9 pr-4 py-1.5 text-xs outline-none text-slate-800 dark:text-slate-200"
                      />
                    </div>
                    {/* Layout Switcher */}
                    <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg border border-slate-200 dark:border-slate-700/60 flex-shrink-0">
                      <button
                        onClick={() => setViewLayout('card')}
                        className={`p-1.5 rounded-md transition-colors ${viewLayout === 'card' ? 'bg-white dark:bg-slate-900 shadow-xs text-indigo-650 dark:text-indigo-400' : 'text-slate-455 hover:text-slate-655'}`}
                        title="卡片视图"
                      >
                        <LayoutGrid className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => setViewLayout('table')}
                        className={`p-1.5 rounded-md transition-colors ${viewLayout === 'table' ? 'bg-white dark:bg-slate-900 shadow-xs text-indigo-650 dark:text-indigo-400' : 'text-slate-455 hover:text-slate-655'}`}
                        title="表格视图"
                      >
                        <List className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                  {primaryTab === 'workbench' && (
                    <button 
                      onClick={handleOpenCreateReport}
                      className="bg-indigo-650 hover:bg-indigo-700 text-white text-xs font-semibold px-4 py-2 rounded-lg flex items-center gap-1 transition-colors whitespace-nowrap"
                    >
                      <Plus className="w-4 h-4" />
                      新建报表模版
                    </button>
                  )}
                </div>

                {showMarketplace ? (
                  <div className="space-y-6">
                    {/* Official Reports */}
                    <div className="space-y-3">
                      <h3 className="text-xs font-bold text-slate-800 dark:text-slate-300">官方内置报表 ({visibleOfficialReports.length})</h3>
                      {visibleOfficialReports.length === 0 ? (
                        <p className="text-xs text-slate-400 italic">暂无官方内置报表模板。</p>
                      ) : viewLayout === 'card' ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {visibleOfficialReports.map(report => (
                            <div key={getAssetIdentity(report, report.report_id)} className="bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 rounded-xl p-5 space-y-4 shadow-sm hover:border-slate-350 transition-colors">
                              <div className="flex justify-between items-start gap-2">
                                <div>
                                  <h4 className="font-bold text-slate-900 dark:text-white text-xs">{report.name}</h4>
                                  <span className="text-[9px] font-mono text-slate-400 bg-slate-50 dark:bg-slate-950 px-1.5 py-0.5 rounded inline-block mt-1">{report.report_id}</span>
                                </div>
                                <span className="px-2 py-0.5 text-[9px] rounded-full font-bold bg-indigo-50 text-indigo-755 dark:bg-indigo-950/20 dark:text-indigo-400">官方</span>
                              </div>
                              <p className="text-xs text-slate-500 dark:text-slate-400 leading-normal line-clamp-2">{report.description}</p>
                              
                              <div className="flex gap-2 text-[9px] text-slate-400 border-t border-slate-50 dark:border-slate-850 pt-2.5">
                                <div>输出格式：{report.outputTypes?.join(', ') || 'N/A'}</div>
                                <div>推送渠道：{report.channels?.join(', ') || 'N/A'}</div>
                              </div>

                              <div className="flex justify-end gap-2 pt-1 border-t border-slate-50 dark:border-slate-850/60">
                                {onPreviewReport && (
                                  <button 
                                    onClick={() => onPreviewReport(report)}
                                    className="px-2.5 py-1.5 rounded hover:bg-slate-105 dark:hover:bg-slate-800 text-[10px] text-slate-655 dark:text-slate-355 border border-slate-200 dark:border-slate-800 flex items-center gap-0.5 font-semibold"
                                  >
                                    查看模版
                                  </button>
                                )}
                                <button 
                                  onClick={() => handleDeriveToCustom('report', report.report_id, report.name)}
                                  disabled={isCloning}
                                  className="px-2.5 py-1.5 rounded bg-indigo-50 hover:bg-indigo-105 dark:bg-indigo-950/30 text-[10px] text-indigo-650 dark:text-indigo-400 font-bold flex items-center gap-0.5"
                                >
                                  <Save className="w-3.5 h-3.5" />
                                  另存为我的报表
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="w-full overflow-x-auto rounded-xl border border-slate-200/80 dark:border-slate-800/85 bg-white dark:bg-slate-900 shadow-xs">
                          <table className="min-w-full text-xs text-left border-collapse">
                            <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200/80 dark:border-slate-800/85">
                              <tr>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">模板名称</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">模板 ID</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">输出格式</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300 text-right">操作</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/70">
                              {visibleOfficialReports.map(report => (
                                <tr key={getAssetIdentity(report, report.report_id)} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30 transition-colors">
                                  <td className="px-4 py-3.5 font-bold text-slate-900 dark:text-white">{report.name}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-500 dark:text-slate-400">{report.report_id}</td>
                                  <td className="px-4 py-3.5">
                                    <div className="flex gap-1 flex-wrap">
                                      {report.outputTypes?.map(t => (
                                        <span key={t} className="px-1.5 py-0.5 bg-indigo-50/60 dark:bg-indigo-950/20 text-indigo-650 dark:text-indigo-400 rounded text-[10px] font-mono uppercase">{t}</span>
                                      ))}
                                    </div>
                                  </td>
                                  <td className="px-4 py-3.5 text-right space-x-2">
                                    {onPreviewReport && (
                                      <button onClick={() => onPreviewReport(report)} className="text-slate-555 hover:text-slate-855 dark:text-slate-400 dark:hover:text-slate-200 hover:underline">查看模版</button>
                                    )}
                                    <button onClick={() => handleDeriveToCustom('report', report.report_id, report.name)} className="text-indigo-650 hover:text-indigo-855 dark:text-indigo-400 dark:hover:text-indigo-300 hover:underline font-semibold">另存为我的</button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>

                    {/* Shared Reports */}
                    <div className="space-y-3">
                      <h3 className="text-xs font-bold text-slate-800 dark:text-slate-300">组织内部共享报表 ({visibleSharedReports.length})</h3>
                      {visibleSharedReports.length === 0 ? (
                        <p className="text-xs text-slate-400 italic">暂无共享报表模板。</p>
                      ) : viewLayout === 'card' ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {visibleSharedReports.map(report => (
                            <div key={getAssetIdentity(report, report.report_id)} className="bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 rounded-xl p-5 space-y-4 shadow-sm hover:border-slate-350 transition-colors">
                              <div className="flex justify-between items-start gap-2">
                                <div>
                                  <h4 className="font-bold text-slate-900 dark:text-white text-xs">{report.name}</h4>
                                  <span className="text-[9px] font-mono text-slate-400 bg-slate-50 dark:bg-slate-950 px-1.5 py-0.5 rounded inline-block mt-1">{report.report_id}</span>
                                </div>
                                <span className="px-2 py-0.5 text-[9px] rounded-full font-bold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/20 dark:text-emerald-400">共享</span>
                              </div>
                              <p className="text-xs text-slate-500 dark:text-slate-400 leading-normal line-clamp-2">{report.description}</p>
                              
                              <div className="flex gap-2 text-[9px] text-slate-400 border-t border-slate-50 dark:border-slate-850 pt-2.5">
                                <div>输出格式：{report.outputTypes?.join(', ') || 'N/A'}</div>
                                <div>推送渠道：{report.channels?.join(', ') || 'N/A'}</div>
                              </div>

                              <div className="flex justify-end gap-2 pt-1 border-t border-slate-50 dark:border-slate-850/60">
                                {onPreviewReport && (
                                  <button 
                                    onClick={() => onPreviewReport(report)}
                                    className="px-2.5 py-1.5 rounded hover:bg-slate-105 dark:hover:bg-slate-800 text-[10px] text-slate-655 dark:text-slate-350 border border-slate-200 dark:border-slate-800 flex items-center gap-0.5 font-semibold"
                                  >
                                    查看模版
                                  </button>
                                )}
                                <button 
                                  onClick={() => handleDeriveToCustom('report', report.report_id, report.name)}
                                  disabled={isCloning}
                                  className="px-2.5 py-1.5 rounded bg-indigo-50 hover:bg-indigo-105 dark:bg-indigo-950/30 text-[10px] text-indigo-650 dark:text-indigo-400 font-bold flex items-center gap-0.5"
                                >
                                  <Save className="w-3.5 h-3.5" />
                                  另存为我的报表
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="w-full overflow-x-auto rounded-xl border border-slate-200/80 dark:border-slate-800/85 bg-white dark:bg-slate-900 shadow-xs">
                          <table className="min-w-full text-xs text-left border-collapse">
                            <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200/80 dark:border-slate-800/85">
                              <tr>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">模板名称</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">模板 ID</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">输出格式</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300 font-mono">共享者</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300 text-right">操作</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/70">
                              {visibleSharedReports.map(report => (
                                <tr key={getAssetIdentity(report, report.report_id)} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30 transition-colors">
                                  <td className="px-4 py-3.5 font-bold text-slate-900 dark:text-white">{report.name}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-500 dark:text-slate-400">{report.report_id}</td>
                                  <td className="px-4 py-3.5">
                                    <div className="flex gap-1 flex-wrap">
                                      {report.outputTypes?.map(t => (
                                        <span key={t} className="px-1.5 py-0.5 bg-indigo-50/60 dark:bg-indigo-950/20 text-indigo-650 dark:text-indigo-400 rounded text-[10px] font-mono uppercase">{t}</span>
                                      ))}
                                    </div>
                                  </td>
                                  <td className="px-4 py-3.5 text-slate-555 dark:text-slate-450">{report.owner}</td>
                                  <td className="px-4 py-3.5 text-right space-x-2">
                                    {onPreviewReport && (
                                      <button onClick={() => onPreviewReport(report)} className="text-slate-555 hover:text-slate-855 dark:text-slate-400 dark:hover:text-slate-200 hover:underline">查看模版</button>
                                    )}
                                    <button onClick={() => handleDeriveToCustom('report', report.report_id, report.name)} className="text-indigo-650 hover:text-indigo-855 dark:text-indigo-400 dark:hover:text-indigo-300 hover:underline font-semibold">另存为我的</button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="space-y-6">
                    {/* Custom workbench reports list */}
                    <div className="space-y-3">
                      <h3 className="text-xs font-bold text-slate-800 dark:text-slate-300">我创建的报表模版 ({visibleCustomReports.length})</h3>
                      {visibleCustomReports.length === 0 ? (
                        <p className="text-xs text-slate-400 italic">暂无自定义报表。</p>
                      ) : viewLayout === 'card' ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {visibleCustomReports.map(report => (
                            <div key={getAssetIdentity(report, report.report_id)} className="bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 rounded-xl p-5 space-y-4 shadow-sm hover:border-slate-350 transition-colors">
                              <div className="flex justify-between items-start gap-2">
                                <div>
                                  <h4 className="font-bold text-slate-900 dark:text-white text-xs">{report.name}</h4>
                                  <span className="text-[9px] font-mono text-slate-400 bg-slate-50 dark:bg-slate-950 px-1.5 py-0.5 rounded inline-block mt-1">{report.report_id}</span>
                                </div>
                                <span className={`px-2 py-0.5 text-[9px] rounded-full font-bold ${
                                  report.visibility === 'shared' 
                                    ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/20 dark:text-emerald-400' 
                                    : 'bg-amber-50 text-amber-700 dark:bg-amber-950/20 dark:text-amber-400'
                                }`}>{report.visibility === 'shared' ? '共享' : '私有'}</span>
                              </div>
                              <p className="text-xs text-slate-500 dark:text-slate-400 leading-normal line-clamp-2">{report.description}</p>
                              
                              <div className="flex gap-2 text-[9px] text-slate-450 border-t border-slate-50 dark:border-slate-850 pt-2.5">
                                <div>输出格式：{report.outputTypes.join(', ')}</div>
                                <div>推送渠道：{report.channels.join(', ')}</div>
                              </div>

                              {renderAdvancedMetadata(report, `report_${report.report_id}`)}

                              <div className="flex justify-end gap-2 pt-1 border-t border-slate-50 dark:border-slate-850/60">
                                <button 
                                  onClick={() => handleOpenPromotion(report, 'report')}
                                  className="hidden"
                                >
                                  <ArrowUpCircle className="w-3.5 h-3.5" />
                                  晋升企业包
                                </button>
                                <button 
                                  onClick={() => handleOpenEditReport(report)}
                                  className="px-2.5 py-1.5 rounded bg-indigo-50 hover:bg-indigo-100 dark:bg-indigo-950/30 text-[10px] text-indigo-650 dark:text-indigo-400 font-bold flex items-center gap-0.5"
                                >
                                  <Wand2 className="w-3.5 h-3.5" />
                                  编辑推送规则
                                </button>
                                <button 
                                  onClick={() => handleDeleteReport(report.report_id)}
                                  className="px-2 py-1.5 rounded hover:bg-rose-50 hover:text-rose-600 text-[10px] text-slate-400 transition-colors"
                                  title="删除"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="w-full overflow-x-auto rounded-xl border border-slate-200/80 dark:border-slate-800/85 bg-white dark:bg-slate-900 shadow-xs">
                          <table className="min-w-full text-xs text-left border-collapse">
                            <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200/80 dark:border-slate-800/85">
                              <tr>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">模板名称</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">模板 ID</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">工作区</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">版本</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">输出格式</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">可见性</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300 font-mono">订阅调度</th>
                                <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300 text-right">操作</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/70">
                              {visibleCustomReports.map(report => (
                                <tr key={getAssetIdentity(report, report.report_id)} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30 transition-colors">
                                  <td className="px-4 py-3.5 font-bold text-slate-900 dark:text-white">{report.name}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-500 dark:text-slate-400">{report.report_id}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-550 dark:text-slate-400">{report.workspace_id || '个人空间'}</td>
                                  <td className="px-4 py-3.5 font-mono text-slate-550 dark:text-slate-400">{report.version || 'v1.0.0'}</td>
                                  <td className="px-4 py-3.5">
                                    <div className="flex gap-1 flex-wrap">
                                      {report.outputTypes?.map(t => (
                                        <span key={t} className="px-1.5 py-0.5 bg-indigo-50/60 dark:bg-indigo-950/20 text-indigo-655 dark:text-indigo-400 rounded text-[10px] font-mono uppercase">{t}</span>
                                      ))}
                                    </div>
                                  </td>
                                  <td className="px-4 py-3.5">
                                    <span className={`px-2 py-0.5 text-[10px] rounded-full font-semibold ${
                                      report.visibility === 'shared' 
                                        ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/20 dark:text-emerald-400' 
                                        : 'bg-amber-50 text-amber-700 dark:bg-amber-950/20 dark:text-amber-400'
                                    }`}>{report.visibility === 'shared' ? '共享' : '私有'}</span>
                                  </td>
                                  <td className="px-4 py-3.5 text-slate-550 dark:text-slate-455 font-mono">
                                    {report.schedule?.mode === 'scheduled' ? `定时 (${report.schedule.status === 'stopped' ? '已暂停' : '已激活'})` : '即时执行'}
                                  </td>
                                  <td className="px-4 py-3.5 text-right space-x-2">
                                    <button onClick={() => handleOpenEditReport(report)} className="text-indigo-655 hover:text-indigo-855 dark:text-indigo-400 dark:hover:text-indigo-300 hover:underline">编辑推送规则</button>
                                    <button onClick={() => handleDeleteReport(report.report_id)} className="text-rose-655 hover:text-rose-855 dark:text-rose-400 dark:hover:text-rose-350 hover:underline">删除</button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </>
            ) : (
              // Create or Edit Report Form view
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 shadow-sm space-y-5">
                <div className="flex justify-between items-center border-b border-slate-100 dark:border-slate-800 pb-3">
                  <h2 className="text-sm font-bold text-slate-900 dark:text-white">{reportMode === 'create' ? '新建报表发布计划' : `编辑计划: ${selectedReport?.name}`}</h2>
                  <button onClick={() => setReportMode('list')} className="text-slate-400 hover:text-slate-600"><X className="w-5 h-5" /></button>
                </div>

                <div className="grid grid-cols-5 gap-2 rounded-xl bg-slate-50 p-1 dark:bg-slate-950">{(['html', 'pdf', 'pptx', 'docx', 'push'] as const).map(type => <button type="button" key={type} onClick={() => { setReportDraft(current => ({ ...current, outputTypes: [type], channels: type === 'push' ? (current.channels.length ? current.channels : ['email']) : [] })); setReportTemplate(type === 'docx' || type === 'pdf' ? 'formal_report' : type === 'html' ? 'interactive_dashboard' : 'management_review'); setReportAiPlan(null); setReportPreviewVersion(0); }} className={`rounded-lg px-3 py-2 text-xs font-bold ${reportDraft.outputTypes[0] === type ? 'bg-white text-indigo-700 shadow-sm dark:bg-slate-800 dark:text-indigo-300' : 'text-slate-500'}`}>{reportOutputLabels[type]}</button>)}</div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
                  <div className="space-y-4">
                    <div>
                      <label className="block text-[10px] text-slate-400 font-semibold mb-1">报表大纲名称</label>
                      <input 
                        type="text" 
                        placeholder="例如: 每日准时交付时效日报"
                        value={reportDraft.name}
                        onChange={e => setReportDraft({...reportDraft, name: e.target.value})}
                        className="w-full bg-slate-50 dark:bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-250 dark:border-slate-700 outline-none text-slate-800 dark:text-slate-200"
                      />
                    </div>

                    <div>
                      <label className="block text-[10px] text-slate-400 font-semibold mb-1">推送内容与业务目的描述</label>
                      <textarea 
                        rows={3}
                        placeholder="描述该推送大纲的计算指标及其排版排版大纲..."
                        value={reportDraft.description}
                        onChange={e => setReportDraft({...reportDraft, description: e.target.value})}
                        className="w-full bg-slate-50 dark:bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-250 dark:border-slate-700 outline-none text-slate-800 dark:text-slate-200 resize-none font-sans"
                      />
                    </div>

                    <div className="grid grid-cols-3 gap-3"><div><label className="mb-1 block text-[10px] font-semibold text-slate-400">时间粒度</label><input value={reportTimeGrain} onChange={e => setReportTimeGrain(e.target.value)} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-800" /></div><div><label className="mb-1 block text-[10px] font-semibold text-slate-400">汇报人</label><input value={reportPresenter} onChange={e => setReportPresenter(e.target.value)} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-800" /></div><div><label className="mb-1 block text-[10px] font-semibold text-slate-400">阅读 / 汇报对象</label><input value={reportAudience} onChange={e => setReportAudience(e.target.value)} placeholder="管理层、业务负责人" className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-800" /></div></div>

                    <div><label className="mb-1 block text-[10px] font-semibold text-slate-400">报告内容背景与重点</label><textarea value={reportContent} onChange={e => setReportContent(e.target.value)} rows={3} placeholder="说明业务范围、关键问题、需要突出展示的结论" className="w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-800" /></div>

                    {reportDraft.outputTypes[0] !== 'push' && <div className="space-y-2 rounded-xl border border-slate-200 p-3 dark:border-slate-800"><div className="flex gap-4 text-[10px] font-bold"><label><input type="radio" checked={reportTemplateMode === 'built_in'} onChange={() => setReportTemplateMode('built_in')} /> 内置模板</label><label><input type="radio" checked={reportTemplateMode === 'upload'} onChange={() => setReportTemplateMode('upload')} /> 上传模板</label></div>{reportTemplateMode === 'built_in' ? <select value={reportTemplate} onChange={e => setReportTemplate(e.target.value)} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-800">{reportTemplates[reportDraft.outputTypes[0] as 'pptx' | 'docx' | 'html'].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select> : <input type="file" accept={reportDraft.outputTypes[0] === 'pptx' ? '.pptx' : reportDraft.outputTypes[0] === 'docx' ? '.docx' : '.html,.zip'} className="w-full text-xs" />}</div>}

                    <div className="grid grid-cols-2 gap-3"><div><label className="mb-1 block text-[10px] font-semibold text-slate-400">绑定指标</label><div className="max-h-32 space-y-1 overflow-y-auto rounded-lg border border-slate-200 p-2 dark:border-slate-700">{metrics.map(metric => <label key={metric.metric_code} className="flex items-center gap-2 text-[10px]"><input type="checkbox" checked={reportBoundMetrics.includes(metric.metric_code)} onChange={e => setReportBoundMetrics(current => e.target.checked ? [...current, metric.metric_code] : current.filter(code => code !== metric.metric_code))} /> <span className="truncate">{metric.name}</span></label>)}</div></div><div><label className="mb-1 block text-[10px] font-semibold text-slate-400">绑定技能</label><div className="max-h-32 space-y-1 overflow-y-auto rounded-lg border border-slate-200 p-2 dark:border-slate-700">{skills.map(skill => <label key={skill.skill_id} className="flex items-center gap-2 text-[10px]"><input type="checkbox" checked={reportBoundSkills.includes(skill.skill_id)} onChange={e => setReportBoundSkills(current => e.target.checked ? [...current, skill.skill_id] : current.filter(id => id !== skill.skill_id))} /> <span className="truncate">{skill.name}</span></label>)}</div></div></div>

                    <div>
                      <label className="block text-[10px] text-slate-400 font-semibold mb-1">LLM 组装工作流 Prompt 大纲</label>
                      <textarea 
                        rows={3}
                        placeholder="大模型根据该 Prompt 自动调用对应的指标及文本渲染格式拼装 PPTX/DOCX..."
                        value={reportDraft.flow}
                        onChange={e => setReportDraft({...reportDraft, flow: e.target.value})}
                        className="w-full bg-slate-50 dark:bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-250 dark:border-slate-700 outline-none text-slate-800 dark:text-slate-200 resize-none font-mono"
                      />
                    </div>
                  </div>

                  <div className="space-y-4 bg-slate-50 dark:bg-slate-900/60 p-4 rounded-xl border border-slate-100 dark:border-slate-800/80">
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-200">生成与分发设定</span>
                    <button type="button" onClick={() => void handleBuildReportPlan()} disabled={isBuildingReportPlan} className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50"><Wand2 className="h-3.5 w-3.5" />{isBuildingReportPlan ? '正在生成' : reportPreviewVersion ? '重新生成预览' : '生成 AI 大纲与预览'}</button>

                    {reportAiPlan && <div className="space-y-3 rounded-xl border border-indigo-100 bg-white p-3 dark:border-indigo-900/60 dark:bg-slate-900"><div className="flex justify-between"><span className="text-[10px] font-bold text-indigo-600">{reportOutputLabels[reportDraft.outputTypes[0]]} 预览 v{reportPreviewVersion}</span><span className="text-[10px] text-slate-400">{reportTemplateMode === 'upload' ? '上传模板' : '内置模板'}</span></div><h3 className="text-sm font-bold">{reportAiPlan.title || reportDraft.name}</h3><div className="grid grid-cols-2 gap-2">{(reportAiPlan.sections || reportDraft.sections).slice(0, 6).map((section, index) => <div key={`${section}_${index}`} className="min-h-20 rounded-lg border border-slate-200 bg-slate-50 p-2 dark:border-slate-700 dark:bg-slate-800"><span className="text-[9px] text-slate-400">{index + 1}</span><p className="mt-1 text-[10px] font-bold">{section}</p><p className="mt-1 line-clamp-2 text-[9px] text-slate-400">{reportAiPlan.outline?.[index] || `${reportBoundMetrics.length} 个指标 · ${reportBoundSkills.length} 个技能`}</p></div>)}</div><p className="rounded-lg bg-slate-50 p-2 text-[10px] text-slate-500 dark:bg-slate-800">{reportAiPlan.flow || reportDraft.flow}</p><div className="flex gap-2"><input value={reportAdjustment} onChange={e => setReportAdjustment(e.target.value)} placeholder="继续调整大纲、顺序、内容或样式" className="min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-950" /><button type="button" onClick={() => void handleBuildReportPlan(reportAdjustment)} disabled={!reportAdjustment.trim() || isBuildingReportPlan} className="rounded-lg border border-indigo-200 px-3 text-xs font-bold text-indigo-600 disabled:opacity-50">迭代</button></div></div>}
                    {reportArtifact && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/20 dark:text-emerald-300"><div className="flex items-center gap-2 font-bold"><CheckCircle2 className="h-4 w-4" /> 文件已生成：{reportArtifact.filename}</div><div className="mt-3 flex gap-2"><a href={runtimeAssetUrl(reportArtifact.download_url)} className="rounded-lg bg-emerald-600 px-3 py-2 font-bold text-white">下载文件</a>{reportArtifact.view_url && <a href={runtimeAssetUrl(reportArtifact.view_url)} target="_blank" rel="noreferrer" className="rounded-lg border border-emerald-300 px-3 py-2 font-bold">发布预览</a>}<button type="button" onClick={() => setReportMode('list')} className="ml-auto rounded-lg border border-slate-200 px-3 py-2">完成</button></div></div>}
                    
                    <div className="space-y-3 text-xs">
                      <div>
                        <span className="block text-[10px] text-slate-400 font-semibold mb-1">支持输出格式</span>
                        <div className="flex gap-4">
                          {['pptx', 'docx', 'html'].map(type => (
                            <label key={type} className="flex items-center gap-1.5 cursor-pointer uppercase font-bold">
                              <input 
                                type="checkbox" 
                                checked={reportDraft.outputTypes.includes(type as any)} 
                                onChange={e => {
                                  const list = e.target.checked 
                                    ? [...reportDraft.outputTypes, type as any]
                                    : reportDraft.outputTypes.filter(t => t !== type);
                                  setReportDraft({...reportDraft, outputTypes: list});
                                }}
                                className="rounded text-indigo-650"
                              />
                              {type}
                            </label>
                          ))}
                        </div>
                      </div>

                      <div>
                        <span className="block text-[10px] text-slate-400 font-semibold mb-1">推送渠道</span>
                        <div className="flex gap-4">
                          {['ec', 'email'].map(ch => (
                            <label key={ch} className="flex items-center gap-1.5 cursor-pointer uppercase font-bold">
                              <input 
                                type="checkbox" 
                                checked={reportDraft.channels.includes(ch as any)} 
                                onChange={e => {
                                  const list = e.target.checked 
                                    ? [...reportDraft.channels, ch as any]
                                    : reportDraft.channels.filter(t => t !== ch);
                                  setReportDraft({...reportDraft, channels: list});
                                }}
                                className="rounded text-indigo-650"
                              />
                              {ch === 'ec' ? '企业微信' : '电子邮箱'}
                            </label>
                          ))}
                        </div>
                      </div>

                      <div>
                        <span className="block text-[10px] text-slate-400 font-semibold mb-1">分发排期</span>
                        <div className="flex gap-4 mb-2">
                          <label className="flex items-center gap-1.5 cursor-pointer">
                            <input 
                              type="radio" 
                              name="sched_mode" 
                              checked={reportDraft.schedule.mode === 'immediate'} 
                              onChange={() => setReportDraft({
                                ...reportDraft,
                                schedule: {...reportDraft.schedule, mode: 'immediate'}
                              })}
                            />
                            立即触发 (一次性)
                          </label>
                          <label className="flex items-center gap-1.5 cursor-pointer">
                            <input 
                              type="radio" 
                              name="sched_mode" 
                              checked={reportDraft.schedule.mode === 'scheduled'} 
                              onChange={() => setReportDraft({
                                ...reportDraft,
                                schedule: {...reportDraft.schedule, mode: 'scheduled'}
                              })}
                            />
                            定时自动推送 (Cron)
                          </label>
                        </div>

                        {reportDraft.schedule.mode === 'scheduled' && (
                          <input 
                            type="text" 
                            placeholder="Cron 表达式，例如: 0 9 * * 1 (每周一早上九点)" 
                            value={reportDraft.schedule.sendAt}
                            onChange={e => setReportDraft({
                              ...reportDraft,
                              schedule: {...reportDraft.schedule, sendAt: e.target.value}
                            })}
                            className="w-full bg-white dark:bg-slate-950 text-xs px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-800 outline-none text-slate-800 dark:text-slate-200 font-mono"
                          />
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="flex justify-end gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
                  <button 
                    onClick={() => setReportMode('list')}
                    className="border border-slate-200 dark:border-slate-800 px-4 py-2 rounded-lg text-xs text-slate-650 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800"
                  >
                    取消
                  </button>
                  <button 
                    onClick={handleSaveReport}
                    disabled={isSavingReport}
                    className="bg-indigo-650 hover:bg-indigo-700 disabled:opacity-60 text-white text-xs font-semibold px-4 py-2 rounded-lg transition-colors flex items-center gap-1.5"
                  >
                    <Save className="w-4 h-4" />
                    保存报表计划
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Promotion Wizard Modal */}
        {showPromotionModal && selectedAssetForPromotion && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/70 backdrop-blur-md transition-opacity duration-300">
            <div className="relative w-full max-w-3xl max-h-[85vh] bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl overflow-y-auto flex flex-col scale-100 transition-transform duration-300">
              
              {/* Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 dark:border-slate-800 bg-gradient-to-r from-slate-50 to-white dark:from-slate-900/50 dark:to-slate-900">
                <div>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-1.5">
                    <ArrowUpCircle className="w-5 h-5 text-amber-500" />
                    资产晋升审查向导 (Promotion Review Wizard)
                  </h3>
                  <p className="text-[10px] text-slate-450 mt-0.5">晋升个人分析资产为受治理的企业扩展包资产</p>
                </div>
                <button onClick={() => setShowPromotionModal(false)} className="text-slate-400 hover:text-slate-655 dark:hover:text-slate-200">
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Main Content */}
              <div className="p-6 flex-1 space-y-5">
                
                {/* Step Indicator */}
                <div className="flex items-center gap-3">
                  <div className={`flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${wizardStage === 'preview' ? 'bg-amber-500 text-white' : 'bg-slate-105 dark:bg-slate-800 text-slate-400'}`}>1</div>
                  <div className="text-[10px] font-semibold text-slate-500 dark:text-slate-400">审查晋升预览</div>
                  <div className="flex-1 h-px bg-slate-200 dark:bg-slate-800"></div>
                  <div className={`flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${wizardStage === 'status' ? 'bg-indigo-600 text-white' : 'bg-slate-105 dark:bg-slate-800 text-slate-400'}`}>2</div>
                  <div className="text-[10px] font-semibold text-slate-500 dark:text-slate-400">晋升生命周期状态</div>
                </div>

                {wizardStage === 'preview' ? (
                  <div className="space-y-4">
                    
                    {/* Asset summary card */}
                    <div className="bg-slate-50 dark:bg-slate-950 p-4 rounded-xl border border-slate-100 dark:border-slate-900">
                      <div className="font-semibold text-xs text-slate-850 dark:text-slate-200 mb-2">选定晋升资产：</div>
                      <div className="grid grid-cols-2 gap-4 text-xs font-mono">
                        <div>
                          <span className="text-slate-450 font-sans">资产类型:</span> <span className="font-bold text-slate-700 dark:text-slate-300">{selectedAssetForPromotion.asset_type === 'metric' ? '指标' : selectedAssetForPromotion.asset_type === 'skill' ? '技能' : '报表'}</span>
                        </div>
                        <div>
                          <span className="text-slate-450 font-sans">本地编码:</span> <span className="font-bold text-slate-700 dark:text-slate-300">{selectedAssetForPromotion.local_code}</span>
                        </div>
                        <div>
                          <span className="text-slate-450 font-sans">工作区归属:</span> <span className="font-bold text-slate-700 dark:text-slate-300">{selectedAssetForPromotion.workspace_id}</span>
                        </div>
                        <div>
                          <span className="text-slate-450 font-sans">精确版本:</span> <span className="font-bold text-slate-700 dark:text-slate-300">{selectedAssetForPromotion.version}</span>
                        </div>
                      </div>
                    </div>

                    {/* Target Pack and Conflict Simulation Selector */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-[10px] font-bold text-slate-700 dark:text-slate-300 mb-1.5">目标企业领域包</label>
                        <select
                          value={selectedTargetPackId}
                          onChange={(e) => setSelectedTargetPackId(e.target.value)}
                          className="w-full text-xs bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg p-2.5 focus:outline-none focus:ring-1 focus:ring-amber-500 text-slate-800 dark:text-slate-200 animate-none"
                        >
                          <option value="" disabled>选择目标包...</option>
                          {enterprisePacksList.map(pack => (
                            <option key={pack.pack_id} value={pack.pack_id}>{pack.name} ({pack.version})</option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="block text-[10px] font-bold text-slate-700 dark:text-slate-300 mb-1.5">模拟晋升审查冲突</label>
                        <div className="flex items-center h-10 px-3 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg">
                          <input
                            type="checkbox"
                            id="chk-simulate-conflicts"
                            checked={simulateConflicts}
                            onChange={(e) => setSimulateConflicts(e.target.checked)}
                            className="w-4 h-4 text-amber-500 bg-slate-100 border-slate-300 rounded focus:ring-amber-500 cursor-pointer"
                          />
                          <label htmlFor="chk-simulate-conflicts" className="ml-2 text-xs text-slate-650 dark:text-slate-355 cursor-pointer select-none">模拟冲突 (如数据源范围不兼容)</label>
                        </div>
                      </div>
                    </div>

                    {/* Preview Results */}
                    {previewLoading ? (
                      <div className="flex items-center justify-center p-12 text-slate-500 dark:text-slate-400">
                        <RefreshCw className="w-6 h-6 animate-spin mr-2 text-amber-500" />
                        <span className="text-xs">获取晋升资格审查中...</span>
                      </div>
                    ) : promotionPreviewResult ? (
                      <div className="space-y-4">
                        
                        {/* Eligibility Check Status */}
                        {promotionPreviewResult.eligible ? (
                          <div className="flex items-center gap-2 bg-emerald-50 dark:bg-emerald-950/20 text-emerald-700 dark:text-emerald-400 p-4 rounded-xl border border-emerald-100 dark:border-emerald-900/40 text-xs">
                            <CheckCircle2 className="w-5 h-5 shrink-0 text-emerald-500" />
                            <div>
                              <div className="font-bold">资格审查通过 (Eligibility Verified)</div>
                              <div className="text-[10px] text-emerald-600 dark:text-emerald-400/80 mt-0.5">该资产符合企业包版本兼容性、无循环依赖、无有效范围冲突。</div>
                            </div>
                          </div>
                        ) : (
                          <div className="space-y-2">
                            <div className="flex items-center gap-2 bg-rose-50 dark:bg-rose-950/20 text-rose-700 dark:text-rose-400 p-4 rounded-xl border border-rose-100 dark:border-rose-900/40 text-xs">
                              <AlertTriangle className="w-5 h-5 shrink-0 text-rose-500" />
                              <div>
                                <div className="font-bold">晋升资格审查未通过 (Eligibility Verification Failed)</div>
                                <div className="text-[10px] text-rose-600 dark:text-rose-400/80 mt-0.5">由于存在冲突，晋升已锁定。请根据以下详情调整资产后再试。</div>
                              </div>
                            </div>
                            {promotionPreviewResult.conflicts.map((conflict, idx) => (
                              <div key={idx} className="bg-slate-50 dark:bg-slate-950/50 border-l-4 border-rose-500 p-3 text-[10px] text-slate-700 dark:text-slate-300 rounded-r-lg">
                                <div className="font-bold text-rose-600 dark:text-rose-400">冲突原因: {conflict.code === 'scope_mismatch' ? '数据源/范围不匹配' : conflict.code}</div>
                                <div className="mt-1">{conflict.message}</div>
                                {conflict.asset_ref && (
                                  <div className="mt-1 font-mono text-[9px] text-slate-450">关联资产: {conflict.asset_ref.asset.local_code} (版本: {conflict.asset_ref.version})</div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Lineage Info */}
                        <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-100 dark:border-slate-800 space-y-2">
                          <h4 className="text-[10px] font-bold text-slate-800 dark:text-slate-200">晋升溯源血缘 (Lineage Provenance)</h4>
                          <p className="text-[9px] text-slate-450">以下资产快照将被复制并写入企业扩展包草稿中，而原始个人资产将完全保持独立且不可变。</p>
                          <div className="flex items-center gap-2 py-1.5 text-[10px] font-mono">
                            <span className="bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-400 px-2 py-1 rounded">个人资产: {selectedAssetForPromotion.local_code} ({selectedAssetForPromotion.version})</span>
                            <span className="text-slate-400">→</span>
                            <span className="bg-indigo-100 text-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-400 px-2 py-1 rounded">企业草稿资产: {selectedAssetForPromotion.local_code} (Draft)</span>
                          </div>
                        </div>

                        {/* Standard Field Proposals */}
                        {promotionPreviewResult.standard_fields.length > 0 && (
                          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-100 dark:border-slate-800 space-y-2 animate-none">
                            <h4 className="text-[10px] font-bold text-slate-800 dark:text-slate-200">生成的候选标准字段 (Generated Standard Field Proposals)</h4>
                            <div className="overflow-x-auto">
                              <table className="min-w-full text-[10px] text-left border-collapse">
                                <thead>
                                  <tr className="border-b border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-slate-500">
                                    <th className="px-2 py-1.5">物理表/列</th>
                                    <th className="px-2 py-1.5">标准字段ID</th>
                                    <th className="px-2 py-1.5">推荐业务名称</th>
                                    <th className="px-2 py-1.5">推导凭证 (Evidence)</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 text-slate-700 dark:text-slate-300">
                                  {promotionPreviewResult.standard_fields.map((f, idx) => (
                                    <tr key={idx} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/20">
                                      <td className="px-2 py-2 font-mono">{f.physical_table}.{f.physical_column}</td>
                                      <td className="px-2 py-2 font-mono font-bold text-indigo-650 dark:text-indigo-400">{f.field_id}</td>
                                      <td className="px-2 py-2">{f.business_name}</td>
                                      <td className="px-2 py-2 text-slate-455">{f.evidence}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}

                        {/* Mapping Candidates */}
                        {promotionPreviewResult.mapping_candidates.length > 0 && (
                          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-100 dark:border-slate-800 space-y-2 animate-none">
                            <h4 className="text-[10px] font-bold text-slate-800 dark:text-slate-200">物理映射建议候选 (Mapping Candidate Proposals)</h4>
                            <div className="overflow-x-auto">
                              <table className="min-w-full text-[10px] text-left border-collapse">
                                <thead>
                                  <tr className="border-b border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-slate-500">
                                    <th className="px-2 py-1.5">标准字段ID</th>
                                    <th className="px-2 py-1.5">映射表/列</th>
                                    <th className="px-2 py-1.5">置信度</th>
                                    <th className="px-2 py-1.5">依据</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 text-slate-700 dark:text-slate-300">
                                  {promotionPreviewResult.mapping_candidates.map((m, idx) => (
                                    <tr key={idx} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/20">
                                      <td className="px-2 py-2 font-mono font-bold">{m.standard_field_id}</td>
                                      <td className="px-2 py-2 font-mono">{m.physical_table}.{m.physical_column}</td>
                                      <td className="px-2 py-2">
                                        <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold ${m.confidence >= 0.9 ? 'bg-emerald-50 text-emerald-650 dark:bg-emerald-950/20' : 'bg-amber-50 text-amber-650 dark:bg-amber-950/20'}`}>{(m.confidence * 100).toFixed(0)}%</span>
                                      </td>
                                      <td className="px-2 py-2 text-slate-455">{m.evidence}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}

                      </div>
                    ) : (
                      <div className="text-center py-6 text-slate-400 text-xs italic">请选择目标企业领域包以开始审查预览。</div>
                    )}
                  </div>
                ) : (
                  <div className="space-y-6">
                    
                    {/* Success record header */}
                    {promotionRecord && (
                      <div className="space-y-4">
                        <div className="flex items-center gap-2 bg-indigo-50 dark:bg-indigo-950/20 text-indigo-750 dark:text-indigo-400 p-4 rounded-xl border border-indigo-100 dark:border-indigo-900/40 text-xs">
                          <CheckCircle2 className="w-5 h-5 shrink-0 text-indigo-500" />
                          <div>
                            <div className="font-bold">晋升成功！资产已提交至目标包草稿层</div>
                            <div className="text-[10px] text-indigo-600 dark:text-indigo-400/80 mt-0.5">晋升批次ID: {promotionRecord.promotion_id}，可在企业领域包编辑器中管理此更改。</div>
                          </div>
                        </div>

                        {/* Progress bar displaying separate lifecycle states */}
                        <div className="bg-slate-50 dark:bg-slate-950 p-6 rounded-xl border border-slate-100 dark:border-slate-900">
                          <div className="font-bold text-[10px] text-slate-700 dark:text-slate-300 mb-4">晋升治理状态跟踪 (Lifecycle State Machine):</div>
                          <div className="flex items-center justify-between w-full">
                            {[
                              { state: 'draft', label: '草稿 (Draft)', desc: '资产进入企业草稿包' },
                              { state: 'published', label: '发布 (Published)', desc: '通过包版本冻结归档' },
                              { state: 'deployed', label: '部署 (Deployed)', desc: '部署实例已绑定' },
                              { state: 'validated', label: '校验 (Validated)', desc: '系统自动化冒烟通过' },
                              { state: 'activated', label: '激活 (Activated)', desc: '正式上线，对所有人可见' }
                            ].map((step, idx, arr) => {
                              const statesOrder = ['draft', 'published', 'deployed', 'validated', 'activated'];
                              const currentIdx = statesOrder.indexOf(promotionRecord.lifecycle);
                              const stepIdx = statesOrder.indexOf(step.state);
                              
                              const isCompleted = stepIdx < currentIdx;
                              const isActive = stepIdx === currentIdx;
                              
                              return (
                                <React.Fragment key={step.state}>
                                  <div className="flex flex-col items-center relative z-10">
                                    <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-xs shadow-md transition-all duration-300 ${
                                      isCompleted ? 'bg-emerald-500 text-white' : (isActive ? 'bg-indigo-600 text-white ring-4 ring-indigo-500/20' : 'bg-slate-200 dark:bg-slate-800 text-slate-400')
                                    }`}>
                                      {isCompleted ? '✓' : stepIdx + 1}
                                    </div>
                                    <span className={`text-[10px] font-bold mt-2 ${isActive ? 'text-indigo-650 dark:text-indigo-400' : 'text-slate-500'}`}>{step.label}</span>
                                    <span className="text-[7px] text-slate-400 mt-0.5 text-center w-20 line-clamp-1">{step.desc}</span>
                                  </div>
                                  {idx < arr.length - 1 && (
                                    <div className="flex-1 h-1 mx-2 rounded-full relative -mt-4 bg-slate-250 dark:bg-slate-800">
                                      <div className="absolute inset-0 bg-emerald-500 rounded-full transition-all duration-500" style={{ width: stepIdx < currentIdx ? '100%' : '0%' }}></div>
                                    </div>
                                  )}
                                </React.Fragment>
                              );
                            })}
                          </div>
                        </div>

                        {/* Permitted Next Action Gate */}
                        <div className="bg-slate-50 dark:bg-slate-950 p-4 rounded-xl border border-slate-100 dark:border-slate-900 space-y-3">
                          <div className="flex justify-between items-center">
                            <div>
                              <div className="font-bold text-xs text-slate-850 dark:text-slate-200">当前授权操作许可：</div>
                              <p className="text-[10px] text-slate-450 mt-0.5">生命周期操作需在对应的发布/部署工作台完成；此处刷新后端状态。</p>
                            </div>
                            {promotionRecord.lifecycle === 'activated' ? (
                              <span className="px-3 py-1.5 rounded-lg bg-emerald-500/10 text-emerald-500 font-bold text-[10px]">✓ 资产已激活</span>
                            ) : (
                              <button
                                onClick={handleAdvanceLifecycle}
                                disabled={statusLoading || promotionRecord.next_action === 'none'}
                                className="px-4 py-2 bg-indigo-650 hover:bg-indigo-700 disabled:opacity-50 text-white font-bold text-xs rounded-lg shadow-md transition-all duration-300 flex items-center gap-1.5"
                              >
                                {statusLoading && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                                刷新状态
                                {promotionRecord.next_action === 'publish_pack' && ' · 下一步：发布企业包'}
                                {promotionRecord.next_action === 'create_deployment' && ' · 下一步：创建部署'}
                                {promotionRecord.next_action === 'validate_deployment' && ' · 下一步：验证部署'}
                                {promotionRecord.next_action === 'activate_deployment' && ' · 下一步：激活部署'}
                              </button>
                            )}
                          </div>
                        </div>

                      </div>
                    )}

                  </div>
                )}

              </div>

              {/* Footer */}
              <div className="flex items-center justify-between px-6 py-4 border-t border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/50 rounded-b-2xl">
                <div>
                  {wizardStage === 'preview' && promotionPreviewResult && (
                    <span className="text-[10px] text-slate-450 font-medium">
                      包含 {promotionPreviewResult.standard_fields.length} 个标准字段建议，{promotionPreviewResult.mapping_candidates.length} 个映射建议
                    </span>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setShowPromotionModal(false)}
                    className="px-4 py-2 text-xs font-semibold bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-slate-550 dark:hover:bg-slate-750 text-slate-700 dark:text-slate-300 rounded-lg transition-colors"
                  >
                    关闭向导
                  </button>
                  {wizardStage === 'preview' && (
                    <button
                      onClick={handleConfirmPromotion}
                      disabled={promoting || !promotionPreviewResult?.eligible || !selectedTargetPackId}
                      className="px-4 py-2 text-xs font-bold bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white rounded-lg shadow-md transition-all duration-300 flex items-center gap-1"
                    >
                      {promoting && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                      确认晋升快照
                    </button>
                  )}
                </div>
              </div>

            </div>
          </div>
        )}
      </div>
      </div>
    </div>
  );
};
