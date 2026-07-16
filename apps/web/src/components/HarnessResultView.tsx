import React, { useState } from 'react';
import { 
  CheckCircle2, 
  MessageSquare, 
  AlertTriangle, 
  Cpu, 
  Clock, 
  Coins, 
  ChevronDown, 
  ChevronUp, 
  ShieldAlert, 
  ArrowRight
} from 'lucide-react';
import { QueryResultView } from './QueryResultView';
import type { 
  HarnessResult, 
  SemanticField, 
  QueryResult
} from '../api';

interface HarnessResultViewProps {
  harnessResult: HarnessResult;
  fields?: SemanticField[];
  darkMode?: boolean;
  onClarifySubmit?: (runId: string, clarificationText: string) => void;
  onConfirmSubmit?: (runId: string, token: string) => void;
  onCancel?: () => void;
}

export const HarnessResultView: React.FC<HarnessResultViewProps> = ({
  harnessResult,
  fields = [],
  darkMode = false,
  onConfirmSubmit,
  onCancel
}) => {
  const { run_id, status, result, clarification, confirmation, trace, budget, failure, provenance } = harnessResult;

  const [expandedSteps, setExpandedSteps] = useState<Record<number, boolean>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const toggleStep = (index: number) => {
    setExpandedSteps(prev => ({ ...prev, [index]: !prev[index] }));
  };

  const handleConfirmSend = () => {
    if (!confirmation || !onConfirmSubmit) return;
    setIsSubmitting(true);
    onConfirmSubmit(run_id, confirmation.token);
  };

  const getToolDisplayName = (tool: string | null | undefined): string => {
    if (!tool) return '自主规划决策';
    const mappings: Record<string, string> = {
      resolve_scope: '解析数据源与环境范围 (Resolve Scope)',
      search_assets: '检索可用数据资产 (Search Assets)',
      inspect_asset: '检查资产计算公式 (Inspect Asset)',
      execute_metric: '执行确定性指标计算 (Execute Metric)',
      execute_skill: '调用分析技能 (Execute Skill)',
      execute_report: '生成正式报表 (Execute Report)',
      explore_fields: '受控探索表字段 (Explore Fields)',
      lookup_semantic_gap: '匹配语义空白 (Lookup Semantic Gap)',
      save_personal_asset: '持久化保存为个人指标 (Save Personal Asset)',
    };
    return mappings[tool] || tool;
  };

  const renderStatusBanner = () => {
    switch (status) {
      case 'completed':
        return (
          <div className="flex items-center gap-3 p-4 rounded-xl border border-emerald-250 bg-emerald-50/30 dark:bg-emerald-950/20 dark:border-emerald-800 text-emerald-850 dark:text-emerald-400">
            <CheckCircle2 className="w-5 h-5 text-emerald-555 flex-shrink-0 animate-bounce" />
            <div className="text-xs">
              <strong className="font-bold">智能规划执行成功 (Planning Completed)</strong>
              <p className="mt-1 text-[11px] opacity-90">Harness 规划器已通过受控工具链完成所有检索与计算，并输出确定性结果。</p>
            </div>
          </div>
        );
      case 'clarification_required':
        return (
          <div className="flex items-center gap-3 p-4 rounded-xl border border-indigo-250 bg-indigo-50/30 dark:bg-indigo-950/20 dark:border-indigo-800 text-indigo-850 dark:text-indigo-400">
            <MessageSquare className="w-5 h-5 text-indigo-555 flex-shrink-0 animate-pulse" />
            <div className="text-xs">
              <strong className="font-bold">需要补充查询口径 (Clarification Required)</strong>
              <p className="mt-1 text-[11px] opacity-90">系统检测到当前的意图或资产匹配存在歧义，需要您提供更多细节以供规划器重新分析。</p>
            </div>
          </div>
        );
      case 'confirmation_required':
        return (
          <div className="flex items-center gap-3 p-4 rounded-xl border border-amber-250 bg-amber-50/30 dark:bg-amber-955/20 dark:border-amber-800 text-amber-850 dark:text-amber-400">
            <AlertTriangle className="w-5 h-5 text-amber-555 flex-shrink-0 animate-pulse" />
            <div className="text-xs">
              <strong className="font-bold">等待安全写入确认 (Confirmation Required)</strong>
              <p className="mt-1 text-[11px] opacity-90">规划器提出了持久化写入个人资产的申请。根据安全界限规则，这需要您显式确认。</p>
            </div>
          </div>
        );
      case 'failed':
        return (
          <div className="flex items-center gap-3 p-4 rounded-xl border border-red-250 bg-red-50/30 dark:bg-red-955/20 dark:border-red-800 text-red-850 dark:text-red-400">
            <ShieldAlert className="w-5 h-5 text-red-555 flex-shrink-0" />
            <div className="text-xs">
              <strong className="font-bold">智能规划执行失败 (Planning Failed)</strong>
              <p className="mt-1 text-[11px] opacity-90">在规划或工具执行过程中触及安全、权限或预算边界，执行已安全终止。</p>
            </div>
          </div>
        );
      default:
        return null;
    }
  };

  const renderContinuationPanel = () => {
    if (status === 'clarification_required' && clarification) {
      return (
        <div className="mt-3 rounded-xl border border-indigo-100 bg-indigo-50/40 p-3 dark:border-indigo-900 dark:bg-indigo-950/20">
          <div className="flex items-center gap-2 text-xs font-bold text-slate-800 dark:text-slate-200">
            <MessageSquare className="w-4 h-4 text-indigo-500" />
            <span>需要你补充一点信息</span>
          </div>
          <div className="mt-2 whitespace-pre-wrap text-xs leading-5 text-slate-600 dark:text-slate-400">
            {clarification}
          </div>
          <p className="mt-2 text-[10px] text-slate-400">直接在下方对话框补充即可，我会沿用本轮上下文继续分析。</p>
        </div>
      );
    }

    if (status === 'confirmation_required' && confirmation) {
      return (
        <div className="mt-4 p-4 border border-amber-200 dark:border-amber-900/60 rounded-xl bg-white dark:bg-slate-900 shadow-sm space-y-4">
          <div className="flex items-center gap-2 text-xs font-bold text-amber-850 dark:text-amber-400">
            <AlertTriangle className="w-4 h-4 text-amber-500" />
            <span>安全确认请求 (Security Approval Requested)</span>
          </div>
          <p className="text-xs text-slate-700 dark:text-slate-350 leading-relaxed font-semibold">
            {confirmation.prompt}
          </p>
          <div className="text-[10px] text-slate-400 dark:text-slate-500 flex justify-between items-center bg-slate-50 dark:bg-slate-950 p-2.5 rounded-lg border border-slate-100 dark:border-slate-800/80 font-mono">
            <span>操作哈希: {confirmation.operation_digest}</span>
            <span>过期时间: {new Date(confirmation.expires_at).toLocaleTimeString()}</span>
          </div>
          <div className="flex gap-2 justify-end">
            <button
              onClick={onCancel}
              disabled={isSubmitting}
              className="px-4 py-2 border border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-750 dark:text-slate-300 rounded-lg text-xs font-bold transition-colors"
            >
              取消操作
            </button>
            <button
              onClick={handleConfirmSend}
              disabled={isSubmitting}
              className="bg-amber-600 hover:bg-amber-700 text-white px-5 py-2 rounded-lg text-xs font-bold flex items-center gap-1.5 transition-colors shadow-sm"
            >
              {isSubmitting ? '确认中...' : '确认保存资产'}
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      );
    }

    return null;
  };

  const renderBudgetPanel = () => {
    const elapsedSeconds = (budget.elapsed_ms / 1000).toFixed(2);
    return (
      <div className="my-4 grid grid-cols-3 gap-3 p-3.5 rounded-xl border border-slate-150 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm text-center shrink-0">
        <div>
          <span className="text-[10px] text-slate-400 dark:text-slate-500 block uppercase tracking-wider font-semibold">规划步数</span>
          <div className="mt-1 flex items-center justify-center gap-1">
            <Cpu className="w-3.5 h-3.5 text-indigo-500" />
            <span className="text-sm font-black text-slate-800 dark:text-white font-mono">{budget.steps}</span>
            <span className="text-[10px] text-slate-400">/ 8</span>
          </div>
          <div className="w-full bg-slate-100 dark:bg-slate-800 h-1 rounded-full mt-1.5 overflow-hidden">
            <div className="bg-indigo-500 h-full rounded-full" style={{ width: `${Math.min(100, (budget.steps / 8) * 100)}%` }} />
          </div>
        </div>

        <div className="border-x border-slate-100 dark:border-slate-800/80">
          <span className="text-[10px] text-slate-400 dark:text-slate-500 block uppercase tracking-wider font-semibold">耗时秒数</span>
          <div className="mt-1 flex items-center justify-center gap-1">
            <Clock className="w-3.5 h-3.5 text-indigo-500" />
            <span className="text-sm font-black text-slate-800 dark:text-white font-mono">{elapsedSeconds}s</span>
            <span className="text-[10px] text-slate-400">/ 45s</span>
          </div>
          <div className="w-full bg-slate-100 dark:bg-slate-800 h-1 rounded-full mt-1.5 overflow-hidden">
            <div className="bg-indigo-500 h-full rounded-full" style={{ width: `${Math.min(100, (budget.elapsed_ms / 45000) * 100)}%` }} />
          </div>
        </div>

        <div>
          <span className="text-[10px] text-slate-400 dark:text-slate-500 block uppercase tracking-wider font-semibold">消耗预算</span>
          <div className="mt-1 flex items-center justify-center gap-1">
            <Coins className="w-3.5 h-3.5 text-indigo-500" />
            <span className="text-sm font-black text-slate-800 dark:text-white font-mono">{budget.cost_units}</span>
            <span className="text-[10px] text-slate-400">/ 20</span>
          </div>
          <div className="w-full bg-slate-100 dark:bg-slate-800 h-1 rounded-full mt-1.5 overflow-hidden">
            <div className="bg-indigo-500 h-full rounded-full" style={{ width: `${Math.min(100, (budget.cost_units / 20) * 100)}%` }} />
          </div>
        </div>
      </div>
    );
  };

  const renderTimeline = () => {
    if (!trace || trace.length === 0) {
      return (
        <div className="text-center py-6 text-xs text-slate-400 dark:text-slate-500 italic">
          无可用工具调用追踪记录
        </div>
      );
    }

    return (
      <div className="space-y-3">
        <h4 className="text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">工具调用时序 timeline</h4>
        <div className="relative border-l border-indigo-100 dark:border-indigo-950 pl-4 space-y-4 ml-2">
          {trace.map((step, idx) => {
            const isExpanded = expandedSteps[step.index] || false;
            const hasError = step.observation && !step.observation.ok;
            return (
              <div key={idx} className="relative group">
                {/* Timeline node icon */}
                <div className={`absolute -left-[23px] top-0.5 w-4 h-4 rounded-full border-2 flex items-center justify-center text-[8px] font-bold ${
                  hasError
                    ? 'bg-red-500 border-red-500 text-white'
                    : step.command === 'finish'
                      ? 'bg-emerald-500 border-emerald-500 text-white'
                      : 'bg-white dark:bg-slate-900 border-indigo-500 text-indigo-600 dark:text-indigo-400'
                }`}>
                  {step.index}
                </div>

                <div className="space-y-1">
                  <div className="flex items-center justify-between">
                    <button
                      onClick={() => toggleStep(step.index)}
                      className="text-left text-xs font-bold text-slate-800 dark:text-slate-200 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors flex items-center gap-1"
                    >
                      <span className="font-mono text-slate-400">Step {step.index}:</span>
                      <span>{step.command === 'call_tool' ? getToolDisplayName(step.tool) : getToolDisplayName(step.command)}</span>
                      {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                    </button>
                    <div className="flex items-center gap-2 text-[10px] text-slate-400 font-mono">
                      <span>{step.duration_ms}ms</span>
                      <span>•</span>
                      <span>{step.cost_units} units</span>
                    </div>
                  </div>

                  {/* Summary of observation always visible */}
                  {step.observation?.summary && (
                    <p className={`text-[11px] pl-1 leading-relaxed ${
                      hasError ? 'text-red-650 dark:text-red-400 font-medium' : 'text-slate-500 dark:text-slate-400'
                    }`}>
                      {step.observation.summary}
                    </p>
                  )}

                  {/* Collapsible Arguments and Observation detail */}
                  {isExpanded && (
                    <div className="mt-2 pl-3 py-2.5 border-l-2 border-slate-100 dark:border-slate-800/80 bg-slate-50/50 dark:bg-slate-900/30 rounded-r-lg text-[10px] space-y-2.5 font-mono">
                      <div>
                        <span className="text-slate-400 dark:text-gray-500 block uppercase tracking-wider font-semibold">输入参数 Arguments</span>
                        <pre className="mt-1 text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-950 p-2 rounded border border-slate-200/50 dark:border-slate-800 overflow-x-auto max-h-36">
                          {JSON.stringify(step.arguments, null, 2)}
                        </pre>
                      </div>
                      {step.observation?.data && Object.keys(step.observation.data).length > 0 && (
                        <div>
                          <span className="text-slate-400 dark:text-gray-500 block uppercase tracking-wider font-semibold">观察输出 Observation Data</span>
                          <pre className="mt-1 text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-950 p-2 rounded border border-slate-200/50 dark:border-slate-800 overflow-x-auto max-h-36">
                            {JSON.stringify(step.observation.data, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  const renderFailureDetails = () => {
    if (!failure) return null;
    return (
      <div className="mt-4 p-4 rounded-xl border border-red-200 dark:border-red-900 bg-red-50/15 dark:bg-red-955/10 text-xs text-red-700 dark:text-red-400 space-y-2">
        <div className="flex items-center gap-2 font-bold">
          <ShieldAlert className="w-4 h-4 text-red-555" />
          <span>意图规划阻断详情 (Failure Details)</span>
        </div>
        <p className="leading-relaxed">
          <strong className="font-bold">错误描述：</strong>{failure.message}
        </p>
        <div className="grid grid-cols-2 gap-2 text-[10px] font-mono bg-white dark:bg-slate-950 p-2 rounded-lg border border-red-100 dark:border-red-950/60 mt-1">
          <span>错误码: {failure.code}</span>
          <span>阻断步骤: {failure.step !== null ? `Step ${failure.step}` : '全局规划'}</span>
        </div>
      </div>
    );
  };

  const renderQueryResultCompat = () => {
    if (status !== 'completed' || !result) return null;
    const rawViews = Array.isArray(result.views)
      ? result.views.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
      : [];
    if (rawViews.length > 0) {
      const sharedLineage = result.lineage as QueryResult['lineage'];
      return (
        <div className="mt-2 space-y-5">
          {rawViews.map((view, index) => {
            const viewColumns = Array.isArray(view.columns) ? view.columns as string[] : [];
            const viewRows = Array.isArray(view.rows) ? view.rows as unknown[][] : [];
            if (viewColumns.length === 0) return null;
            const viewResult: QueryResult = {
              query_id: `${run_id}_view_${index}`,
              audit_id: `aud_${run_id}_${index}`,
              columns: viewColumns,
              rows: viewRows,
              chart_suggestion: view.chart_suggestion as QueryResult['chart_suggestion'],
              lineage: sharedLineage,
              summary: '',
              execution_path: 'formal_metric',
            };
            return (
              <section key={`${run_id}_${index}`} className="space-y-2">
                <h4 className="text-xs font-bold text-slate-700 dark:text-slate-200">{String(view.title || `分析视图 ${index + 1}`)}</h4>
                <QueryResultView result={viewResult} fields={fields} darkMode={darkMode} hideLineage={true} compact={true} />
              </section>
            );
          })}
        </div>
      );
    }
    const columns = Array.isArray(result.columns) ? result.columns as string[] : [];
    const rows = Array.isArray(result.rows) ? result.rows as unknown[][] : [];
    if (columns.length === 0) return null;
    // A single scalar is already expressed naturally in the assistant answer.
    // Repeating it as a one-cell table only adds visual noise.
    if (columns.length === 1 && rows.length === 1) return null;
    if (rows.length === 1 && result.ranking && typeof result.ranking === 'object') return null;
    const chartSuggestion = (
      result.chart_suggestion && typeof result.chart_suggestion === 'object'
        ? result.chart_suggestion
        : { chart_type: 'TABLE', title: '分析结果' }
    ) as QueryResult['chart_suggestion'];
    const lineage = (
      result.lineage && typeof result.lineage === 'object'
        ? result.lineage
        : {
            lineage_id: `lin_${run_id}`,
            source_system: 'Unknown',
            data_source_id: typeof provenance?.data_source_id === 'string' ? provenance.data_source_id : 'unknown',
            metric_codes: [],
            metric_versions: {},
            physical_tables: [],
            physical_fields: [],
          }
    ) as QueryResult['lineage'];
    const provenanceDataSource = typeof provenance?.data_source_id === 'string' ? provenance.data_source_id : '';
    const provenanceEnvironment = typeof provenance?.environment === 'string' ? provenance.environment : 'default';
    const provenanceWorkspace = typeof provenance?.workspace_id === 'string' ? provenance.workspace_id : null;
    const provenanceSpaces = Array.isArray(provenance?.semantic_space_ids)
      ? provenance.semantic_space_ids.filter((item): item is string => typeof item === 'string')
      : [];

    // Convert result to compat QueryResult structure for QueryResultView
    const queryResultCompat: QueryResult = {
      query_id: run_id,
      audit_id: `aud_${run_id}`,
      columns,
      rows,
      chart_suggestion: chartSuggestion,
      lineage,
      summary: '',
      execution_path: 'formal_metric',
      execution_provenance: provenance ? {
        data_source_id: provenanceDataSource,
        environment: provenanceEnvironment,
        workspace_id: provenanceWorkspace,
        semantic_space_ids: provenanceSpaces,
      } : null,
      execution_timings: trace.map(t => ({
        stage: t.tool || t.command,
        duration_ms: t.duration_ms,
      })),
    };

    return (
      <div className="mt-2">
        <QueryResultView 
          result={queryResultCompat}
          fields={fields}
          darkMode={darkMode}
          hideLineage={true}
          compact={true}
        />
      </div>
    );
  };

  const renderTraceability = () => {
    const lineage = result?.lineage && typeof result.lineage === 'object'
      ? result.lineage as Record<string, unknown>
      : {};
    const metricCodes = Array.isArray(lineage.metric_codes)
      ? lineage.metric_codes.filter((item): item is string => typeof item === 'string')
      : [];
    const tables = Array.isArray(lineage.physical_tables)
      ? lineage.physical_tables.filter((item): item is string => typeof item === 'string')
      : [];
    const fieldsUsed = Array.isArray(lineage.physical_fields)
      ? [...new Set(lineage.physical_fields.filter((item): item is string => typeof item === 'string'))]
      : [];
    const inspected = trace.find(step => step.tool === 'inspect_asset')?.observation?.data;
    const asset = inspected?.asset && typeof inspected.asset === 'object'
      ? inspected.asset as Record<string, unknown>
      : {};
    const assetName = String(asset.name || asset.metric_code || asset.skill_id || asset.report_id || '');
    const dataSource = String(lineage.data_source_id || provenance?.data_source_id || '');
    const lineageId = String(lineage.lineage_id || '');
    if (!assetName && metricCodes.length === 0 && tables.length === 0 && fieldsUsed.length === 0 && !dataSource) return null;
    return (
      <div className="mt-2 text-[10px] leading-5 text-slate-400 dark:text-slate-500">
        <div className="flex flex-wrap gap-x-4 gap-y-0.5">
          {(assetName || metricCodes.length > 0) && <span>使用资产：{assetName || metricCodes.join('、')}</span>}
          {dataSource && <span>数据源：{dataSource}</span>}
          {tables.length > 0 && <span>来源表：{tables.join('、')}</span>}
          {fieldsUsed.length > 0 && <span>使用字段：{fieldsUsed.join('、')}</span>}
          {lineageId && <span className="font-mono">血缘 ID：{lineageId}</span>}
        </div>
      </div>
    );
  };

  return (
    <div>
      {renderQueryResultCompat()}
      {renderTraceability()}
      {renderContinuationPanel()}
      <details className="mt-2 text-xs">
        <summary className="cursor-pointer select-none text-[10px] font-medium text-slate-400 hover:text-slate-600 dark:hover:text-slate-300">执行详情</summary>
        <div className="mt-3 space-y-4">
          {renderStatusBanner()}
          {renderBudgetPanel()}
          {renderFailureDetails()}
          {renderTimeline()}
        </div>
      </details>
    </div>
  );
};
