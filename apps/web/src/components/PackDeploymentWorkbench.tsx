import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  CircleDashed,
  Loader2,
  Play,
  PowerOff,
} from 'lucide-react';
import { api } from '../api';
import type {
  DataSource,
  FieldMapping,
  MountStatus,
  PendingMapping,
  SmokeTestResult,
} from '../api';

interface PackDeploymentWorkbenchProps {
  userContext: { user_id: string; display_name?: string };
  dataSources: DataSource[];
  initialDeploymentId?: string | null;
  onBack: () => void;
}

type Notice = { type: 'success' | 'error' | 'info'; message: string };
type CandidateScope = 'bound_space' | 'scanned_catalog';
const SMOKE_TEST_TIMEOUT_MS = 45_000;

function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      reject(new Error('数据库连接超时，请检查网络和数据源配置后重试。'));
    }, timeoutMs);
    promise.then(
      value => {
        window.clearTimeout(timeout);
        resolve(value);
      },
      error => {
        window.clearTimeout(timeout);
        reject(error);
      },
    );
  });
}

export const PackDeploymentWorkbench: React.FC<PackDeploymentWorkbenchProps> = ({
  userContext,
  dataSources,
  initialDeploymentId,
  onBack,
}) => {
  const [status, setStatus] = useState<MountStatus | null>(null);
  const [pendingMappings, setPendingMappings] = useState<PendingMapping[]>([]);
  const [remapPending, setRemapPending] = useState<PendingMapping | null>(null);
  const [remapLoadingFieldId, setRemapLoadingFieldId] = useState<string | null>(null);
  const [selectedFieldId, setSelectedFieldId] = useState('');
  const [selectedCandidate, setSelectedCandidate] = useState(0);
  const [selectedCandidateScope, setSelectedCandidateScope] = useState<CandidateScope>('bound_space');
  const [smokeResult, setSmokeResult] = useState<SmokeTestResult | null>(null);
  const [smokeRunning, setSmokeRunning] = useState(false);
  const [smokeCheckedFields, setSmokeCheckedFields] = useState(0);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const loadDeployment = useCallback(async () => {
    if (!initialDeploymentId) return;
    setLoading(true);
    try {
      const [nextStatus, pending] = await Promise.all([
        api.getMountStatus(initialDeploymentId),
        api.getPendingMappings(initialDeploymentId),
      ]);
      setStatus(nextStatus);
      setPendingMappings(pending);
      setRemapPending(null);
      setSmokeResult(nextStatus.smoke_test || null);
      setSelectedFieldId(current =>
        pending.some(item => item.standard_field_id === current)
          ? current
          : '',
      );
    } catch (error) {
      setNotice({
        type: 'error',
        message: `加载领域包适配失败：${error instanceof Error ? error.message : '未知错误'}`,
      });
    } finally {
      setLoading(false);
    }
  }, [initialDeploymentId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadDeployment(), 0);
    return () => window.clearTimeout(timer);
  }, [loadDeployment]);

  const selectedPending = pendingMappings.find(item => item.standard_field_id === selectedFieldId) || null;
  const activePending = selectedPending
    || (remapPending?.standard_field_id === selectedFieldId ? remapPending : null);
  const mappingByField = useMemo(
    () => new Map((status?.mappings || []).map(mapping => [mapping.standard_field_id, mapping])),
    [status?.mappings],
  );
  const pendingByField = useMemo(
    () => new Map(pendingMappings.map(pending => [pending.standard_field_id, pending])),
    [pendingMappings],
  );
  const dataSourceName = dataSources.find(item => item.data_source_id === status?.data_source_id)?.name;
  const orderedFields = useMemo(() => {
    const fields = status?.standard_fields || [];
    const rank = (field: (typeof fields)[number]) => {
      const mapped = mappingByField.has(field.field_id);
      if (!mapped && field.required) return 0;
      if (!mapped) return 1;
      return 2;
    };
    return [...fields].sort((left, right) => rank(left) - rank(right));
  }, [mappingByField, status?.standard_fields]);
  const smokeFields = orderedFields.filter(field => mappingByField.has(field.field_id));

  const confirmMapping = async (candidateScope: CandidateScope) => {
    if (!status || !activePending || !initialDeploymentId) return;
    setWorking(true);
    try {
      await api.confirmMapping(initialDeploymentId, {
        pack_id: status.pack_id,
        data_source_id: status.data_source_id,
        standard_field_id: activePending.standard_field_id,
        mapping_request_id: activePending.mapping_request_id,
        confirmed_by: userContext.display_name || userContext.user_id,
        chosen_candidate_index: selectedCandidate,
        candidate_scope: candidateScope,
      });
      setSelectedCandidate(0);
      setNotice({
        type: 'success',
        message: candidateScope === 'scanned_catalog'
          ? '已将扫描候选纳入语义空间并完成字段映射。'
          : '字段映射已确认，覆盖率已重新计算。',
      });
      await loadDeployment();
    } catch (error) {
      setNotice({ type: 'error', message: `确认失败：${error instanceof Error ? error.message : '未知错误'}` });
    } finally {
      setWorking(false);
    }
  };

  const selectField = async (
    fieldId: string,
    mapping: FieldMapping | undefined,
    inScopeCount: number,
  ) => {
    if (selectedFieldId === fieldId) {
      setSelectedFieldId('');
      setRemapPending(null);
      return;
    }
    setSelectedFieldId(fieldId);
    setSelectedCandidate(0);
    setSelectedCandidateScope(inScopeCount > 0 ? 'bound_space' : 'scanned_catalog');
    if (!mapping || !initialDeploymentId) return;
    setRemapPending(null);
    setRemapLoadingFieldId(fieldId);
    try {
      const remap = await api.prepareMappingChange(initialDeploymentId, fieldId);
      setRemapPending(remap);
    } catch (error) {
      setNotice({ type: 'error', message: `加载修改候选失败：${error instanceof Error ? error.message : '未知错误'}` });
      setSelectedFieldId('');
    } finally {
      setRemapLoadingFieldId(null);
    }
  };

  const runSmoke = async () => {
    if (!initialDeploymentId || !status) return;
    setWorking(true);
    setSmokeRunning(true);
    setSmokeCheckedFields(0);
    setSmokeResult(null);
    setNotice(null);
    try {
      const smokeRequest = withTimeout(
        api.runSmokeTest(initialDeploymentId),
        SMOKE_TEST_TIMEOUT_MS,
      );
      const stepDelay = Math.max(60, Math.floor(1200 / Math.max(smokeFields.length, 1)));
      for (let index = 0; index < smokeFields.length; index += 1) {
        await new Promise(resolve => window.setTimeout(resolve, stepDelay));
        setSmokeCheckedFields(index + 1);
      }
      const result = await smokeRequest;
      setSmokeResult(result);
      if (result.all_passed) {
        await api.activateDeployment(initialDeploymentId);
        setNotice({ type: 'success', message: '全部校验通过，领域包已启用。' });
      } else {
        setNotice({ type: 'error', message: '校验存在失败项，请查看结果并处理。' });
      }
      await loadDeployment();
    } catch (error) {
      setNotice({ type: 'error', message: `校验失败：${error instanceof Error ? error.message : '未知错误'}` });
    } finally {
      setSmokeRunning(false);
      setWorking(false);
    }
  };

  const stopDeployment = async () => {
    if (!initialDeploymentId || !status) return;
    setWorking(true);
    try {
      await api.deactivateDeployment(initialDeploymentId);
      setSmokeCheckedFields(0);
      setSmokeResult(null);
      setNotice({ type: 'success', message: '领域包已停用。再次启用前需要重新完成冒烟测试。' });
      await loadDeployment();
    } catch (error) {
      setNotice({ type: 'error', message: `操作失败：${error instanceof Error ? error.message : '未知错误'}` });
    } finally {
      setWorking(false);
    }
  };

  if (loading) {
    return <div className="flex-1 grid place-items-center text-sm text-slate-500"><Loader2 className="w-5 h-5 animate-spin mr-2" />正在加载适配关系…</div>;
  }

  if (!status) {
    return (
      <div className="flex-1 grid place-items-center">
        <div className="text-center space-y-3">
          <AlertTriangle className="w-7 h-7 text-amber-500 mx-auto" />
          <p className="text-sm text-slate-600 dark:text-slate-300">无法加载该领域包的适配关系。</p>
          <button onClick={onBack} className="text-xs text-indigo-600 dark:text-indigo-400">返回领域包</button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col bg-slate-50 dark:bg-slate-950 text-left">
      <div className="shrink-0 px-6 py-4 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <button onClick={onBack} className="inline-flex items-center gap-1 text-xs text-indigo-600 dark:text-indigo-400 hover:underline">
              <ArrowLeft className="w-3.5 h-3.5" />返回领域包
            </button>
            <h2 className="mt-2 text-base font-bold text-slate-900 dark:text-white">
              {status.pack_id.toUpperCase()} 领域包适配
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              {dataSourceName || status.data_source_id} · v{status.pack_version || '1.0.0'} · {status.semantic_space_names?.join('、') || status.semantic_space_ids?.join('、') || '系统自动语义空间'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="px-2.5 py-1.5 rounded-lg bg-indigo-50 dark:bg-indigo-950/30 text-indigo-700 dark:text-indigo-300">
              实际映射 {status.mapped_fields}/{status.total_standard_fields}
            </span>
            <span className={`px-2.5 py-1.5 rounded-lg ${status.is_ready ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300' : 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300'}`}>
              {status.is_ready ? '已就绪' : `覆盖率 ${Math.round(status.coverage * 100)}%`}
            </span>
            {status.is_active ? (
              <button
                onClick={() => void stopDeployment()}
                disabled={working}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 disabled:opacity-40"
              >
                <PowerOff className="w-3.5 h-3.5" />停用
              </button>
            ) : (
              <button
                onClick={() => void runSmoke()}
                disabled={working || status.coverage < 1 || status.binding_status === 'unavailable'}
                title={status.coverage < 1 ? '请先完成必填字段映射' : '校验通过后自动启用'}
                className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 font-bold text-white disabled:cursor-not-allowed disabled:opacity-40"
              >
                {smokeRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                {smokeRunning ? '校验中…' : '冒烟测试'}
              </button>
            )}
          </div>
        </div>
        {notice && (
          <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${notice.type === 'error' ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/20 dark:text-rose-300' : notice.type === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/20 dark:text-emerald-300' : 'border-indigo-200 bg-indigo-50 text-indigo-700'}`}>
            {notice.message}
          </div>
        )}
        {status.binding_status === 'unavailable' && (
          <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-900 dark:bg-rose-950/20 dark:text-rose-300">
            历史绑定的语义空间已删除（{status.unavailable_semantic_space_ids?.join('、')}），该适配不可继续使用。请返回领域包重新执行自动适配或选择有效空间。
          </div>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-6">
        <div className="max-w-7xl mx-auto space-y-6">
          <section className="space-y-5">
            <div>
              <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
                <table className="w-full min-w-[820px] table-fixed text-left text-xs">
                  <thead className="bg-slate-50 text-[10px] uppercase tracking-wide text-slate-400 dark:bg-slate-950/60">
                    <tr>
                      <th className="w-[22%] px-4 py-3 font-semibold">标准字段</th>
                      <th className="w-[13%] px-4 py-3 font-semibold">要求</th>
                      <th className="w-[28%] px-4 py-3 font-semibold">当前物理字段</th>
                      <th className="w-[22%] px-4 py-3 font-semibold">候选情况</th>
                      <th className="w-[15%] px-4 py-3 font-semibold">部署校验</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {orderedFields.map(field => {
                      const mapping = mappingByField.get(field.field_id);
                      const pending = pendingByField.get(field.field_id);
                      const inScopeCount = pending?.candidates.length || 0;
                      const catalogCount = pending?.outside_scope_candidates?.length || 0;
                      const isSelected = selectedFieldId === field.field_id;
                      const configurationPending = pending
                        || (remapPending?.standard_field_id === field.field_id ? remapPending : null);
                      const isPreparingChange = remapLoadingFieldId === field.field_id;
                      const smokeFieldIndex = smokeFields.findIndex(item => item.field_id === field.field_id);
                      const validationPassed = Boolean(mapping)
                        && status.is_active
                        && Boolean(smokeResult?.all_passed);
                      const validationChecking = Boolean(mapping)
                        && smokeRunning
                        && smokeFieldIndex === smokeCheckedFields;
                      const validationAwaitingResult = Boolean(mapping)
                        && smokeRunning
                        && !validationChecking;
                      return (
                        <React.Fragment key={field.field_id}>
                        <tr
                          onClick={() => {
                            if (!mapping && !pending) return;
                            void selectField(field.field_id, mapping, inScopeCount);
                          }}
                          className={`transition-colors ${mapping || pending ? 'cursor-pointer' : ''} ${isSelected ? 'bg-indigo-50/80 dark:bg-indigo-950/20' : mapping || pending ? 'hover:bg-slate-50 dark:hover:bg-slate-800/40' : ''}`}
                        >
                          <td className="px-4 py-3">
                            <p className="truncate font-semibold text-slate-800 dark:text-slate-200" title={field.business_name}>{field.business_name}</p>
                            <p className="mt-0.5 truncate font-mono text-[10px] text-slate-400" title={field.field_id}>{field.field_id}</p>
                          </td>
                          <td className="px-4 py-3">
                            <span className={field.required ? 'text-rose-600 dark:text-rose-400' : 'text-slate-500'}>{field.required ? '最低必填' : '可选扩展'}</span>
                          </td>
                          <td className="px-4 py-3">
                            <span className="block truncate font-mono text-[11px] text-slate-700 dark:text-slate-300" title={mapping ? `${mapping.physical_table}.${mapping.physical_column}` : undefined}>
                              {mapping ? `${mapping.physical_table}.${mapping.physical_column}` : '—'}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-slate-500">
                            {mapping
                              ? '已确认，可点击修改'
                              : inScopeCount > 0
                                ? `${inScopeCount} 个空间内候选`
                                : catalogCount > 0
                                  ? `${catalogCount} 个扫描候选（需扩展）`
                                  : '未找到扫描候选'}
                          </td>
                          <td className="px-4 py-3">
                            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[10px] font-semibold ${validationPassed ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300' : validationChecking || validationAwaitingResult ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-300' : pending ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300' : 'bg-slate-100 text-slate-500 dark:bg-slate-800'}`}>
                              {validationPassed ? <CheckCircle2 className="h-3 w-3" /> : validationChecking ? <Loader2 className="h-3 w-3 animate-spin" /> : validationAwaitingResult ? <CircleDashed className="h-3 w-3" /> : pending ? <CircleDashed className="h-3 w-3" /> : <AlertTriangle className="h-3 w-3" />}
                              {validationPassed ? '校验通过' : validationChecking ? '校验中' : validationAwaitingResult ? '等待结果' : pending ? '待配置' : mapping ? '待校验' : '未匹配'}
                            </span>
                          </td>
                        </tr>
                        {isSelected && isPreparingChange && (
                          <tr className="bg-indigo-50/40 dark:bg-indigo-950/10">
                            <td colSpan={5} className="px-5 py-5 text-xs text-indigo-600 dark:text-indigo-300">
                              <Loader2 className="mr-2 inline h-3.5 w-3.5 animate-spin" />正在加载可选字段…
                            </td>
                          </tr>
                        )}
                        {isSelected && configurationPending && !isPreparingChange && (
                          <tr className="bg-indigo-50/40 dark:bg-indigo-950/10">
                            <td colSpan={5} className="px-5 py-5">
                              <FieldConfiguration
                                pending={configurationPending}
                                currentMapping={mapping}
                                selectedCandidate={selectedCandidate}
                                selectedCandidateScope={selectedCandidateScope}
                                working={working}
                                onSelect={(scope, index) => {
                                  setSelectedCandidateScope(scope);
                                  setSelectedCandidate(index);
                                }}
                                onConfirm={scope => void confirmMapping(scope)}
                              />
                            </td>
                          </tr>
                        )}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

          </section>

        </div>
      </div>
    </div>
  );
};

interface FieldConfigurationProps {
  pending: PendingMapping;
  currentMapping?: FieldMapping;
  selectedCandidate: number;
  selectedCandidateScope: CandidateScope;
  working: boolean;
  onSelect: (scope: CandidateScope, index: number) => void;
  onConfirm: (scope: CandidateScope) => void;
}

const FieldConfiguration: React.FC<FieldConfigurationProps> = ({
  pending,
  currentMapping,
  selectedCandidate,
  selectedCandidateScope,
  working,
  onSelect,
  onConfirm,
}) => (
  <div className="space-y-5">
    <div>
      <h3 className="text-sm font-bold text-slate-900 dark:text-white">
        {currentMapping ? <>修改“{pending.business_name}”的映射</> : <>配置“{pending.business_name}”</>}
      </h3>
      <p className="mt-1 text-xs text-slate-500">请选择与标准字段对应的数据字段。</p>
    </div>
    {currentMapping && (
      <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-xs dark:border-slate-800 dark:bg-slate-900">
        <p className="text-slate-500">当前映射</p>
        <p className="mt-1 font-mono font-semibold text-slate-800 dark:text-slate-200">{currentMapping.physical_table}.{currentMapping.physical_column}</p>
        <p className="mt-2 text-slate-500">确认修改后，需重新完成冒烟测试才能启用领域包。</p>
      </div>
    )}
    {pending.candidates.length > 0 && (
      <div className="space-y-3">
        <h4 className="text-xs font-bold text-slate-700 dark:text-slate-300">当前语义空间候选</h4>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {pending.candidates.map((candidate, index) => (
            <button
              key={`${candidate.physical_table}.${candidate.physical_column}`}
              onClick={() => onSelect('bound_space', index)}
              className={`rounded-xl border p-4 text-left ${selectedCandidateScope === 'bound_space' && selectedCandidate === index ? 'border-indigo-400 bg-indigo-50/60 dark:bg-indigo-950/20' : 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900'}`}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="font-mono text-xs font-bold text-slate-800 dark:text-slate-200">{candidate.physical_table}.{candidate.physical_column}</span>
                <span className="text-xs font-bold text-indigo-600">{Math.round(candidate.confidence * 100)}%</span>
              </div>
              <p className="mt-2 text-xs text-slate-500">{candidate.reason}</p>
            </button>
          ))}
        </div>
      </div>
    )}
    {(pending.outside_scope_candidates || []).length > 0 && (
      <div className="space-y-3 border-t border-slate-200 pt-4 dark:border-slate-800">
        <div>
          <h4 className="text-xs font-bold text-slate-700 dark:text-slate-300">扫描目录候选</h4>
          <p className="mt-1 text-[10px] text-amber-600">确认后会将对应数据表纳入当前语义空间。</p>
        </div>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {pending.outside_scope_candidates.map((candidate, index) => (
            <button
              key={`outside-${candidate.physical_table}.${candidate.physical_column}`}
              onClick={() => onSelect('scanned_catalog', index)}
              className={`rounded-xl border p-4 text-left ${selectedCandidateScope === 'scanned_catalog' && selectedCandidate === index ? 'border-amber-400 bg-amber-50/70 dark:bg-amber-950/20' : 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900'}`}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="font-mono text-xs font-bold text-slate-800 dark:text-slate-200">{candidate.physical_table}.{candidate.physical_column}</span>
                <span className="text-xs font-bold text-amber-600">{Math.round(candidate.confidence * 100)}%</span>
              </div>
              <p className="mt-2 text-xs text-slate-500">{candidate.reason}</p>
            </button>
          ))}
        </div>
      </div>
    )}
    {pending.candidates.length > 0 || pending.outside_scope_candidates?.length > 0 ? (
      <button onClick={() => onConfirm(selectedCandidateScope)} disabled={working} className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-bold text-white disabled:opacity-50">
        {working && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        {selectedCandidateScope === 'scanned_catalog'
          ? (currentMapping ? '纳入语义空间并确认修改' : '纳入语义空间并确认')
          : (currentMapping ? '确认修改映射' : '确认候选映射')}
      </button>
    ) : (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-700 dark:border-amber-900 dark:bg-amber-950/20 dark:text-amber-300">
        暂无可用候选，请重新扫描数据源或重新执行自动适配。
      </div>
    )}
  </div>
);
