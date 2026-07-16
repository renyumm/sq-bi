import React, { useCallback, useState, useEffect, useRef } from 'react';
import { 
  Table, 
  Layers, 
  Search, 
  Sparkles, 
  Info,
  RefreshCw,
  ArrowLeft,
  History,
  CheckCircle,
  X,
  FileText,
  HelpCircle,
  Pencil
} from 'lucide-react';
import { api } from '../api';
import type { 
  SemanticSpace, 
  SemanticSpaceDiff, 
  SemanticProfileField,
  SemanticFieldUpdate,
  FieldStatus, 
  EvidenceSource
} from '../api';

interface SemanticProfileViewerProps {
  dsId: string;
  spaceId: string;
  isAdmin: boolean;
  onBack: () => void;
  preSelectedFieldId?: string | null;
}

const EVIDENCE_SOURCE_LABELS: Record<EvidenceSource, { label: string; color: string }> = {
  comment: { label: '表/列注释', color: 'text-emerald-500 bg-emerald-50 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-900' },
  document: { label: '设计文档', color: 'text-indigo-500 bg-indigo-50 dark:bg-indigo-950/20 border-indigo-200 dark:border-indigo-900' },
  name: { label: '物理命名', color: 'text-blue-500 bg-blue-50 dark:bg-blue-950/20 border-blue-200 dark:border-blue-900' },
  sample: { label: '样本数据', color: 'text-amber-500 bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-900' },
  user_note: { label: '人工批注', color: 'text-pink-500 bg-pink-50 dark:bg-pink-950/20 border-pink-200 dark:border-pink-900' },
  official_pack: { label: '行业领域包', color: 'text-teal-500 bg-teal-50 dark:bg-teal-950/20 border-teal-200 dark:border-teal-900' },
  ai_inference: { label: '系统推断', color: 'text-violet-500 bg-violet-50 dark:bg-violet-950/20 border-violet-200 dark:border-violet-900' }
};

