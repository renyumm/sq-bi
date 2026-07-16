import React from 'react';
import { 
  Clock, 
  Share2, 
  Cpu,
  Sparkles,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  Database,
  Filter,
  Layers,
  Check,
  Save,
  MessageSquare,
  RefreshCw,
  AlertTriangle
} from 'lucide-react';
import { 
  ResponsiveContainer, 
  BarChart, 
  Bar, 
  LineChart, 
  Line, 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip as RechartsTooltip, 
  Legend 
} from 'recharts';
import { api } from '../api';
import type { QueryResult, SemanticField, SaveExplorationAsMetricRequest, EnterprisePack, Lineage } from '../api';

const columnNameLabels: Record<string, string> = {
  factory: '厂区',
  carrier: '承运商',
  status: '状态',
  shipments: '发货量',
  freight: '运费',
  cost: '成本',
  rate: '率',
  on_time: '准时数',
  delay: '延迟数',
  total_amount: '总金额',
  category: '类别',
  dimension: '维度',
  result: '结果'
};

const columnKey = (column: unknown): string => {
  if (typeof column === 'string') return column;
  if (column && typeof column === 'object') {
    const item = column as { key?: unknown; label?: unknown };
    if (typeof item.key === 'string') return item.key;
    if (typeof item.label === 'string') return item.label;
  }
  return '';
};

const formatColumnName = (column: unknown, fields: SemanticField[] = []): string => {
  const key = columnKey(column);
  if (!key) return '结果';
  const normalized = key.trim().toLowerCase();
  const matchedField = fields.find(field => 
    field.physical_name.toLowerCase() === normalized || 
    field.field_id.toLowerCase().endsWith(`.${normalized}`)
  );
  if (matchedField?.business_name) return matchedField.business_name;
  if (columnNameLabels[normalized]) return columnNameLabels[normalized];
  if (normalized.endsWith('_cnt')) return `${formatColumnName(normalized.replace(/_cnt$/, ''), fields)}数量`;
  if (normalized.endsWith('_rate')) return `${formatColumnName(normalized.replace(/_rate$/, ''), fields)}率`;
  if (normalized.endsWith('_amount')) return `${formatColumnName(normalized.replace(/_amount$/, ''), fields)}金额`;
  return key;
};

interface QueryResultViewProps {
  result: QueryResult;
  fields?: SemanticField[];
  darkMode?: boolean;
  hideChart?: boolean;
  hideTable?: boolean;
  hideLineage?: boolean;
  compact?: boolean;
  maxTableRows?: number;
  onShareClick?: (queryId: string) => void;
  onLineageClick?: (lineage: Lineage) => void;
  onMetricClick?: (metricId: string) => void;
  onClarifySubmit?: (interpretation: string) => void;
  onCorrectSubmit?: (correctionText: string) => void;
  onSaveMetric?: (payload: SaveExplorationAsMetricRequest) => Promise<void>;
  currentUserId?: string;
  onAdoptGap?: (dsId: string, spaceId: string, fieldId: string) => void;
}

