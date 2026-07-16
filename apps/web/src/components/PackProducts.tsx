import React, { useState, useEffect } from 'react';
import { 
  Package, 
  BookOpen, 
  Cpu, 
  FileText, 
  Copy, 
  Eye, 
  Check,
  Plus,
  RefreshCw,
  AlertTriangle,
  UploadCloud,
  X,
  Sparkles,
  Search,
  Database,
  Trash2
} from 'lucide-react';
import { api } from '../api';
import { getAssetIdentity } from '../assetIdentity';
import { confirmAction } from '../systemDialog';
import { PackAdaptModal } from './PackAdaptModal';
import { ActionButton, ManagementHeader, ManagementPage } from './ui/ManagementUI';
import type {
  MetricDefinition,
  SkillDefinition,
  ReportDefinition,
  EnterprisePack,
  PackCreateMode,
  PackDraftResult,
  DataSourceDocument,
  DataSource,
  PackWithDeployments,
  PackSkill,
  OfficialPackContent,
  PackExtensionLayer,
  EffectiveDomainPack,
  EnterprisePackDraft,
  UserContext,
  PackImportPreview
} from '../api';

interface PackProductsProps {
  metrics: MetricDefinition[];
  skills: SkillDefinition[];
  reports: ReportDefinition[];
  userContext: UserContext;
  onRefreshData: () => Promise<void>;
  onPreviewMetric: (metric: MetricDefinition) => void;
  onPreviewReport: (report: ReportDefinition) => void;
  onEditEnterprisePack: (pack: EnterprisePack) => void;
  onOpenMounting?: (deploymentId: string) => void;
  activeDataSourceId: string;
}

const OFFICIAL_PACKS = [
  {
    id: 'tms' as const,
    name: 'TMS 运输管理系统领域包',
    description: '覆盖发货申请、履约跟踪、运费询价以及承运商对账等核心场景。',
    version: 'v1.0.0',
    industry: '物流运输'
  },
  {
    id: 'wms' as const,
    name: 'WMS 智能仓储系统领域包',
    description: '覆盖入库制单、货位对齐、库存周转、出库拣货以及盘点损益分析等核心场景。',
    version: 'v1.2.0',
    industry: '仓储管理'
  }
];

type PackListFilter = 'all' | 'official' | 'enterprise';

// Kept only so pre-migration helpers remain type-compatible. These paths are
// intentionally not rendered in the first-product domain-pack wizard.
const LEGACY_CREATION_MODES = false;
const showLegacyAssetPanels = Boolean(import.meta.env.VITE_LEGACY_PACK_VIEW);

type OfficialPreviewKind = 'field' | 'metric' | 'report';

interface OfficialContentPreview {
  kind: OfficialPreviewKind;
  title: string;
  id: string;
  description: string;
  payload: Record<string, unknown>;
}

const asRecord = (value: unknown): Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};

const asText = (value: unknown, fallback = '—'): string =>
  typeof value === 'string' && value.trim() ? value : fallback;

const asTextList = (value: unknown): string[] =>
  Array.isArray(value) ? value.map(item => String(item)) : [];