const FIELD_STATUS_META: Record<FieldStatus, { label: string; className: string }> = {
  confirmed: { label: '已纳入', className: 'bg-emerald-50 dark:bg-emerald-950/20 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-900/40' },
  pending: { label: '待确认', className: 'bg-amber-50 dark:bg-amber-950/20 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-900/40' },
  excluded: { label: '已排除', className: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700' },
  sensitive: { label: '敏感', className: 'bg-purple-50 dark:bg-purple-950/20 text-purple-700 dark:text-purple-400 border-purple-200 dark:border-purple-900/40' },
  invalid: { label: '不可用', className: 'bg-red-50 dark:bg-red-950/20 text-red-700 dark:text-red-400 border-red-200 dark:border-red-900/40' }
};

const SEMANTIC_ROLE_OPTIONS = [
  { value: '', label: '未设置' },
  { value: 'dimension', label: '维度' },
  { value: 'measure', label: '度量' },
  { value: 'time', label: '时间' },
  { value: 'status', label: '状态' },
  { value: 'identifier', label: '标识' },
  { value: 'primary_key', label: '主键' }
];

const AGGREGATION_OPTIONS = [
  { value: '', label: '不聚合' },
  { value: 'sum', label: '求和' },
  { value: 'count', label: '计数' },
  { value: 'avg', label: '平均' },
  { value: 'min', label: '最小值' },
  { value: 'max', label: '最大值' }
];

interface FieldDraft {
  business_name: string;
  description: string;
  semantic_role: string;
  default_aggregation: string;
  synonymsText: string;
}

const fieldDraftFrom = (field: SemanticProfileField | null | undefined): FieldDraft => ({
  business_name: field?.business_name || '',
  description: field?.description || '',
  semantic_role: field?.semantic_role || '',
  default_aggregation: field?.default_aggregation || '',
  synonymsText: (field?.synonyms || []).join(', ')
});

const parseSynonyms = (value: string): string[] => {
  const seen = new Set<string>();
  return value
    .split(/[,，;；\n]+/)
    .map(item => item.trim())
    .filter(Boolean)
    .filter(item => {
      const key = item.toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
};

const fieldUpdateFromDraft = (draft: FieldDraft): SemanticFieldUpdate => ({
  business_name: draft.business_name.trim(),
  description: draft.description.trim(),
  semantic_role: draft.semantic_role || '',
  default_aggregation: draft.default_aggregation || '',
  synonyms: parseSynonyms(draft.synonymsText)
});

const isFieldDraftChanged = (field: SemanticProfileField | null | undefined, draft: FieldDraft): boolean => {
  if (!field) return false;
  const current = fieldDraftFrom(field);
  return (
    current.business_name !== draft.business_name ||
    current.description !== draft.description ||
    current.semantic_role !== draft.semantic_role ||
    current.default_aggregation !== draft.default_aggregation ||
    current.synonymsText !== draft.synonymsText
  );
};

const metadataStatusFor = (field: SemanticProfileField): { label: string; className: string } => {
  if (field.is_candidate) {
    return { label: '新增候选', className: 'bg-blue-50 dark:bg-blue-950/20 text-blue-700 dark:text-blue-400 border-blue-200 dark:border-blue-900/40' };
  }
  if (!field.data_type) {
    return { label: '类型缺失', className: 'bg-amber-50 dark:bg-amber-950/20 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-900/40' };
  }
  return { label: '正常', className: 'bg-slate-50 dark:bg-slate-900 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-800' };
};

const fieldStatusFor = (
  field: SemanticProfileField,
  draftStatuses: Record<string, FieldStatus>
): FieldStatus => draftStatuses[field.field_id] || field.status || (field.is_candidate ? 'pending' : 'confirmed');

const getSpaceStatuses = (target: SemanticSpace): Record<string, FieldStatus> => {
  const statuses: Record<string, FieldStatus> = {};
  target.entities.forEach(entity => {
    entity.fields.forEach(field => {
      statuses[field.field_id] = field.status || (field.is_candidate ? 'pending' : 'confirmed');
    });
  });
  return statuses;
};

export const SemanticProfileViewer: React.FC<SemanticProfileViewerProps> = ({
  dsId,
  spaceId,
  isAdmin,
  onBack,
  preSelectedFieldId
}) => {
  const [space, setSpace] = useState<SemanticSpace | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Active sub-views
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [selectedFieldId, setSelectedFieldId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Business description and staged field status edits
  const [editedDesc, setEditedDesc] = useState('');
  const [draftStatuses, setDraftStatuses] = useState<Record<string, FieldStatus>>({});
  const [fieldDraft, setFieldDraft] = useState<FieldDraft>(fieldDraftFrom(null));
  const [savingDraft, setSavingDraft] = useState(false);
  const [savingFieldId, setSavingFieldId] = useState<string | null>(null);

  // Stepper state
  const [stepperActive, setStepperActive] = useState(false);
  const [stepperStep, setStepperStep] = useState<1 | 2 | 3 | 4>(1);
  const [refreshLoading, setRefreshLoading] = useState(false);
  const [spaceDiff, setSpaceDiff] = useState<SemanticSpaceDiff | null>(null);
  const [confirmedSuggestions, setConfirmedSuggestions] = useState<string[]>([]);
  const [publishing, setPublishing] = useState(false);

  // Versioning state
  const [versionHistory, setVersionHistory] = useState<number[]>([1]);
  const [viewingVersion, setViewingVersion] = useState<number | null>(null);
  const saveSeqRef = useRef(0);

  const fetchSpace = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getSemanticSpace(dsId, spaceId);
      setSpace(data);
      setEditedDesc(data.description || '');
      setDraftStatuses(getSpaceStatuses(data));

      // Pre-select entity based on preSelectedFieldId if provided
      if (preSelectedFieldId) {
        let foundEntityId = null;
        for (const ent of data.entities) {
          if (ent.fields.some(f => f.field_id === preSelectedFieldId)) {
            foundEntityId = ent.entity_id;
            break;
          }
        }
        if (foundEntityId) {
          setSelectedEntityId(foundEntityId);
          setSelectedFieldId(preSelectedFieldId);
        } else {
          setSelectedEntityId(data.entities[0]?.entity_id || null);
          setSelectedFieldId(null);
        }
      } else {
        setSelectedEntityId(data.entities[0]?.entity_id || null);
        setSelectedFieldId(null);
      }
    } catch (err: any) {
      console.error('Failed to load semantic space:', err);
      setError('无法加载当前业务语义空间，可能是元数据服务断开连接。');
    } finally {
      setLoading(false);
    }
  }, [dsId, preSelectedFieldId, spaceId]);

  useEffect(() => {
    void fetchSpace();
  }, [fetchSpace]);

  // Version history mock setup
  useEffect(() => {
    if (space?.version) {
      const hist = [];
      for (let i = 1; i <= space.version; i++) {
        hist.push(i);
      }
      setVersionHistory(hist.reverse());
    }
  }, [space]);

  const persistDraft = useCallback(async (
    description: string = editedDesc,
    statuses: Record<string, FieldStatus> = draftStatuses,
    fieldUpdates?: Record<string, SemanticFieldUpdate>
  ) => {
    if (!space || !isAdmin) return;
    const seq = saveSeqRef.current + 1;
    saveSeqRef.current = seq;
    setSavingDraft(true);
    try {
      const updated = await api.updateSemanticSpaces(dsId, [
        {
          space_id: spaceId,
          accepted: space.accepted,
          description,
          field_statuses: statuses,
          field_updates: fieldUpdates
        }
      ]);
      const nextSpace = updated.spaces.find(s => s.space_id === spaceId);
      if (nextSpace && saveSeqRef.current === seq) {
        setSpace(nextSpace);
      } else if (!nextSpace && saveSeqRef.current === seq) {
        await fetchSpace();
      }
    } catch (err: any) {
      console.error('Failed to auto-save semantic space draft:', err);
      alert(`自动保存失败: ${err?.message || '未知错误'}`);
    } finally {
      if (saveSeqRef.current === seq) {
        setSavingDraft(false);
      }
    }
  }, [draftStatuses, dsId, editedDesc, fetchSpace, isAdmin, space, spaceId]);

  const handleStatusChange = (fieldId: string, status: FieldStatus) => {
    if (!isAdmin) return;
    const nextStatuses = { ...draftStatuses, [fieldId]: status };
    setDraftStatuses(nextStatuses);
    persistDraft(editedDesc, nextStatuses);
  };

  const persistFieldDraft = useCallback(async (fieldId: string, draft: FieldDraft) => {
    if (!isAdmin) return;
    setSavingFieldId(fieldId);
    try {
      await persistDraft(editedDesc, draftStatuses, {
        [fieldId]: fieldUpdateFromDraft(draft)
      });
    } finally {
      setSavingFieldId(current => current === fieldId ? null : current);
    }
  }, [draftStatuses, editedDesc, isAdmin, persistDraft]);

  // Stepper Actions
  const handleStartRefresh = () => {
    setStepperActive(true);
    setStepperStep(1);
    setSpaceDiff(null);
  };

  const handleExecuteRefresh = async () => {
    setRefreshLoading(true);
    try {
      const diff = await api.refreshSemanticSpace(dsId, spaceId);
      setSpaceDiff(diff);
      setStepperStep(2);
      // Pre-select new fields as suggestions to be confirmed
      setConfirmedSuggestions(diff.new_fields.map(f => f.field_id));
    } catch (err: any) {
      alert(`AI 语义刷新异常: ${err?.message}`);
    } finally {
      setRefreshLoading(false);
    }
  };

  const handleToggleSuggestion = (fieldId: string) => {
    setConfirmedSuggestions(prev => 
      prev.includes(fieldId) ? prev.filter(id => id !== fieldId) : [...prev, fieldId]
    );
  };

  const handlePublish = async () => {
    setPublishing(true);
    try {
      const updatedSpace = await api.publishSemanticSpace(dsId, spaceId, {
        confirmed_suggestions: confirmedSuggestions
      });
      setSpace(updatedSpace);
      setDraftStatuses(getSpaceStatuses(updatedSpace));
      setStepperActive(false);
      alert('语义空间已成功发布新版本！');
    } catch (err: any) {
      alert(`发布失败: ${err?.message}`);
    } finally {
      setPublishing(false);
    }
  };

  // Select active items
  const activeEntity = space?.entities.find(e => e.entity_id === selectedEntityId);
  const selectedField = activeEntity?.fields.find(f => f.field_id === selectedFieldId) || null;
  const changedStatusCount = space ? space.entities.reduce((count, ent) => (
    count + ent.fields.filter(field => (
      fieldStatusFor(field, draftStatuses) !== (field.status || (field.is_candidate ? 'pending' : 'confirmed'))
    )).length
  ), 0) : 0;
  const descriptionChanged = space ? editedDesc !== (space.description || '') : false;
  const isSpaceEnabled = space
    ? space.entities.reduce((sum, ent) => sum + (ent.fields?.length || 0), 0) > 0
    : false;
  const fieldDraftChanged = isFieldDraftChanged(selectedField, fieldDraft);
  const hasDraftChanges = changedStatusCount > 0 || descriptionChanged || fieldDraftChanged;

  useEffect(() => {
    if (!activeEntity) return;
    if (!activeEntity.fields.some(f => f.field_id === selectedFieldId)) {
      setSelectedFieldId(null);
    }
  }, [activeEntity, selectedFieldId]);

  useEffect(() => {
    setFieldDraft(fieldDraftFrom(selectedField));
  }, [selectedField]);

  useEffect(() => {
    if (!space || !isAdmin || !descriptionChanged) return;
    const timer = window.setTimeout(() => {
      persistDraft(editedDesc, draftStatuses);
    }, 900);
    return () => window.clearTimeout(timer);
  }, [descriptionChanged, draftStatuses, editedDesc, isAdmin, persistDraft, space, spaceId]);

  useEffect(() => {
    if (!selectedField || !isAdmin || !fieldDraftChanged) return;
    const timer = window.setTimeout(() => {
      persistFieldDraft(selectedField.field_id, fieldDraft);
    }, 900);
    return () => window.clearTimeout(timer);
  }, [fieldDraft, fieldDraftChanged, isAdmin, persistFieldDraft, selectedField, selectedFieldId]);

  // Filtered fields in right detail tab
  const filteredFields = activeEntity?.fields.filter(f => {
    const q = searchQuery.toLowerCase();
    return (
      f.physical_column.toLowerCase().includes(q) ||
      f.business_name.toLowerCase().includes(q) ||
      (f.description && f.description.toLowerCase().includes(q))
    );
  }) || [];

  if (loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center py-20 text-slate-400">
        <RefreshCw className="w-8 h-8 animate-spin text-indigo-500 mb-3" />
        <p className="text-sm font-medium">正在进入业务语义空间工作台...</p>
      </div>
    );
  }

  if (error || !space) {
    return (
      <div className="flex-1 max-w-xl mx-auto py-16 text-center space-y-4">
        <div className="w-12 h-12 bg-amber-50 dark:bg-amber-950/20 border border-amber-250 dark:border-amber-900 rounded-full flex items-center justify-center mx-auto text-amber-500">
          <Layers className="w-6 h-6" />
        </div>
        <div>
          <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200">语义空间加载失败</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">{error}</p>
        </div>
        <div className="pt-2 flex gap-3 justify-center">
          <button onClick={onBack} className="border border-slate-200 text-xs px-4 py-2 rounded-lg font-semibold cursor-pointer">
            返回数据源列表
          </button>
          <button onClick={fetchSpace} className="bg-indigo-600 text-white text-xs px-4 py-2 rounded-lg font-semibold cursor-pointer">
            重新尝试
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-white dark:bg-slate-950 text-left">
      
      {/* Header with Back, Title, Description Edit, Actions */}
      <div className="px-6 py-4 border-b border-slate-150 dark:border-slate-850 space-y-3 shrink-0">
        
        {/* Back Link and Main Title row */}
        <div className="flex justify-between items-start flex-wrap gap-4">
          <div className="flex items-center gap-3">
            <button 
              onClick={onBack}
              className="p-1.5 hover:bg-slate-50 dark:hover:bg-slate-900 rounded-lg text-slate-500 hover:text-slate-700 dark:text-slate-400 transition-colors cursor-pointer border border-slate-200/50 dark:border-slate-800"
            >
              <ArrowLeft className="w-4 h-4" />
            </button>
            
            <div className="space-y-0.5">
              <div className="flex items-center gap-2.5">
                <h2 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
                  <Layers className="w-5 h-5 text-indigo-500" />
                  {space.name}
                </h2>
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                  isSpaceEnabled
                    ? 'bg-green-50 dark:bg-green-950/20 text-green-700 dark:text-green-400 border-green-200 dark:border-green-900/30' 
                    : 'bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-900/30'
                }`}>
                  版本 v{space.version || 1} · {isSpaceEnabled ? '已启用' : '配置中'}
                </span>
              </div>
              <p className="text-[10px] text-slate-400 dark:text-slate-500">
                所属数据源: <span className="font-mono">{dsId}</span>
              </p>
            </div>
          </div>

          {/* Primary workspace actions */}
          <div className="flex items-center justify-end gap-2 flex-wrap">
            <span className={`text-[10px] font-semibold rounded-lg px-2 py-1 border ${
              savingDraft
                ? 'text-indigo-700 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/20 border-indigo-200 dark:border-indigo-900/40'
                : hasDraftChanges
                ? 'text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-900/40'
                : 'text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-900/40'
            }`}>
              {savingDraft ? '自动保存中' : hasDraftChanges ? '等待自动保存' : '已自动保存'}
            </span>

            {/* Version History Selector */}
            <div className="flex items-center gap-1.5 text-xs border border-slate-200 dark:border-slate-800 rounded-lg px-2.5 py-1.5 bg-slate-50/50 dark:bg-slate-900/30">
              <History className="w-3.5 h-3.5 text-slate-405" />
              <span className="text-slate-500">版本历史:</span>
              <select 
                value={viewingVersion || space.version || 1} 
                onChange={(e) => setViewingVersion(Number(e.target.value))}
                className="bg-transparent border-none outline-none font-bold text-slate-700 dark:text-slate-350 cursor-pointer font-mono"
              >
                {versionHistory.map(v => (
                  <option key={v} value={v}>v{v} {v === space.version ? '(当前)' : ''}</option>
                ))}
              </select>
            </div>

            {isAdmin && !stepperActive && (
              <button
                onClick={handleStartRefresh}
                className="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 dark:bg-slate-800 dark:hover:bg-slate-750 text-white text-xs font-bold px-4 py-2 rounded-lg shadow-sm transition-colors cursor-pointer"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                AI 语义刷新
              </button>
            )}
          </div>
        </div>

        {/* Space Description Editor */}
        <div className="bg-slate-50/50 dark:bg-slate-900/20 p-3 rounded-lg border border-slate-100 dark:border-slate-800 text-xs">
          <div className="grid grid-cols-1 lg:grid-cols-[88px_minmax(0,1fr)] gap-2 lg:gap-3 min-w-0">
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400 pt-2">
              业务背景定义
            </label>
            {isAdmin ? (
              <textarea
                value={editedDesc}
                onChange={e => setEditedDesc(e.target.value)}
                rows={2}
                placeholder="说明该空间覆盖的业务、口径边界、常见分析问题。"
                className="w-full bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-750 rounded-lg p-2 outline-none focus:border-indigo-500 text-xs resize-none text-slate-700 dark:text-slate-300"
              />
            ) : (
              <p className="text-slate-655 dark:text-slate-400 leading-relaxed">
                {space.description || '暂无业务背景定义'}
              </p>
            )}
          </div>
        </div>

      </div>

      {/* Main Refresh Stepper Box */}
      {stepperActive && (
        <div className="bg-indigo-50/20 dark:bg-indigo-950/10 border-b border-indigo-150/40 dark:border-indigo-950 p-6 space-y-5 shrink-0 text-xs text-left">
          
          {/* Stepper Status Indicators */}
          <div className="flex justify-between items-center max-w-2xl mx-auto">
            {[
              { step: 1, label: '1. AI 重新扫描' },
              { step: 2, label: '2. 元数据变更对比' },
              { step: 3, label: '3. 自动生成建议' },
              { step: 4, label: '4. 确认并发布' }
            ].map(item => (
              <div key={item.step} className="flex items-center gap-2">
                <span className={`w-6 h-6 rounded-full flex items-center justify-center font-bold text-[10px] border ${
                  stepperStep === item.step
                    ? 'bg-indigo-600 text-white border-indigo-600'
                    : stepperStep > item.step
                    ? 'bg-emerald-500 text-white border-emerald-500'
                    : 'bg-white dark:bg-slate-900 text-slate-400 border-slate-205 dark:border-slate-800'
                }`}>
                  {item.step}
                </span>
                <span className={`font-semibold ${stepperStep === item.step ? 'text-indigo-600 dark:text-indigo-400' : 'text-slate-400'}`}>
                  {item.label}
                </span>
              </div>
            ))}
            <button 
              onClick={() => setStepperActive(false)} 
              className="text-slate-400 hover:text-slate-655 ml-4"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="max-w-2xl mx-auto bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
            
            {/* Step 1: Trigger scan */}
            {stepperStep === 1 && (
              <div className="space-y-3 text-center py-4">
                <HelpCircle className="w-10 h-10 text-indigo-500 mx-auto" />
                <div className="space-y-1">
                  <span className="font-bold text-slate-800 dark:text-slate-200 text-sm">将使用当前的数据库架构启动 AI 语义刷新</span>
                  <p className="text-slate-405 leading-relaxed">
                    AI 引擎将扫描底层物理表结构的变化，并与现有语义空间进行差分，以确定是否有新的字段或已排除的表存在关联。
                  </p>
                </div>
                <button
                  onClick={handleExecuteRefresh}
                  disabled={refreshLoading}
                  className="bg-indigo-600 hover:bg-indigo-755 text-white font-bold px-6 py-2.5 rounded-lg shadow-sm flex items-center gap-1.5 mx-auto transition-colors cursor-pointer"
                >
                  {refreshLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                  {refreshLoading ? '分析模型重新扫描中...' : '开始重新计算语义'}
                </button>
              </div>
            )}

            {/* Step 2: Compare Diff */}
            {stepperStep === 2 && spaceDiff && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-slate-800 dark:text-slate-200 font-bold border-b pb-2">
                  <FileText className="w-4 h-4 text-indigo-500" />
                  架构差分清单 (Schema Diff)
                </div>
                <div className="max-h-40 overflow-y-auto space-y-2 pr-1 font-mono text-[10px]">
                  {spaceDiff.new_fields.length === 0 && spaceDiff.removed_fields.length === 0 && spaceDiff.changed_fields.length === 0 ? (
                    <p className="text-slate-400 italic text-center py-4">无底层元数据架构发生变更。</p>
                  ) : (
                    <>
                      {spaceDiff.new_fields.map((f, i) => (
                        <div key={i} className="flex gap-2 text-green-600 bg-green-50/50 dark:bg-green-950/10 p-1.5 rounded">
                          <span>[+] 新增物理列:</span>
                          <code>{f.physical_table}.{f.physical_column} ({f.data_type})</code>
                        </div>
                      ))}
                      {spaceDiff.changed_fields.map((c, i) => (
                        <div key={i} className="flex gap-2 text-blue-600 bg-blue-50/50 dark:bg-blue-950/10 p-1.5 rounded">
                          <span>[*] 列定义变更:</span>
                          <code>{c.field_id}: {JSON.stringify(c.before)} → {JSON.stringify(c.after)}</code>
                        </div>
                      ))}
                    </>
                  )}
                </div>
                <div className="flex justify-end gap-3 pt-2">
                  <button 
                    onClick={() => setStepperStep(3)}
                    className="bg-indigo-650 hover:bg-indigo-700 text-white font-bold px-4 py-2 rounded-lg"
                  >
                    查看 AI 采纳建议
                  </button>
                </div>
              </div>
            )}

            {/* Step 3: Suggestions */}
            {stepperStep === 3 && spaceDiff && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-slate-800 dark:text-slate-200 font-bold border-b pb-2">
                  <Sparkles className="w-4 h-4 text-violet-500" />
                  AI 生成的字段采纳建议
                </div>
                <p className="text-[10px] text-slate-400">
                  AI 分析了物理字段并推荐了以下语义别名和角色，请勾选确认要纳入本语义空间的字段建议：
                </p>
	                <div className="max-h-48 overflow-y-auto space-y-2 pr-1">
	                  {spaceDiff.new_fields.length === 0 && (
	                    <div className="text-center py-6 text-slate-400 bg-slate-50/50 dark:bg-slate-900/40 border border-dashed border-slate-200 dark:border-slate-800 rounded-lg">
	                      没有新的待采纳字段，可直接进入发布确认。
	                    </div>
	                  )}
	                  {spaceDiff.new_fields.map(f => {
                    const isSelected = confirmedSuggestions.includes(f.field_id);
                    return (
                      <div 
                        key={f.field_id}
                        onClick={() => handleToggleSuggestion(f.field_id)}
                        className={`p-3 border rounded-lg cursor-pointer transition-all flex items-start gap-3 ${
                          isSelected 
                            ? 'bg-indigo-50/40 dark:bg-indigo-950/10 border-indigo-300 dark:border-indigo-900' 
                            : 'bg-slate-50/30 dark:bg-slate-900 border-slate-200 dark:border-slate-800'
                        }`}
                      >
                        <input type="checkbox" checked={isSelected} onChange={() => {}} className="mt-1" />
                        <div className="space-y-1 text-left flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-slate-800 dark:text-slate-200">{f.business_name}</span>
                            <span className="text-[9px] bg-indigo-50 border border-indigo-200 px-1 rounded text-indigo-650">{f.semantic_role === 'measure' ? '度量' : '维度'}</span>
                          </div>
                          <p className="text-[10px] text-slate-405 leading-relaxed truncate">{f.description}</p>
                          <div className="text-[9px] text-slate-400 font-mono">
                            物理来源: <code>{f.physical_table}.{f.physical_column} ({f.data_type})</code>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="flex justify-end gap-3 pt-2">
                  <button 
                    onClick={() => setStepperStep(4)}
                    className="bg-indigo-655 hover:bg-indigo-700 text-white font-bold px-5 py-2 rounded-lg"
                  >
                    下一步
                  </button>
                </div>
              </div>
            )}

            {/* Step 4: Publish Confirm */}
            {stepperStep === 4 && (
              <div className="space-y-4">
                <div className="flex items-center gap-2 text-slate-800 dark:text-slate-200 font-bold border-b pb-2">
                  <CheckCircle className="w-4 h-4 text-emerald-500" />
                  确认发布新版本
                </div>
                <div className="space-y-2 p-3 bg-slate-50/50 dark:bg-slate-900 rounded-lg text-slate-655 dark:text-slate-400">
                  <div className="flex justify-between">
                    <span>当前空间版本:</span>
                    <strong className="font-mono">v{space.version || 1}</strong>
                  </div>
	                  <div className="flex justify-between">
	                    <span>发布后版本:</span>
	                    <strong className="font-mono text-indigo-650 dark:text-indigo-400">
	                      v{space.version_state === 'published' ? (space.version || 1) + 1 : (space.version || 1)}
	                    </strong>
	                  </div>
                  <div className="flex justify-between">
                    <span>新增采纳的 AI 字段:</span>
                    <strong>{confirmedSuggestions.length} 个</strong>
                  </div>
                </div>

                <div className="flex justify-end gap-2.5 pt-2">
                  <button 
                    type="button" 
                    onClick={() => setStepperStep(3)}
                    className="px-4 py-2 rounded border border-slate-200 hover:bg-slate-50"
                  >
                    上一步
                  </button>
                  <button 
                    type="button" 
                    onClick={handlePublish}
                    disabled={publishing}
                    className="bg-emerald-600 hover:bg-emerald-700 text-white font-bold px-6 py-2 rounded-lg flex items-center gap-1.5 shadow-sm"
                  >
                    {publishing && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                    确认并正式发布新版本
                  </button>
                </div>
              </div>
            )}

          </div>
        </div>
      )}

      {/* Content layout split: Left Entity tree list, Right Field editor */}
      <div className="flex-1 flex min-h-0">
        
        {/* Left Side: Tables inside this space */}
        <div className="w-64 border-r border-slate-150 dark:border-slate-850 overflow-y-auto flex flex-col shrink-0 select-none">
          <div className="p-3 bg-slate-50/50 dark:bg-slate-900/10 border-b border-slate-150 dark:border-slate-850 flex justify-between items-center">
            <span className="text-[10px] font-bold text-slate-450 uppercase tracking-wider">空间内数据表实体</span>
            <span className="text-[9px] bg-indigo-50 border border-indigo-200/50 px-1 rounded text-indigo-655 font-bold font-mono">
              {space.entities.length}
            </span>
          </div>

          <div className="flex-1 p-2 space-y-0.5">
            {space.entities.length === 0 ? (
              <p className="text-[10px] text-slate-400 italic text-center py-6">此空间暂无包含的数据表实体，请点击刷新扫描引入。</p>
            ) : (
              space.entities.map(entity => {
                const isSelected = entity.entity_id === selectedEntityId;
                return (
                  <div
                    key={entity.entity_id}
                    onClick={() => setSelectedEntityId(entity.entity_id)}
                    className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-semibold cursor-pointer transition-colors ${
                      isSelected
                        ? 'bg-indigo-50 dark:bg-indigo-950/30 text-indigo-650 dark:text-indigo-400'
                        : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-900/30'
                    }`}
                  >
                    <Table className="w-4 h-4 shrink-0 opacity-60" />
                    <span className="truncate">{entity.business_name || entity.physical_table}</span>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right Side: Entity detail viewer & fields cards status editor */}
        <div className="flex-1 overflow-y-auto p-6 flex flex-col space-y-6">
          {activeEntity ? (
            <>
              {/* Fields List Header and Search Input */}
              <div className="space-y-4 min-h-0 flex-1 flex flex-col">
                <div className="flex justify-between items-center gap-4 flex-wrap">
                  <h4 className="text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
                    字段语义与采纳状态 ({filteredFields.length} / {activeEntity.fields.length})
                  </h4>
                  
                  {/* Search input */}
                  <div className="relative w-64">
                    <Search className="w-3.5 h-3.5 text-slate-405 absolute left-2.5 top-1/2 -translate-y-1/2" />
                    <input
                      type="text"
                      placeholder="搜索字段别名/物理列名..."
                      value={searchQuery}
                      onChange={e => setSearchQuery(e.target.value)}
                      className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg pl-8 pr-3 py-1.5 text-xs outline-none focus:border-indigo-500 dark:focus:border-indigo-650"
                    />
                  </div>
                </div>

                {/* Fields compact overview + semantic editor */}
                {filteredFields.length === 0 ? (
                  <p className="text-center py-12 text-slate-400 italic">未找到匹配的字段或度量。</p>
                ) : (
                  <div className={`grid grid-cols-1 gap-4 min-h-0 ${selectedField ? '2xl:grid-cols-[minmax(0,1fr)_380px]' : ''}`}>
                    <div className="border border-slate-200/80 dark:border-slate-800 rounded-xl overflow-hidden bg-white dark:bg-slate-900 shadow-sm">
                      <div className="grid grid-cols-[minmax(180px,1.45fr)_minmax(150px,1fr)_82px_88px_92px_minmax(92px,.85fr)_76px] gap-2 px-3 py-2 bg-slate-50 dark:bg-slate-900/70 border-b border-slate-200 dark:border-slate-800 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                        <span>字段语义</span>
                        <span>物理字段</span>
                        <span>角色</span>
                        <span>语义状态</span>
                        <span>元数据状态</span>
                        <span>来源</span>
                        <span className="text-right">操作</span>
                      </div>
                      <div className="divide-y divide-slate-100 dark:divide-slate-800 max-h-[560px] overflow-y-auto">
                        {filteredFields.map(field => {
                          const status = fieldStatusFor(field, draftStatuses);
                          const statusMeta = FIELD_STATUS_META[status];
                          const metaStatus = metadataStatusFor(field);
                          const roleLabel = SEMANTIC_ROLE_OPTIONS.find(opt => opt.value === (field.semantic_role || ''))?.label || field.semantic_role || '未设置';
                          const isSelected = selectedFieldId === field.field_id;
                          const sourceBadges = Array.from(
                            new Map(
                              (field.evidence || []).map(ev => [
                                ev.source,
                                EVIDENCE_SOURCE_LABELS[ev.source] || { label: ev.source, color: 'text-slate-500 bg-slate-50 border-slate-205' }
                              ])
                            ).values()
                          ).slice(0, 2);

                          return (
                            <div
                              key={field.field_id}
                              id={`field-card-${field.field_id}`}
                              className={`w-full grid grid-cols-[minmax(180px,1.45fr)_minmax(150px,1fr)_82px_88px_92px_minmax(92px,.85fr)_76px] gap-2 px-3 py-2.5 text-left items-center transition-colors ${
                                isSelected
                                  ? 'bg-indigo-50/70 dark:bg-indigo-950/20'
                                  : 'hover:bg-slate-50 dark:hover:bg-slate-850'
                              }`}
                            >
                              <span className="min-w-0">
                                <span className="block text-xs font-bold text-slate-850 dark:text-slate-200 truncate">{field.business_name}</span>
                                <span className="block text-[10px] text-slate-400 truncate">{field.description || '未填写业务解释'}</span>
                              </span>
                              <span className="min-w-0 font-mono text-[10px] text-slate-500 dark:text-slate-400">
                                <span className="block truncate">{field.physical_column}</span>
                                <span className="block text-slate-400 truncate">{field.data_type || '未知类型'}</span>
                              </span>
                              <span className="text-[10px] text-slate-600 dark:text-slate-400 truncate">{roleLabel}</span>
                              <span className={`inline-flex w-fit px-1.5 py-0.5 rounded border text-[9px] font-bold ${statusMeta.className}`}>
                                {statusMeta.label}
                              </span>
                              <span className={`inline-flex w-fit px-1.5 py-0.5 rounded border text-[9px] font-bold ${metaStatus.className}`}>
                                {metaStatus.label}
                              </span>
                              <span className="flex flex-wrap gap-1">
                                {sourceBadges.length > 0 ? sourceBadges.map(source => (
                                  <span key={source.label} className={`px-1 py-0.5 rounded border text-[9px] font-bold ${source.color}`}>
                                    {source.label}
                                  </span>
                                )) : (
                                  <span className="px-1 py-0.5 rounded border text-[9px] font-bold text-slate-400 bg-slate-50 border-slate-200 dark:bg-slate-900 dark:border-slate-800">
                                    未记录
                                  </span>
                                )}
                              </span>
                              <span className="flex justify-end">
                                <button
                                  type="button"
                                  onClick={() => setSelectedFieldId(field.field_id)}
                                  className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[10px] font-bold transition-colors cursor-pointer ${
                                    isSelected
                                      ? 'border-indigo-200 bg-indigo-600 text-white dark:border-indigo-800'
                                      : 'border-slate-200 bg-white text-slate-600 hover:border-indigo-200 hover:text-indigo-650 dark:border-slate-750 dark:bg-slate-950 dark:text-slate-300'
                                  }`}
                                >
                                  <Pencil className="w-3 h-3" />
                                  修改
                                </button>
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    {selectedField && (
                      <aside className="border border-slate-200/80 dark:border-slate-800 rounded-xl bg-white dark:bg-slate-900 shadow-sm p-4 text-xs space-y-4 h-fit 2xl:sticky 2xl:top-4">
                        {(() => {
                        const status = fieldStatusFor(selectedField, draftStatuses);
                        const statusMeta = FIELD_STATUS_META[status];
                        const metaStatus = metadataStatusFor(selectedField);
                        const hasEvidenceDetails = selectedField.evidence.some(ev => !!ev.detail?.trim());
                        return (
                          <>
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">字段语义编辑</div>
                                <div className="mt-1 font-mono text-[10px] text-slate-400 truncate">{selectedField.physical_table}.{selectedField.physical_column}</div>
                              </div>
                              <div className="shrink-0 flex items-center gap-1.5">
                                <span className={`px-1.5 py-0.5 rounded border text-[9px] font-bold ${savingFieldId === selectedField.field_id ? 'bg-indigo-50 text-indigo-700 border-indigo-200' : statusMeta.className}`}>
                                  {savingFieldId === selectedField.field_id ? '保存中' : statusMeta.label}
                                </span>
                                <button
                                  type="button"
                                  onClick={() => setSelectedFieldId(null)}
                                  className="p-1 rounded-lg border border-slate-200 text-slate-400 hover:text-slate-700 hover:bg-slate-50 dark:border-slate-750 dark:hover:bg-slate-850 cursor-pointer"
                                  title="关闭编辑"
                                >
                                  <X className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            </div>

                            <div className="space-y-3">
                              <label className="block space-y-1">
                                <span className="text-[10px] font-bold text-slate-400">业务字段名</span>
                                <input
                                  value={fieldDraft.business_name}
                                  onChange={e => setFieldDraft(prev => ({ ...prev, business_name: e.target.value }))}
                                  disabled={!isAdmin}
                                  className="w-full rounded-lg border border-slate-200 dark:border-slate-750 bg-slate-50 dark:bg-slate-950 px-2 py-1.5 outline-none focus:border-indigo-500 text-slate-750 dark:text-slate-200"
                                />
                              </label>

                              <label className="block space-y-1">
                                <span className="text-[10px] font-bold text-slate-400">业务解释</span>
                                <textarea
                                  rows={3}
                                  value={fieldDraft.description}
                                  onChange={e => setFieldDraft(prev => ({ ...prev, description: e.target.value }))}
                                  disabled={!isAdmin}
                                  className="w-full rounded-lg border border-slate-200 dark:border-slate-750 bg-slate-50 dark:bg-slate-950 px-2 py-1.5 outline-none focus:border-indigo-500 text-slate-750 dark:text-slate-200 resize-none"
                                />
                              </label>

                              <label className="block space-y-1">
                                <span className="text-[10px] font-bold text-slate-400">别名</span>
                                <textarea
                                  rows={2}
                                  value={fieldDraft.synonymsText}
                                  onChange={e => setFieldDraft(prev => ({ ...prev, synonymsText: e.target.value }))}
                                  disabled={!isAdmin}
                                  placeholder="多个别名用逗号分隔"
                                  className="w-full rounded-lg border border-slate-200 dark:border-slate-750 bg-slate-50 dark:bg-slate-950 px-2 py-1.5 outline-none focus:border-indigo-500 text-slate-750 dark:text-slate-200 resize-none"
                                />
                              </label>

                              <div className="grid grid-cols-2 gap-2">
                                <label className="block space-y-1">
                                  <span className="text-[10px] font-bold text-slate-400">语义角色</span>
                                  <select
                                    value={fieldDraft.semantic_role}
                                    onChange={e => setFieldDraft(prev => ({ ...prev, semantic_role: e.target.value }))}
                                    disabled={!isAdmin}
                                    className="w-full rounded-lg border border-slate-200 dark:border-slate-750 bg-slate-50 dark:bg-slate-950 px-2 py-1.5 outline-none focus:border-indigo-500"
                                  >
                                    {SEMANTIC_ROLE_OPTIONS.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                                  </select>
                                </label>
                                <label className="block space-y-1">
                                  <span className="text-[10px] font-bold text-slate-400">默认聚合</span>
                                  <select
                                    value={fieldDraft.default_aggregation}
                                    onChange={e => setFieldDraft(prev => ({ ...prev, default_aggregation: e.target.value }))}
                                    disabled={!isAdmin}
                                    className="w-full rounded-lg border border-slate-200 dark:border-slate-750 bg-slate-50 dark:bg-slate-950 px-2 py-1.5 outline-none focus:border-indigo-500"
                                  >
                                    {AGGREGATION_OPTIONS.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                                  </select>
                                </label>
                              </div>

                              <label className="block space-y-1">
                                <span className="text-[10px] font-bold text-slate-400">语义采纳状态</span>
                                <select
                                  value={status}
                                  onChange={e => handleStatusChange(selectedField.field_id, e.target.value as FieldStatus)}
                                  disabled={!isAdmin}
                                  className="w-full rounded-lg border border-slate-200 dark:border-slate-750 bg-slate-50 dark:bg-slate-950 px-2 py-1.5 outline-none focus:border-indigo-500"
                                >
                                  {Object.entries(FIELD_STATUS_META).map(([value, meta]) => <option key={value} value={value}>{meta.label}</option>)}
                                </select>
                              </label>
                            </div>

                            <div className="border-t border-slate-100 dark:border-slate-800 pt-3 space-y-2">
                              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">只读物理元数据</div>
                              <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px] text-slate-500 dark:text-slate-400">
                                <span>物理表</span><code className="truncate">{selectedField.physical_table}</code>
                                <span>物理列</span><code className="truncate">{selectedField.physical_column}</code>
                                <span>类型</span><code>{selectedField.data_type || '未知'}</code>
                                <span>元数据状态</span><span className={`w-fit px-1.5 py-0.5 rounded border font-bold ${metaStatus.className}`}>{metaStatus.label}</span>
                              </div>
                            </div>

                            <div className="border-t border-slate-100 dark:border-slate-800 pt-3 space-y-2">
                              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1">
                                <Info className="w-3 h-3 text-indigo-400" />
                                语义来源
                              </div>
                              {selectedField.evidence.length > 0 ? (
                                <div className="space-y-2">
                                  <div className="flex flex-wrap gap-1.5">
                                    {selectedField.evidence.map((ev, idx) => {
                                      const cfg = EVIDENCE_SOURCE_LABELS[ev.source] || { label: ev.source, color: 'text-slate-500 bg-slate-50 border-slate-205' };
                                      return <span key={idx} className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${cfg.color}`}>{cfg.label}</span>;
                                    })}
                                  </div>
                                  {hasEvidenceDetails ? (
                                    <div className="space-y-1">
                                      {selectedField.evidence.filter(ev => !!ev.detail?.trim()).map((ev, idx) => {
                                        const cfg = EVIDENCE_SOURCE_LABELS[ev.source] || { label: ev.source, color: 'text-slate-500 bg-slate-50 border-slate-205' };
                                        return <div key={idx} className="text-[10px] text-slate-500 dark:text-slate-400"><strong>{cfg.label}</strong> {ev.detail}</div>;
                                      })}
                                    </div>
                                  ) : (
                                    <p className="text-[10px] text-slate-400 italic">该字段由系统根据字段名、注释和上下文自动识别。</p>
                                  )}
                                </div>
                              ) : (
                                <p className="text-[10px] text-slate-400 italic">该字段来自底层元数据定义。</p>
                              )}
                            </div>
                          </>
                        );
                      })()}
                    </aside>
                    )}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center py-20 text-slate-400">
              <Table className="w-8 h-8 opacity-30 mb-2" />
              <p className="text-xs">请选择左侧的数据表以展示字段明细工作台。</p>
            </div>
          )}
        </div>

      </div>
    </div>
  );
};
