import React, { useEffect, useState } from 'react';
import { 
  ArrowLeft,
  Lock,
  FileText,
  BookOpen,
  Cpu,
  Layers,
  HelpCircle,
  Save,
  Send,
  X,
  PlusCircle,
  RefreshCw,
  Sparkles,
  ChevronRight,
  Package
} from 'lucide-react';
import { api } from '../api';
import { confirmAction } from '../systemDialog';
import type { 
  EnterprisePack, 
  EnterprisePackDraft,
  PackEntity,
  PackEnterpriseField,
  PackEnterpriseMetric,
  PackSkill,
  PackReport,
  PackTerm,
  PackAcceptanceQuestion,
  DomainPackAuthoringResult,
  DomainPackAuthoringScope
} from '../api';

interface PackEditorProps {
  pack: EnterprisePack;
  userContext: any;
  onClose: () => void;
  onRefreshPack: (updatedPack: EnterprisePack) => void;
}

type TabType = 'info' | 'entities' | 'fields' | 'metrics' | 'skills' | 'reports' | 'terms' | 'questions';
type AssetTabType = Exclude<TabType, 'info'>;

const AUTHORING_STEPS: Array<{ id: TabType; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { id: 'info', label: '基本信息', icon: FileText },
  { id: 'fields', label: '标准字段', icon: Layers },
  { id: 'metrics', label: '指标', icon: BookOpen },
  { id: 'skills', label: '技能', icon: Cpu },
  { id: 'reports', label: '报表', icon: FileText },
  { id: 'questions', label: '自检', icon: HelpCircle }
];

const ASSET_TYPE_LABELS: Record<AssetTabType, string> = {
  entities: '业务实体',
  fields: '标准字段',
  metrics: '指标',
  skills: '技能',
  reports: '报表',
  terms: '业务术语',
  questions: '自检问题'
};