const OfficialContentPreviewModal: React.FC<{
  preview: OfficialContentPreview;
  onClose: () => void;
}> = ({ preview, onClose }) => {
  const logicalFormula = asRecord(preview.payload.logical_formula);
  const physicalFormula = asRecord(preview.payload.formula);
  const widgets = Array.isArray(preview.payload.widgets)
    ? preview.payload.widgets.map(asRecord)
    : [];
  const Icon = preview.kind === 'field' ? Database : preview.kind === 'metric' ? BookOpen : FileText;
  const kindLabel = preview.kind === 'field' ? '标准字段' : preview.kind === 'metric' ? '官方指标' : '官方报表';

  return (
    <div className="fixed inset-0 z-[75] bg-slate-900/50 dark:bg-slate-950/70 backdrop-blur-sm flex items-center justify-center p-4" onMouseDown={onClose}>
      <div className="w-full max-w-2xl max-h-[82vh] overflow-y-auto rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-2xl" onMouseDown={event => event.stopPropagation()}>
        <div className="sticky top-0 z-10 bg-white/95 dark:bg-slate-900/95 backdrop-blur border-b border-slate-100 dark:border-slate-800 px-5 py-4 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400"><Icon className="w-3.5 h-3.5" />{kindLabel}详情</div>
            <h3 className="mt-1 font-bold text-base text-slate-900 dark:text-white truncate">{preview.title}</h3>
            <div className="mt-1 text-[10px] font-mono text-slate-400 break-all">{preview.id}</div>
          </div>
          <button type="button" onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label={`关闭${kindLabel}预览`}><X className="w-4 h-4" /></button>
        </div>

        <div className="p-5 space-y-5 text-xs">
          <section>
            <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">业务说明</h4>
            <p className="leading-relaxed text-slate-700 dark:text-slate-300">{preview.description}</p>
          </section>

          {preview.kind === 'field' && (
            <>
              <section className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-slate-100 dark:border-slate-800 p-3"><div className="text-[10px] text-slate-400">数据类型</div><div className="mt-1 font-mono font-bold text-slate-800 dark:text-slate-200">{asText(preview.payload.data_type)}</div></div>
                <div className="rounded-lg border border-slate-100 dark:border-slate-800 p-3"><div className="text-[10px] text-slate-400">映射要求</div><div className="mt-1 font-bold text-slate-800 dark:text-slate-200">{preview.payload.required === true ? '必填字段' : '可选字段'}</div></div>
              </section>
              {asTextList(preview.payload.enum_values).length > 0 && (
                <section><h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">枚举值</h4><div className="flex flex-wrap gap-1.5">{asTextList(preview.payload.enum_values).map(value => <span key={value} className="px-2 py-1 rounded-md bg-slate-100 dark:bg-slate-800 font-mono text-[10px] text-slate-700 dark:text-slate-300">{value}</span>)}</div></section>
              )}
            </>
          )}

          {preview.kind === 'metric' && (
            <>
              <section className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-slate-100 dark:border-slate-800 p-3"><div className="text-[10px] text-slate-400">数据源</div><div className="mt-1 font-mono text-slate-800 dark:text-slate-200">{asText(preview.payload.data_source_id)}</div></div>
                <div className="rounded-lg border border-slate-100 dark:border-slate-800 p-3"><div className="text-[10px] text-slate-400">版本</div><div className="mt-1 font-mono text-slate-800 dark:text-slate-200">v{asText(preview.payload.version, '1.0.0')}</div></div>
              </section>
              <section>
                <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">计算口径</h4>
                <pre className="rounded-lg bg-slate-950 text-slate-200 p-3 overflow-x-auto text-[11px] leading-relaxed whitespace-pre-wrap">{asText(logicalFormula.expression, asText(physicalFormula.expression, '暂无计算表达式'))}</pre>
                {asTextList(logicalFormula.referenced_standard_fields).length > 0 && <p className="mt-2 text-[10px] text-slate-500">标准字段：{asTextList(logicalFormula.referenced_standard_fields).join('、')}</p>}
              </section>
              {asTextList(preview.payload.synonyms).length > 0 && <section><h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">同义词</h4><div className="flex flex-wrap gap-1.5">{asTextList(preview.payload.synonyms).map(value => <span key={value} className="px-2 py-1 rounded-md bg-indigo-50 dark:bg-indigo-950/30 text-indigo-700 dark:text-indigo-300">{value}</span>)}</div></section>}
            </>
          )}

          {preview.kind === 'report' && (
            <>
              <section className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-slate-100 dark:border-slate-800 p-3"><div className="text-[10px] text-slate-400">时间粒度</div><div className="mt-1 font-bold text-slate-800 dark:text-slate-200">{asText(preview.payload.time_grain, '未限定')}</div></div>
                <div className="rounded-lg border border-slate-100 dark:border-slate-800 p-3"><div className="text-[10px] text-slate-400">组件数量</div><div className="mt-1 font-bold text-slate-800 dark:text-slate-200">{widgets.length}</div></div>
              </section>
              <section>
                <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">报表结构</h4>
                <div className="space-y-2">
                  {widgets.length === 0 && <div className="text-slate-400">暂无报表组件。</div>}
                  {widgets.map((widget, index) => (
                    <div key={asText(widget.widget_id, String(index))} className="rounded-lg border border-slate-100 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/40 p-3">
                      <div className="flex items-center justify-between gap-3"><span className="font-bold text-slate-800 dark:text-slate-200">{index + 1}. {asText(widget.title, '未命名组件')}</span><span className="text-[10px] text-indigo-600 dark:text-indigo-400">{asText(widget.chart_type, 'table')}</span></div>
                      <div className="mt-2 text-[10px] text-slate-500">指标：{asTextList(widget.metric_codes).join('、') || '无'}</div>
                      <div className="mt-1 text-[10px] text-slate-500">维度：{asTextList(widget.dimensions).join('、') || '无'}</div>
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

type BrowserTab = 'fields' | 'metrics' | 'skills' | 'reports';

interface BrowserAsset {
  id: string;
  name: string;
  description: string;
  type: BrowserTab;
  source: 'base' | 'extension';
  definition: Record<string, unknown>;
}

interface PackBrowserTarget {
  id: string;
  name: string;
  version: string;
  kind: 'official' | 'enterprise';
}

const browserTabs: Array<{ id: BrowserTab; label: string; icon: typeof Database }> = [
  { id: 'fields', label: '标准字段', icon: Database },
  { id: 'metrics', label: '指标', icon: BookOpen },
  { id: 'skills', label: '技能', icon: Cpu },
  { id: 'reports', label: '报表', icon: FileText },
];

const AssetDetailDialog: React.FC<{ asset: BrowserAsset; onClose: () => void }> = ({ asset, onClose }) => {
  const dependencies = [
    ...asTextList(asset.definition.referenced_standard_fields),
    ...asTextList(asset.definition.metric_codes),
    ...asTextList(asset.definition.skill_ids),
    ...asTextList(asset.definition.dimension_field_ids),
  ];
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div className="max-h-[82vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900" onMouseDown={event => event.stopPropagation()}>
        <header className="sticky top-0 flex items-start justify-between gap-4 border-b border-slate-100 bg-white/95 px-5 py-4 backdrop-blur dark:border-slate-800 dark:bg-slate-900/95">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[10px] font-bold tracking-wide text-indigo-600 dark:text-indigo-400">
              {browserTabs.find(tab => tab.id === asset.type)?.label}详情
              <span className={`rounded border px-1.5 py-0.5 ${asset.source === 'extension' ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300' : 'border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900 dark:bg-indigo-950/30 dark:text-indigo-300'}`}>{asset.source === 'extension' ? '扩建层新增' : '基础包'}</span>
            </div>
            <h3 className="mt-1 truncate text-base font-bold text-slate-900 dark:text-white">{asset.name}</h3>
            <p className="mt-1 break-all font-mono text-[10px] text-slate-400">{asset.id}</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="关闭资产详情"><X className="h-4 w-4" /></button>
        </header>
        <div className="space-y-5 p-5 text-xs">
          <section><h4 className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">业务说明</h4><p className="leading-relaxed text-slate-700 dark:text-slate-300">{asset.description || '暂无描述。'}</p></section>
          {dependencies.length > 0 && <section><h4 className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">依赖资源</h4><div className="flex flex-wrap gap-1.5">{dependencies.map(dependency => <span key={dependency} className="rounded-md bg-slate-100 px-2 py-1 font-mono text-[10px] text-slate-700 dark:bg-slate-800 dark:text-slate-300">{dependency}</span>)}</div></section>}
          <section><h4 className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">定义</h4><pre className="overflow-x-auto rounded-xl bg-slate-950 p-3 text-[10px] leading-relaxed text-slate-200">{JSON.stringify(asset.definition, null, 2)}</pre></section>
        </div>
      </div>
    </div>
  );
};

const DomainPackBrowserDialog: React.FC<{
  target: PackBrowserTarget;
  assets: Record<BrowserTab, BrowserAsset[]>;
  initialTab: BrowserTab;
  onClose: () => void;
}> = ({ target, assets, initialTab, onClose }) => {
  const [tab, setTab] = useState<BrowserTab>(initialTab);
  const [selectedAsset, setSelectedAsset] = useState<BrowserAsset | null>(null);
  const [query, setQuery] = useState('');
  const visible = assets[tab].filter(asset => `${asset.name} ${asset.id} ${asset.description}`.toLowerCase().includes(query.trim().toLowerCase()));
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div className="flex h-[min(48rem,calc(100vh-2rem))] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900" onMouseDown={event => event.stopPropagation()}>
        <header className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 px-6 py-5 dark:border-slate-800">
          <div className="min-w-0"><div className="text-[10px] font-bold tracking-wider text-indigo-600 dark:text-indigo-400">{target.kind === 'official' ? '官方内置领域包' : '企业自建领域包'} · 只读浏览</div><h2 className="mt-1 truncate text-lg font-bold text-slate-900 dark:text-white">{target.name}</h2><p className="mt-1 font-mono text-[10px] text-slate-400">{target.id} · v{target.version}</p></div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="关闭领域包浏览"><X className="h-5 w-5" /></button>
        </header>
        <div className="flex flex-col gap-3 border-b border-slate-100 px-6 pt-3 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between">
          <nav className="flex overflow-x-auto">{browserTabs.map(({ id, label, icon: Icon }) => <button key={id} type="button" onClick={() => setTab(id)} className={`flex shrink-0 items-center gap-1.5 border-b-2 px-4 py-3 text-xs font-bold ${tab === id ? 'border-indigo-600 text-indigo-600 dark:border-indigo-400 dark:text-indigo-400' : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-300'}`}><Icon className="h-4 w-4" />{label} ({assets[id].length})</button>)}</nav>
          <div className="relative mb-2 w-full sm:w-64"><Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索当前分类" className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-8 pr-3 text-xs outline-none focus:border-indigo-500 dark:border-slate-700 dark:bg-slate-950" /></div>
        </div>
        <main className="min-h-0 flex-1 overflow-y-auto p-6"><div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">{visible.map(asset => <button key={`${asset.source}-${asset.id}`} type="button" onClick={() => setSelectedAsset(asset)} className="min-h-32 rounded-xl border border-slate-100 p-4 text-left transition-colors hover:border-indigo-300 hover:bg-indigo-50/40 focus:outline-none focus:ring-2 focus:ring-indigo-200 dark:border-slate-800 dark:hover:border-indigo-800 dark:hover:bg-indigo-950/20"><div className="flex items-start justify-between gap-2"><h3 className="truncate text-xs font-bold text-slate-850 dark:text-white">{asset.name}</h3><span className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] font-bold ${asset.source === 'extension' ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300' : 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-300'}`}>{asset.source === 'extension' ? '扩建层' : '基础包'}</span></div><p className="mt-1 truncate font-mono text-[9px] text-slate-400">{asset.id}</p><p className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">{asset.description || '暂无描述。'}</p></button>)}</div>{visible.length === 0 && <div className="py-20 text-center text-sm text-slate-400">当前分类没有匹配的资产。</div>}</main>
      </div>
      {selectedAsset && <AssetDetailDialog asset={selectedAsset} onClose={() => setSelectedAsset(null)} />}
    </div>
  );
};

const ExtensionLayerManagerDialog: React.FC<{
  target: PackBrowserTarget;
  layer: PackExtensionLayer;
  onClose: () => void;
  onSave: (draft: EnterprisePackDraft) => Promise<void>;
  onLifecycle: (action: 'publish' | 'deactivate' | 'archive' | 'restore' | 'delete') => Promise<void>;
}> = ({ target, layer, onClose, onSave, onLifecycle }) => {
  const [tab, setTab] = useState<BrowserTab>('fields');
  const [draft, setDraft] = useState<EnterprisePackDraft>(layer.draft);
  const [assetId, setAssetId] = useState('');
  const [assetName, setAssetName] = useState('');
  const [assetDescription, setAssetDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const entries = tab === 'fields' ? draft.fields : tab === 'metrics' ? draft.metrics : tab === 'skills' ? draft.skills : draft.reports;
  const getEntry = (item: typeof entries, index: number) => {
    const entry = item[index];
    if (tab === 'fields') return { id: (entry as EnterprisePackDraft['fields'][number]).field_id, name: (entry as EnterprisePackDraft['fields'][number]).business_name, description: (entry as EnterprisePackDraft['fields'][number]).description || '' };
    if (tab === 'metrics') return { id: (entry as EnterprisePackDraft['metrics'][number]).metric_code, name: (entry as EnterprisePackDraft['metrics'][number]).name, description: (entry as EnterprisePackDraft['metrics'][number]).definition };
    if (tab === 'skills') return { id: (entry as EnterprisePackDraft['skills'][number]).skill_id, name: (entry as EnterprisePackDraft['skills'][number]).name, description: (entry as EnterprisePackDraft['skills'][number]).description || '' };
    return { id: (entry as EnterprisePackDraft['reports'][number]).report_id, name: (entry as EnterprisePackDraft['reports'][number]).name, description: (entry as EnterprisePackDraft['reports'][number]).description || '' };
  };
  const addAsset = () => {
    if (!assetId.trim() || !assetName.trim()) return;
    if (tab === 'fields') setDraft(current => ({ ...current, fields: [...current.fields, { field_id: assetId.trim(), business_name: assetName.trim(), data_type: 'string', description: assetDescription.trim() || null, entity_id: null, synonyms: [], source: 'extension' }] }));
    if (tab === 'metrics') setDraft(current => ({ ...current, metrics: [...current.metrics, { metric_code: assetId.trim(), name: assetName.trim(), definition: assetDescription.trim() || '待补充指标定义', formula: { expression: '0', filters: [] }, entity_id: null, synonyms: [], source: 'extension' }] }));
    if (tab === 'skills') setDraft(current => ({ ...current, skills: [...current.skills, { skill_id: assetId.trim(), name: assetName.trim(), description: assetDescription.trim() || null, steps: [] }] }));
    if (tab === 'reports') setDraft(current => ({ ...current, reports: [...current.reports, { report_id: assetId.trim(), name: assetName.trim(), description: assetDescription.trim() || null, metric_codes: [], skill_ids: [] }] }));
    setAssetId(''); setAssetName(''); setAssetDescription('');
  };
  const removeAsset = (index: number) => {
    if (tab === 'fields') setDraft(current => ({ ...current, fields: current.fields.filter((_, itemIndex) => itemIndex !== index) }));
    if (tab === 'metrics') setDraft(current => ({ ...current, metrics: current.metrics.filter((_, itemIndex) => itemIndex !== index) }));
    if (tab === 'skills') setDraft(current => ({ ...current, skills: current.skills.filter((_, itemIndex) => itemIndex !== index) }));
    if (tab === 'reports') setDraft(current => ({ ...current, reports: current.reports.filter((_, itemIndex) => itemIndex !== index) }));
  };
  const save = async () => { setSaving(true); try { await onSave(draft); } finally { setSaving(false); } };
  return (
    <div className="fixed inset-0 z-[85] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div className="flex h-[min(46rem,calc(100vh-2rem))] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900" onMouseDown={event => event.stopPropagation()}>
        <header className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-5 dark:border-slate-800"><div><div className="text-[10px] font-bold tracking-wider text-amber-700 dark:text-amber-300">扩建层 · {layer.state === 'active' ? '已启用' : layer.state === 'archived' ? '已归档' : '未启用'}</div><h2 className="mt-1 text-lg font-bold text-slate-900 dark:text-white">{target.name} 的扩建</h2><p className="mt-1 text-[10px] text-slate-400">固定基础版本 v{layer.base_pack_version} · 新增内容不会改写基础包</p></div><button type="button" onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="关闭扩建管理"><X className="h-5 w-5" /></button></header>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-6 pt-3 dark:border-slate-800"><nav className="flex overflow-x-auto">{browserTabs.map(({ id, label, icon: Icon }) => <button key={id} type="button" onClick={() => setTab(id)} className={`flex shrink-0 items-center gap-1.5 border-b-2 px-4 py-3 text-xs font-bold ${tab === id ? 'border-amber-500 text-amber-700 dark:border-amber-400 dark:text-amber-300' : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-300'}`}><Icon className="h-4 w-4" />{label}</button>)}</nav><div className="mb-2 flex gap-2">{layer.state === 'archived' ? <button type="button" onClick={() => void onLifecycle('restore')} className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-[10px] font-bold text-slate-650 dark:border-slate-700 dark:text-slate-300">恢复</button> : <><button type="button" onClick={() => void onLifecycle('publish')} className="rounded-lg bg-indigo-600 px-2.5 py-1.5 text-[10px] font-bold text-white hover:bg-indigo-700">发布并启用</button>{layer.state === 'active' && <button type="button" onClick={() => void onLifecycle('deactivate')} className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-[10px] font-bold text-slate-650 dark:border-slate-700 dark:text-slate-300">停用</button>}<button type="button" onClick={() => void onLifecycle('archive')} className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-[10px] font-bold text-slate-650 dark:border-slate-700 dark:text-slate-300">归档</button></>}</div></div>
        <main className="grid min-h-0 flex-1 grid-cols-1 gap-5 overflow-y-auto p-6 lg:grid-cols-[1fr_19rem]"><section className="space-y-3">{entries.length === 0 ? <div className="rounded-xl border border-dashed border-slate-200 p-10 text-center text-xs text-slate-400 dark:border-slate-800">尚未新增{browserTabs.find(item => item.id === tab)?.label}。</div> : entries.map((_, index) => { const entry = getEntry(entries, index); return <div key={entry.id} className="flex items-start justify-between gap-3 rounded-xl border border-slate-100 p-4 dark:border-slate-800"><div className="min-w-0"><h3 className="truncate text-xs font-bold text-slate-850 dark:text-white">{entry.name}</h3><p className="mt-1 truncate font-mono text-[10px] text-slate-400">{entry.id}</p><p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">{entry.description || '暂无描述。'}</p></div><button type="button" onClick={() => removeAsset(index)} className="shrink-0 rounded px-2 py-1 text-[10px] font-bold text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/20">移除</button></div>; })}</section><aside className="h-fit rounded-xl border border-amber-200 bg-amber-50/40 p-4 dark:border-amber-900 dark:bg-amber-950/10"><h3 className="text-xs font-bold text-slate-850 dark:text-white">新增{browserTabs.find(item => item.id === tab)?.label}</h3><p className="mt-1 text-[10px] leading-relaxed text-slate-500 dark:text-slate-400">新增资产可以引用基础包已有资源；基础包资产保持只读。</p><div className="mt-4 space-y-3"><input value={assetId} onChange={event => setAssetId(event.target.value)} placeholder="唯一标识" className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs outline-none focus:border-amber-500 dark:border-slate-700 dark:bg-slate-950" /><input value={assetName} onChange={event => setAssetName(event.target.value)} placeholder="名称" className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs outline-none focus:border-amber-500 dark:border-slate-700 dark:bg-slate-950" /><textarea value={assetDescription} onChange={event => setAssetDescription(event.target.value)} placeholder="业务说明" className="min-h-20 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs outline-none focus:border-amber-500 dark:border-slate-700 dark:bg-slate-950" /><button type="button" onClick={addAsset} className="w-full rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-bold text-amber-700 hover:bg-amber-50 dark:border-amber-900 dark:bg-slate-900 dark:text-amber-300">加入扩建层</button></div></aside></main>
        <footer className="flex items-center justify-between border-t border-slate-100 px-6 py-4 dark:border-slate-800"><button type="button" onClick={() => void onLifecycle('delete')} className="text-xs font-bold text-rose-600 hover:text-rose-700">删除扩建层</button><div className="flex gap-2"><button type="button" onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-bold text-slate-650 dark:border-slate-700 dark:text-slate-300">取消</button><button type="button" disabled={saving} onClick={() => void save()} className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-bold text-white hover:bg-indigo-700 disabled:opacity-60">{saving ? '保存中…' : '保存扩建内容'}</button></div></footer>
      </div>
    </div>
  );
};

export const PackProducts: React.FC<PackProductsProps> = ({
  metrics,
  skills,
  reports,
  userContext,
  onRefreshData,
  onPreviewMetric,
  onPreviewReport,
  onEditEnterprisePack,
  onOpenMounting,
  activeDataSourceId
}) => {
  const [selectedPack, setSelectedPack] = useState<string>('tms');
  const [activeSubTab, setActiveSubTab] = useState<'fields' | 'metrics' | 'skills' | 'reports'>('fields');
  const [searchQuery, setSearchQuery] = useState('');
  const [packListFilter, setPackListFilter] = useState<PackListFilter>('all');
  const [isPackDetailPanelOpen, setIsPackDetailPanelOpen] = useState(false);
  const [skillPreview, setSkillPreview] = useState<SkillDefinition | PackSkill | null>(null);
  const [officialPreview, setOfficialPreview] = useState<OfficialContentPreview | null>(null);
  const [browserTarget, setBrowserTarget] = useState<PackBrowserTarget | null>(null);
  const [browserTab, setBrowserTab] = useState<BrowserTab>('fields');
  const [openingExtension, setOpeningExtension] = useState<string | null>(null);
  const [deletingPackId, setDeletingPackId] = useState<string | null>(null);
  const [openedExtensionLayers, setOpenedExtensionLayers] = useState<Record<string, PackExtensionLayer>>({});
  const [effectiveContent, setEffectiveContent] = useState<EffectiveDomainPack | null>(null);
  const [managedExtension, setManagedExtension] = useState<{ target: PackBrowserTarget; layer: PackExtensionLayer } | null>(null);
  const [notice, setNotice] = useState<{ type: 'success' | 'error' | 'info'; message: string } | null>(null);
  const [showPackImport, setShowPackImport] = useState(false);
  const [packImportFile, setPackImportFile] = useState<File | null>(null);
  const [packImportPreview, setPackImportPreview] = useState<PackImportPreview | null>(null);
  const [packImportBusy, setPackImportBusy] = useState(false);

  // Enterprise packs states
  const [enterprisePacks, setEnterprisePacks] = useState<EnterprisePack[]>([]);
  const [loadingPacks, setLoadingPacks] = useState(false);

  // Semantic space adaptation modal state
  const [packDeployments, setPackDeployments] = useState<PackWithDeployments[]>([]);
  const [officialContent, setOfficialContent] = useState<OfficialPackContent | null>(null);
  const [adaptTarget, setAdaptTarget] = useState<{ id: string; name: string } | null>(null);

  // Wizard modal state
  const [showWizard, setShowWizard] = useState(false);
  const [wizardStep, setWizardStep] = useState<'mode' | 'config' | 'review'>('mode');
  const [wizardMode, setWizardMode] = useState<PackCreateMode | null>(null);
  
  // Wizard form state
  const [packName, setPackName] = useState('');
  const [packDesc, setPackDesc] = useState('');
  const [selectedOfficialBase, setSelectedOfficialBase] = useState<'tms' | 'wms'>('tms');
  const [selectedEnterpriseBase, setSelectedEnterpriseBase] = useState('');
  const [selectedDsId, setSelectedDsId] = useState('');
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  
  // Document Uploader state
  const [uploadingDoc, setUploadingDoc] = useState(false);
  const [uploadedDocs, setUploadedDocs] = useState<DataSourceDocument[]>([]);
  
  // AI Draft Review state
  const [generatingDraft, setGeneratingDraft] = useState(false);
  const [draftResult, setDraftResult] = useState<PackDraftResult | null>(null);
  
  // Review checkboxes
  const [selectedEntities, setSelectedEntities] = useState<Record<string, boolean>>({});
  const [selectedFields, setSelectedFields] = useState<Record<string, boolean>>({});
  const [selectedMetrics, setSelectedMetrics] = useState<Record<string, boolean>>({});
  const [selectedTerms, setSelectedTerms] = useState<Record<string, boolean>>({});
  const [selectedQuestions, setSelectedQuestions] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    setLoadingPacks(true);
    void Promise.all([
      api.listEnterprisePacks().catch(error => {
        console.error('获取企业包失败', error);
        return [] as EnterprisePack[];
      }),
      api.getDataSources().catch(error => {
        console.error('获取数据源失败', error);
        return [] as DataSource[];
      }),
      api.getAdminPacks().catch(error => {
        console.error('获取领域包适配状态失败', error);
        return [] as PackWithDeployments[];
      }),
    ]).then(([enterpriseList, sourceList, deploymentList]) => {
      if (cancelled) return;
      setEnterprisePacks(enterpriseList);
      setDataSources(sourceList);
      setPackDeployments(deploymentList);
      if (sourceList.length > 0) {
        setSelectedDsId(current => current || sourceList[0].data_source_id);
      }
    }).finally(() => {
      if (!cancelled) setLoadingPacks(false);
    });
    return () => { cancelled = true; };
  }, [activeDataSourceId]);

  useEffect(() => {
    if (!packDeployments.some(pack => pack.pack_id === selectedPack)) {
      setOfficialContent(null);
      return;
    }
    api.getPackContent(selectedPack)
      .then(setOfficialContent)
      .catch(error => {
        console.error('获取领域包真实内容失败', error);
        setOfficialContent(null);
      });
  }, [selectedPack, packDeployments]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const showNotice = (type: 'success' | 'error' | 'info', message: string) => {
    setNotice({ type, message });
  };

  async function fetchEnterprisePacks() {
    try {
      const list = await api.listEnterprisePacks();
      setEnterprisePacks(list);
    } catch (e) {
      console.error('获取企业包失败', e);
    }
  }

  async function fetchPackDeployments() {
    try {
      const list = await api.getAdminPacks();
      setPackDeployments(list);
    } catch (e) {
      console.error('获取领域包适配状态失败', e);
    }
  }

  // Filter OFFICIAL assets for the selected official pack. Enterprise pack
  // selection is handled from its own versioned draft below.
  const normalizedSearch = searchQuery.trim().toLowerCase();
  const officialPackSummaries = packDeployments.map(backendPack => {
    const builtIn = OFFICIAL_PACKS.find(item => item.id === backendPack.pack_id);
    return {
      id: backendPack.pack_id,
      name: backendPack.name || builtIn?.name || backendPack.pack_id,
      description: backendPack.description || builtIn?.description || '通过领域包文件安装的标准分析资产包。',
      version: `v${backendPack.pack_version}`,
      industry: builtIn?.industry || backendPack.tags?.[0] || '外部领域包',
      distributionSource: backendPack.distribution_source || 'built_in',
      fieldCount: backendPack.standard_field_count || 0,
      metricCount: backendPack.metric_count || 0,
      skillCount: backendPack.skill_count || 0,
      reportCount: backendPack.report_count || 0
    };
  });
  const filteredOfficialPacks = officialPackSummaries.filter(pack => {
    if (packListFilter === 'enterprise') return false;
    if (!normalizedSearch) return true;
    return [pack.id, pack.name, pack.description, pack.industry]
      .some(value => value.toLowerCase().includes(normalizedSearch));
  });
  const filteredEnterprisePacks = enterprisePacks.filter(pack => {
    // Extension layers are owned by a base card and never become cards.
    if (pack.create_mode === 'extend_official' || pack.base_pack_id) return false;
    if (packListFilter === 'official') return false;
    if (!normalizedSearch) return true;
    return [
      pack.pack_id,
      pack.name,
      pack.description || '',
      pack.base_pack_id || '',
      pack.create_mode
    ].some(value => String(value).toLowerCase().includes(normalizedSearch));
  });
  const totalVisiblePacks = filteredOfficialPacks.length + filteredEnterprisePacks.length;
  const selectedOfficialSummary = officialPackSummaries.find(pack => pack.id === selectedPack);
  const selectedOfficialId = selectedOfficialSummary?.id;
  const officialMetrics = selectedOfficialId
    ? metrics.filter(metric => metric.visibility === 'official' && (metric.metric_code.startsWith(selectedOfficialId) || officialContent?.metrics.some(item => item.metric_code === metric.metric_code)))
    : [];
  const officialSkills = selectedOfficialId
    ? skills.filter(skill => skill.visibility === 'official' && (skill.namespace === selectedOfficialId || skill.skill_id.startsWith(selectedOfficialId)))
    : [];
  const officialReports = selectedOfficialId
    ? reports.filter(report => report.visibility === 'official' && report.report_id.startsWith(selectedOfficialId))
    : [];
  const selectedEnterprisePack = enterprisePacks.find(pack => pack.pack_id === selectedPack);

  const browserAssets = (): Record<BrowserTab, BrowserAsset[]> => {
    const fromRecord = (type: BrowserTab, items: Array<Record<string, unknown>>, source: 'base' | 'extension' = 'base'): BrowserAsset[] => items.map((item, index) => ({
      id: String(item.field_id || item.metric_code || item.skill_id || item.report_id || item.report_skill_id || index),
      name: String(item.business_name || item.name || item.metric_code || item.skill_id || item.report_id || '未命名资产'),
      description: String(item.description || item.definition || '暂无描述。'),
      type,
      source,
      definition: item,
    }));
    if (effectiveContent && effectiveContent.base_pack_id === browserTarget?.id) {
      const resolved = effectiveContent;
      const fromEffective = (type: BrowserTab, items: EffectiveDomainPack['fields']): BrowserAsset[] => items.map(asset => ({
        id: asset.asset_id,
        name: asset.name,
        description: asText(asset.definition.description, asText(asset.definition.definition, '暂无描述。')),
        type,
        source: asset.source,
        definition: asset.definition,
      }));
      return {
        fields: fromEffective('fields', resolved.fields),
        metrics: fromEffective('metrics', resolved.metrics),
        skills: fromEffective('skills', resolved.skills),
        reports: fromEffective('reports', resolved.reports),
      };
    }
    if (browserTarget?.kind === 'official' && officialContent) {
      return {
        fields: officialContent.standard_fields.map(field => ({ id: field.field_id, name: field.business_name, description: field.description || '暂无描述。', type: 'fields', source: 'base', definition: { ...field } })),
        metrics: fromRecord('metrics', officialContent.metrics),
        skills: fromRecord('skills', officialContent.skills),
        reports: fromRecord('reports', officialContent.reports),
      };
    }
    const enterprise = enterprisePacks.find(pack => pack.pack_id === browserTarget?.id);
    const extension = enterprise?.extension_layer;
    const additions = extension?.state === 'active' ? extension.draft : null;
    return {
      fields: [...(enterprise?.draft.fields || []), ...(additions?.fields || [])].map((field, index) => ({ id: field.field_id, name: field.business_name, description: field.description || '暂无描述。', type: 'fields', source: index >= (enterprise?.draft.fields.length || 0) ? 'extension' : 'base', definition: { ...field } })),
      metrics: [...(enterprise?.draft.metrics || []), ...(additions?.metrics || [])].map((metric, index) => ({ id: metric.metric_code, name: metric.name, description: metric.definition, type: 'metrics', source: index >= (enterprise?.draft.metrics.length || 0) ? 'extension' : 'base', definition: { ...metric } })),
      skills: [...(enterprise?.draft.skills || []), ...(additions?.skills || [])].map((skill, index) => ({ id: skill.skill_id, name: skill.name, description: skill.description || '暂无描述。', type: 'skills', source: index >= (enterprise?.draft.skills.length || 0) ? 'extension' : 'base', definition: { ...skill } })),
      reports: [...(enterprise?.draft.reports || []), ...(additions?.reports || [])].map((report, index) => ({ id: report.report_id, name: report.name, description: report.description || '暂无描述。', type: 'reports', source: index >= (enterprise?.draft.reports.length || 0) ? 'extension' : 'base', definition: { ...report } })),
    };
  };

  const getPackActivation = (packId: string) => {
    const officialDeployments = packDeployments.find(pack => pack.pack_id === packId)?.deployments || [];
    const enterpriseDeployments = enterprisePacks.find(pack => pack.pack_id === packId)?.deployments || [];
    const deployments = officialDeployments.length > 0 ? officialDeployments : enterpriseDeployments;
    const activeDeployment = deployments.find(deployment => deployment.is_active);
    const readyDeployment = deployments.find(deployment => deployment.validation_status === 'ready');
    return {
      isActive: Boolean(activeDeployment),
      deployment: activeDeployment || readyDeployment || deployments[0],
      deploymentCount: deployments.length,
    };
  };
  const getExtensionLayer = (packId: string) => openedExtensionLayers[packId] || enterprisePacks.find(pack => pack.pack_id === packId)?.extension_layer || null;
  const selectedActivation = getPackActivation(selectedPack);
  const selectedPackDetail = selectedOfficialSummary
    ? {
        name: selectedOfficialSummary.name,
        description: selectedOfficialSummary.description,
        sourceLabel: selectedOfficialSummary.distributionSource === 'imported' ? '文件导入' : '官方内置',
        fields: selectedOfficialSummary.fieldCount,
        metrics: selectedOfficialSummary.metricCount,
        skills: selectedOfficialSummary.skillCount,
        reports: selectedOfficialSummary.reportCount,
      }
    : selectedEnterprisePack
      ? {
          name: selectedEnterprisePack.name,
          description: selectedEnterprisePack.description || '暂无详细描述。',
          sourceLabel: '企业自建',
          fields: selectedEnterprisePack.draft.fields.length,
          metrics: selectedEnterprisePack.draft.metrics.length,
          skills: selectedEnterprisePack.draft.skills.length,
          reports: selectedEnterprisePack.draft.reports.length,
        }
      : null;

  const openBrowser = (target: PackBrowserTarget, tab: BrowserTab = 'fields') => {
    setSelectedPack(target.id);
    setBrowserTab(tab);
    setBrowserTarget(target);
    setEffectiveContent(null);
    void api.getEffectivePackContent(target.id, target.kind).then(setEffectiveContent).catch(() => {
      // Backwards-compatible servers still provide the base content endpoint.
    });
  };

  const openExtension = async (target: PackBrowserTarget) => {
    setOpeningExtension(target.id);
    try {
      const layer = await api.openPackExtensionLayer(target.id, { base_kind: target.kind, created_by: userContext.user_id });
      setOpenedExtensionLayers(current => ({ ...current, [target.id]: layer }));
      setManagedExtension({ target, layer });
      await fetchEnterprisePacks();
      showNotice('success', `已${layer.created_at ? '创建' : '打开'}「${target.name}」的扩建层。扩建内容仅作为该领域包的增量，不会生成新的领域包卡片。`);
    } catch (error) {
      showNotice('error', `打开扩建层失败：${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setOpeningExtension(null);
    }
  };

  const handleDeleteEnterprisePack = async (pack: EnterprisePack) => {
    if (!await confirmAction(`确认删除企业自建领域包“${pack.name}”吗？此操作会删除该包的草稿和历史版本，且无法撤销。`)) return;
    setDeletingPackId(pack.pack_id);
    try {
      await api.deleteEnterprisePack(pack.pack_id);
      if (selectedPack === pack.pack_id) setSelectedPack('tms');
      await fetchEnterprisePacks();
      await fetchPackDeployments();
      showNotice('success', `已删除“${pack.name}”。`);
    } catch (error) {
      showNotice('error', error instanceof Error ? error.message : '删除领域包失败。');
    } finally {
      setDeletingPackId(null);
    }
  };

  const handleDeriveToCustom = async (assetType: 'metric' | 'skill' | 'report', assetId: string) => {
    try {
      if (assetType === 'metric') {
        await api.copyMetric(assetId, { user_id: userContext.user_id });
        showNotice('success', '已将官方指标另存到您的个人资产，可前往「资产中心」继续编辑。');
      } else if (assetType === 'skill') {
        await api.copySkill(assetId, { user_id: userContext.user_id });
        showNotice('success', '已将官方技能另存到您的个人资产，可前往「资产中心」继续编辑。');
      } else if (assetType === 'report') {
        await api.copyReport(assetId, { user_id: userContext.user_id });
        showNotice('success', '已将官方报表另存到您的个人资产，可前往「资产中心」继续修改。');
      }
      await onRefreshData();
    } catch (e) {
      showNotice('error', '另存副本失败：' + (e instanceof Error ? e.message : '未知错误'));
    }
  };

  // File Upload Handler for Grounding Documents
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selectedDsId) return;
    setUploadingDoc(true);
    try {
      const doc = await api.uploadDataSourceDocument(selectedDsId, file);
      setUploadedDocs(prev => [...prev, doc]);
    } catch (err) {
      showNotice('error', '上传文档失败：' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setUploadingDoc(false);
    }
  };

  // Submit AI Draft Request
  const handleGenerateAIDraft = async () => {
    if (!selectedDsId) return;
    setGeneratingDraft(true);
    try {
      const result = await api.draftEnterprisePack({
        data_source_id: selectedDsId,
        document_ids: uploadedDocs.map(d => d.document_id),
        user_id: userContext.user_id
      });
      setDraftResult(result);
      
      // Initialize checkboxes
      const entitiesInit: Record<string, boolean> = {};
      result.draft.entities.forEach(e => { entitiesInit[e.entity_id] = true; });
      setSelectedEntities(entitiesInit);

      const fieldsInit: Record<string, boolean> = {};
      result.draft.fields.forEach(f => { fieldsInit[f.field_id] = true; });
      setSelectedFields(fieldsInit);

      const metricsInit: Record<string, boolean> = {};
      result.draft.metrics.forEach(m => { metricsInit[m.metric_code] = true; });
      setSelectedMetrics(metricsInit);

      const termsInit: Record<string, boolean> = {};
      result.draft.terms.forEach(t => { termsInit[t.term_id] = true; });
      setSelectedTerms(termsInit);

      const questionsInit: Record<string, boolean> = {};
      result.draft.acceptance_questions.forEach(q => { questionsInit[q.question_id] = true; });
      setSelectedQuestions(questionsInit);

      setWizardStep('review');
    } catch (err) {
      showNotice('error', 'AI 草稿生成失败：' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setGeneratingDraft(false);
    }
  };

  // Finalize Pack Creation
  const handleCreatePack = async () => {
    if (!packName.trim()) {
      showNotice('info', '请填写企业领域包名称。');
      return;
    }
    try {
      if (wizardMode !== 'extend_official' && wizardMode !== 'blank') {
        showNotice('error', '请选择“扩展官方领域包”或“空白新建”。');
        return;
      }
      const selectedBase = OFFICIAL_PACKS.find(pack => pack.id === selectedOfficialBase);
      const basePackId = wizardMode === 'extend_official' ? selectedOfficialBase : null;

      // 1. Create the pack metadata
      const newPack = await api.createEnterprisePack({
        name: packName,
        description: packDesc,
        mode: wizardMode,
        base_pack_id: basePackId,
        base_pack_version: wizardMode === 'extend_official' ? selectedBase?.version ?? null : null,
        created_by: userContext.user_id
      });

      setShowWizard(false);
      // Reset form
      setPackName('');
      setPackDesc('');
      setUploadedDocs([]);
      setDraftResult(null);
      
      // Refresh list and open editor
      await fetchEnterprisePacks();
      // Fetch latest metadata to get the full draft pack
      const fullPack = await api.getEnterprisePack(newPack.pack_id);
      onEditEnterprisePack(fullPack);
    } catch (err) {
      showNotice('error', '创建企业包失败：' + (err instanceof Error ? err.message : '未知错误'));
    }
  };

  const handleStartBlankPack = () => {
    onEditEnterprisePack({
      pack_id: '__new__',
      name: '',
      description: '',
      version: '0.1.0',
      version_state: 'draft',
      base_pack_id: null,
      base_pack_version: null,
      create_mode: 'blank',
      draft: {
        entities: [], fields: [], metrics: [], skills: [], reports: [], terms: [], acceptance_questions: []
      },
      created_by: userContext.user_id,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    });
  };

  const handlePackImportFile = async (file: File | null) => {
    setPackImportFile(file);
    setPackImportPreview(null);
    if (!file) return;
    setPackImportBusy(true);
    try {
      setPackImportPreview(await api.previewPackImport(file));
    } catch (error) {
      showNotice('error', `领域包校验失败：${error instanceof Error ? error.message : '文件不可用'}`);
    } finally {
      setPackImportBusy(false);
    }
  };

  const handleConfirmPackImport = async () => {
    if (!packImportFile || !packImportPreview?.can_import) return;
    setPackImportBusy(true);
    try {
      const imported = await api.importPack(packImportFile);
      await fetchPackDeployments();
      await onRefreshData();
      setSelectedPack(imported.pack_id);
      setShowPackImport(false);
      setPackImportFile(null);
      setPackImportPreview(null);
      showNotice('success', `领域包“${imported.name}”已导入，等待适配语义空间。`);
    } catch (error) {
      showNotice('error', `领域包导入失败：${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setPackImportBusy(false);
    }
  };

  return (
    <ManagementPage>
      {notice && (
        <div
          role="status"
          aria-live="polite"
          className={`fixed top-5 right-5 z-[80] max-w-sm rounded-xl border px-4 py-3 shadow-xl backdrop-blur-sm flex items-start gap-2.5 text-xs ${
            notice.type === 'success'
              ? 'bg-emerald-50/95 dark:bg-emerald-950/95 border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300'
              : notice.type === 'error'
                ? 'bg-rose-50/95 dark:bg-rose-950/95 border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-300'
                : 'bg-indigo-50/95 dark:bg-indigo-950/95 border-indigo-200 dark:border-indigo-800 text-indigo-800 dark:text-indigo-300'
          }`}
        >
          {notice.type === 'error' ? <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" /> : <Check className="w-4 h-4 shrink-0 mt-0.5" />}
          <span className="leading-relaxed font-medium">{notice.message}</span>
          <button type="button" onClick={() => setNotice(null)} className="ml-1 opacity-60 hover:opacity-100" aria-label="关闭提示">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
      <ManagementHeader
        icon={<Package className="w-5 h-5 text-indigo-500" />}
        title="领域包管理"
        description="管理官方内置包和企业自建包，并从包卡片发起语义空间适配。"
        actions={<>
          <ActionButton
            type="button"
            onClick={() => setShowPackImport(true)}
          >
            <UploadCloud className="h-3.5 w-3.5" />导入领域包
          </ActionButton>
          <ActionButton
            variant="primary"
            type="button"
            onClick={handleStartBlankPack}
          >
            <span className="text-base leading-none">+</span> 新建领域包
          </ActionButton>
        </>}
      />

      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
        <div className="relative w-full lg:max-w-sm">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="搜索领域包名称、说明或 ID"
            className="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950 pl-9 pr-3 py-2 text-xs outline-none focus:border-indigo-500"
          />
        </div>
        <div className="flex items-center gap-1.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50/80 dark:bg-slate-900/40 p-1">
          {[
            { id: 'all', label: `全部 (${officialPackSummaries.length + enterprisePacks.length})` },
            { id: 'official', label: `官方内置 (${officialPackSummaries.length})` },
            { id: 'enterprise', label: `企业自建 (${enterprisePacks.length})` }
          ].map(item => (
            <button
              key={item.id}
              type="button"
              onClick={() => setPackListFilter(item.id as PackListFilter)}
              className={`px-3 py-1.5 rounded-md text-xs font-bold transition-colors ${
                packListFilter === item.id
                  ? 'bg-white dark:bg-slate-800 text-indigo-650 dark:text-indigo-400 shadow-sm'
                  : 'text-slate-500 hover:text-slate-750 dark:hover:text-slate-300'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {loadingPacks ? (
        <div className="py-12 text-center text-slate-400">
          <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-indigo-500" />
          加载领域包列表中...
        </div>
      ) : totalVisiblePacks === 0 ? (
        <div className="border border-dashed border-slate-200 dark:border-slate-800 rounded-xl p-10 text-center text-slate-400 bg-slate-50/30 dark:bg-slate-900/10">
          <Package className="w-8 h-8 mx-auto mb-3 text-slate-300 dark:text-slate-700" />
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">没有匹配的领域包</p>
          <p className="text-xs mt-1">调整搜索词或筛选条件后重试。</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {filteredOfficialPacks.map(pack => (
            <div
              key={pack.id}
              role="button"
              tabIndex={0}
              onClick={() => setSelectedPack(pack.id)}
              onKeyDown={event => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  setSelectedPack(pack.id);
                }
              }}
              className={`relative border rounded-xl p-4 shadow-sm transition-colors h-[226px] flex flex-col cursor-pointer ${
                selectedPack === pack.id
                  ? 'border-indigo-300 bg-indigo-50/45 dark:border-indigo-800 dark:bg-indigo-950/15'
                  : 'bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 hover:border-slate-350 dark:hover:border-slate-700'
              }`}
            >
              <div className="absolute top-4 right-4 flex items-center gap-1">
                <span className={`px-1.5 py-0.5 rounded border text-[9px] font-bold ${
                  getPackActivation(pack.id).isActive
                    ? 'border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/20 text-emerald-650 dark:text-emerald-400'
                    : 'border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-500 dark:text-slate-400'
                }`}>{getPackActivation(pack.id).isActive ? '已激活' : '未激活'}</span>
                <span className="px-1.5 py-0.5 rounded border border-indigo-200 dark:border-indigo-900 bg-indigo-50 dark:bg-indigo-950/20 text-indigo-650 dark:text-indigo-400 text-[9px] font-bold">{pack.distributionSource === 'imported' ? '文件导入' : '官方内置'}</span>
                {getExtensionLayer(pack.id) && <span className="px-1.5 py-0.5 rounded border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/20 text-amber-700 dark:text-amber-300 text-[9px] font-bold">{getExtensionLayer(pack.id)?.state === 'active' ? '扩建已启用' : '有扩建层'}</span>}
              </div>
              <div className="flex items-start justify-between gap-3 min-h-[82px]">
                <div className="min-w-0 space-y-1 overflow-hidden pr-20">
                  <div className="min-w-0">
                    <h3 title={pack.name} className="font-bold text-sm text-slate-900 dark:text-white truncate">{pack.name}</h3>
                  </div>
                  <p title={pack.description} className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2 min-h-[32px]">{pack.description}</p>
                  <div className="flex items-center gap-2 text-[10px] text-slate-400 overflow-hidden whitespace-nowrap">
                    <span className="font-mono truncate">{pack.id}</span>
                    <span>{pack.version}</span>
                    <span>{pack.industry}</span>
                  </div>
                </div>
              </div>

              <div className="mt-3 grid grid-cols-4 gap-2 text-center text-[10px]">
                <div className="rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-100 dark:border-slate-800 py-1.5">
                  <div className="font-bold text-slate-850 dark:text-slate-200">{pack.fieldCount}</div>
                  <div className="text-slate-400">字段</div>
                </div>
                <div className="rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-100 dark:border-slate-800 py-1.5">
                  <div className="font-bold text-slate-850 dark:text-slate-200">{pack.metricCount}</div>
                  <div className="text-slate-400">指标</div>
                </div>
                <div className="rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-100 dark:border-slate-800 py-1.5">
                  <div className="font-bold text-slate-850 dark:text-slate-200">{pack.skillCount}</div>
                  <div className="text-slate-400">Skill</div>
                </div>
                <div className="rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-100 dark:border-slate-800 py-1.5">
                  <div className="font-bold text-slate-850 dark:text-slate-200">{pack.reportCount}</div>
                  <div className="text-slate-400">报表</div>
                </div>
              </div>

              <div className="mt-auto pt-3 border-t border-slate-100 dark:border-slate-800 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={event => {
                    event.stopPropagation();
                    void openExtension({ id: pack.id, name: pack.name, version: pack.version.replace(/^v/, ''), kind: 'official' });
                  }}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-750 text-slate-650 dark:text-slate-300 text-xs font-bold hover:bg-slate-50 dark:hover:bg-slate-850"
                >
                  {openingExtension === pack.id ? '打开中…' : getExtensionLayer(pack.id) ? '管理扩建' : '扩建'}
                </button>
                <button
                  type="button"
                  onClick={event => {
                    event.stopPropagation();
                    openBrowser({ id: pack.id, name: pack.name, version: pack.version.replace(/^v/, ''), kind: 'official' });
                  }}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-750 text-slate-650 dark:text-slate-300 text-xs font-bold hover:bg-slate-50 dark:hover:bg-slate-850"
                >
                  浏览
                </button>
                <button
                  type="button"
                  onClick={event => {
                    event.stopPropagation();
                    setAdaptTarget({ id: pack.id, name: pack.name });
                  }}
                  className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold"
                >
                  适配语义空间
                </button>
              </div>
            </div>
          ))}

          {filteredEnterprisePacks.map(pack => (
            <div
              key={pack.pack_id}
              role="button"
              tabIndex={0}
              onClick={() => setSelectedPack(pack.pack_id)}
              onKeyDown={event => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  setSelectedPack(pack.pack_id);
                }
              }}
              className={`relative border rounded-xl p-4 shadow-sm transition-colors h-[226px] flex flex-col cursor-pointer ${
                selectedPack === pack.pack_id
                  ? 'border-indigo-300 bg-indigo-50/45 dark:border-indigo-800 dark:bg-indigo-950/15'
                  : 'bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 hover:border-slate-350 dark:hover:border-slate-700'
              }`}
            >
              <div className="flex items-start justify-between gap-3 min-h-[82px]">
                <div className="min-w-0 space-y-1 overflow-hidden pr-28">
                  <h3 title={pack.name} className="font-bold text-sm text-slate-900 dark:text-white truncate">{pack.name}</h3>
                  <p title={pack.description || '暂无详细描述。'} className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2 min-h-[32px]">{pack.description || '暂无详细描述。'}</p>
                  <div className="flex items-center gap-2 text-[10px] text-slate-400 overflow-hidden whitespace-nowrap">
                    <span className="font-mono truncate">{pack.pack_id}</span>
                    <span>v{pack.version}</span>
                    <span>
                      {pack.create_mode === 'extend_official' && `扩展自 ${pack.base_pack_id}`}
                      {pack.create_mode === 'clone_enterprise' && '旧版草稿（待迁移）'}
                      {pack.create_mode === 'ai_from_profile' && '旧版草稿（待迁移）'}
                      {pack.create_mode === 'blank' && '空白创建'}
                    </span>
                  </div>
                </div>
              </div>

              <div className="absolute top-4 right-4 flex items-center gap-1">
                <span className={`px-1.5 py-0.5 rounded border text-[9px] font-bold ${
                  getPackActivation(pack.pack_id).isActive
                    ? 'border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/20 text-emerald-650 dark:text-emerald-400'
                    : 'border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-500 dark:text-slate-400'
                }`}>{getPackActivation(pack.pack_id).isActive ? '已激活' : '未激活'}</span>
                <span className="px-1.5 py-0.5 rounded border border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/20 text-emerald-650 dark:text-emerald-400 text-[9px] font-bold">企业自建</span>
                {getExtensionLayer(pack.pack_id) && <span className="px-1.5 py-0.5 rounded border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/20 text-amber-700 dark:text-amber-300 text-[9px] font-bold">{getExtensionLayer(pack.pack_id)?.state === 'active' ? '扩建已启用' : '有扩建层'}</span>}
              </div>

              <div className="mt-3 grid grid-cols-4 gap-2 text-center text-[10px]">
                <div className="rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-100 dark:border-slate-800 py-1.5">
                  <div className="font-bold text-slate-850 dark:text-slate-200">{pack.draft.fields.length}</div>
                  <div className="text-slate-400">字段</div>
                </div>
                <div className="rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-100 dark:border-slate-800 py-1.5">
                  <div className="font-bold text-slate-850 dark:text-slate-200">{pack.draft.metrics.length}</div>
                  <div className="text-slate-400">指标</div>
                </div>
                <div className="rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-100 dark:border-slate-800 py-1.5">
                  <div className="font-bold text-slate-850 dark:text-slate-200">{pack.draft.skills.length}</div>
                  <div className="text-slate-400">技能</div>
                </div>
                <div className="rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-100 dark:border-slate-800 py-1.5">
                  <div className="font-bold text-slate-850 dark:text-slate-200">{pack.draft.reports.length}</div>
                  <div className="text-slate-400">报表</div>
                </div>
              </div>

              <div className="mt-auto pt-3 border-t border-slate-100 dark:border-slate-800 flex justify-end gap-2">
                <button
                  type="button"
                  disabled={deletingPackId === pack.pack_id}
                  onClick={event => {
                    event.stopPropagation();
                    void handleDeleteEnterprisePack(pack);
                  }}
                  title="删除企业自建领域包"
                  className="mr-auto inline-flex items-center gap-1 rounded-lg border border-rose-200 px-2.5 py-1.5 text-xs font-bold text-rose-600 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-900 dark:text-rose-400 dark:hover:bg-rose-950/20"
                >
                  <Trash2 className="h-3.5 w-3.5" /> {deletingPackId === pack.pack_id ? '删除中…' : '删除'}
                </button>
                <button
                  type="button"
                  onClick={event => {
                    event.stopPropagation();
                    onEditEnterprisePack(pack);
                  }}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-750 text-slate-650 dark:text-slate-300 text-xs font-bold hover:bg-slate-50 dark:hover:bg-slate-850"
                >
                  修改
                </button>
                <button
                  type="button"
                  onClick={event => {
                    event.stopPropagation();
                    void openExtension({ id: pack.pack_id, name: pack.name, version: pack.version, kind: 'enterprise' });
                  }}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-750 text-slate-650 dark:text-slate-300 text-xs font-bold hover:bg-slate-50 dark:hover:bg-slate-850"
                >
                  {openingExtension === pack.pack_id ? '打开中…' : getExtensionLayer(pack.pack_id) ? '管理扩建' : '扩建'}
                </button>
                <button
                  type="button"
                  onClick={event => {
                    event.stopPropagation();
                    openBrowser({ id: pack.pack_id, name: pack.name, version: pack.version, kind: 'enterprise' }, 'metrics');
                  }}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-750 text-slate-650 dark:text-slate-300 text-xs font-bold hover:bg-slate-50 dark:hover:bg-slate-850"
                >
                  浏览
                </button>
                <button
                  type="button"
                  onClick={event => {
                    event.stopPropagation();
                    setAdaptTarget({ id: pack.pack_id, name: pack.name });
                  }}
                  className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold"
                >
                  适配语义空间
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {isPackDetailPanelOpen && selectedPackDetail && (
        <aside className="fixed right-5 top-24 z-40 w-[min(22rem,calc(100vw-2.5rem))] rounded-2xl border border-slate-200 dark:border-slate-750 bg-white/95 dark:bg-slate-900/95 p-5 shadow-2xl backdrop-blur">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className={`rounded border px-1.5 py-0.5 text-[9px] font-bold ${selectedActivation.isActive ? 'border-emerald-200 bg-emerald-50 text-emerald-650 dark:border-emerald-900 dark:bg-emerald-950/20 dark:text-emerald-400' : 'border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400'}`}>{selectedActivation.isActive ? '已激活' : '未激活'}</span>
                <span className="text-[10px] font-bold text-slate-400">{selectedPackDetail.sourceLabel}</span>
              </div>
              <h3 className="mt-2 truncate text-sm font-bold text-slate-900 dark:text-white">{selectedPackDetail.name}</h3>
              <p className="mt-1.5 line-clamp-3 text-xs leading-relaxed text-slate-500 dark:text-slate-400">{selectedPackDetail.description}</p>
            </div>
            <button type="button" onClick={() => setIsPackDetailPanelOpen(false)} className="shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="关闭领域包详情"><X className="h-4 w-4" /></button>
          </div>
          <div className="mt-4 grid grid-cols-4 gap-2 text-center text-[10px]">
            {[
              ['字段', selectedPackDetail.fields],
              ['指标', selectedPackDetail.metrics],
              ['技能', selectedPackDetail.skills],
              ['报表', selectedPackDetail.reports],
            ].map(([label, count]) => (
              <div key={label} className="rounded-lg border border-slate-100 bg-slate-50/70 py-2 dark:border-slate-800 dark:bg-slate-950/40"><div className="font-bold text-slate-850 dark:text-slate-200">{count}</div><div className="mt-0.5 text-slate-400">{label}</div></div>
            ))}
          </div>
          <div className="mt-4 border-t border-slate-100 pt-3 text-[11px] text-slate-500 dark:border-slate-800 dark:text-slate-400">
            {selectedActivation.deployment
              ? <>适配：{selectedActivation.deployment.data_source_id} · 覆盖率 {Math.round(selectedActivation.deployment.coverage * 100)}%</>
              : '尚未创建适配实例'}
          </div>
          <div className="mt-3 flex flex-wrap justify-end gap-2">
            {selectedActivation.deployment && onOpenMounting && (
              <button type="button" onClick={() => onOpenMounting(selectedActivation.deployment!.deployment_id)} className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-[10px] font-bold text-slate-650 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800">部署详情</button>
            )}
            <button type="button" onClick={() => document.getElementById('pack-asset-details')?.scrollIntoView({ behavior: 'smooth', block: 'start' })} className="rounded-lg bg-indigo-600 px-2.5 py-1.5 text-[10px] font-bold text-white hover:bg-indigo-700">浏览全部资产</button>
          </div>
        </aside>
      )}

      {/* Official Pack Content: loaded from the selected backend pack, never from mock arrays. */}
      {showLegacyAssetPanels && selectedOfficialSummary && officialContent && (
        <div id="pack-asset-details" className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden shadow-sm">
          <div className="bg-slate-50/50 dark:bg-slate-900/50 border-b border-slate-150 dark:border-slate-800 px-5 flex flex-wrap justify-between items-center text-xs font-bold">
            <div className="flex overflow-x-auto">
              {([
                ['fields', `标准字段 (${officialContent.standard_fields.length})`, Database],
                ['metrics', `官方指标 (${officialContent.metrics.length})`, BookOpen],
                ['skills', `官方技能 (${officialContent.skills.length})`, Cpu],
                ['reports', `官方报表 (${officialContent.reports.length})`, FileText],
              ] as const).map(([tab, label, Icon]) => (
                <button
                  key={tab}
                  onClick={() => setActiveSubTab(tab)}
                  className={`px-4 py-3 border-b-2 flex items-center gap-1.5 whitespace-nowrap ${activeSubTab === tab ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400' : 'border-transparent text-slate-500'}`}
                >
                  <Icon className="w-4 h-4" />{label}
                </button>
              ))}
            </div>
            <span className="text-[10px] font-mono text-slate-400">{officialContent.name} · v{officialContent.version}</span>
          </div>
          <div className="p-5">
            {activeSubTab === 'fields' ? (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {officialContent.standard_fields.map(field => (
                  <button
                    type="button"
                    key={field.field_id}
                    onClick={() => setOfficialPreview({
                      kind: 'field',
                      title: field.business_name,
                      id: field.field_id,
                      description: field.description || '暂无描述',
                      payload: { ...field },
                    })}
                    className="h-28 rounded-xl border border-slate-100 dark:border-slate-800 p-4 overflow-hidden text-left hover:border-indigo-250 hover:bg-indigo-50/35 dark:hover:border-indigo-900 dark:hover:bg-indigo-950/15 transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-200"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <h4 className="text-xs font-bold text-slate-850 dark:text-white truncate">{field.business_name}</h4>
                      {field.required && <span className="text-[9px] text-rose-500 shrink-0">必填</span>}
                    </div>
                    <p className="mt-1 text-[9px] font-mono text-slate-400 truncate">{field.field_id} · {field.data_type}</p>
                    <p className="mt-2 text-[11px] text-slate-500 line-clamp-2">{field.description || '暂无描述'}</p>
                  </button>
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {(activeSubTab === 'metrics' ? officialContent.metrics : activeSubTab === 'skills' ? officialContent.skills : officialContent.reports).map((item, index) => {
                  const id = String(item.metric_code || item.skill_id || item.report_skill_id || index);
                  const name = String(item.name || id);
                  const description = String(item.definition || item.description || '暂无描述');
                  return (
                    <div
                      key={id}
                      role={activeSubTab === 'skills' ? undefined : 'button'}
                      tabIndex={activeSubTab === 'skills' ? undefined : 0}
                      onClick={() => {
                        if (activeSubTab === 'skills') return;
                        setOfficialPreview({
                          kind: activeSubTab === 'metrics' ? 'metric' : 'report',
                          title: name,
                          id,
                          description,
                          payload: item,
                        });
                      }}
                      onKeyDown={event => {
                        if (activeSubTab === 'skills' || (event.key !== 'Enter' && event.key !== ' ')) return;
                        event.preventDefault();
                        setOfficialPreview({
                          kind: activeSubTab === 'metrics' ? 'metric' : 'report',
                          title: name,
                          id,
                          description,
                          payload: item,
                        });
                      }}
                      className={`min-h-36 border border-slate-100 dark:border-slate-800 rounded-xl p-4 flex flex-col justify-between overflow-hidden transition-colors ${activeSubTab === 'skills' ? '' : 'cursor-pointer hover:border-indigo-250 hover:bg-indigo-50/35 dark:hover:border-indigo-900 dark:hover:bg-indigo-950/15 focus:outline-none focus:ring-2 focus:ring-indigo-200'}`}
                    >
                      <div className="min-w-0">
                        <div className="flex justify-between items-start gap-2">
                          <h4 className="font-bold text-slate-850 dark:text-white text-xs truncate">{name}</h4>
                          <span className="px-1.5 py-0.5 rounded text-[8px] font-bold bg-indigo-50 dark:bg-indigo-950/20 text-indigo-650 dark:text-indigo-400 shrink-0">官方发布</span>
                        </div>
                        <p className="mt-2 text-[9px] font-mono text-slate-400 truncate">{id}</p>
                        <p className="mt-2 text-[11px] text-slate-555 dark:text-slate-400 line-clamp-2">{description}</p>
                      </div>
                      <div className="mt-3 border-t border-slate-50 pt-3 text-[10px] text-slate-400 dark:border-slate-800">官方资产可直接用于问数与报表，不在领域包管理中另存或编辑。</div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Legacy official asset view retained only for compatibility with older payloads. */}
      {Boolean(import.meta.env.VITE_LEGACY_PACK_VIEW) && selectedOfficialSummary && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden shadow-sm">
          <div className="bg-slate-50/50 dark:bg-slate-900/50 border-b border-slate-150 dark:border-slate-800 px-5 flex justify-between items-center text-xs font-bold">
            <div className="flex">
              <button 
                onClick={() => setActiveSubTab('metrics')}
                className={`px-4 py-3 border-b-2 flex items-center gap-1.5 transition-all ${
                  activeSubTab === 'metrics'
                    ? 'border-indigo-600 text-indigo-600 dark:border-indigo-400 dark:text-indigo-400'
                    : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-350'
                }`}
              >
                <BookOpen className="w-4 h-4" />
                官方指标 ({officialMetrics.length})
              </button>
              <button 
                onClick={() => setActiveSubTab('skills')}
                className={`px-4 py-3 border-b-2 flex items-center gap-1.5 transition-all ${
                  activeSubTab === 'skills'
                    ? 'border-indigo-600 text-indigo-600 dark:border-indigo-400 dark:text-indigo-400'
                    : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-350'
                }`}
              >
                <Cpu className="w-4 h-4" />
                官方报表技能 ({officialSkills.length})
              </button>
              <button 
                onClick={() => setActiveSubTab('reports')}
                className={`px-4 py-3 border-b-2 flex items-center gap-1.5 transition-all ${
                  activeSubTab === 'reports'
                    ? 'border-indigo-600 text-indigo-600 dark:border-indigo-400 dark:text-indigo-400'
                    : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-350'
                }`}
              >
                <FileText className="w-4 h-4" />
                官方内置报表 ({officialReports.length})
              </button>
            </div>
            <span className="text-[10px] font-mono text-slate-400">
              {selectedOfficialSummary.name}
            </span>
          </div>

          <div className="p-5">
            {activeSubTab === 'metrics' && (
              <div className="space-y-4">
                {officialMetrics.length === 0 ? (
                  <div className="py-8 text-center text-xs text-slate-400 italic">本领域包暂无内置官方指标。</div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {officialMetrics.map(metric => (
                      <div key={getAssetIdentity(metric, metric.metric_code)} className="border border-slate-100 dark:border-slate-800 rounded-xl p-4 space-y-3 flex flex-col justify-between hover:border-slate-200 dark:hover:border-slate-700 transition-colors">
                        <div className="space-y-2">
                          <div className="flex justify-between items-start gap-2">
                            <h4 className="font-bold text-slate-850 dark:text-white text-xs">{metric.name}</h4>
                            <span className="px-1.5 py-0.5 rounded text-[8px] font-bold bg-indigo-50 dark:bg-indigo-950/20 text-indigo-650 dark:text-indigo-400">官方发布</span>
                          </div>
                          <span className="text-[9px] font-mono text-slate-400 break-all bg-slate-50 dark:bg-slate-950 px-1.5 py-0.5 rounded inline-block">{metric.metric_code}</span>
                          <p className="text-[11px] text-slate-555 dark:text-slate-400 leading-normal line-clamp-2">{metric.definition}</p>
                        </div>
                        <div className="flex justify-end gap-2 pt-2 border-t border-slate-50 dark:border-slate-850">
                          <button 
                            onClick={() => onPreviewMetric(metric)}
                            className="px-2.5 py-1.5 rounded bg-slate-50 hover:bg-slate-100 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-650 dark:text-slate-350 text-[10px] font-bold flex items-center gap-0.5"
                          >
                            <Eye className="w-3 h-3" /> 预览口径
                          </button>
                          <button 
                            onClick={() => handleDeriveToCustom('metric', metric.metric_code)}
                            className="px-2.5 py-1.5 rounded bg-indigo-605 text-white hover:bg-indigo-700 text-[10px] font-bold flex items-center gap-0.5"
                          >
                            <Copy className="w-3 h-3" /> 另存为我的指标
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeSubTab === 'skills' && (
              <div className="space-y-4">
                {officialSkills.length === 0 ? (
                  <div className="py-8 text-center text-xs text-slate-400 italic">本领域包暂无内置官方技能。</div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {officialSkills.map(skill => (
                      <div key={getAssetIdentity(skill, skill.skill_id)} className="border border-slate-100 dark:border-slate-800 rounded-xl p-4 space-y-3 flex flex-col justify-between hover:border-slate-200 dark:hover:border-slate-700 transition-colors">
                        <div className="space-y-2">
                          <div className="flex justify-between items-start gap-2">
                            <h4 className="font-bold text-slate-855 dark:text-white text-xs">{skill.name}</h4>
                            <span className="px-1.5 py-0.5 rounded text-[8px] font-bold bg-indigo-50 dark:bg-indigo-950/20 text-indigo-650 dark:text-indigo-400">官方发布</span>
                          </div>
                          <span className="text-[9px] font-mono text-slate-400 break-all bg-slate-50 dark:bg-slate-950 px-1.5 py-0.5 rounded inline-block">{skill.skill_id}</span>
                          <p className="text-[11px] text-slate-555 dark:text-slate-400 leading-normal line-clamp-2">{skill.description}</p>
                        </div>
                        <div className="flex justify-end gap-2 pt-2 border-t border-slate-50 dark:border-slate-855">
                          <button 
                            onClick={() => setSkillPreview(skill)}
                            className="px-2.5 py-1.5 rounded bg-slate-50 hover:bg-slate-100 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-650 dark:text-slate-350 text-[10px] font-bold flex items-center gap-0.5"
                          >
                            <Eye className="w-3 h-3" /> 预览结构
                          </button>
                          <button 
                            onClick={() => handleDeriveToCustom('skill', skill.skill_id)}
                            className="px-2.5 py-1.5 rounded bg-indigo-600 text-white hover:bg-indigo-700 text-[10px] font-bold flex items-center gap-0.5 shadow-sm"
                          >
                            <Copy className="w-3 h-3" /> 另存为我的技能
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeSubTab === 'reports' && (
              <div className="space-y-4">
                {officialReports.length === 0 ? (
                  <div className="py-8 text-center text-xs text-slate-400 italic">本领域包暂无内置官方报表。</div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {officialReports.map(report => (
                      <div key={getAssetIdentity(report, report.report_id)} className="border border-slate-100 dark:border-slate-800 rounded-xl p-4 space-y-3 flex flex-col justify-between hover:border-slate-200 dark:hover:border-slate-700 transition-colors">
                        <div className="space-y-2">
                          <div className="flex justify-between items-start gap-2">
                            <h4 className="font-bold text-slate-855 dark:text-white text-xs">{report.name}</h4>
                            <span className="px-1.5 py-0.5 rounded text-[8px] font-bold bg-indigo-50 dark:bg-indigo-950/20 text-indigo-650 dark:text-indigo-400">官方发布</span>
                          </div>
                          <span className="text-[9px] font-mono text-slate-400 break-all bg-slate-50 dark:bg-slate-950 px-1.5 py-0.5 rounded inline-block">{report.report_id}</span>
                          <p className="text-[11px] text-slate-555 dark:text-slate-400 leading-normal line-clamp-2">{report.description}</p>
                        </div>
                        <div className="flex justify-end gap-2 pt-2 border-t border-slate-50 dark:border-slate-855">
                          <button 
                            onClick={() => onPreviewReport(report)}
                            className="px-2.5 py-1.5 rounded bg-slate-50 hover:bg-slate-100 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-650 dark:text-slate-350 text-[10px] font-bold flex items-center gap-0.5"
                          >
                            <Eye className="w-3 h-3" /> 预览大纲
                          </button>
                          <button 
                            onClick={() => handleDeriveToCustom('report', report.report_id)}
                            className="px-2.5 py-1.5 rounded bg-indigo-605 text-white hover:bg-indigo-700 text-[10px] font-bold flex items-center gap-0.5"
                          >
                            <Copy className="w-3 h-3" /> 另存为我的报表
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Enterprise pack content follows the selected enterprise card. */}
      {showLegacyAssetPanels && selectedEnterprisePack && (
        <div id="pack-asset-details" className="bg-white dark:bg-slate-900 border border-indigo-200 dark:border-indigo-900 rounded-xl overflow-hidden shadow-sm">
          <div className="bg-slate-50/50 dark:bg-slate-900/50 border-b border-slate-150 dark:border-slate-800 px-5 flex justify-between items-center text-xs font-bold">
            <div className="flex">
              {([
                ['metrics', `企业指标 (${selectedEnterprisePack.draft.metrics.length})`, BookOpen],
                ['skills', `企业 Skill (${selectedEnterprisePack.draft.skills.length})`, Cpu],
                ['reports', `企业报表 (${selectedEnterprisePack.draft.reports.length})`, FileText]
              ] as const).map(([tab, label, Icon]) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setActiveSubTab(tab)}
                  className={`px-4 py-3 border-b-2 flex items-center gap-1.5 transition-all ${
                    activeSubTab === tab
                      ? 'border-indigo-600 text-indigo-600 dark:border-indigo-400 dark:text-indigo-400'
                      : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-300'
                  }`}
                >
                  <Icon className="w-4 h-4" /> {label}
                </button>
              ))}
            </div>
            <span title={selectedEnterprisePack.name} className="text-[10px] font-mono text-slate-400 truncate max-w-[220px]">
              {selectedEnterprisePack.name} · v{selectedEnterprisePack.version}
            </span>
          </div>

          <div className="p-5">
            {activeSubTab === 'metrics' && (
              selectedEnterprisePack.draft.metrics.length === 0
                ? <div className="py-8 text-center text-xs text-slate-400 italic">该企业领域包暂无指标。</div>
                : <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {selectedEnterprisePack.draft.metrics.map(metric => (
                      <div key={metric.metric_code} className="border border-slate-100 dark:border-slate-800 rounded-xl p-4 min-h-[142px] flex flex-col">
                        <div className="min-w-0">
                          <h4 title={metric.name} className="font-bold text-xs text-slate-850 dark:text-white truncate">{metric.name}</h4>
                          <div title={metric.metric_code} className="mt-1 text-[9px] font-mono text-slate-400 truncate">{metric.metric_code}</div>
                          <p title={metric.definition} className="mt-2 text-[11px] text-slate-555 dark:text-slate-400 line-clamp-2">{metric.definition}</p>
                        </div>
                        <div className="mt-auto pt-2 text-[9px] text-slate-400 truncate">来源：{metric.source}</div>
                      </div>
                    ))}
                  </div>
            )}
            {activeSubTab === 'skills' && (
              selectedEnterprisePack.draft.skills.length === 0
                ? <div className="py-8 text-center text-xs text-slate-400 italic">该企业领域包暂无 Skill。</div>
                : <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {selectedEnterprisePack.draft.skills.map(skill => (
                      <div key={skill.skill_id} className="border border-slate-100 dark:border-slate-800 rounded-xl p-4 min-h-[142px] flex flex-col">
                        <h4 title={skill.name} className="font-bold text-xs text-slate-850 dark:text-white truncate">{skill.name}</h4>
                        <div title={skill.skill_id} className="mt-1 text-[9px] font-mono text-slate-400 truncate">{skill.skill_id}</div>
                        <p title={skill.description || ''} className="mt-2 text-[11px] text-slate-555 dark:text-slate-400 line-clamp-2">{skill.description || '暂无描述。'}</p>
                        <button type="button" onClick={() => setSkillPreview(skill)} className="mt-auto self-end px-2.5 py-1.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-[10px] font-bold flex items-center gap-1">
                          <Eye className="w-3 h-3" /> 预览结构
                        </button>
                      </div>
                    ))}
                  </div>
            )}
            {activeSubTab === 'reports' && (
              selectedEnterprisePack.draft.reports.length === 0
                ? <div className="py-8 text-center text-xs text-slate-400 italic">该企业领域包暂无报表。</div>
                : <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {selectedEnterprisePack.draft.reports.map(report => (
                      <div key={report.report_id} className="border border-slate-100 dark:border-slate-800 rounded-xl p-4 min-h-[142px] flex flex-col">
                        <h4 title={report.name} className="font-bold text-xs text-slate-850 dark:text-white truncate">{report.name}</h4>
                        <div title={report.report_id} className="mt-1 text-[9px] font-mono text-slate-400 truncate">{report.report_id}</div>
                        <p title={report.description || ''} className="mt-2 text-[11px] text-slate-555 dark:text-slate-400 line-clamp-2">{report.description || '暂无描述。'}</p>
                        <div className="mt-auto pt-2 text-[9px] text-slate-400">指标 {report.metric_codes.length} · Skill {report.skill_ids.length}</div>
                      </div>
                    ))}
                  </div>
            )}
          </div>
        </div>
      )}

      {officialPreview && (
        <OfficialContentPreviewModal
          preview={officialPreview}
          onClose={() => setOfficialPreview(null)}
        />
      )}

      {skillPreview && (
        <div className="fixed inset-0 z-[70] bg-slate-900/50 dark:bg-slate-950/70 backdrop-blur-sm flex items-center justify-center p-4" onMouseDown={() => setSkillPreview(null)}>
          <div className="w-full max-w-2xl max-h-[82vh] overflow-y-auto rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-2xl" onMouseDown={event => event.stopPropagation()}>
            <div className="sticky top-0 bg-white/95 dark:bg-slate-900/95 backdrop-blur border-b border-slate-100 dark:border-slate-800 px-5 py-4 flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="text-[10px] font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">Skill 结构</div>
                <h3 className="mt-1 font-bold text-base text-slate-900 dark:text-white truncate">{skillPreview.name}</h3>
                <div className="mt-1 text-[10px] font-mono text-slate-400 truncate">{skillPreview.skill_id}</div>
              </div>
              <button type="button" onClick={() => setSkillPreview(null)} className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="关闭结构预览"><X className="w-4 h-4" /></button>
            </div>
            <div className="p-5 space-y-5 text-xs">
              <section>
                <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">用途说明</h4>
                <p className="leading-relaxed text-slate-700 dark:text-slate-300">{skillPreview.description || '暂无描述。'}</p>
              </section>
              {'steps' in skillPreview ? (
                <section>
                  <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">执行步骤</h4>
                  <div className="space-y-2">
                    {skillPreview.steps.length === 0 && <div className="text-slate-400">暂无步骤。</div>}
                    {skillPreview.steps.map((step, index) => (
                      <div key={step.step_id} className="rounded-lg border border-slate-100 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-950/50 p-3">
                        <div className="font-bold text-slate-800 dark:text-slate-200">{index + 1}. {step.description}</div>
                        <div className="mt-1.5 text-[10px] text-slate-500">指标：{step.metric_codes.join(', ') || '无'} · 维度：{step.dimension_field_ids.join(', ') || '无'}</div>
                      </div>
                    ))}
                  </div>
                </section>
              ) : (
                <>
                  <section>
                    <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">输入参数</h4>
                    <div className="space-y-2">
                      {skillPreview.parameters.length === 0 && <div className="text-slate-400">无需参数。</div>}
                      {skillPreview.parameters.map(parameter => (
                        <div key={parameter.name} className="rounded-lg border border-slate-100 dark:border-slate-800 p-3 flex justify-between gap-4">
                          <div><span className="font-mono font-bold text-slate-800 dark:text-slate-200">{parameter.name}</span><p className="mt-1 text-[10px] text-slate-500">{parameter.description || '暂无说明'}</p></div>
                          <span className="shrink-0 text-[10px] text-indigo-600 dark:text-indigo-400">{parameter.data_type}{parameter.required ? ' · 必填' : ' · 可选'}</span>
                        </div>
                      ))}
                    </div>
                  </section>
                  <section>
                    <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">输出结构</h4>
                    <pre className="rounded-lg bg-slate-950 text-slate-200 p-3 overflow-x-auto text-[10px] leading-relaxed">{JSON.stringify(skillPreview.output_schema || {}, null, 2)}</pre>
                  </section>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {browserTarget && (
        <DomainPackBrowserDialog
          target={browserTarget}
          assets={browserAssets()}
          initialTab={browserTab}
          onClose={() => setBrowserTarget(null)}
        />
      )}

      {managedExtension && (
        <ExtensionLayerManagerDialog
          target={managedExtension.target}
          layer={managedExtension.layer}
          onClose={() => setManagedExtension(null)}
          onSave={async draft => {
            const layer = await api.updatePackExtensionLayer(managedExtension.layer.extension_id, { draft });
            setOpenedExtensionLayers(current => ({ ...current, [managedExtension.target.id]: layer }));
            setManagedExtension(current => current ? { ...current, layer } : null);
            showNotice('success', '扩建层内容已保存。');
          }}
          onLifecycle={async action => {
            if (action === 'delete') {
              await api.deletePackExtensionLayer(managedExtension.layer.extension_id);
              setOpenedExtensionLayers(current => {
                const next = { ...current };
                delete next[managedExtension.target.id];
                return next;
              });
              setManagedExtension(null);
              showNotice('success', '扩建层已删除，基础领域包未受影响。');
              return;
            }
            const layer = await api.transitionPackExtensionLayer(managedExtension.layer.extension_id, action);
            setOpenedExtensionLayers(current => ({ ...current, [managedExtension.target.id]: layer }));
            setManagedExtension(current => current ? { ...current, layer } : null);
            showNotice('success', `扩建层已${action === 'publish' ? '发布并启用' : action === 'deactivate' ? '停用' : action === 'archive' ? '归档' : '恢复'}。`);
          }}
        />
      )}

      {showPackImport && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm" onMouseDown={() => !packImportBusy && setShowPackImport(false)}>
          <div className="w-full max-w-2xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900" onMouseDown={event => event.stopPropagation()}>
            <header className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-5 dark:border-slate-800">
              <div>
                <div className="flex items-center gap-2 text-base font-bold text-slate-900 dark:text-white"><UploadCloud className="h-5 w-5 text-indigo-500" />导入领域包</div>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">安装标准字段、指标、技能和报表定义；不会导入数据库凭据或激活状态。</p>
              </div>
              <button type="button" disabled={packImportBusy} onClick={() => setShowPackImport(false)} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 disabled:opacity-50 dark:hover:bg-slate-800" aria-label="关闭导入"><X className="h-4 w-4" /></button>
            </header>
            <div className="space-y-4 p-6">
              <label className="flex min-h-36 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50/60 px-5 text-center hover:border-indigo-400 hover:bg-indigo-50/30 dark:border-slate-700 dark:bg-slate-950/40 dark:hover:border-indigo-700">
                <UploadCloud className="h-7 w-7 text-indigo-500" />
                <span className="mt-2 text-xs font-bold text-slate-700 dark:text-slate-200">{packImportFile?.name || '选择领域包文件'}</span>
                <span className="mt-1 text-[10px] text-slate-400">支持 .sqbipack、.zip、.tar.gz、.tgz，最大 20 MB</span>
                <input type="file" accept=".sqbipack,.zip,.tar,.tar.gz,.tgz,application/zip,application/gzip" className="hidden" disabled={packImportBusy} onChange={event => void handlePackImportFile(event.target.files?.[0] || null)} />
              </label>

              {packImportBusy && !packImportPreview && <div className="flex items-center justify-center gap-2 py-4 text-xs text-indigo-600"><RefreshCw className="h-4 w-4 animate-spin" />正在检查领域包结构与资产引用…</div>}

              {packImportPreview && (
                <div className={`rounded-xl border p-4 ${packImportPreview.can_import ? 'border-emerald-200 bg-emerald-50/40 dark:border-emerald-900 dark:bg-emerald-950/10' : 'border-rose-200 bg-rose-50/50 dark:border-rose-900 dark:bg-rose-950/10'}`}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <h3 className="truncate text-sm font-bold text-slate-900 dark:text-white">{packImportPreview.name}</h3>
                      <p className="mt-1 truncate font-mono text-[10px] text-slate-400">{packImportPreview.pack_id} · v{packImportPreview.version}</p>
                      <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-600 dark:text-slate-300">{packImportPreview.description || '暂无领域包说明。'}</p>
                    </div>
                    <span className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-bold ${packImportPreview.can_import ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300' : 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300'}`}>{packImportPreview.can_import ? '校验通过' : '存在冲突'}</span>
                  </div>
                  <div className="mt-4 grid grid-cols-4 gap-2 text-center text-[10px]">
                    {[['字段', packImportPreview.standard_field_count], ['指标', packImportPreview.metric_count], ['Skill', packImportPreview.skill_count], ['报表', packImportPreview.report_count]].map(([label, count]) => <div key={String(label)} className="rounded-lg border border-white/80 bg-white/70 px-2 py-2 dark:border-slate-800 dark:bg-slate-900"><div className="font-bold text-slate-800 dark:text-slate-200">{count}</div><div className="text-slate-400">{label}</div></div>)}
                  </div>
                  {packImportPreview.conflict && <div className="mt-3 rounded-lg border border-rose-200 bg-white/70 px-3 py-2 text-xs text-rose-700 dark:border-rose-900 dark:bg-slate-900 dark:text-rose-300">{packImportPreview.conflict}</div>}
                  {packImportPreview.warnings.map(warning => <p key={warning} className="mt-3 text-[10px] text-slate-500 dark:text-slate-400">提示：{warning}</p>)}
                </div>
              )}
            </div>
            <footer className="flex items-center justify-end gap-2 border-t border-slate-100 px-6 py-4 dark:border-slate-800">
              <button type="button" disabled={packImportBusy} onClick={() => setShowPackImport(false)} className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-bold text-slate-600 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300">取消</button>
              <button type="button" disabled={packImportBusy || !packImportPreview?.can_import} onClick={() => void handleConfirmPackImport()} className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-bold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-40">{packImportBusy ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <UploadCloud className="h-3.5 w-3.5" />}{packImportBusy ? '正在导入…' : '确认导入'}</button>
            </footer>
          </div>
        </div>
      )}

      {/* Creation Wizard Dialog */}
      {showWizard && (
        <div className="fixed inset-0 bg-slate-900/50 dark:bg-slate-950/70 backdrop-blur-xs flex items-center justify-center z-50 p-4 animate-fade-in">
          <div className="bg-white dark:bg-slate-900 border border-slate-205 dark:border-slate-800 rounded-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto shadow-2xl flex flex-col justify-between p-6">
            
            {/* Wizard Header */}
            <div className="flex justify-between items-center pb-4 border-b border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-indigo-500 animate-pulse" />
                <h3 className="font-bold text-slate-900 dark:text-white text-base">
                  {wizardStep === 'mode' && '选择创建模式'}
                  {wizardStep === 'config' && '配置基本信息'}
                  {wizardStep === 'review' && LEGACY_CREATION_MODES && '审核 AI 建议草稿'}
                </h3>
              </div>
              <button onClick={() => setShowWizard(false)} className="text-slate-400 hover:text-slate-650"><X className="w-5 h-5" /></button>
            </div>

            {/* Step Content */}
            <div className="py-6 flex-1">
              
              {/* Step 1: Mode Select */}
              {wizardStep === 'mode' && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {[
                    { id: 'extend_official' as const, name: '扩展官方领域包', desc: '固定引用一个官方领域包版本；官方内容保持只读，仅编辑企业新增内容。', icon: Package },
                    { id: 'blank' as const, name: '空白新建', desc: '从空白逻辑模板建立标准字段、指标、技能和报表；创建时不关联数据库。', icon: Plus }
                  ].map(mode => (
                    <div 
                      key={mode.id}
                      onClick={() => {
                        setWizardMode(mode.id);
                        setWizardStep('config');
                      }}
                      className="border border-slate-200 dark:border-slate-800 hover:border-indigo-500 dark:hover:border-indigo-400 hover:bg-indigo-50/5 p-4 rounded-xl cursor-pointer transition-all flex gap-3 text-left active:scale-[0.99]"
                    >
                      <div className="bg-indigo-50 dark:bg-indigo-950/20 p-2.5 rounded-lg shrink-0 h-10 w-10 flex items-center justify-center">
                        <mode.icon className="w-5 h-5 text-indigo-500" />
                      </div>
                      <div className="space-y-1">
                        <h4 className="font-bold text-xs text-slate-800 dark:text-white">{mode.name}</h4>
                        <p className="text-[10px] text-slate-400 dark:text-gray-450 leading-relaxed">{mode.desc}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Step 2: Config Form */}
              {wizardStep === 'config' && (
                <form onSubmit={(e) => {
                  e.preventDefault();
                  if (LEGACY_CREATION_MODES && wizardMode === 'ai_from_profile') {
                    void handleGenerateAIDraft();
                    return;
                  }
                  void handleCreatePack();
                }} className="space-y-5 text-xs text-left">
                  <div className="space-y-1">
                    <label className="block font-bold text-slate-700 dark:text-slate-300">分析包名称</label>
                    <input 
                      type="text" 
                      required
                      value={packName}
                      onChange={e => setPackName(e.target.value)}
                      placeholder="e.g. 物流域运费对账包"
                      className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-800 dark:text-slate-250 outline-none focus:border-indigo-500 focus:bg-white transition-all"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="block font-bold text-slate-700 dark:text-slate-300">包描述信息</label>
                    <textarea 
                      value={packDesc}
                      onChange={e => setPackDesc(e.target.value)}
                      placeholder="选填，描述该分析包主要服务的业务场景及包含的资产范围..."
                      className="w-full px-3 py-2 min-h-[64px] bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-800 dark:text-slate-250 outline-none focus:border-indigo-500 focus:bg-white transition-all"
                    />
                  </div>

                  {/* Mode Specific Configs */}
                  {wizardMode === 'extend_official' && (
                    <div className="space-y-1">
                      <label className="block font-bold text-slate-700 dark:text-slate-300">选择基础官方包</label>
                      <select 
                        value={selectedOfficialBase}
                        onChange={e => setSelectedOfficialBase(e.target.value as 'tms' | 'wms')}
                        className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-800 dark:text-slate-250 outline-none"
                      >
                        <option value="tms">TMS 运输管理系统领域包 v1.0.0</option>
                        <option value="wms">WMS 智能仓储系统领域包 v1.2.0</option>
                      </select>
                    </div>
                  )}

                  {LEGACY_CREATION_MODES && wizardMode === 'clone_enterprise' && (
                    <div className="space-y-1">
                      <label className="block font-bold text-slate-700 dark:text-slate-300">选择要复制的源分析包</label>
                      <select 
                        value={selectedEnterpriseBase}
                        onChange={e => setSelectedEnterpriseBase(e.target.value)}
                        required
                        className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-800 dark:text-slate-250 outline-none"
                      >
                        <option value="">-- 请选择要克隆的分析包 --</option>
                        {enterprisePacks.map(p => (
                          <option key={p.pack_id} value={p.pack_id}>{p.name} (v{p.version})</option>
                        ))}
                      </select>
                    </div>
                  )}

                  {LEGACY_CREATION_MODES && (wizardMode === 'ai_from_profile' || wizardMode === 'blank') && (
                    <div className="space-y-1">
                      <label className="block font-bold text-slate-700 dark:text-slate-300">关联数据源</label>
                      <select 
                        value={selectedDsId}
                        onChange={e => setSelectedDsId(e.target.value)}
                        required
                        className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-800 dark:text-slate-250 outline-none"
                      >
                        {dataSources.map(ds => (
                          <option key={ds.data_source_id} value={ds.data_source_id}>{ds.name} ({ds.data_source_id})</option>
                        ))}
                      </select>
                    </div>
                  )}

                  {/* Grounding documents uploader for AI mode */}
                  {LEGACY_CREATION_MODES && wizardMode === 'ai_from_profile' && (
                    <div className="space-y-2 border-t border-slate-100 dark:border-slate-800 pt-4">
                      <label className="block font-bold text-slate-700 dark:text-slate-300">上传建模背景文档 (Grounding Documents)</label>
                      <p className="text-[10px] text-slate-400 dark:text-gray-450 mb-2">
                        上传企业自身的口径文档、数据手册或业务问数指引，AI 将充分参考以建立高准确率的语义指标口径。
                      </p>
                      
                      {/* Upload box */}
                      <div className="border border-dashed border-slate-200 dark:border-slate-800 rounded-xl p-4 bg-slate-50/40 dark:bg-slate-900/30 text-center relative hover:bg-slate-50 dark:hover:bg-slate-900/50 transition-colors">
                        <input 
                          type="file" 
                          id="pack-doc-file"
                          onChange={handleFileUpload}
                          className="hidden" 
                        />
                        <label htmlFor="pack-doc-file" className="cursor-pointer block space-y-2">
                          <UploadCloud className="w-6 h-6 text-slate-400 mx-auto" />
                          <div className="text-[11px] text-slate-500 font-semibold">
                            {uploadingDoc ? '正在上传及内省...' : '点击或拖拽文件上传背景文档'}
                          </div>
                          <span className="text-[9px] text-slate-400 font-mono block">支持 PDF, DOCX, CSV 或 Markdown 文件</span>
                        </label>
                      </div>

                      {/* Uploaded Documents List */}
                      {uploadedDocs.length > 0 && (
                        <div className="space-y-1.5 mt-2">
                          {uploadedDocs.map(doc => (
                            <div key={doc.document_id} className="flex justify-between items-center bg-indigo-50/30 dark:bg-indigo-950/20 border border-indigo-100/50 dark:border-indigo-950/60 p-2.5 rounded-lg text-[10px] font-medium text-slate-700 dark:text-slate-300">
                              <div className="flex items-center gap-1.5 truncate">
                                <FileText className="w-3.5 h-3.5 text-indigo-500 shrink-0" />
                                <span className="truncate">{doc.filename}</span>
                              </div>
                              <button 
                                type="button"
                                onClick={() => setUploadedDocs(prev => prev.filter(d => d.document_id !== doc.document_id))}
                                className="text-slate-400 hover:text-red-500"
                              >
                                <X className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Navigation Buttons */}
                  <div className="flex justify-between items-center border-t border-slate-100 dark:border-slate-800 pt-4 mt-6">
                    <button 
                      type="button" 
                      onClick={() => setWizardStep('mode')}
                      className="px-4 py-2 border border-slate-200 dark:border-slate-700 rounded-lg font-bold text-slate-550 dark:text-slate-400"
                    >
                      返回上一步
                    </button>
                    <button 
                      type="submit"
                      disabled={!wizardMode || generatingDraft}
                      className="bg-indigo-600 hover:bg-indigo-700 text-white font-bold px-5 py-2 rounded-lg flex items-center gap-1.5 shadow-md transition-all active:scale-[0.98]"
                    >
                      确认创建领域包
                    </button>
                  </div>
                </form>
              )}

              {/* Step 3: AI Draft Review */}
              {LEGACY_CREATION_MODES && wizardStep === 'review' && draftResult && (
                <div className="space-y-6 text-xs text-left max-h-[50vh] overflow-y-auto pr-1">
                  <div className="bg-indigo-50/20 dark:bg-indigo-950/10 border border-indigo-100 dark:border-indigo-900 rounded-xl p-4 space-y-2">
                    <div className="flex items-center gap-1.5 text-indigo-650 dark:text-indigo-400 font-bold">
                      <Sparkles className="w-4 h-4" />
                      AI 智能建模建议已生成
                    </div>
                    <p className="text-[10px] text-slate-500 dark:text-slate-400 leading-relaxed">
                      系统已通过深度扫描数据源语义并结合上传的口径文档，为您规划了以下口径资产。您可以勾选想要导入的项目。
                    </p>
                  </div>

                  {/* Review lists per category */}
                  <div className="space-y-5">
                    
                    {/* Entities Review */}
                    {draftResult.draft.entities.length > 0 && (
                      <div className="space-y-2">
                        <h4 className="font-bold text-slate-700 dark:text-slate-300 border-b pb-1">1. 业务实体建模 (Entities)</h4>
                        <div className="space-y-1.5">
                          {draftResult.draft.entities.map(ent => (
                            <label key={ent.entity_id} className="flex items-start gap-2.5 p-2 rounded bg-slate-50 dark:bg-slate-800/40 hover:bg-slate-100/50 cursor-pointer">
                              <input 
                                type="checkbox"
                                checked={!!selectedEntities[ent.entity_id]}
                                onChange={e => setSelectedEntities(p => ({ ...p, [ent.entity_id]: e.target.checked }))}
                                className="mt-0.5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                              />
                              <div>
                                <span className="font-bold text-slate-800 dark:text-white">{ent.name}</span>
                                <span className="ml-2 font-mono text-[9px] text-slate-400">{ent.entity_id} ({ent.physical_table})</span>
                                <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-0.5">{ent.description}</p>
                              </div>
                            </label>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Fields Review */}
                    {draftResult.draft.fields.length > 0 && (
                      <div className="space-y-2">
                        <h4 className="font-bold text-slate-700 dark:text-slate-300 border-b pb-1">2. 企业字段体系 (Fields)</h4>
                        <div className="space-y-1.5">
                          {draftResult.draft.fields.map(field => (
                            <label key={field.field_id} className="flex items-start gap-2.5 p-2 rounded bg-slate-50 dark:bg-slate-800/40 hover:bg-slate-100/50 cursor-pointer">
                              <input 
                                type="checkbox"
                                checked={!!selectedFields[field.field_id]}
                                onChange={e => setSelectedFields(p => ({ ...p, [field.field_id]: e.target.checked }))}
                                className="mt-0.5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                              />
                              <div>
                                <span className="font-bold text-slate-800 dark:text-white">{field.business_name}</span>
                                <span className="ml-2 font-mono text-[9px] text-slate-400">{field.field_id} ({field.physical_table}.{field.physical_column})</span>
                                <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-0.5">{field.description}</p>
                              </div>
                            </label>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Metrics Review */}
                    {draftResult.draft.metrics.length > 0 && (
                      <div className="space-y-2">
                        <h4 className="font-bold text-slate-700 dark:text-slate-300 border-b pb-1">3. 业务指标定义 (Metrics)</h4>
                        <div className="space-y-1.5">
                          {draftResult.draft.metrics.map(met => (
                            <label key={met.metric_code} className="flex items-start gap-2.5 p-2 rounded bg-slate-50 dark:bg-slate-800/40 hover:bg-slate-100/50 cursor-pointer">
                              <input 
                                type="checkbox"
                                checked={!!selectedMetrics[met.metric_code]}
                                onChange={e => setSelectedMetrics(p => ({ ...p, [met.metric_code]: e.target.checked }))}
                                className="mt-0.5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                              />
                              <div>
                                <span className="font-bold text-slate-800 dark:text-white">{met.name}</span>
                                <span className="ml-2 font-mono text-[9px] text-slate-400">{met.metric_code}</span>
                                <pre className="bg-slate-100 dark:bg-slate-900 px-2 py-1 rounded font-mono text-[9px] text-slate-500 mt-1">{met.formula.expression}</pre>
                                <p className="text-[10px] text-slate-555 dark:text-slate-400 mt-1">{met.definition}</p>
                              </div>
                            </label>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Terms Review */}
                    {draftResult.draft.terms.length > 0 && (
                      <div className="space-y-2">
                        <h4 className="font-bold text-slate-700 dark:text-slate-300 border-b pb-1">4. 业务同义词与术语 (Business Terms)</h4>
                        <div className="space-y-1.5">
                          {draftResult.draft.terms.map(term => (
                            <label key={term.term_id} className="flex items-start gap-2.5 p-2 rounded bg-slate-50 dark:bg-slate-800/40 hover:bg-slate-100/50 cursor-pointer">
                              <input 
                                type="checkbox"
                                checked={!!selectedTerms[term.term_id]}
                                onChange={e => setSelectedTerms(p => ({ ...p, [term.term_id]: e.target.checked }))}
                                className="mt-0.5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                              />
                              <div>
                                <span className="font-bold text-slate-800 dark:text-white">{term.term}</span>
                                {term.synonyms.length > 0 && (
                                  <span className="ml-2 bg-indigo-55/10 text-indigo-650 px-1.5 py-0.5 rounded text-[8px]">{term.synonyms.join(', ')}</span>
                                )}
                                <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-0.5">{term.definition}</p>
                              </div>
                            </label>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Acceptance Questions */}
                    {draftResult.draft.acceptance_questions.length > 0 && (
                      <div className="space-y-2">
                        <h4 className="font-bold text-slate-700 dark:text-slate-300 border-b pb-1">5. 问数验收集 (Acceptance Questions)</h4>
                        <div className="space-y-1.5">
                          {draftResult.draft.acceptance_questions.map(q => (
                            <label key={q.question_id} className="flex items-start gap-2.5 p-2 rounded bg-slate-50 dark:bg-slate-800/40 hover:bg-slate-100/50 cursor-pointer">
                              <input 
                                type="checkbox"
                                checked={!!selectedQuestions[q.question_id]}
                                onChange={e => setSelectedQuestions(p => ({ ...p, [q.question_id]: e.target.checked }))}
                                className="mt-0.5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                              />
                              <div>
                                <span className="font-bold text-slate-850 dark:text-white">{q.question}</span>
                                {q.expected_metric_code && (
                                  <div className="text-[9px] text-slate-400 mt-0.5">预期指标：<code>{q.expected_metric_code}</code></div>
                                )}
                              </div>
                            </label>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Dropped / Rejected Warnings */}
                    {(draftResult.dropped_fields.length > 0 || draftResult.rejected_metrics.length > 0) && (
                      <div className="space-y-3 bg-red-50/40 dark:bg-red-950/10 border border-red-100 dark:border-red-950/60 p-4 rounded-xl">
                        <div className="flex items-center gap-1.5 text-red-650 dark:text-red-400 font-bold">
                          <AlertTriangle className="w-4 h-4" />
                          发现未治理或冲突项 (已自动跳过)
                        </div>
                        <ul className="list-disc pl-4 space-y-1 text-[10px] text-slate-550 dark:text-slate-400">
                          {draftResult.dropped_fields.map(f => (
                            <li key={f}>元数据物理列 <code>{f}</code> 校验不符，已从字段列表中过滤。</li>
                          ))}
                          {draftResult.rejected_metrics.map(m => (
                            <li key={m}>AI 指标建议 <code>{m}</code> 冲突或不完整：{draftResult.rejection_reasons[m] || '未满足语法一致性规则'}。</li>
                          ))}
                        </ul>
                      </div>
                    )}

                  </div>

                  {/* Wizard Actions */}
                  <div className="flex justify-between items-center border-t border-slate-100 dark:border-slate-800 pt-4 mt-6">
                    <button 
                      type="button" 
                      onClick={() => setWizardStep('config')}
                      className="px-4 py-2 border border-slate-200 dark:border-slate-700 rounded-lg font-bold text-slate-550 dark:text-slate-400"
                    >
                      返回基本信息
                    </button>
                    <button 
                      type="button"
                      onClick={handleCreatePack}
                      className="bg-indigo-600 hover:bg-indigo-700 text-white font-bold px-6 py-2 rounded-lg shadow-md transition-all active:scale-[0.98]"
                    >
                      确认导入并创建领域包
                    </button>
                  </div>

                </div>
              )}

            </div>
          </div>
        </div>
      )}

      {/* Semantic Space Adaptation Modal */}
      {adaptTarget && (
        <PackAdaptModal
          packId={adaptTarget.id}
          packName={adaptTarget.name}
          dataSources={dataSources}
          deployments={packDeployments.find(p => p.pack_id === adaptTarget.id)?.deployments || enterprisePacks.find(p => p.pack_id === adaptTarget.id)?.deployments || []}
          userContext={userContext}
          onClose={() => setAdaptTarget(null)}
          onNotify={showNotice}
          onSelectDeployment={(deploymentId) => {
            setAdaptTarget(null);
            onOpenMounting?.(deploymentId);
          }}
        />
      )}
    </ManagementPage>
  );
};