export const QueryResultView: React.FC<QueryResultViewProps> = ({
  result,
  fields = [],
  darkMode = false,
  hideChart = false,
  hideTable = false,
  hideLineage = false,
  compact = false,
  maxTableRows,
  onShareClick,
  onLineageClick,
  onMetricClick,
  onClarifySubmit,
  onSaveMetric,
  currentUserId,
  onAdoptGap
}) => {
  const { chart_suggestion, columns, rows, lineage, lineage_info, summary } = result;
  const columnKeys = columns.map(columnKey);
  const compactHasChart = compact && ['BAR', 'LINE', 'AREA'].includes(
    String(chart_suggestion?.chart_type || '').toUpperCase()
  );

  const [showAssumptions, setShowAssumptions] = React.useState(false);
  const [isSaving, setIsSaving] = React.useState(false);
  const [saveSuccess, setSaveSuccess] = React.useState(false);
  const [enterprisePacks, setEnterprisePacks] = React.useState<EnterprisePack[]>([]);
  const [selectedPackId, setSelectedPackId] = React.useState<string>('');

  React.useEffect(() => {
    if (onSaveMetric) {
      api.listEnterprisePacks().then(setEnterprisePacks).catch(console.error);
    }
  }, [onSaveMetric]);

  const answerPath = (() => {
    if (result.answer_path) return result.answer_path;
    const path = result.execution_path;
    const provenance = result.execution_provenance;
    if (provenance?.asset_ref?.asset?.source_type === 'enterprise_pack') {
      return 'enterprise';
    }
    if (provenance?.asset_ref?.asset?.source_type === 'official_pack') {
      return 'official';
    }
    if (provenance?.asset_ref?.asset?.source_type === 'personal_workspace') {
      return 'personal';
    }
    if (path === 'controlled_exploration' || path === 'exploration') return 'ai_exploration';
    return result.is_exploratory ? 'ai_exploration' : 'official';
  })();

  const renderCaliberBadge = () => {
    let label = '官方标准';
    let sublabel = '经过官方认证的标准化统计口径，数据准确可靠';
    let badgeStyle = 'bg-indigo-50 text-indigo-700 border-indigo-200 dark:bg-indigo-950/30 dark:text-indigo-400 dark:border-indigo-800/80';

    if (answerPath === 'enterprise') {
      label = '企业正式';
      sublabel = '企业指标库已收录口径，符合正式经营分析标准';
      badgeStyle = 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-955/30 dark:text-emerald-400 dark:border-emerald-800/80';
    } else if (answerPath === 'personal') {
      label = '个人私有';
      sublabel = '个人工作区内的指标口径，仅在您的工作区可见';
      badgeStyle = 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-955/30 dark:text-amber-400 dark:border-amber-800/80';
    } else if (answerPath === 'ai_exploration') {
      label = 'AI 探索';
      sublabel = '基于物理数据库字段进行探索性分析，非官方正式口径';
      badgeStyle = 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-955/30 dark:text-purple-400 dark:border-purple-800/80';
    }

    return (
      <div className="flex flex-col sm:flex-row sm:items-center gap-2 mb-3 border-b border-slate-100 dark:border-slate-800/50 pb-2 shrink-0">
        <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold border ${badgeStyle} shrink-0 w-fit shadow-sm`}>
          {answerPath === 'ai_exploration' && <Sparkles className="w-3 h-3 text-purple-500 animate-pulse" />}
          {answerPath === 'enterprise' && <CheckCircle2 className="w-3 h-3 text-emerald-500" />}
          {answerPath === 'personal' && <Database className="w-3 h-3 text-amber-500" />}
          {answerPath === 'official' && <Cpu className="w-3 h-3 text-indigo-500" />}
          {label}
        </span>
        <span className="text-[11px] text-slate-400 dark:text-slate-500 leading-none">
          {sublabel}
        </span>
      </div>
    );
  };

  const renderProvenanceMetadata = () => {
    const provenance = result.execution_provenance;
    const execPath = result.execution_path;
    const timings = result.execution_timings;

    if (!provenance && !execPath && (!timings || timings.length === 0)) return null;

    return (
      <div className="mb-3 px-3 py-2.5 rounded-xl border border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/30 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-slate-500 dark:text-slate-400 shrink-0">
        {execPath && (
          <span className="flex items-center gap-1">
            <Cpu className="w-3 h-3 text-indigo-555" />
            <span>执行路径:</span>
            <span className="font-bold text-slate-700 dark:text-slate-200">
              {execPath === 'formal_metric' || execPath === 'formal'
                ? 'Staged Deterministic (正式)'
                : execPath === 'controlled_exploration' || execPath === 'exploration'
                  ? 'Controlled Exploration (探索)'
                  : execPath}
            </span>
          </span>
        )}
        {provenance && (
          <>
            {provenance.asset_ref?.asset && (
              <span className="flex items-center gap-1">
                <Layers className="w-3 h-3 text-indigo-555" />
                <span>源资产:</span>
                <span className="font-mono bg-slate-100 dark:bg-slate-800 px-1 py-0.2 rounded text-slate-700 dark:text-slate-300">
                  {provenance.asset_ref.asset.local_code} (v{provenance.asset_ref.version || '1.0.0'})
                </span>
              </span>
            )}
            {provenance.deployment_id && (
              <span className="flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3 text-emerald-555" />
                <span>部署:</span>
                <span className="font-mono bg-slate-100 dark:bg-slate-800 px-1 py-0.2 rounded text-slate-700 dark:text-slate-300">
                  {provenance.deployment_id}
                </span>
              </span>
            )}
            {provenance.workspace_id && (
              <span className="flex items-center gap-1">
                <Database className="w-3 h-3 text-amber-555" />
                <span>工作区:</span>
                <span className="font-mono bg-slate-100 dark:bg-slate-800 px-1 py-0.2 rounded text-slate-700 dark:text-slate-300">
                  {provenance.workspace_id}
                </span>
              </span>
            )}
            <span className="flex items-center gap-1">
               <Database className="w-3 h-3 text-indigo-500" />
               <span>环境:</span>
               <span className="bg-slate-100 dark:bg-slate-800 px-1 py-0.2 rounded text-slate-700 dark:text-slate-300">
                 {provenance.environment || 'default'}
               </span>
             </span>
            {provenance.semantic_space_ids && provenance.semantic_space_ids.length > 0 && (
              <span className="flex items-center gap-1">
                <Filter className="w-3 h-3 text-purple-550" />
                <span>语义空间:</span>
                <span className="bg-slate-100 dark:bg-slate-800 px-1 py-0.2 rounded text-slate-700 dark:text-slate-300 font-mono">
                  {provenance.semantic_space_ids.join(', ')}
                </span>
              </span>
            )}
          </>
        )}
        {timings && timings.length > 0 && (
          <span className="ml-auto flex flex-wrap items-center gap-1.5 text-[10px] text-slate-400 dark:text-slate-500 border-l border-slate-200 dark:border-slate-850 pl-3">
            <Clock className="w-3 h-3" />
            <span>阶段耗时:</span>
            {timings.map(({ stage, duration_ms }) => (
              <span key={stage} className="font-mono bg-slate-100 dark:bg-slate-800 px-1 py-0.2 rounded text-slate-600 dark:text-slate-400">
                {stage}: {duration_ms}ms
              </span>
            ))}
          </span>
        )}
      </div>
    );
  };

  const renderFailurePanel = () => {
    if (!result.execution_failure) return null;

    const { stage, code, message } = result.execution_failure;
    const normalizedStage = String(stage).toLowerCase().replace('_', '-');

    let title = '执行阶段失败';
    let description = message || '发生了未知错误';
    let tip = '请重试或联系管理员。';
    let containerStyle = 'bg-red-50/50 dark:bg-red-950/20 border-red-200 dark:border-red-900/80 text-red-900 dark:text-red-300';
    let icon = <AlertTriangle className="w-5 h-5 text-red-500 shrink-0" />;

    if (normalizedStage === 'plan-validation' || normalizedStage === 'plan_validation') {
      title = '查询计划规则校验未通过 (Plan Validation Failed)';
      description = message || 'AI 探索计划中包含不受支持或未授权 of database joins or operations, 已拒绝执行。';
      tip = '请尝试使用更简单的词汇或直接查询已知指标。';
      containerStyle = 'bg-amber-50/50 dark:bg-amber-955/20 border-amber-250 dark:border-amber-800/80 text-amber-900 dark:text-amber-300';
      icon = <Filter className="w-5 h-5 text-amber-500 shrink-0" />;
    } else if (normalizedStage === 'compilation' || normalizedStage === 'compile') {
      title = '逻辑指标编译校验阻断 (Logical Compilation Failed)';
      description = message || '指标逻辑或标准字段映射不完整或配置有误，无法转换为物理 SQL 语句。';
      tip = '请联系管理员检查当前部署的数据源字段映射关系，确保指标引用的所有标准字段均已正确挂载。';
      containerStyle = 'bg-amber-50/50 dark:bg-amber-955/20 border-amber-255 dark:border-amber-800/80 text-amber-900 dark:text-amber-300';
      icon = <Layers className="w-5 h-5 text-amber-500 shrink-0" />;
    } else if (normalizedStage === 'guardrail' || normalizedStage === 'guard') {
      title = '安全防火墙拦截阻断 (SQL Guardrail Blocked)';
      description = message || '安全策略分析引擎发现所生成物理 SQL 包含敏感操作或非授权范围，拦截执行。';
      tip = '为了数据安全，该查询已被阻断。系统已拒绝非只读操作、多句执行或表/列越权访问。';
      containerStyle = 'bg-rose-50/50 dark:bg-rose-955/20 border-rose-250 dark:border-rose-800/80 text-rose-900 dark:text-rose-300';
      icon = <Cpu className="w-5 h-5 text-rose-500 shrink-0 animate-pulse" />;
    } else if (code === 'execution_timeout') {
      title = '数据库查询运行超时 (Execution Timeout)';
      description = message || '物理查询语句在规定时间内（超时阈值）未能成功返回数据结果。';
      tip = '可能因为当前数据集过于庞大或关联路径较复杂。请尝试缩小提问的时间范围或添加更多筛选条件。';
      containerStyle = 'bg-blue-50/50 dark:bg-blue-955/20 border-blue-250 dark:border-blue-800/80 text-blue-900 dark:text-blue-300';
      icon = <Clock className="w-5 h-5 text-blue-500 shrink-0" />;
    } else if (normalizedStage === 'execution' || normalizedStage === 'execute') {
      title = '物理数据库执行阻断 (Database Execution Error)';
      description = message || 'SQL 语句在物理数据库执行时遇到底层结构错误或连接异常。';
      tip = '可能由于物理表临时不可用或数据源发生变更，请稍后重试或联系技术支持。';
      containerStyle = 'bg-red-50/50 dark:bg-red-955/20 border-red-250 dark:border-red-800/80 text-red-900 dark:text-red-300';
      icon = <Database className="w-5 h-5 text-red-500 shrink-0" />;
    }

    return (
      <div className={`p-4 rounded-xl border ${containerStyle} space-y-3.5 shadow-sm transition-all duration-300`}>
        <div className="flex items-start gap-3">
          {icon}
          <div className="space-y-1">
            <h4 className="text-xs font-bold uppercase tracking-wider">{title}</h4>
            <p className="text-[11px] font-mono leading-relaxed opacity-90">{description}</p>
          </div>
        </div>

        <div className="text-[11px] border-t border-current/10 pt-2.5 mt-2 space-y-1.5">
          <div className="font-semibold">💡 建议操作：</div>
          <div className="opacity-95 leading-normal">{tip}</div>
        </div>

        {code && (
          <div className="text-[9px] font-mono opacity-60">
            错误识别码 (Error Code): {code}
          </div>
        )}

      </div>
    );
  };

  const renderClarificationChoices = () => {
    if (!result.clarification || answerPath !== 'ai_exploration') return null;

    return (
      <div className="my-4 p-4 border border-indigo-105 dark:border-indigo-950/60 rounded-xl bg-indigo-50/20 dark:bg-indigo-950/10 space-y-3 shadow-sm">
        <h4 className="text-xs font-bold text-indigo-900 dark:text-indigo-300 flex items-center gap-1.5">
          <MessageSquare className="w-3.5 h-3.5 text-indigo-500" />
          系统需要您澄清查询口径 (Clarification Required)
        </h4>
        <p className="text-[11px] text-slate-505 dark:text-slate-400">
          {result.clarification.question}
        </p>
        <div className="flex flex-col gap-2">
          {result.clarification.options.map((opt, idx) => (
            <button
              key={idx}
              onClick={() => onClarifySubmit?.(opt.interpretation)}
              className="w-full text-left p-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-indigo-500 dark:hover:border-indigo-400 hover:bg-indigo-50/10 dark:hover:bg-indigo-955/10 transition-all group"
            >
              <div className="text-xs font-bold text-slate-850 dark:text-slate-200 group-hover:text-indigo-650 dark:group-hover:text-indigo-400">
                {opt.label}
              </div>
              {opt.description && (
                <p className="text-[10px] text-slate-400 dark:text-slate-500 mt-1">
                  {opt.description}
                </p>
              )}
            </button>
          ))}
        </div>
      </div>
    );
  };

  const renderAssumptionPanel = () => {
    if (answerPath !== 'ai_exploration' || !result.assumptions || result.assumptions.length === 0) return null;

    const assumption = result.assumptions[0];
    const confidence = result.confidence_tier || 'medium';

    let confidenceLabel = '中置信度';
    let confidenceStyle = 'text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-955/20';
    if (confidence === 'high') {
      confidenceLabel = '高置信度';
      confidenceStyle = 'text-emerald-650 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-955/20';
    } else if (confidence === 'low') {
      confidenceLabel = '低置信度';
      confidenceStyle = 'text-red-650 dark:text-red-400 bg-red-50 dark:bg-red-955/20';
    }

    return (
      <div className="mt-4 border border-purple-100 dark:border-purple-950/60 rounded-xl overflow-hidden bg-gradient-to-br from-purple-50/30 to-indigo-50/10 dark:from-purple-955/10 dark:to-slate-900/30 shadow-sm transition-all duration-300">
        <button
          onClick={() => setShowAssumptions(!showAssumptions)}
          className="w-full flex items-center justify-between px-4 py-3 text-xs font-semibold text-purple-900 dark:text-purple-300 hover:bg-purple-50/50 dark:hover:bg-purple-955/20 transition-colors"
        >
          <div className="flex items-center gap-2">
            <Sparkles className="w-3.5 h-3.5 text-purple-500 dark:text-purple-400 animate-pulse" />
            <span>AI 探索计算假设 & 规则推导</span>
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${confidenceStyle}`}>
              {confidenceLabel}
            </span>
          </div>
          {showAssumptions ? (
            <ChevronUp className="w-4 h-4 text-purple-600 dark:text-purple-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-purple-600 dark:text-purple-400" />
          )}
        </button>

        {showAssumptions && (
          <div className="px-4 pb-4 pt-2 border-t border-purple-100/50 dark:border-purple-955/30 space-y-3.5 text-xs text-slate-600 dark:text-slate-350">
            {/* Fields used */}
            {assumption.fields_used && assumption.fields_used.length > 0 && (
              <div>
                <h4 className="font-bold text-slate-700 dark:text-slate-200 mb-1.5 flex items-center gap-1.5">
                  <Database className="w-3.5 h-3.5 text-purple-500" />
                  推导字段 (Fields Used)
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {assumption.fields_used.map((field, idx) => (
                    <div key={idx} className="p-2 rounded bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-805 shadow-sm">
                      <div className="flex items-center justify-between gap-1.5">
                        <span className="font-bold text-slate-800 dark:text-slate-200">{field.business_name}</span>
                        <span className="px-1 py-0.5 rounded text-[8px] bg-slate-100 dark:bg-slate-800 text-slate-500 font-mono">
                          {field.origin}
                        </span>
                      </div>
                      <div className="text-[10px] text-slate-400 dark:text-slate-500 font-mono mt-0.5">
                        {field.physical_table}.{field.physical_column}
                      </div>
                      {field.inferred_meaning && (
                        <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-1 italic border-l-2 border-purple-200 dark:border-purple-900 pl-1.5">
                          含义: {field.inferred_meaning}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Aggregation & Time Field & Filters */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* Aggregation & Time */}
              <div className="space-y-2">
                {assumption.aggregation && (
                  <div>
                    <span className="font-bold text-slate-700 dark:text-slate-200 block mb-1">聚合方式</span>
                    <code className="px-1.5 py-0.5 rounded bg-purple-50/80 dark:bg-purple-955/20 text-purple-600 dark:text-purple-400 font-mono text-[10px] border border-purple-100/30">
                      {assumption.aggregation}
                    </code>
                  </div>
                )}
                {(assumption.time_field || assumption.time_grain) && (
                  <div>
                    <span className="font-bold text-slate-700 dark:text-slate-200 block mb-1">时间维度</span>
                    <span className="text-[10px] font-mono text-slate-500 dark:text-slate-400">
                      字段: <code className="px-1 py-0.2 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-350">{assumption.time_field || '未配置'}</code>
                      {assumption.time_grain && ` (粒度: ${assumption.time_grain})`}
                    </span>
                  </div>
                )}
              </div>

              {/* Filters */}
              {assumption.filters && assumption.filters.length > 0 && (
                <div>
                  <span className="font-bold text-slate-700 dark:text-slate-200 block mb-1 flex items-center gap-1">
                    <Filter className="w-3.5 h-3.5 text-purple-500" />
                    过滤条件 (Filters)
                  </span>
                  <ul className="list-disc list-inside space-y-0.5 text-[10px] font-mono text-slate-500 dark:text-slate-400 bg-white dark:bg-slate-900 p-2 rounded border border-slate-100 dark:border-slate-800">
                    {assumption.filters.map((f, idx) => (
                      <li key={idx} className="truncate">{f}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {/* Joins */}
            {assumption.joins && assumption.joins.length > 0 && (
              <div>
                <h4 className="font-bold text-slate-700 dark:text-slate-200 mb-1.5 flex items-center gap-1.5">
                  <Layers className="w-3.5 h-3.5 text-purple-500" />
                  多表关联路径 (Join Path)
                </h4>
                <div className="space-y-1.5">
                  {assumption.joins.map((join, idx) => (
                    <div key={idx} className="p-2 rounded bg-slate-50 dark:bg-slate-900 border border-slate-100/50 dark:border-slate-800/80 text-[11px]">
                      <div className="flex flex-wrap items-center gap-1.5 text-slate-700 dark:text-slate-300 font-mono">
                        <span className="font-bold">{join.left_table}</span>
                        <span className="text-purple-500">⟷</span>
                        <span className="font-bold">{join.right_table}</span>
                        <span className="text-[10px] text-slate-400 dark:text-slate-500">
                          (关联键: <code className="px-1 py-0.2 bg-slate-200/50 dark:bg-slate-800 rounded">{join.join_key}</code>)
                        </span>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
                        {join.note && <span className="text-slate-500 dark:text-slate-400 italic text-[10px]">{join.note}</span>}
                        <span className="px-1.5 py-0.2 rounded text-[8px] font-bold bg-indigo-50 text-indigo-650 dark:bg-indigo-950/20 dark:text-indigo-400">
                          关联凭证: {join.evidence === 'foreign_key' ? '外键约束 (FK)' : join.evidence === 'declared_relation' ? '已声明关系' : join.evidence === 'llm_guess' ? '大模型推理 (LLM Guess)' : join.evidence}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  const handleSaveMetricClick = async () => {
    if (!onSaveMetric || !result.assumptions || result.assumptions.length === 0) return;
    setIsSaving(true);
    try {
      const assumption = result.assumptions[0];
      const payload: SaveExplorationAsMetricRequest = {
        business_name: result.chart_suggestion?.title || '各厂区发货量',
        definition: result.summary || 'AI 探索推导指标',
        data_source_id: result.lineage.data_source_id || 'oracle_tms',
        entity: assumption.fields_used[0]?.physical_table || null,
        aggregation: assumption.aggregation || 'SUM',
        time_field: assumption.time_field || null,
        filters: assumption.filters || [],
        synonyms: [],
        field_mapping: assumption.fields_used,
        sql: null,
        lineage: result.lineage as unknown as Record<string, unknown>,
        visibility: 'enterprise',
        user_id: currentUserId || 'user_dev',
        ...(selectedPackId ? { target_pack_id: selectedPackId } : {})
      };
      await onSaveMetric(payload);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (e) {
      alert(`保存失败: ${e instanceof Error ? e.message : '未知错误'}`);
    } finally {
      setIsSaving(false);
    }
  };

  const renderSaveMetricAction = () => {
    if (answerPath !== 'ai_exploration' || result.clarification || !onSaveMetric || !result.assumptions || result.assumptions.length === 0) return null;

    return (
      <div className="mt-4 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 p-3 rounded-lg border border-purple-100 dark:border-purple-900 bg-purple-50/10 dark:bg-purple-950/5 shrink-0 text-left">
        <div className="text-[11px] text-slate-500 dark:text-slate-400">
          💡 该口径推导符合您的预期吗？您可以将其沉淀为企业指标。
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {enterprisePacks.length > 0 && !saveSuccess && (
            <select
              value={selectedPackId}
              onChange={e => setSelectedPackId(e.target.value)}
              className="text-[10px] bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded px-2 py-1 outline-none text-slate-700 dark:text-slate-350"
            >
              <option value="">-- 选择目标自建领域包 (可选) --</option>
              {enterprisePacks.map(p => (
                <option key={p.pack_id} value={p.pack_id}>{p.name} (v{p.version})</option>
              ))}
            </select>
          )}

          {saveSuccess ? (
            <span className="flex items-center gap-1 text-[11px] font-bold text-emerald-650 dark:text-emerald-400 shrink-0">
              <Check className="w-3.5 h-3.5" />
              已沉淀为指标
            </span>
          ) : (
            <button
              onClick={handleSaveMetricClick}
              disabled={isSaving}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-purple-600 to-indigo-650 hover:from-purple-700 hover:to-indigo-700 text-white rounded-lg text-[11px] font-semibold shadow-sm transition-all shrink-0"
            >
              {isSaving ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Save className="w-3.5 h-3.5" />
              )}
              沉淀为企业指标
            </button>
          )}
        </div>
      </div>
    );
  };

  const renderChart = () => {
    if (hideChart || !chart_suggestion || !rows || rows.length === 0) return null;

    const data = rows.map(row => {
      const obj: Record<string, unknown> = {};
      columnKeys.forEach((col, idx) => {
        obj[col] = row[idx];
      });
      return obj;
    });

    const xField = chart_suggestion.x_field || columnKeys[0] || '';
    const yField = chart_suggestion.y_field || columnKeys[1] || columnKeys[0] || '';
    const yFieldLabel = formatColumnName(yField, fields);
    const chartType = chart_suggestion.chart_type?.toUpperCase();

    // Premium indigo-violet palette
    const chartColor = darkMode ? '#818CF8' : '#4F46E5';
    const gridColor = darkMode ? '#334155' : '#E2E8F0';
    const textColor = darkMode ? '#94A3B8' : '#64748B';
    const tooltipBg = darkMode ? '#1E293B' : '#FFFFFF';
    const tooltipBorder = darkMode ? '#334155' : '#E2E8F0';
    const tooltipText = darkMode ? '#F1F5F9' : '#0F172A';

    const renderTooltip = () => (
      <RechartsTooltip 
        formatter={(value, name) => [value, formatColumnName(String(name), fields)]} 
        contentStyle={{ 
          backgroundColor: tooltipBg, 
          borderColor: tooltipBorder, 
          color: tooltipText,
          borderRadius: '8px',
          boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)'
        }} 
      />
    );

    const commonProps = {
      data,
      margin: { top: 16, right: 16, left: 0, bottom: 0 }
    };

    let chartNode = null;

    if (chartType === 'BAR') {
      chartNode = (
        <BarChart {...commonProps}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />
          <XAxis dataKey={xField} tick={{ fill: textColor, fontSize: 11 }} />
          <YAxis tick={{ fill: textColor, fontSize: 11 }} />
          {renderTooltip()}
          <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
          <Bar dataKey={yField} fill={chartColor} name={chart_suggestion.title || yFieldLabel} radius={[4, 4, 0, 0]} />
        </BarChart>
      );
    } else if (chartType === 'LINE') {
      chartNode = (
        <LineChart {...commonProps}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />
          <XAxis dataKey={xField} tick={{ fill: textColor, fontSize: 11 }} />
          <YAxis tick={{ fill: textColor, fontSize: 11 }} />
          {renderTooltip()}
          <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
          <Line type="monotone" dataKey={yField} stroke={chartColor} strokeWidth={2} activeDot={{ r: 6 }} name={chart_suggestion.title || yFieldLabel} />
        </LineChart>
      );
    } else if (chartType === 'AREA') {
      chartNode = (
        <AreaChart {...commonProps}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />
          <XAxis dataKey={xField} tick={{ fill: textColor, fontSize: 11 }} />
          <YAxis tick={{ fill: textColor, fontSize: 11 }} />
          {renderTooltip()}
          <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
          <Area type="monotone" dataKey={yField} stroke={chartColor} fill={chartColor} fillOpacity={0.15} name={chart_suggestion.title || yFieldLabel} />
        </AreaChart>
      );
    }

    if (!chartNode) {
      return null;
    }

    return (
      <div className="h-64 w-full mt-4 pb-8 mb-2">
        <ResponsiveContainer width="100%" height="100%">
          {chartNode}
        </ResponsiveContainer>
      </div>
    );
  };

  const renderTable = () => {
    if (hideTable || !columns || !rows || rows.length === 0) return null;

    const displayRows = maxTableRows ? rows.slice(0, maxTableRows) : rows;

    return (
      <div className="w-full min-h-0 flex-1 overflow-auto rounded-lg border border-slate-100 dark:border-slate-800/80">
        <table className="min-w-full text-xs text-left border-collapse">
          <thead className="bg-slate-50 dark:bg-slate-800/50 sticky top-0 backdrop-blur-sm z-10 border-b border-slate-100 dark:border-slate-800">
            <tr>
              {columns.map((col, idx) => (
                <th 
                  key={idx} 
                  className="px-4 py-2.5 font-semibold text-slate-700 dark:text-slate-300 whitespace-nowrap"
                >
                  {formatColumnName(columnKey(col), fields)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 bg-white dark:bg-slate-900">
            {displayRows.map((row, rowIdx) => (
              <tr 
                key={rowIdx} 
                className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30 transition-colors"
              >
                {row.map((val, valIdx) => (
                  <td 
                    key={valIdx} 
                    className="px-4 py-2.5 font-mono text-slate-600 dark:text-slate-400 whitespace-nowrap"
                  >
                    {val === null || val === undefined ? '-' : String(val)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const renderMetadata = () => {
    if (hideLineage || !lineage) return null;

    const hasLineageMetrics = (lineage_info?.metrics?.length || 0) > 0;
    const watermark = lineage_info?.data_watermark || (lineage.executed_at ? new Date(lineage.executed_at).toLocaleString() : '实时查询');

    return (
      <div className="mt-4 pt-3 border-t border-slate-100 dark:border-slate-800 flex flex-col gap-3">
        {hasLineageMetrics && (
          <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
            <span className="font-medium">依赖指标：</span>
            {lineage_info?.metrics.map(metric => (
              onMetricClick ? (
                <button
                  key={metric.metric_id}
                  onClick={() => onMetricClick(metric.metric_id || metric.metric_name)}
                  className="inline-flex items-center px-1.5 py-0.5 rounded bg-indigo-50 hover:bg-indigo-100 dark:bg-indigo-950/20 text-indigo-650 dark:text-indigo-400 font-mono font-bold hover:underline transition-colors"
                >
                  {metric.metric_name}
                </button>
              ) : (
                <span 
                  key={metric.metric_id}
                  className="inline-flex items-center px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-mono"
                >
                  {metric.metric_name}
                </span>
              )
            ))}
          </div>
        )}
        
        <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-400 dark:text-slate-500">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <Cpu className="w-3 h-3" />
              数据溯源 ID: <span className="font-mono text-slate-500 dark:text-slate-400">{lineage.lineage_id}</span>
            </span>
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              数据时效：{watermark}
            </span>
          </div>

          <div className="flex items-center gap-2">
            {onLineageClick && (
              <button 
                onClick={() => onLineageClick(lineage)}
                className="flex items-center gap-1 px-2 py-0.5 rounded border border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 transition-colors"
              >
                查看数据血缘
              </button>
            )}
            {onShareClick && (
              <button 
                onClick={() => onShareClick(result.query_id)}
                className="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-50 dark:bg-slate-800 hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors"
              >
                <Share2 className="w-2.5 h-2.5" />
                分享结果
              </button>
            )}
          </div>
        </div>
      </div>
    );
  };

  const renderGapSuggestions = () => {
    if (!result.gap_candidates || result.gap_candidates.length === 0) return null;

    return (
      <div className="mt-4 space-y-3 shrink-0 text-left">
        <div className="flex items-center justify-between text-xs font-bold text-slate-705 dark:text-slate-300">
          <span className="flex items-center gap-1.5 text-amber-600 dark:text-amber-500 font-bold uppercase tracking-wider">
            <Sparkles className="w-4 h-4 animate-pulse" />
            AI 检测到提问相关的未捕获物理字段 (Semantic Gap)
          </span>
        </div>

        <div className="space-y-2">
          {result.gap_candidates.map(candidate => (
            <div 
              key={candidate.field_id}
              className="bg-amber-500/5 dark:bg-amber-500/10 border border-amber-500/20 dark:border-amber-900 rounded-xl p-4 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 text-xs"
            >
              <div className="space-y-1 text-left flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-slate-850 dark:text-slate-200">{candidate.business_name}</span>
                  <span className="text-[10px] bg-amber-50 dark:bg-amber-955 border border-amber-200 dark:border-amber-800 text-amber-705 dark:text-amber-400 px-1.5 rounded font-bold font-mono">未纳入口径</span>
                </div>
                <p className="text-[10px] text-slate-500 dark:text-slate-400 leading-normal">
                  {candidate.suggested_reason}
                </p>
                <div className="text-[9px] text-slate-400 font-mono">
                  物理源: <code>{candidate.physical_table}.{candidate.physical_column}</code>
                </div>
              </div>

              <button
                type="button"
                onClick={() => {
                  const dsId = lineage?.data_source_id || 'oracle_tms';
                  const spaceId = 'space_scheduling';
                  onAdoptGap?.(dsId, spaceId, candidate.field_id);
                }}
                className="bg-amber-600 hover:bg-amber-700 text-white font-semibold text-xs px-4 py-2 rounded-lg transition-all shadow-sm shrink-0 whitespace-nowrap cursor-pointer"
              >
                纳入业务语义空间
              </button>
            </div>
          ))}
        </div>
      </div>
    );
  };

  if (result.execution_failure) {
    return (
      <div className="flex flex-col w-full h-full min-h-0 gap-1.5 text-left">
        {renderCaliberBadge()}
        {renderProvenanceMetadata()}
        {renderFailurePanel()}
      </div>
    );
  }

  return (
    <div className="flex flex-col w-full h-full min-h-0 gap-1.5">
      {!compact && renderCaliberBadge()}
      {!compact && renderProvenanceMetadata()}
      {summary && (
        <div className="text-sm text-slate-700 dark:text-slate-305 leading-relaxed mb-1">
          {summary}
        </div>
      )}
      {renderClarificationChoices()}
      {renderGapSuggestions()}
      {!compact && renderAssumptionPanel()}
      {renderChart()}
      {!compactHasChart && renderTable()}
      {renderSaveMetricAction()}
      {renderMetadata()}
    </div>
  );
};