export const PackEditor: React.FC<PackEditorProps> = ({
  pack,
  userContext,
  onClose,
  onRefreshPack
}) => {
  const isUnpersisted = pack.pack_id === '__new__';
  const [activeTab, setActiveTab] = useState<TabType>(isUnpersisted ? 'info' : 'fields');
  const [packName, setPackName] = useState(pack.name);
  const [businessContext, setBusinessContext] = useState(pack.business_context ?? pack.description ?? '');
  const [savingPackInfo, setSavingPackInfo] = useState(false);
  const [aiInstruction, setAiInstruction] = useState('');
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResult, setAiResult] = useState<DomainPackAuthoringResult | null>(null);
  const [selectedCandidates, setSelectedCandidates] = useState<Set<string>>(new Set());
  const [aiError, setAiError] = useState('');
  const [selfCheckConfirmed, setSelfCheckConfirmed] = useState(false);
  
  // Publish dialog state
  const [showPublishModal, setShowPublishModal] = useState(false);
  const [publishVersion, setPublishVersion] = useState('');
  const [publishing, setPublishing] = useState(false);

  // Modal forms states
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingItemType, setEditingItemType] = useState<AssetTabType | null>(null);
  const [editingItemData, setEditingItemData] = useState<any | null>(null);
  const [isNewItem, setIsNewItem] = useState(false);

  const isPublished = pack.version_state === 'published';

  useEffect(() => {
    setPackName(pack.name);
    setBusinessContext(pack.business_context ?? pack.description ?? '');
  }, [pack]);

  const isExtension = Boolean(pack.base_pack_id && pack.base_pack_version);
  const isOfficialBaseItem = (item: object) => isExtension && (item as { source?: string }).source === 'official';

  // The portable-pack API owns draft-version creation. The editor never clones
  // a second enterprise package identity on behalf of the administrator.
  const confirmPublishedEdit = async (): Promise<boolean> => {
    if (!await confirmAction('当前包为已发布状态（只读）。对包内容的任何修改都将自动为您生成新的草稿版本（Fork新版本）。是否继续？')) {
      return false;
    }
    return true;
  };

  // Safe wrapper for draft operations
  const runWithDraft = async (action: (packId: string) => Promise<void>) => {
    const targetPackId = pack.pack_id;
    if (isPublished) {
      if (!await confirmPublishedEdit()) return;
    }
    await action(targetPackId);
  };

  // Publish handler
  const handlePublish = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!publishVersion.trim()) return;
    setPublishing(true);
    try {
      const updated = await api.publishEnterprisePack(pack.pack_id, {
        version: publishVersion,
        published_by: userContext.user_id
      });
      alert('🎉 分析领域包已成功发布发布，版本：v' + updated.version);
      setShowPublishModal(false);
      onRefreshPack(updated);
    } catch (err) {
      alert('发布失败：' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setPublishing(false);
    }
  };

  const persistPackInfo = async (): Promise<EnterprisePack> => {
    const name = packName.trim();
    if (!name) throw new Error('请先填写领域包名称。');
    if (isUnpersisted) {
      const created = await api.createEnterprisePack({
        name,
        description: businessContext.trim(),
        business_context: businessContext.trim(),
        mode: 'blank',
        base_pack_id: null,
        base_pack_version: null,
        created_by: userContext.user_id
      });
      onRefreshPack(created);
      return created;
    }
    const updated = await api.updateEnterprisePack(pack.pack_id, {
      name,
      description: businessContext.trim(),
      business_context: businessContext.trim(),
      updated_by: userContext.user_id
    });
    onRefreshPack(updated);
    setSelfCheckConfirmed(false);
    return updated;
  };

  const handleSavePackInfo = async (goNext = false) => {
    setSavingPackInfo(true);
    try {
      await persistPackInfo();
      if (goNext) {
        setAiResult(null);
        setSelectedCandidates(new Set());
        setAiError('');
        setActiveTab('fields');
      }
    } catch (err) {
      alert('保存领域包信息失败：' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setSavingPackInfo(false);
    }
  };

  const candidateEntries = (result: DomainPackAuthoringResult | null) => {
    if (!result) return [];
    return [
      ...result.draft.fields.map(item => ({ token: `fields:${item.field_id}`, type: 'fields' as const, id: item.field_id, name: item.business_name, detail: item.description || item.data_type })),
      ...result.draft.metrics.map(item => ({ token: `metrics:${item.metric_code}`, type: 'metrics' as const, id: item.metric_code, name: item.name, detail: item.definition })),
      ...result.draft.skills.map(item => ({ token: `skills:${item.skill_id}`, type: 'skills' as const, id: item.skill_id, name: item.name, detail: item.description || `${item.steps.length} 个分析步骤` })),
      ...result.draft.reports.map(item => ({ token: `reports:${item.report_id}`, type: 'reports' as const, id: item.report_id, name: item.name, detail: item.description || '报告候选' })),
      ...result.draft.acceptance_questions.map(item => ({ token: `questions:${item.question_id}`, type: 'questions' as const, id: item.question_id, name: item.question, detail: item.expected_answer_hint || '自检问题' }))
    ];
  };

  const authoringScope = (): DomainPackAuthoringScope => {
    if (activeTab === 'info') return 'all';
    if (activeTab === 'questions') return 'self_check';
    if (activeTab === 'fields' || activeTab === 'metrics' || activeTab === 'skills' || activeTab === 'reports') return activeTab;
    return 'all';
  };

  const handleAskAI = async (scope: DomainPackAuthoringScope = authoringScope()) => {
    if (!packName.trim()) {
      setAiError('请先填写领域包名称和业务背景。');
      return;
    }
    setAiLoading(true);
    setAiError('');
    try {
      const activeStepLabel = AUTHORING_STEPS.find(step => step.id === activeTab)?.label || '当前步骤';
      const instruction = scope === 'all' && activeTab !== 'info'
        ? `保留草稿中已经确认的步骤，不要改写前序内容；从“${activeStepLabel}”之后补全尚未完成的配置。${aiInstruction.trim()}`
        : aiInstruction.trim();
      const result = await api.suggestDomainPackAuthoring({
        scope,
        name: packName.trim(),
        description: businessContext.trim(),
        business_context: businessContext.trim(),
        instruction,
        draft: pack.draft
      });
      setAiResult(result);
      setSelectedCandidates(new Set(candidateEntries(result).map(item => item.token)));
    } catch (err) {
      const message = err instanceof Error
        ? err.message
        : err && typeof err === 'object' && 'message' in err
          ? String((err as { message?: unknown }).message || 'AI 建议生成失败。')
          : 'AI 建议生成失败。';
      setAiError(message);
    } finally {
      setAiLoading(false);
    }
  };

  const mergeCandidates = (current: EnterprisePackDraft, result: DomainPackAuthoringResult): EnterprisePackDraft => {
    const merge = <T,>(base: T[], candidates: T[], type: string, idOf: (item: T) => string): T[] => {
      const accepted = candidates.filter(item => selectedCandidates.has(`${type}:${idOf(item)}`));
      const acceptedIds = new Set(accepted.map(idOf));
      return [...base.filter(item => !acceptedIds.has(idOf(item))), ...accepted];
    };
    return {
      ...current,
      fields: merge(current.fields, result.draft.fields, 'fields', item => item.field_id),
      metrics: merge(current.metrics, result.draft.metrics, 'metrics', item => item.metric_code),
      skills: merge(current.skills, result.draft.skills, 'skills', item => item.skill_id),
      reports: merge(current.reports, result.draft.reports, 'reports', item => item.report_id),
      acceptance_questions: merge(current.acceptance_questions, result.draft.acceptance_questions, 'questions', item => item.question_id)
    };
  };

  const handleApplyCandidates = async () => {
    if (!aiResult || selectedCandidates.size === 0) return;
    setAiLoading(true);
    setAiError('');
    try {
      const target = await persistPackInfo();
      const mergedDraft = mergeCandidates(target.draft, aiResult);
      const updated = await api.updateEnterprisePack(target.pack_id, {
        draft: mergedDraft,
        updated_by: userContext.user_id
      });
      onRefreshPack(updated);
      setSelfCheckConfirmed(false);
      setSelectedCandidates(new Set());
      if (activeTab === 'info') {
        const check = await api.suggestDomainPackAuthoring({
          scope: 'self_check',
          name: updated.name,
          description: businessContext.trim(),
          business_context: businessContext.trim(),
          instruction: '检查刚刚生成的完整领域包草稿，指出依赖、口径和完整性问题。',
          draft: mergedDraft
        });
        setActiveTab('questions');
        setAiResult(check);
      } else {
        setAiResult(null);
      }
    } catch (err) {
      setAiError(err instanceof Error ? err.message : '采用 AI 候选失败。');
    } finally {
      setAiLoading(false);
    }
  };

  // Save changes back to draft
  const handleSaveItem = async (e: React.FormEvent) => {
    e.preventDefault();
    await runWithDraft(async (targetPackId) => {
      // 1. Fetch latest draft pack to ensure we modify correct base
      const latestPack = await api.getEnterprisePack(targetPackId);
      const draft = { ...latestPack.draft };
      
      const keyMap: Record<AssetTabType, keyof EnterprisePackDraft> = {
        entities: 'entities',
        fields: 'fields',
        metrics: 'metrics',
        skills: 'skills',
        reports: 'reports',
        terms: 'terms',
        questions: 'acceptance_questions'
      };
      
      const key = keyMap[editingItemType!];
      let itemsList = [...(draft[key] as any[])];

      if (isNewItem) {
        itemsList.push({ ...editingItemData, source: 'enterprise' });
      } else {
        const idFields: Record<AssetTabType, string> = {
          entities: 'entity_id',
          fields: 'field_id',
          metrics: 'metric_code',
          skills: 'skill_id',
          reports: 'report_id',
          terms: 'term_id',
          questions: 'question_id'
        };
        const idField = idFields[editingItemType!];
        itemsList = itemsList.map(item => 
          item[idField] === editingItemData[idField] ? { ...editingItemData, source: 'enterprise' } : item
        );
      }

      const updatedDraft = {
        ...draft,
        [key]: itemsList
      };

      const updated = await api.updateEnterprisePack(targetPackId, {
        draft: updatedDraft,
        updated_by: userContext.user_id
      });
      
      alert('保存成功！');
      setShowEditModal(false);
      onRefreshPack(updated);
      setSelfCheckConfirmed(false);
    });
  };

  // Delete handler
  const handleDeleteItem = async (itemType: AssetTabType, itemId: string) => {
    if (!await confirmAction('确认删除该分析项吗？')) return;
    
    await runWithDraft(async (targetPackId) => {
      const latestPack = await api.getEnterprisePack(targetPackId);
      const draft = { ...latestPack.draft };
      
      const keyMap: Record<AssetTabType, keyof EnterprisePackDraft> = {
        entities: 'entities',
        fields: 'fields',
        metrics: 'metrics',
        skills: 'skills',
        reports: 'reports',
        terms: 'terms',
        questions: 'acceptance_questions'
      };
      
      const key = keyMap[itemType];
      const idFields: Record<AssetTabType, string> = {
        entities: 'entity_id',
        fields: 'field_id',
        metrics: 'metric_code',
        skills: 'skill_id',
        reports: 'report_id',
        terms: 'term_id',
        questions: 'question_id'
      };
      const idField = idFields[itemType];
      
      const updatedDraft = {
        ...draft,
        [key]: (draft[key] as any[]).filter(item => item[idField] !== itemId)
      };

      const updated = await api.updateEnterprisePack(targetPackId, {
        draft: updatedDraft,
        updated_by: userContext.user_id
      });

      alert('删除成功！');
      onRefreshPack(updated);
      setSelfCheckConfirmed(false);
    });
  };

  // Init Form Helpers
  const openNewItemModal = (type: AssetTabType) => {
    setIsNewItem(true);
    setEditingItemType(type);
    
    const initialData: Record<AssetTabType, any> = {
      entities: { entity_id: `ent_${Math.random().toString(36).substring(2, 7)}`, name: '', description: '', tags: [] },
      fields: { field_id: `ef_${Math.random().toString(36).substring(2, 7)}`, business_name: '', data_type: 'VARCHAR', description: '', entity_id: '', synonyms: [] },
      metrics: { metric_code: `met_${Math.random().toString(36).substring(2, 7)}`, name: '', definition: '', formula: { expression: '', filters: [] }, entity_id: '', synonyms: [] },
      skills: { skill_id: `skill_${Math.random().toString(36).substring(2, 7)}`, name: '', description: '', steps: [] },
      reports: { report_id: `rep_${Math.random().toString(36).substring(2, 7)}`, name: '', description: '', metric_codes: [], skill_ids: [] },
      terms: { term_id: `term_${Math.random().toString(36).substring(2, 7)}`, term: '', definition: '', synonyms: [], related_field_ids: [] },
      questions: { question_id: `aq_${Math.random().toString(36).substring(2, 7)}`, question: '', expected_metric_code: '', expected_answer_hint: '' }
    };
    
    setEditingItemData(initialData[type]);
    setShowEditModal(true);
  };

  const openEditItemModal = (type: AssetTabType, item: any) => {
    setIsNewItem(false);
    setEditingItemType(type);
    setEditingItemData({ ...item });
    setShowEditModal(true);
  };

  const renderAiAuthoring = (showControls = true) => {
    const stepLabel = activeTab === 'info'
      ? '标准字段'
      : AUTHORING_STEPS.find(step => step.id === activeTab)?.label || '当前步骤';
    const entries = candidateEntries(aiResult);
    return (
      <section className="management-card space-y-3">
        {showControls && <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0 flex-1 space-y-1.5">
            <label className="flex items-center gap-1.5 text-xs font-bold text-slate-700 dark:text-slate-300"><Sparkles className="h-3.5 w-3.5 text-indigo-500" />补充生成要求（可选）</label>
            <input value={aiInstruction} onChange={event => setAiInstruction(event.target.value)} placeholder="不填写则直接依据前序已确认内容生成；也可补充关注重点或口径限制" className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] outline-none focus:border-indigo-500 dark:border-slate-800 dark:bg-slate-950" />
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <button type="button" onClick={() => { void handleAskAI(activeTab === 'info' ? 'fields' : authoringScope()); }} disabled={aiLoading || !packName.trim()} className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-white px-3 py-2 text-xs font-bold text-indigo-700 hover:bg-indigo-50 disabled:opacity-50 dark:border-indigo-900 dark:bg-slate-900 dark:text-indigo-300 dark:hover:bg-indigo-950/30">
              {aiLoading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
              {activeTab === 'questions' ? '运行 AI 自检' : `AI 生成${stepLabel}建议`}
            </button>
            {activeTab !== 'questions' && <button type="button" onClick={() => { void handleAskAI('all'); }} disabled={aiLoading || !packName.trim()} className="management-primary-action">
              <Sparkles className="h-3.5 w-3.5" /> AI 补全后续配置
            </button>}
          </div>
        </div>}

        {aiError && <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-[11px] text-rose-700 dark:border-rose-900 dark:bg-rose-950/20 dark:text-rose-300">{aiError}</div>}
        {aiResult && (
          <div className="space-y-3 border-t border-slate-100 pt-3 dark:border-slate-800">
            <div className={`rounded-lg border p-3 text-[11px] font-medium ${aiResult.input_assessment.reasonable ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/20 dark:text-emerald-300' : 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/20 dark:text-amber-300'}`}>
              {aiResult.input_assessment.feedback}
            </div>
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/60 p-3 text-[11px] leading-5 text-slate-700 dark:border-indigo-900/60 dark:bg-indigo-950/20 dark:text-slate-300">{aiResult.summary}</div>
            {aiResult.issues.length > 0 && <div className="space-y-1 rounded-lg border border-amber-200 bg-amber-50 p-3 text-[10px] text-amber-800 dark:border-amber-900 dark:bg-amber-950/20 dark:text-amber-300">{aiResult.issues.map(issue => <p key={issue}>• {issue}</p>)}</div>}
            {aiResult.suggestions.length > 0 && <div className="space-y-1 text-[10px] leading-4 text-slate-500 dark:text-slate-400">{aiResult.suggestions.map(item => <p key={item}>建议：{item}</p>)}</div>}
            {entries.length > 0 && (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-[10px] font-bold text-slate-500"><span>候选预览</span><span>{selectedCandidates.size}/{entries.length}</span></div>
                <div className="grid gap-2 md:grid-cols-2">
                  {entries.map(item => (
                    <label key={item.token} className={`block cursor-pointer rounded-lg border p-3 transition-colors ${selectedCandidates.has(item.token) ? 'border-indigo-300 bg-indigo-50/50 dark:border-indigo-800 dark:bg-indigo-950/20' : 'border-slate-200 dark:border-slate-800'}`}>
                      <div className="flex items-start gap-2">
                        {activeTab !== 'info' && <input type="checkbox" checked={selectedCandidates.has(item.token)} onChange={() => setSelectedCandidates(current => {
                          const next = new Set(current);
                          if (next.has(item.token)) next.delete(item.token); else next.add(item.token);
                          return next;
                        })} className="mt-0.5" />}
                        <div className="min-w-0"><p className="truncate text-[11px] font-bold text-slate-800 dark:text-slate-200">{item.name}</p><p className="mt-0.5 line-clamp-2 text-[10px] leading-4 text-slate-500">{item.detail}</p></div>
                      </div>
                    </label>
                  ))}
                </div>
                <div className="flex justify-end"><button type="button" onClick={() => { void handleApplyCandidates(); }} disabled={aiLoading || selectedCandidates.size === 0} className="management-primary-action">{activeTab === 'info' ? '确认采用全部并自检' : '采用选中内容'}</button></div>
              </div>
            )}
            {aiResult.scope === 'self_check' && (
              <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-slate-200 p-3 text-[11px] leading-5 text-slate-600 dark:border-slate-800 dark:text-slate-300">
                <input type="checkbox" checked={selfCheckConfirmed} onChange={event => setSelfCheckConfirmed(event.target.checked)} className="mt-1" />
                <span>我已审阅 AI 建议和确定性检查结果，确认当前配置可以发布。</span>
              </label>
            )}
          </div>
        )}
      </section>
    );
  };

  return (
    <div className="management-page flex-1 flex flex-col h-full overflow-hidden text-left">
      
      {/* Pack Header Area */}
      <div className="shrink-0 space-y-4">
        
        {/* Back and title bar */}
        <div className="management-header">
          <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h1 className="management-title"><Package className="h-5 w-5 text-indigo-500" />{isUnpersisted ? '新建领域包' : pack.name}</h1>
                {!isUnpersisted && <span className={`px-2 py-0.5 rounded-full text-[9px] font-bold border ${
                  pack.version_state === 'published'
                    ? 'bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-900'
                    : 'bg-amber-50 dark:bg-amber-950/20 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-900'
                }`}>
                  {pack.version_state === 'published' ? '已发布' : '草稿'} v{pack.version}
                </span>}
              </div>
              <p className="management-description">六步完成逻辑定义；发布后再从领域包卡片适配语义空间。</p>
          </div>

          <div className="flex items-center gap-2">
            {!isPublished && !isUnpersisted && activeTab === 'questions' && (
              <button 
                onClick={() => {
                  setPublishVersion(pack.version);
                  setShowPublishModal(true);
                }}
                disabled={!selfCheckConfirmed}
                title={selfCheckConfirmed ? '发布当前领域包版本' : '请先运行 AI 自检并人工确认'}
                className="management-primary-action"
              >
                <Send className="w-3.5 h-3.5" /> 发布此版本
              </button>
            )}
            <button 
              onClick={onClose}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> 返回领域包管理
            </button>
          </div>
        </div>

        {/* Warning banner for published packs */}
        {isPublished && (
          <div className="bg-amber-50/50 dark:bg-amber-955/10 border border-amber-205 dark:border-amber-900/50 rounded-xl px-4 py-2.5 flex items-start gap-2.5 text-xs text-amber-800 dark:text-amber-400 font-medium">
            <Lock className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
            <div>
              <span className="font-bold">当前包已发布（只读）：</span>
              系统保护此版本的稳定运行。如果您在此处做出任何修改或增添，后台将自动在当前包的基础上为您派生 (Fork) 出一个新的草稿迭代版本。
            </div>
          </div>
        )}

        {isExtension && (
          <div className="rounded-xl border border-indigo-200 bg-indigo-50/60 px-4 py-3 text-xs text-indigo-900 dark:border-indigo-900/60 dark:bg-indigo-950/20 dark:text-indigo-200">
            <div className="flex items-center gap-1.5 font-bold"><Lock className="w-3.5 h-3.5" />固定官方基础（只读）</div>
            <p className="mt-1">本扩展固定引用 <span className="font-mono">{pack.base_pack_id}</span> v{pack.base_pack_version}。官方资产以“官方”来源显示，不能编辑或删除；本页面只保存企业新增内容。</p>
          </div>
        )}

        {/* Categories Tab selector */}
        <div className="grid grid-cols-6 gap-1 bg-slate-50 dark:bg-slate-950 p-1 rounded-xl w-full">
          {AUTHORING_STEPS.map((tab, index) => (
            <button
              key={tab.id}
              type="button"
              disabled={isUnpersisted && tab.id !== 'info'}
              onClick={() => { setActiveTab(tab.id); setAiResult(null); setSelectedCandidates(new Set()); setAiError(''); }}
              className={`px-3 py-2 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-all disabled:cursor-not-allowed disabled:opacity-40 ${
                activeTab === tab.id
                  ? 'bg-white dark:bg-slate-900 text-slate-850 dark:text-white shadow-sm border border-slate-200/50 dark:border-slate-800'
                  : 'text-slate-400 hover:text-slate-700 dark:hover:text-slate-350'
              }`}
            >
              <span className="flex h-4 w-4 items-center justify-center rounded-full bg-slate-200 text-[9px] dark:bg-slate-800">{index + 1}</span>
              <tab.icon className="w-3.5 h-3.5" />
              {tab.label}
            </button>
          ))}
        </div>

      </div>

      {/* Editor Main Content list */}
      <div className="flex-1 min-h-0 overflow-y-auto p-5">
        <div className="min-w-0 space-y-4">

        {activeTab === 'info' && (
          <div className="management-card space-y-5">
            <div>
              <h2 className="text-sm font-bold text-slate-900 dark:text-white">第一步：定义领域包用途</h2>
              <p className="mt-1 text-[11px] text-slate-500">这些信息会成为后续 AI 生成字段、指标、技能和报表的统一上下文。</p>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-slate-700 dark:text-slate-300">领域包名称</label>
              <input value={packName} onChange={event => setPackName(event.target.value)} placeholder="例如：运输履约经营分析" className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-xs outline-none focus:border-indigo-500 dark:border-slate-800 dark:bg-slate-950" />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-slate-700 dark:text-slate-300">领域包描述与业务背景</label>
              <textarea value={businessContext} onChange={event => setBusinessContext(event.target.value)} rows={7} placeholder="说明领域包要解决的问题、业务流程、管理目标、关键角色、常用分析问题和口径约束。信息越具体，AI 建议越准确。" className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-xs leading-5 outline-none focus:border-indigo-500 dark:border-slate-800 dark:bg-slate-950" />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
              <button type="button" onClick={() => { void handleAskAI('all'); }} disabled={aiLoading || !packName.trim()} className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-white px-4 py-2 text-xs font-bold text-indigo-700 hover:bg-indigo-50 disabled:opacity-50 dark:border-indigo-900 dark:bg-slate-900 dark:text-indigo-300 dark:hover:bg-indigo-950/30">
                {aiLoading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />} AI 创建完整草稿
              </button>
              <button type="button" onClick={() => { void handleSavePackInfo(true); }} disabled={savingPackInfo || !packName.trim()} className="management-primary-action">
                {savingPackInfo ? '保存中…' : '保存并进入标准字段'} <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}

        {activeTab === 'info' ? ((aiResult || aiError) && renderAiAuthoring(false)) : renderAiAuthoring()}

        {activeTab !== 'info' && <div className="flex justify-between items-center">
          <div>
            <h2 className="text-xs font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">
              {activeTab === 'fields' && '标准字段'}
              {activeTab === 'metrics' && '基于标准字段定义指标口径'}
              {activeTab === 'skills' && '基于指标和技能组织分析逻辑'}
              {activeTab === 'reports' && '基于指标和技能组织正式报告'}
              {activeTab === 'questions' && '自检与验收问题'}
            </h2>
          </div>
          <button
            onClick={() => openNewItemModal(activeTab as AssetTabType)}
            className="flex items-center gap-1 text-[11px] font-bold text-indigo-650 dark:text-indigo-400 bg-indigo-50/50 dark:bg-indigo-950/20 hover:bg-indigo-50 dark:hover:bg-indigo-950/40 px-3 py-1.5 rounded-lg border border-indigo-150/40 dark:border-indigo-900/50 transition-all active:scale-[0.98]"
          >
            <PlusCircle className="w-3.5 h-3.5" /> 手动添加
          </button>
        </div>}

        {/* Entities Table */}
        {activeTab === 'entities' && (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden shadow-xs">
            <table className="w-full table-fixed text-left text-xs border-collapse">
              <thead className="bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">实体名称 (ID)</th>
                  <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">标准实体</th>
                  <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">所属包来源</th>
                  <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">业务描述</th>
                  <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {(pack.draft.entities || []).length === 0 ? (
                  <tr><td colSpan={5} className="py-8 text-center text-slate-400 italic">暂无实体映射。</td></tr>
                ) : (
                  pack.draft.entities.map((item: PackEntity) => (
                    <tr key={item.entity_id} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors">
                      <td className="px-4 py-3">
                        <span className="font-bold text-slate-850 dark:text-white">{item.name}</span>
                        <code className="block text-[10px] text-slate-400 mt-0.5">{item.entity_id}</code>
                      </td>
                      <td className="px-4 py-3 text-slate-500">旧版实体信息</td>
                      <td className="px-4 py-3">
                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                          isOfficialBaseItem(item)
                            ? 'bg-indigo-50 dark:bg-indigo-950/20 text-indigo-650 dark:text-indigo-400 border border-indigo-100 dark:border-indigo-900/50'
                            : 'bg-teal-50 dark:bg-teal-950/20 text-teal-600 dark:text-teal-400 border border-teal-200 dark:border-teal-900/50'
                        }`}>
                          {isOfficialBaseItem(item) ? '官方基础（只读）' : '企业新增'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-500 max-w-xs truncate">{item.description}</td>
                      <td className="px-4 py-3 text-right space-x-2">
                        {isOfficialBaseItem(item) ? (
                          <span className="text-[10px] text-slate-400 inline-flex items-center gap-0.5"><Lock className="w-3 h-3" /> 只读</span>
                        ) : (
                          <>
                            <button type="button" onClick={() => openEditItemModal('entities', item)} className="text-indigo-600 hover:text-indigo-800 dark:text-indigo-400 hover:underline">编辑</button>
                            <button type="button" onClick={() => handleDeleteItem('entities', item.entity_id)} className="text-red-500 hover:text-red-750 hover:underline">删除</button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Fields Table */}
        {activeTab === 'fields' && (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden shadow-xs">
            <table className="w-full table-fixed text-left text-xs border-collapse">
              <thead className="bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="w-[26%] whitespace-nowrap px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">列名 (ID)</th>
                  <th className="w-[40%] whitespace-nowrap px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">字段说明</th>
                  <th className="w-[14%] whitespace-nowrap px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">数据类型</th>
                  <th className="w-[20%] whitespace-nowrap px-4 py-3 text-right font-semibold text-slate-700 dark:text-slate-300">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {(pack.draft.fields || []).length === 0 ? (
                  <tr><td colSpan={4} className="py-8 text-center text-slate-400 italic">暂无标准字段。</td></tr>
                ) : (
                  pack.draft.fields.map((item: PackEnterpriseField) => (
                    <tr key={item.field_id} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors">
                      <td className="min-w-0 px-4 py-3" title={`${item.business_name} (${item.field_id})`}>
                        <span className="block truncate whitespace-nowrap font-bold text-slate-850 dark:text-white">{item.business_name}</span>
                        <code className="mt-0.5 block truncate whitespace-nowrap text-[10px] text-slate-400">{item.field_id}</code>
                      </td>
                      <td className="truncate whitespace-nowrap px-4 py-3 text-slate-500" title={item.description || '—'}>{item.description || '—'}</td>
                      <td className="truncate whitespace-nowrap px-4 py-3 font-mono text-[10px] text-slate-400" title={item.data_type}>{item.data_type}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-right space-x-2">
                        {isOfficialBaseItem(item) ? (
                          <span className="text-[10px] text-slate-400 inline-flex items-center gap-0.5"><Lock className="w-3 h-3" /> 只读</span>
                        ) : (
                          <>
                            <button type="button" onClick={() => openEditItemModal('fields', item)} className="text-indigo-600 hover:text-indigo-800 dark:text-indigo-400 hover:underline">编辑</button>
                            <button type="button" onClick={() => handleDeleteItem('fields', item.field_id)} className="text-red-500 hover:text-red-750 hover:underline">删除</button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Metrics Table */}
        {activeTab === 'metrics' && (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden shadow-xs">
            <table className="w-full table-fixed text-left text-xs border-collapse">
              <thead className="bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="w-[24%] whitespace-nowrap px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">指标口径 (Code)</th>
                  <th className="w-[28%] whitespace-nowrap px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">逻辑公式</th>
                  <th className="w-[30%] whitespace-nowrap px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">业务口径定义</th>
                  <th className="w-[18%] whitespace-nowrap px-4 py-3 text-right font-semibold text-slate-700 dark:text-slate-300">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {(pack.draft.metrics || []).length === 0 ? (
                  <tr><td colSpan={4} className="py-8 text-center text-slate-400 italic">暂无指标定义。</td></tr>
                ) : (
                  pack.draft.metrics.map((item: PackEnterpriseMetric) => (
                    <tr key={item.metric_code} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors">
                      <td className="min-w-0 px-4 py-3" title={`${item.name} (${item.metric_code})`}>
                        <span className="block truncate whitespace-nowrap font-bold text-slate-850 dark:text-white">{item.name}</span>
                        <code className="mt-0.5 block truncate whitespace-nowrap text-[10px] text-slate-400">{item.metric_code}</code>
                      </td>
                      <td className="truncate whitespace-nowrap px-4 py-3 font-mono text-[10px] text-slate-500" title={item.formula.expression}>{item.formula.expression}</td>
                      <td className="truncate whitespace-nowrap px-4 py-3 text-slate-500" title={item.definition}>{item.definition}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-right space-x-2">
                        {isOfficialBaseItem(item) ? (
                          <span className="text-[10px] text-slate-400 inline-flex items-center gap-0.5"><Lock className="w-3 h-3" /> 只读</span>
                        ) : (
                          <>
                            <button type="button" onClick={() => openEditItemModal('metrics', item)} className="text-indigo-600 hover:text-indigo-800 dark:text-indigo-400 hover:underline">编辑</button>
                            <button type="button" onClick={() => handleDeleteItem('metrics', item.metric_code)} className="text-red-500 hover:text-red-750 hover:underline">删除</button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Skills Table */}
        {activeTab === 'skills' && (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden shadow-xs">
            <table className="w-full table-fixed text-left text-xs border-collapse">
              <thead className="bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="w-[28%] whitespace-nowrap px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">技能名称 (ID)</th>
                  <th className="w-[18%] whitespace-nowrap px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">分析步骤数</th>
                  <th className="w-[36%] whitespace-nowrap px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">描述</th>
                  <th className="w-[18%] whitespace-nowrap px-4 py-3 text-right font-semibold text-slate-700 dark:text-slate-300">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {(pack.draft.skills || []).length === 0 ? (
                  <tr><td colSpan={4} className="py-8 text-center text-slate-400 italic">暂无技能定义。</td></tr>
                ) : (
                  pack.draft.skills.map((item: PackSkill) => (
                    <tr key={item.skill_id} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors">
                      <td className="min-w-0 px-4 py-3" title={`${item.name} (${item.skill_id})`}>
                        <span className="block truncate whitespace-nowrap font-bold text-slate-850 dark:text-white">{item.name}</span>
                        <code className="mt-0.5 block truncate whitespace-nowrap text-[10px] text-slate-400">{item.skill_id}</code>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 font-bold text-slate-600 dark:text-slate-400">{item.steps.length} 个步骤</td>
                      <td className="truncate whitespace-nowrap px-4 py-3 text-slate-500" title={item.description || ''}>{item.description || '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-right space-x-2">
                        {isOfficialBaseItem(item) ? <span className="text-[10px] text-slate-400 inline-flex items-center gap-0.5"><Lock className="w-3 h-3" />只读</span> : <><button type="button" onClick={() => openEditItemModal('skills', item)} className="text-indigo-600 hover:text-indigo-800 dark:text-indigo-400 hover:underline">编辑</button><button type="button" onClick={() => handleDeleteItem('skills', item.skill_id)} className="text-red-500 hover:text-red-750 hover:underline">删除</button></>}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Reports Table */}
        {activeTab === 'reports' && (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden shadow-xs">
            <table className="w-full table-fixed text-left text-xs border-collapse">
              <thead className="bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="w-[28%] whitespace-nowrap px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">报表模板 (ID)</th>
                  <th className="w-[22%] whitespace-nowrap px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">指标数 / 技能数</th>
                  <th className="w-[32%] whitespace-nowrap px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">描述</th>
                  <th className="w-[18%] whitespace-nowrap px-4 py-3 text-right font-semibold text-slate-700 dark:text-slate-300">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {(pack.draft.reports || []).length === 0 ? (
                  <tr><td colSpan={4} className="py-8 text-center text-slate-400 italic">暂无报表模板。</td></tr>
                ) : (
                  pack.draft.reports.map((item: PackReport) => (
                    <tr key={item.report_id} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors">
                      <td className="min-w-0 px-4 py-3" title={`${item.name} (${item.report_id})`}>
                        <span className="block truncate whitespace-nowrap font-bold text-slate-850 dark:text-white">{item.name}</span>
                        <code className="mt-0.5 block truncate whitespace-nowrap text-[10px] text-slate-400">{item.report_id}</code>
                      </td>
                      <td className="truncate whitespace-nowrap px-4 py-3 font-semibold text-slate-500" title={`${item.metric_codes.length} 指标 / ${item.skill_ids.length} 技能`}>{item.metric_codes.length} 指标 / {item.skill_ids.length} 技能</td>
                      <td className="truncate whitespace-nowrap px-4 py-3 text-slate-500" title={item.description || ''}>{item.description || '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-right space-x-2">
                        {isOfficialBaseItem(item) ? <span className="text-[10px] text-slate-400 inline-flex items-center gap-0.5"><Lock className="w-3 h-3" />只读</span> : <><button type="button" onClick={() => openEditItemModal('reports', item)} className="text-indigo-600 hover:text-indigo-800 dark:text-indigo-400 hover:underline">编辑</button><button type="button" onClick={() => handleDeleteItem('reports', item.report_id)} className="text-red-500 hover:text-red-750 hover:underline">删除</button></>}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Terms Table */}
        {activeTab === 'terms' && (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden shadow-xs">
            <table className="min-w-full text-xs text-left border-collapse">
              <thead className="bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">术语/口径逻辑词</th>
                  <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">同义词集</th>
                  <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">释义口径</th>
                  <th className="px-4 py-3 font-semibold text-slate-700 dark:text-slate-300 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {(pack.draft.terms || []).length === 0 ? (
                  <tr><td colSpan={4} className="py-8 text-center text-slate-400 italic">暂无同义词字典。</td></tr>
                ) : (
                  pack.draft.terms.map((item: PackTerm) => (
                    <tr key={item.term_id} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors">
                      <td className="px-4 py-3">
                        <span className="font-bold text-slate-850 dark:text-white">{item.term}</span>
                        <code className="block text-[10px] text-slate-400 mt-0.5">{item.term_id}</code>
                      </td>
                      <td className="px-4 py-3">
                        {item.synonyms.map(s => (
                          <span key={s} className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 text-[10px] font-mono mr-1">{s}</span>
                        ))}
                      </td>
                      <td className="px-4 py-3 text-slate-500 max-w-xs truncate">{item.definition}</td>
                      <td className="px-4 py-3 text-right space-x-2">
                        {isOfficialBaseItem(item) ? <span className="text-[10px] text-slate-400 inline-flex items-center gap-0.5"><Lock className="w-3 h-3" />只读</span> : <><button type="button" onClick={() => openEditItemModal('terms', item)} className="text-indigo-600 hover:text-indigo-800 dark:text-indigo-400 hover:underline">编辑</button><button type="button" onClick={() => handleDeleteItem('terms', item.term_id)} className="text-red-500 hover:text-red-750 hover:underline">删除</button></>}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Questions Table */}
        {activeTab === 'questions' && (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden shadow-xs">
            <table className="w-full table-fixed text-left text-xs border-collapse">
              <thead className="bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="w-[34%] whitespace-nowrap px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">自动化验收测试问题</th>
                  <th className="w-[22%] whitespace-nowrap px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">预期计算指标</th>
                  <th className="w-[26%] whitespace-nowrap px-4 py-3 font-semibold text-slate-700 dark:text-slate-300">预期答案提示</th>
                  <th className="w-[18%] whitespace-nowrap px-4 py-3 text-right font-semibold text-slate-700 dark:text-slate-300">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {(pack.draft.acceptance_questions || []).length === 0 ? (
                  <tr><td colSpan={4} className="py-8 text-center text-slate-400 italic">暂无验收问题集。</td></tr>
                ) : (
                  pack.draft.acceptance_questions.map((item: PackAcceptanceQuestion) => (
                    <tr key={item.question_id} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors">
                      <td className="truncate whitespace-nowrap px-4 py-3 font-bold text-slate-850 dark:text-white" title={item.question}>{item.question}</td>
                      <td className="truncate whitespace-nowrap px-4 py-3 font-mono text-indigo-650 dark:text-indigo-400" title={item.expected_metric_code || '不限'}>{item.expected_metric_code || <span className="italic text-slate-300">不限</span>}</td>
                      <td className="truncate whitespace-nowrap px-4 py-3 text-slate-500" title={item.expected_answer_hint || '无提示'}>{item.expected_answer_hint || <span className="italic text-slate-300">无提示</span>}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-right space-x-2">
                        {isOfficialBaseItem(item) ? <span className="text-[10px] text-slate-400 inline-flex items-center gap-0.5"><Lock className="w-3 h-3" />只读</span> : <><button type="button" onClick={() => openEditItemModal('questions', item)} className="text-indigo-600 hover:text-indigo-800 dark:text-indigo-400 hover:underline">编辑</button><button type="button" onClick={() => handleDeleteItem('questions', item.question_id)} className="text-red-500 hover:text-red-750 hover:underline">删除</button></>}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {activeTab !== 'info' && (
          <div className="flex items-center justify-between border-t border-slate-200 pt-4 dark:border-slate-800">
            <button type="button" onClick={() => {
              const index = AUTHORING_STEPS.findIndex(step => step.id === activeTab);
              setActiveTab(AUTHORING_STEPS[Math.max(0, index - 1)].id); setAiResult(null); setSelectedCandidates(new Set());
            }} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50 dark:border-slate-800 dark:text-slate-300 dark:hover:bg-slate-900">上一步</button>
            {activeTab !== 'questions' && <button type="button" onClick={() => {
              const index = AUTHORING_STEPS.findIndex(step => step.id === activeTab);
              setActiveTab(AUTHORING_STEPS[Math.min(AUTHORING_STEPS.length - 1, index + 1)].id); setAiResult(null); setSelectedCandidates(new Set());
            }} className="management-primary-action">下一步 <ChevronRight className="h-3.5 w-3.5" /></button>}
          </div>
        )}

        </div>
      </div>

      {/* ── Publish Version Modal ── */}
      {showPublishModal && (
        <div className="fixed inset-0 bg-slate-900/50 dark:bg-slate-950/70 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <form onSubmit={handlePublish} className="bg-white dark:bg-slate-900 border border-slate-205 dark:border-slate-800 rounded-2xl w-full max-w-md p-6 shadow-2xl space-y-4">
            <h3 className="font-bold text-slate-900 dark:text-white text-base">发布新版本领域包</h3>
            <p className="text-xs text-slate-500 dark:text-slate-400">请为此版本配置一个遵循 Semantic Versioning 的版本号：</p>
            <input 
              type="text" 
              required
              value={publishVersion}
              onChange={e => setPublishVersion(e.target.value)}
              placeholder="e.g. 1.0.0"
              className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-800 dark:text-slate-250 outline-none text-xs"
            />
            <div className="flex justify-end gap-2 border-t pt-4">
              <button 
                type="button" 
                onClick={() => setShowPublishModal(false)}
                className="px-3.5 py-1.5 border rounded-lg text-xs font-bold text-slate-550"
              >
                取消
              </button>
              <button 
                type="submit"
                disabled={publishing}
                className="bg-indigo-650 hover:bg-indigo-700 text-white text-xs font-bold px-4 py-1.5 rounded-lg flex items-center gap-1.5"
              >
                {publishing && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                确 认 发 布
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ── Edit Asset Asset Modal Forms ── */}
      {showEditModal && editingItemType && editingItemData && (
        <div className="fixed inset-0 bg-slate-900/50 dark:bg-slate-950/70 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <form onSubmit={handleSaveItem} className="pack-asset-form flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white text-xs shadow-2xl dark:border-slate-800 dark:bg-slate-900">
            <div className="flex shrink-0 items-start justify-between border-b border-slate-100 px-6 py-5 dark:border-slate-800">
              <div>
                <h3 className="text-base font-bold text-slate-900 dark:text-white">
                  {isNewItem ? '新建' : '编辑'}{ASSET_TYPE_LABELS[editingItemType]}
                </h3>
                <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">完善逻辑定义；保存后仍可继续编辑或通过 AI 生成建议。</p>
              </div>
              <button type="button" onClick={() => setShowEditModal(false)} aria-label="关闭" className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"><X className="w-4 h-4" /></button>
            </div>

            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-5">
              
              {/* Form fields for ENTITIES */}
              {editingItemType === 'entities' && (
                <>
                  <div className="space-y-1">
                    <label className="block font-bold">实体标示 (ID)</label>
                    <input
                      type="text"
                      required
                      disabled={!isNewItem}
                      value={editingItemData.entity_id}
                      onChange={e => setEditingItemData({ ...editingItemData, entity_id: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">实体业务名称</label>
                    <input 
                      type="text" 
                      required
                      value={editingItemData.name}
                      onChange={e => setEditingItemData({ ...editingItemData, name: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">业务口径描述</label>
                    <textarea 
                      value={editingItemData.description || ''}
                      onChange={e => setEditingItemData({ ...editingItemData, description: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                </>
              )}

              {/* Form fields for FIELDS */}
              {editingItemType === 'fields' && (
                <>
                  <div className="space-y-1">
                    <label className="block font-bold">字段标示 (ID)</label>
                    <input 
                      type="text" 
                      required
                      disabled={!isNewItem}
                      value={editingItemData.field_id}
                      onChange={e => setEditingItemData({ ...editingItemData, field_id: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">业务显示名称</label>
                    <input 
                      type="text" 
                      required
                      value={editingItemData.business_name}
                      onChange={e => setEditingItemData({ ...editingItemData, business_name: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-805 border rounded-lg"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">字段类型</label>
                    <input
                      type="text"
                      required
                      value={editingItemData.data_type}
                      onChange={e => setEditingItemData({ ...editingItemData, data_type: e.target.value })}
                      placeholder="例如：文本、日期、金额、数量"
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">字段说明</label>
                    <textarea value={editingItemData.description || ''} onChange={e => setEditingItemData({ ...editingItemData, description: e.target.value })} rows={3} className="w-full resize-none px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg" />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">同义词（逗号分隔）</label>
                    <input value={(editingItemData.synonyms || []).join(', ')} onChange={e => setEditingItemData({ ...editingItemData, synonyms: e.target.value.split(/[,，]/).map(value => value.trim()).filter(Boolean) })} className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg" />
                  </div>
                </>
              )}

              {/* Form fields for METRICS */}
              {editingItemType === 'metrics' && (
                <>
                  <div className="space-y-1">
                    <label className="block font-bold">指标编码 (Code)</label>
                    <input 
                      type="text" 
                      required
                      disabled={!isNewItem}
                      value={editingItemData.metric_code}
                      onChange={e => setEditingItemData({ ...editingItemData, metric_code: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">指标显示名称</label>
                    <input 
                      type="text" 
                      required
                      value={editingItemData.name}
                      onChange={e => setEditingItemData({ ...editingItemData, name: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">逻辑计算公式</label>
                    <input 
                      type="text" 
                      required
                      value={editingItemData.formula.expression}
                      onChange={e => setEditingItemData({ ...editingItemData, formula: { ...editingItemData.formula, expression: e.target.value } })}
                      placeholder="例如：SUM(order_amount)，仅引用标准字段 ID"
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg font-mono"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">口径业务释义</label>
                    <textarea 
                      value={editingItemData.definition}
                      onChange={e => setEditingItemData({ ...editingItemData, definition: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                </>
              )}

              {/* Form fields for SKILLS */}
              {editingItemType === 'skills' && (
                <>
                  <div className="space-y-1">
                    <label className="block font-bold">技能主键 (ID)</label>
                    <input 
                      type="text" 
                      required
                      disabled={!isNewItem}
                      value={editingItemData.skill_id}
                      onChange={e => setEditingItemData({ ...editingItemData, skill_id: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg font-mono"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">技能展示名称</label>
                    <input 
                      type="text" 
                      required
                      value={editingItemData.name}
                      onChange={e => setEditingItemData({ ...editingItemData, name: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">技能描述</label>
                    <textarea 
                      value={editingItemData.description || ''}
                      onChange={e => setEditingItemData({ ...editingItemData, description: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">逐步分析链路（每行一个步骤）</label>
                    <textarea
                      value={(editingItemData.steps || []).map((step: { description: string }) => step.description).join('\n')}
                      onChange={e => setEditingItemData({
                        ...editingItemData,
                        steps: e.target.value.split('\n').map((description, index) => description.trim() ? {
                          step_id: editingItemData.steps?.[index]?.step_id || `step_${index + 1}`,
                          description: description.trim(),
                          metric_codes: editingItemData.steps?.[index]?.metric_codes || [],
                          dimension_field_ids: editingItemData.steps?.[index]?.dimension_field_ids || []
                        } : null).filter(Boolean)
                      })}
                      rows={5}
                      placeholder={'读取核心指标\n按区域和时间拆解异常\n输出归因结论与建议'}
                      className="w-full resize-none px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div className="space-y-1"><label className="block font-bold">依赖指标（逗号分隔）</label><input value={Array.from(new Set((editingItemData.steps || []).flatMap((step: { metric_codes?: string[] }) => step.metric_codes || []))).join(', ')} onChange={e => {
                      const values = e.target.value.split(/[,，]/).map(value => value.trim()).filter(Boolean);
                      const steps = editingItemData.steps?.length ? editingItemData.steps : [{ step_id: 'step_1', description: '执行分析', metric_codes: [], dimension_field_ids: [] }];
                      setEditingItemData({ ...editingItemData, steps: steps.map((step: object, index: number) => ({ ...step, metric_codes: index === 0 ? values : [] })) });
                    }} className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg" /></div>
                    <div className="space-y-1"><label className="block font-bold">维度字段（逗号分隔）</label><input value={Array.from(new Set((editingItemData.steps || []).flatMap((step: { dimension_field_ids?: string[] }) => step.dimension_field_ids || []))).join(', ')} onChange={e => {
                      const values = e.target.value.split(/[,，]/).map(value => value.trim()).filter(Boolean);
                      const steps = editingItemData.steps?.length ? editingItemData.steps : [{ step_id: 'step_1', description: '执行分析', metric_codes: [], dimension_field_ids: [] }];
                      setEditingItemData({ ...editingItemData, steps: steps.map((step: object, index: number) => ({ ...step, dimension_field_ids: index === 0 ? values : [] })) });
                    }} className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg" /></div>
                  </div>
                </>
              )}

              {/* Form fields for REPORTS */}
              {editingItemType === 'reports' && (
                <>
                  <div className="space-y-1">
                    <label className="block font-bold">模板主键 (ID)</label>
                    <input 
                      type="text" 
                      required
                      disabled={!isNewItem}
                      value={editingItemData.report_id}
                      onChange={e => setEditingItemData({ ...editingItemData, report_id: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg font-mono"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">看板显示名称</label>
                    <input 
                      type="text" 
                      required
                      value={editingItemData.name}
                      onChange={e => setEditingItemData({ ...editingItemData, name: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-805 border rounded-lg"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">看板描述</label>
                    <textarea 
                      value={editingItemData.description || ''}
                      onChange={e => setEditingItemData({ ...editingItemData, description: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div className="space-y-1"><label className="block font-bold">依赖指标（逗号分隔）</label><input value={(editingItemData.metric_codes || []).join(', ')} onChange={e => setEditingItemData({ ...editingItemData, metric_codes: e.target.value.split(/[,，]/).map(value => value.trim()).filter(Boolean) })} className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg" /></div>
                    <div className="space-y-1"><label className="block font-bold">依赖技能（逗号分隔）</label><input value={(editingItemData.skill_ids || []).join(', ')} onChange={e => setEditingItemData({ ...editingItemData, skill_ids: e.target.value.split(/[,，]/).map(value => value.trim()).filter(Boolean) })} className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg" /></div>
                  </div>
                </>
              )}

              {/* Form fields for TERMS */}
              {editingItemType === 'terms' && (
                <>
                  <div className="space-y-1">
                    <label className="block font-bold">术语别名 (ID)</label>
                    <input 
                      type="text" 
                      required
                      disabled={!isNewItem}
                      value={editingItemData.term_id}
                      onChange={e => setEditingItemData({ ...editingItemData, term_id: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">标准口径词语</label>
                    <input 
                      type="text" 
                      required
                      value={editingItemData.term}
                      onChange={e => setEditingItemData({ ...editingItemData, term: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">指标词意解释</label>
                    <textarea 
                      value={editingItemData.definition}
                      onChange={e => setEditingItemData({ ...editingItemData, definition: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                </>
              )}

              {/* Form fields for QUESTIONS */}
              {editingItemType === 'questions' && (
                <>
                  <div className="space-y-1">
                    <label className="block font-bold">验收问题主键 (ID)</label>
                    <input 
                      type="text" 
                      required
                      disabled={!isNewItem}
                      value={editingItemData.question_id}
                      onChange={e => setEditingItemData({ ...editingItemData, question_id: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block font-bold">测试语意问题 (Question)</label>
                    <input 
                      type="text" 
                      required
                      value={editingItemData.question}
                      onChange={e => setEditingItemData({ ...editingItemData, question: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                    />
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div className="space-y-1">
                      <label className="block font-bold">预期计算指标 (Code)</label>
                      <input 
                        type="text" 
                        value={editingItemData.expected_metric_code || ''}
                        onChange={e => setEditingItemData({ ...editingItemData, expected_metric_code: e.target.value })}
                        placeholder="e.g. usr_freight_total"
                        className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg font-mono"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="block font-bold">预期答案断言提示</label>
                      <input 
                        type="text" 
                        value={editingItemData.expected_answer_hint || ''}
                        onChange={e => setEditingItemData({ ...editingItemData, expected_answer_hint: e.target.value })}
                        placeholder="e.g. 数字应大于 10000"
                        className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border rounded-lg"
                      />
                    </div>
                  </div>
                </>
              )}

            </div>

            <div className="flex shrink-0 justify-end gap-2 border-t border-slate-100 bg-slate-50/70 px-6 py-4 dark:border-slate-800 dark:bg-slate-950/40">
              <button 
                type="button" 
                onClick={() => setShowEditModal(false)}
                className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-600 transition-colors hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                取消
              </button>
              <button 
                type="submit"
                className="management-primary-action"
              >
                <Save className="w-3.5 h-3.5" /> 保存{ASSET_TYPE_LABELS[editingItemType]}
              </button>
            </div>
          </form>
        </div>
      )}

    </div>
  );
};
