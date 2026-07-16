import React, { useCallback, useState, useEffect } from 'react';
import {
  Database,
  RefreshCw,
  ShieldAlert,
  Check,
  X,
  Server,
  Play,
  Layers,
  ChevronDown,
  ChevronUp,
  Sparkles,
  Package,
  AlertTriangle
} from 'lucide-react';
import { api } from '../api';
import { ActionButton, ManagementHeader, ManagementPage } from './ui/ManagementUI';
import type {
  DataSource,
  CreateDataSourceRequest,
  UpdateDataSourceRequest,
  ScanStatus,
  SemanticSpace,
  CatalogOverview,
  ConnectionTestResult,
  PackWithDeployments
} from '../api';
import { SchemaScanProgress } from './SchemaScanProgress';

interface DataSourceManagerProps {
  dataSources: DataSource[];
  isSystemAdmin: boolean;
  onRefreshSources: () => void;
  onViewProfile: (dsId: string) => void;
  onOpenSpace: (dsId: string, spaceId: string) => void;
  focusSemanticSpace?: { dsId: string; spaceId: string; nonce: number } | null;
}

// Fields whose change invalidates the last connection test and requires a
// fresh metadata scan — mirrors the backend's _DS_CONNECTION_CRITICAL_FIELDS.
const CONNECTION_CRITICAL_FIELDS: (keyof CreateDataSourceRequest)[] = [
  'host', 'port', 'database', 'service_name', 'sid', 'dsn', 'username', 'password'
];

export const DataSourceManager: React.FC<DataSourceManagerProps> = ({
  dataSources,
  isSystemAdmin,
  onRefreshSources,
  onViewProfile,
  onOpenSpace,
  focusSemanticSpace
}) => {
  // CRUD states
  const [editingDsId, setEditingDsId] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [deletingDsId, setDeletingDsId] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  // Connection Test UX
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [isTesting, setIsTesting] = useState(false);

  // Form State — technical connection fields only (see CONNECTION_CRITICAL_FIELDS)
  const [formData, setFormData] = useState<Partial<CreateDataSourceRequest>>({
    database_type: 'oracle',
    port: 1521,
    is_read_only: true,
    metadata_scan_enabled: true
  });
  // Snapshot of the connection-critical fields as loaded, to detect changes
  // that require re-testing + rescanning while editing.
  const [originalConnection, setOriginalConnection] = useState<Partial<CreateDataSourceRequest>>({});
  // Advanced/rarely-used connection fields (timeout, Oracle service_name/sid/dsn,
  // description) are collapsed by default to keep the form compact.
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Scanning progress states per data source
  const [activeScans, setActiveScans] = useState<Record<string, ScanStatus>>({});

  const [semanticSpaces, setSemanticSpaces] = useState<Record<string, SemanticSpace[]>>({});
  const [expandedSemanticDsId, setExpandedSemanticDsId] = useState<string | null>(null);
  const [showCreateSpaceDsId, setShowCreateSpaceDsId] = useState<string | null>(null);
  const [newSpaceName, setNewSpaceName] = useState('');
  const [newSpaceDesc, setNewSpaceDesc] = useState('');
  const [newSpaceTablesText, setNewSpaceTablesText] = useState('');
  const [creatingRecommendationId, setCreatingRecommendationId] = useState<string | null>(null);
  const [highlightedSpaceId, setHighlightedSpaceId] = useState<string | null>(null);
  const [deletingSpace, setDeletingSpace] = useState<{ dsId: string; space: SemanticSpace } | null>(null);

  // Catalog overview (元数据概览) — lazy-loaded per data source on demand
  const [catalogOverviews, setCatalogOverviews] = useState<Record<string, CatalogOverview | 'loading' | 'error'>>({});
  const [expandedCatalogDsId, setExpandedCatalogDsId] = useState<string | null>(null);

  // Recommended semantic spaces (推荐语义空间) — lazy-loaded per data source
  const [recommendedSpaces, setRecommendedSpaces] = useState<Record<string, SemanticSpace[] | 'loading'>>({});

  // Associated domain packs (受影响领域包) — loaded once, filtered per data source
  const [adminPacks, setAdminPacks] = useState<PackWithDeployments[]>([]);

  const toggleCatalogOverview = async (dsId: string) => {
    if (expandedCatalogDsId === dsId) {
      setExpandedCatalogDsId(null);
      return;
    }
    setExpandedCatalogDsId(dsId);
    // Recommendations change after every scan. Always refresh when reopening
    // the catalog instead of keeping a previous empty result forever.
    setRecommendedSpaces(prev => ({ ...prev, [dsId]: 'loading' }));
    api.getRecommendedSemanticSpaces(dsId)
      .then(spaces => setRecommendedSpaces(prev => ({ ...prev, [dsId]: spaces })))
      .catch(() => setRecommendedSpaces(prev => ({ ...prev, [dsId]: [] })));
    if (catalogOverviews[dsId] && catalogOverviews[dsId] !== 'error') return;
    setCatalogOverviews(prev => ({ ...prev, [dsId]: 'loading' }));
    try {
      const overview = await api.getCatalogOverview(dsId);
      setCatalogOverviews(prev => ({ ...prev, [dsId]: overview }));
    } catch {
      setCatalogOverviews(prev => ({ ...prev, [dsId]: 'error' }));
    }
  };

  const loadSemanticSpaces = useCallback(async () => {
    try {
      const spacesMap: Record<string, SemanticSpace[]> = {};
      for (const ds of dataSources) {
        spacesMap[ds.data_source_id] = await api.listSemanticSpaces(ds.data_source_id);
      }
      setSemanticSpaces(spacesMap);
    } catch (err) {
      console.error('Failed to load semantic spaces:', err);
    }
  }, [dataSources]);

  useEffect(() => {
    if (dataSources.length > 0) {
      void loadSemanticSpaces();
    }
  }, [dataSources, loadSemanticSpaces]);

  useEffect(() => {
    if (!focusSemanticSpace) return;
    setExpandedSemanticDsId(focusSemanticSpace.dsId);
    setHighlightedSpaceId(focusSemanticSpace.spaceId);
    const scrollTimer = window.setTimeout(() => {
      document.getElementById(`semantic-space-${focusSemanticSpace.spaceId}`)?.scrollIntoView({
        behavior: 'smooth',
        block: 'center'
      });
    }, 120);
    const clearTimer = window.setTimeout(() => setHighlightedSpaceId(null), 2600);
    return () => {
      window.clearTimeout(scrollTimer);
      window.clearTimeout(clearTimer);
    };
  }, [focusSemanticSpace]);

  useEffect(() => {
    api.getAdminPacks().then(setAdminPacks).catch(() => setAdminPacks([]));
  }, [dataSources]);

  const parseTableList = (value: string): string[] => {
    const seen = new Set<string>();
    return value
      .split(/[\s,，;；]+/)
      .map(item => item.trim())
      .filter(Boolean)
      .filter(item => {
        const key = item.toLowerCase();
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
  };

  const resetCreateSpaceForm = () => {
    setNewSpaceName('');
    setNewSpaceDesc('');
    setNewSpaceTablesText('');
    setShowCreateSpaceDsId(null);
  };

  const openCreateSpaceForm = (dsId: string, seed?: SemanticSpace) => {
    setExpandedSemanticDsId(dsId);
    setShowCreateSpaceDsId(dsId);
    setNewSpaceName(seed?.name || '');
    setNewSpaceDesc(seed?.description || '');
    setNewSpaceTablesText(seed?.entities?.map(entity => entity.physical_table).join('\n') || '');
  };

  const spaceSummary = (spaces: SemanticSpace[]) => {
    const tableCount = spaces.reduce((acc, space) => acc + (space.entities?.length || 0), 0);
    const fieldCount = spaces.reduce(
      (acc, space) => acc + (space.entities?.reduce((sum, ent) => sum + (ent.fields?.length || 0), 0) || 0),
      0
    );
    const enabledCount = spaces.filter(space =>
      (space.entities?.reduce((sum, ent) => sum + (ent.fields?.length || 0), 0) || 0) > 0
    ).length;
    const pendingFieldCount = spaces.reduce(
      (acc, space) => acc + (space.entities?.reduce(
        (sum, ent) => sum + (ent.fields?.filter(field => (field.status || 'confirmed') === 'pending').length || 0),
        0
      ) || 0),
      0
    );
    return {
      total: spaces.length,
      tableCount,
      fieldCount,
      enabledCount,
      configuringCount: Math.max(spaces.length - enabledCount, 0),
      pendingFieldCount
    };
  };

  const handleCreateSpace = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!showCreateSpaceDsId || !newSpaceName.trim()) return;
    if (!newSpaceDesc.trim()) {
      alert('请填写该语义空间的业务背景描述。');
      return;
    }
    const dsId = showCreateSpaceDsId;
    try {
      const created = await api.createSemanticSpace(dsId, {
        data_source_id: dsId,
        name: newSpaceName.trim(),
        description: newSpaceDesc.trim(),
        initial_tables: parseTableList(newSpaceTablesText)
      });
      resetCreateSpaceForm();
      setExpandedSemanticDsId(dsId);
      await loadSemanticSpaces();
      onOpenSpace(dsId, created.space_id);
    } catch (err: any) {
      alert(`创建语义空间失败: ${err?.message || '未知错误'}`);
    }
  };

  const handleCreateFromRecommendation = async (dsId: string, seed: SemanticSpace) => {
    setCreatingRecommendationId(seed.space_id);
    try {
      const created = await api.createSemanticSpace(dsId, {
        data_source_id: dsId,
        name: seed.name,
        description: seed.description || `从元数据扫描建议创建：${seed.name}`,
        initial_tables: seed.entities.map(entity => entity.physical_table)
      });
      resetCreateSpaceForm();
      setExpandedSemanticDsId(dsId);
      setRecommendedSpaces(prev => {
        const current = prev[dsId];
        if (!Array.isArray(current)) return prev;
        return { ...prev, [dsId]: current.filter(space => space.space_id !== seed.space_id) };
      });
      await loadSemanticSpaces();
      setHighlightedSpaceId(created.space_id);
      setTimeout(() => {
        document.getElementById(`semantic-space-${created.space_id}`)?.scrollIntoView({
          behavior: 'smooth',
          block: 'center'
        });
      }, 120);
      window.setTimeout(() => setHighlightedSpaceId(null), 2600);
    } catch (err: any) {
      alert(`采纳推荐语义空间失败: ${err?.message || '未知错误'}`);
    } finally {
      setCreatingRecommendationId(null);
    }
  };

  const handleDeleteSpace = async (dsId: string, space: SemanticSpace) => {
    try {
      await api.deleteSemanticSpace(dsId, space.space_id);
      setDeletingSpace(null);
      await loadSemanticSpaces();
    } catch (err: any) {
      alert(`删除语义空间失败: ${err?.message || '未知错误'}`);
    }
  };

  const emptyForm = (): Partial<CreateDataSourceRequest> => ({
    database_type: 'oracle',
    port: 1521,
    is_read_only: true,
    metadata_scan_enabled: true
  });

  // Update text areas when editing data source
  const openEdit = (ds: DataSource) => {
    setEditingDsId(ds.data_source_id);
    const loaded: Partial<CreateDataSourceRequest> = {
      data_source_id: ds.data_source_id,
      name: ds.name,
      database_type: ds.database_type,
      host: ds.host || '',
      port: ds.port || 1521,
      database: ds.database || '',
      service_name: ds.service_name || '',
      sid: ds.sid || '',
      dsn: ds.dsn || '',
      username: ds.username || ds.user_mask || '',
      password: '',
      is_read_only: ds.is_read_only,
      description: ds.description || '',
      connect_timeout_seconds: ds.connect_timeout_seconds ?? undefined,
      metadata_scan_enabled: ds.metadata_scan_enabled ?? true
    };
    setFormData(loaded);
    setOriginalConnection(loaded);
    setTestResult(null);
    setShowAddForm(true);
    // Auto-expand advanced fields if any are already set, so editing doesn't hide them.
    setShowAdvanced(!!(ds.service_name || ds.sid || ds.dsn || ds.connect_timeout_seconds || ds.description));
  };

  // True once the admin has actually edited a connection-critical field —
  // drives the "参数变更后需要重新测试" warning (checklist §修改数据库连接.3).
  const connectionFieldsChanged = editingDsId
    ? CONNECTION_CRITICAL_FIELDS.some(field => {
        if (field === 'password') return !!formData.password; // blank = "not changed"
        return (formData[field] ?? '') !== (originalConnection[field] ?? '');
      })
    : false;

  const handleTestConnection = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      const res = await api.testConnection(formData);
      setTestResult(res);
    } catch (err: any) {
      setTestResult({
        success: false,
        message: err?.message || '连接测试异常，请检查配置',
        capabilities: { can_read_schemas: false, can_read_tables: false, can_read_columns: false, can_read_keys: false }
      });
    } finally {
      setIsTesting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      if (editingDsId) {
        const payload: UpdateDataSourceRequest = {
          name: formData.name,
          database_type: formData.database_type,
          host: formData.host,
          port: formData.port,
          database: formData.database,
          service_name: formData.service_name || null,
          sid: formData.sid || null,
          dsn: formData.dsn || null,
          username: formData.username,
          password: formData.password || undefined,
          is_read_only: formData.is_read_only,
          description: formData.description,
          connect_timeout_seconds: formData.connect_timeout_seconds ?? null,
          metadata_scan_enabled: formData.metadata_scan_enabled
        };
        const updated = await api.updateDataSource(editingDsId, payload);
        // Password is write-only — clear it so "blank = unchanged" holds
        // from this point forward, matching openEdit()'s convention.
        const savedForm = { ...formData, password: '' };
        setFormData(savedForm);
        if (updated.scan_id) {
          setActiveScans(prev => ({
            ...prev,
            [editingDsId]: {
              scan_id: updated.scan_id!,
              data_source_id: editingDsId,
              snapshot_id: updated.snapshot_id,
              phase: 'pending',
              progress_message: '连接参数已变更，正在重新扫描元数据…',
              table_count: 0,
              included_table_count: 0,
              recommendation_counts: {},
              started_at: new Date().toISOString()
            }
          }));
          setOriginalConnection(savedForm); // stepper stays open to show progress
        } else {
          setShowAddForm(false);
          setEditingDsId(null);
        }
      } else {
        const payload: CreateDataSourceRequest = {
          data_source_id: formData.data_source_id!,
          name: formData.name!,
          database_type: formData.database_type!,
          host: formData.host!,
          port: Number(formData.port),
          database: formData.database!,
          service_name: formData.service_name || null,
          sid: formData.sid || null,
          dsn: formData.dsn || null,
          username: formData.username!,
          password: formData.password!,
          is_read_only: !!formData.is_read_only,
          description: formData.description,
          connect_timeout_seconds: formData.connect_timeout_seconds ?? null,
          metadata_scan_enabled: formData.metadata_scan_enabled ?? true
        };
        const created = await api.createDataSource(payload);
        // Scan auto-starts on the backend as soon as the connection is saved
        // — switch straight into the edit view showing scan progress instead
        // of just closing the form.
        if (created.scan_id) {
          setActiveScans(prev => ({
            ...prev,
            [payload.data_source_id]: {
              scan_id: created.scan_id!,
              data_source_id: payload.data_source_id,
              snapshot_id: created.snapshot_id,
              phase: 'pending',
              progress_message: '已保存连接，正在启动元数据扫描…',
              table_count: 0,
              included_table_count: 0,
              recommendation_counts: {},
              started_at: new Date().toISOString()
            }
          }));
        }
        setEditingDsId(payload.data_source_id);
        // Password is write-only — clear it so "blank = unchanged" holds
        // from this point forward, matching openEdit()'s convention.
        const savedForm = { ...formData, password: '' };
        setFormData(savedForm);
        setOriginalConnection(savedForm);
      }
      onRefreshSources();
    } catch (err: any) {
      alert(`保存失败: ${err?.message || '未知错误'}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (dsId: string) => {
    try {
      await api.deleteDataSource(dsId);
      setDeletingDsId(null);
      onRefreshSources();
    } catch (err: any) {
      alert(`删除失败: ${err?.message || '请先移除依赖的部署实例'}`);
    }
  };

  const handleTriggerScan = async (dsId: string) => {
    try {
      const scanStatus = await api.scanDataSource(dsId, { force_rescan: true });
      setActiveScans(prev => ({ ...prev, [dsId]: scanStatus }));
      setCatalogOverviews(prev => { const next = { ...prev }; delete next[dsId]; return next; });
      setRecommendedSpaces(prev => { const next = { ...prev }; delete next[dsId]; return next; });
    } catch (err: any) {
      alert(`触发扫描失败: ${err?.message || '未知错误'}`);
    }
  };

  const handleScanComplete = async (dsId: string, scan: ScanStatus) => {
    setActiveScans(prev => ({ ...prev, [dsId]: scan }));
    onRefreshSources();
    if (scan.phase !== 'done') return;
    try {
      const [overview, spaces] = await Promise.all([
        api.getCatalogOverview(dsId),
        api.getRecommendedSemanticSpaces(dsId)
      ]);
      setCatalogOverviews(prev => ({ ...prev, [dsId]: overview }));
      setRecommendedSpaces(prev => ({ ...prev, [dsId]: spaces }));
    } catch (err) {
      console.error('Failed to refresh scan results:', err);
    }
  };

  const packsForDataSource = (dsId: string) =>
    adminPacks
      .map(pack => ({
        pack,
        deployments: pack.deployments.filter(deployment => (
          deployment.data_source_id === dsId
          && deployment.is_active
          && deployment.binding_status !== 'unavailable'
        ))
      }))
      .filter(({ deployments }) => deployments.length > 0);

  // While creating a brand-new connection, the existing connections list is
  // just noise below the form — hide it until the form closes. Editing an
  // existing connection still shows the others (already excludes itself below).
  const isCreatingNew = showAddForm && !editingDsId;

  const capabilityRow = (label: string, ok: boolean) => (
    <div className="flex items-center gap-1.5">
      {ok ? <Check className="w-3 h-3 text-green-600 dark:text-green-400 shrink-0" /> : <X className="w-3 h-3 text-red-500 shrink-0" />}
      <span className={ok ? 'text-slate-600 dark:text-slate-400' : 'text-slate-400'}>{label}</span>
    </div>
  );

  return (
    <ManagementPage>

      {/* Header section */}
      <ManagementHeader
        icon={<Server className="w-5 h-5 text-indigo-500" />}
        title="数据源管理"
        description="怎么连上数据库，以及这个连接下大概有哪些元数据。业务描述与语义空间请在下方各连接的「语义空间」中配置。"
        actions={isSystemAdmin && !showAddForm ? (
          <ActionButton
            variant="primary"
            onClick={() => {
              setEditingDsId(null);
              const blank = emptyForm();
              setFormData(blank);
              setOriginalConnection(blank);
              setTestResult(null);
              setShowAdvanced(false);
              setShowAddForm(true);
            }}
          >
            <span className="text-base leading-none">+</span> 新建数据源
          </ActionButton>
        ) : undefined}
      />

      {/* Connection Create / Edit Form */}
      {isSystemAdmin && showAddForm && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-5">
          <div className="flex justify-between items-start pb-3 border-b border-slate-100 dark:border-slate-800">
            <div className="flex items-start gap-3">
              <h3 className="text-xs font-bold text-slate-800 dark:text-slate-200 uppercase tracking-wider pt-1.5">
                {editingDsId ? `修改连接 · ${editingDsId}` : '新建数据库连接'}
              </h3>
              <div className="flex flex-col gap-1">
                <button
                  type="button"
                  onClick={handleTestConnection}
                  disabled={isTesting}
                  className="flex items-center gap-1.5 text-[10px] bg-indigo-55/60 hover:bg-indigo-100 dark:bg-indigo-950/20 text-indigo-650 dark:text-indigo-400 border border-indigo-200/50 dark:border-indigo-900/50 px-2.5 py-1 rounded-lg font-bold transition-all cursor-pointer shadow-sm w-fit"
                >
                  {isTesting && <RefreshCw className="w-3 h-3 animate-spin" />}
                  测试连接
                </button>
                {testResult && (
                  <div className="space-y-1 max-w-xs">
                    <div className={`flex items-center gap-1 text-[10px] font-medium ${
                      testResult.success ? 'text-green-650 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                    }`}>
                      {testResult.success ? <Check className="w-3 h-3 shrink-0" /> : <ShieldAlert className="w-3 h-3 shrink-0" />}
                      <span className="truncate" title={testResult.message}>{testResult.message}</span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[9px] pl-4">
                      {capabilityRow('Schema', testResult.capabilities.can_read_schemas)}
                      {capabilityRow('表', testResult.capabilities.can_read_tables)}
                      {capabilityRow('字段', testResult.capabilities.can_read_columns)}
                      {capabilityRow('主外键/索引', testResult.capabilities.can_read_keys)}
                    </div>
                  </div>
                )}
              </div>
            </div>
            <button
              onClick={() => { setShowAddForm(false); setEditingDsId(null); }}
              className="text-slate-400 hover:text-slate-600"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4 text-xs">
            {/* 1. 基本信息 + 连接参数 — merged into one section */}
            <div className="space-y-3">
              <h4 className="text-[10px] font-bold text-slate-450 uppercase tracking-wider">基本信息与连接参数</h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-[10px] text-slate-400 font-semibold mb-1 uppercase tracking-wider">数据源 ID <span className="text-red-400">*</span></label>
                  <input required type="text" placeholder="oracle_tms" value={formData.data_source_id || ''}
                    disabled={!!editingDsId}
                    onChange={e => setFormData(p => ({ ...p, data_source_id: e.target.value }))}
                    className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500 disabled:opacity-60" />
                </div>
                <div>
                  <label className="block text-[10px] text-slate-400 font-semibold mb-1 uppercase tracking-wider">连接名称 <span className="text-red-400">*</span></label>
                  <input required type="text" placeholder="TMS Oracle 数据库" value={formData.name || ''}
                    onChange={e => setFormData(p => ({ ...p, name: e.target.value }))}
                    className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500" />
                </div>
                <div>
                  <label className="block text-[10px] text-slate-400 font-semibold mb-1 uppercase tracking-wider">数据库类型</label>
                  <select value={formData.database_type || 'oracle'}
                    onChange={e => setFormData(p => ({ ...p, database_type: e.target.value }))}
                    className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500">
                    {['oracle', 'mysql', 'postgresql', 'clickhouse'].map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-[10px] text-slate-400 font-semibold mb-1 uppercase tracking-wider">主机地址 <span className="text-red-400">*</span></label>
                  <input required type="text" placeholder="192.168.1.100" value={formData.host || ''}
                    onChange={e => setFormData(p => ({ ...p, host: e.target.value }))}
                    className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500" />
                </div>
                <div>
                  <label className="block text-[10px] text-slate-400 font-semibold mb-1 uppercase tracking-wider">端口 <span className="text-red-400">*</span></label>
                  <input required type="number" placeholder="1521" value={formData.port ?? ''}
                    onChange={e => setFormData(p => ({ ...p, port: Number(e.target.value) }))}
                    className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500" />
                </div>
                <div>
                  <label className="block text-[10px] text-slate-400 font-semibold mb-1 uppercase tracking-wider">数据库 / 服务名 <span className="text-red-400">*</span></label>
                  <input required type="text" placeholder="tms_instance" value={formData.database || ''}
                    onChange={e => setFormData(p => ({ ...p, database: e.target.value }))}
                    className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500" />
                </div>
                <div>
                  <label className="block text-[10px] text-slate-400 font-semibold mb-1 uppercase tracking-wider">用户名 <span className="text-red-400">*</span></label>
                  <input required type="text" placeholder="TMS_BI_READER" value={formData.username || ''}
                    onChange={e => setFormData(p => ({ ...p, username: e.target.value }))}
                    className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500" />
                </div>
                <div>
                  <label className="block text-[10px] text-slate-400 font-semibold mb-1 uppercase tracking-wider">
                    密码 {editingDsId ? '(当前密码：已保存，留空则不修改)' : <span className="text-red-400">*</span>}
                  </label>
                  <input required={!editingDsId} type="password" placeholder="••••••••" value={formData.password || ''}
                    onChange={e => setFormData(p => ({ ...p, password: e.target.value }))}
                    className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500" />
                </div>
              </div>

              <button
                type="button"
                onClick={() => setShowAdvanced(v => !v)}
                className="flex items-center gap-1 text-[10px] font-bold text-indigo-650 dark:text-indigo-400 cursor-pointer pt-1"
              >
                {showAdvanced ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                {showAdvanced ? '收起高级选项' : '高级选项（超时 / Oracle 备用连接方式 / 描述）'}
              </button>

              {showAdvanced && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
                  <div>
                    <label className="block text-[10px] text-slate-400 font-semibold mb-1 uppercase tracking-wider">连接超时（秒，可选）</label>
                    <input type="number" placeholder="5" value={formData.connect_timeout_seconds ?? ''}
                      onChange={e => setFormData(p => ({ ...p, connect_timeout_seconds: e.target.value ? Number(e.target.value) : undefined }))}
                      className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500" />
                  </div>
                  {formData.database_type === 'oracle' && (
                    <>
                      <div>
                        <label className="block text-[10px] text-slate-400 font-semibold mb-1">Service Name（可选，Oracle）</label>
                        <input type="text" placeholder="ORCLPDB1" value={formData.service_name || ''}
                          onChange={e => setFormData(p => ({ ...p, service_name: e.target.value }))}
                          className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500" />
                      </div>
                      <div>
                        <label className="block text-[10px] text-slate-400 font-semibold mb-1">SID（可选，Oracle）</label>
                        <input type="text" placeholder="ORCL" value={formData.sid || ''}
                          onChange={e => setFormData(p => ({ ...p, sid: e.target.value }))}
                          className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500" />
                      </div>
                      <div className="sm:col-span-2">
                        <label className="block text-[10px] text-slate-400 font-semibold mb-1">完整 DSN 覆盖（可选，优先级最高）</label>
                        <input type="text" placeholder="host:port/service_name" value={formData.dsn || ''}
                          onChange={e => setFormData(p => ({ ...p, dsn: e.target.value }))}
                          className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500" />
                      </div>
                    </>
                  )}
                  <div className="sm:col-span-2">
                    <label className="block text-[10px] text-slate-400 font-semibold mb-1">描述（可选，仅描述连接用途）</label>
                    <input type="text" placeholder="例如：生产 Oracle 只读账号" value={formData.description || ''}
                      onChange={e => setFormData(p => ({ ...p, description: e.target.value }))}
                      className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500" />
                  </div>
                </div>
              )}
            </div>

            {/* 2. 安全和访问控制 */}
            <div className="space-y-2 pt-3 border-t border-slate-100 dark:border-slate-800">
              <h4 className="text-[10px] font-bold text-slate-450 uppercase tracking-wider">安全和访问控制</h4>
              <div className="flex items-center gap-2">
                <input type="checkbox" id="is_readonly" checked={!!formData.is_read_only}
                  onChange={e => setFormData(p => ({ ...p, is_read_only: e.target.checked }))}
                  className="rounded border-slate-300 dark:border-slate-800 text-indigo-650" />
                <label htmlFor="is_readonly" className="text-[10px] font-semibold text-slate-600 dark:text-slate-400">
                  只读模式 (仅 SELECT - 强烈推荐)
                </label>
              </div>
              <div className="flex items-center gap-2">
                <input type="checkbox" id="scan_enabled" checked={formData.metadata_scan_enabled !== false}
                  onChange={e => setFormData(p => ({ ...p, metadata_scan_enabled: e.target.checked }))}
                  className="rounded border-slate-300 dark:border-slate-800 text-indigo-650" />
                <label htmlFor="scan_enabled" className="text-[10px] font-semibold text-slate-600 dark:text-slate-400">
                  启用元数据扫描（保存后自动执行）
                </label>
              </div>
              <p className="text-[10px] text-slate-400">凭证保存方式：加密存储。管理该连接：仅系统管理员。</p>
            </div>

            {/* Connection-critical change warning (editing only) */}
            {editingDsId && connectionFieldsChanged && (
              <div className="flex items-start gap-2 text-[10px] text-amber-700 dark:text-amber-400 bg-amber-500/10 px-3 py-2 rounded-lg border border-amber-500/20">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                <span>连接参数变更后，需要重新测试连接并刷新元数据概览。已有语义空间和领域包可能需要重新校验。</span>
              </div>
            )}

            {/* 5. 保存后的自动动作 — scan progress */}
            {formData.data_source_id && activeScans[editingDsId || formData.data_source_id] && (
              <div className="pt-3 border-t border-slate-100 dark:border-slate-800/60">
                <SchemaScanProgress
                  dsId={editingDsId || formData.data_source_id}
                  initialScan={activeScans[editingDsId || formData.data_source_id]}
                  onComplete={(scan) => void handleScanComplete(editingDsId || formData.data_source_id!, scan)}
                  onViewProfile={() => onViewProfile(editingDsId || formData.data_source_id!)}
                />
              </div>
            )}
            {!editingDsId && !activeScans[formData.data_source_id || ''] && (
              <div className="text-[10px] text-slate-400 bg-slate-50/50 dark:bg-slate-900/10 p-2.5 rounded-xl border border-dashed border-slate-200 dark:border-slate-800 text-center">
                连接已保存后，系统将自动扫描元数据概览。
              </div>
            )}

            {/* Footer Buttons */}
            <div className="flex justify-between items-center pt-3 border-t border-slate-100 dark:border-slate-800">
              {editingDsId ? (
                <button type="button" onClick={() => handleTriggerScan(editingDsId)}
                  className="flex items-center gap-1.5 text-[10px] font-bold text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/50 border border-slate-200 dark:border-slate-700 px-3 py-1.5 rounded-lg cursor-pointer">
                  <RefreshCw className="w-3 h-3" /> 刷新元数据概览
                </button>
              ) : <span />}
              <div className="flex gap-2">
                <button type="button" onClick={() => { setShowAddForm(false); setEditingDsId(null); }}
                  className="px-4 py-2 rounded border border-slate-200 dark:border-slate-850 text-slate-500 dark:text-slate-400 hover:bg-slate-50">
                  取消
                </button>
                <button type="submit" disabled={isSaving}
                  className="bg-indigo-600 hover:bg-indigo-700 text-white font-bold px-5 py-2 rounded-lg flex items-center gap-1.5 shadow-sm cursor-pointer">
                  {isSaving && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                  {editingDsId ? '保存修改' : '保存连接'}
                </button>
              </div>
            </div>
          </form>
        </div>
      )}

      {/* Data Source List — hidden while creating a new connection */}
      {!isCreatingNew && (dataSources.length === 0 ? (
        <div className="text-center py-20 text-slate-400 dark:text-slate-600 bg-white dark:bg-slate-900 border border-slate-200/60 dark:border-slate-800 rounded-2xl shadow-sm">
          <Database className="w-12 h-12 mx-auto mb-3 opacity-30 text-indigo-500" />
          <p className="text-sm font-semibold">暂无已配置的数据源</p>
          {isSystemAdmin && <p className="text-xs mt-1 text-slate-405">请点击右上角「新建数据库连接」配置您的第一个数据库连接。</p>}
        </div>
      ) : (
        <div className="space-y-6">
	          {dataSources.filter(ds => ds.data_source_id !== editingDsId).map(ds => {
	            const isDeleting = deletingDsId === ds.data_source_id;
	            const associatedPacks = packsForDataSource(ds.data_source_id);
	            const spaces = semanticSpaces[ds.data_source_id] || [];
	            const semanticSummary = spaceSummary(spaces);

	            return (
              <div
                key={ds.data_source_id}
                className="bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 rounded-2xl p-6 shadow-sm space-y-4 text-xs"
              >

                {/* Delete Warning Drawer */}
                {isDeleting && (
                  <div className="p-4 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900 rounded-xl space-y-3">
                    <div className="flex gap-2 text-red-700 dark:text-red-400">
                      <ShieldAlert className="w-5 h-5 shrink-0" />
                      <div className="space-y-1">
                        <span className="font-bold">删除不可逆！</span>
                        <p className="text-[11px] opacity-90">
                          确认删除数据源 <code>{ds.data_source_id}</code>？此操作将彻底移除连接配置和对应的本地 SQLite 语义缓存。
                        </p>
                      </div>
                    </div>
                    <div className="flex gap-2 pl-7">
                      <button onClick={() => handleDelete(ds.data_source_id)}
                        className="bg-red-600 hover:bg-red-700 text-white font-bold px-4 py-2 rounded-lg transition-colors cursor-pointer">
                        确认删除
                      </button>
                      <button onClick={() => setDeletingDsId(null)}
                        className="border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 px-4 py-2 rounded-lg font-semibold hover:bg-slate-50 dark:hover:bg-slate-800/40">
                        取消
                      </button>
                    </div>
                  </div>
                )}

                {/* 1. 基本信息 — Card Title Bar */}
                <div className="flex justify-between items-start flex-wrap gap-4 border-b border-slate-100 dark:border-slate-800 pb-3">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 bg-indigo-50 dark:bg-indigo-950/40 rounded-xl flex items-center justify-center text-indigo-555">
                      <Database className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold text-slate-850 dark:text-white">{ds.name}</span>
                        <code className="text-[9px] bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded text-slate-500 font-mono">
                          {ds.data_source_id}
                        </code>
                      </div>
                      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 mt-1 text-[10px]">
                        <span className="font-bold font-mono text-slate-500 dark:text-slate-400 uppercase">{ds.database_type}</span>
                        <span className="text-slate-300 dark:text-slate-700">·</span>
                        <code className="font-mono text-slate-450 dark:text-slate-500 truncate max-w-[220px]" title={ds.host}>
                          {ds.host || '-'}{ds.port ? `:${ds.port}` : ''}
                        </code>
                        <span className="text-slate-300 dark:text-slate-700">·</span>
                        <span className={`font-medium ${ds.is_read_only ? 'text-green-650 dark:text-green-400' : 'text-amber-600 dark:text-amber-400'}`}>
                          {ds.is_read_only ? '只读' : '可写'}
                        </span>
                      </div>
                      <p className="text-[10px] text-slate-455 dark:text-slate-500 mt-1 max-w-xl leading-normal">
                        {ds.description || '未填写连接用途说明'}
                      </p>
                    </div>
                  </div>

                  {/* Actions right */}
                  <div className="flex items-center gap-2 shrink-0">
                    {isSystemAdmin && (
                      <>
                        <button onClick={() => openEdit(ds)}
                          className="border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-850 px-2.5 py-1.5 rounded-lg font-bold text-slate-600 dark:text-slate-400 cursor-pointer">
                          修改
                        </button>
                        <button onClick={() => setDeletingDsId(ds.data_source_id)}
                          className="border border-red-200 dark:border-red-900 text-red-500 hover:bg-red-50 dark:hover:bg-red-950/20 px-2.5 py-1.5 rounded-lg font-bold cursor-pointer">
                          删除
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* 2. 元数据概览 — lazy-loaded */}
                <div className="border border-slate-100 dark:border-slate-800 rounded-xl overflow-hidden">
                  <button
                    type="button"
                    onClick={() => toggleCatalogOverview(ds.data_source_id)}
                    className="w-full flex items-center justify-between px-3 py-2 bg-slate-50/20 dark:bg-slate-900/10 hover:bg-slate-50 dark:hover:bg-slate-900/30 transition-colors cursor-pointer"
                  >
                    <span className="flex items-center gap-1.5 text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                      <Layers className="w-3.5 h-3.5 text-indigo-500" />
                      元数据概览
                    </span>
                    {expandedCatalogDsId === ds.data_source_id
                      ? <ChevronUp className="w-3.5 h-3.5 text-slate-400" />
                      : <ChevronDown className="w-3.5 h-3.5 text-slate-400" />}
                  </button>
                  {expandedCatalogDsId === ds.data_source_id && (
                    <div className="p-3 border-t border-slate-100 dark:border-slate-800 text-[10px] space-y-3">
                      {catalogOverviews[ds.data_source_id] === 'loading' && (
                        <div className="flex items-center gap-1.5 text-slate-400 py-2">
                          <RefreshCw className="w-3 h-3 animate-spin" /> 正在加载元数据概览…
                        </div>
                      )}
                      {catalogOverviews[ds.data_source_id] === 'error' && (
                        <div className="flex items-center justify-between text-slate-400 py-2">
                          <span>暂无元数据快照，请先触发一次元数据扫描。</span>
                          {isSystemAdmin && (
                            <button type="button" onClick={() => handleTriggerScan(ds.data_source_id)}
                              className="flex items-center gap-1 text-indigo-650 dark:text-indigo-400 font-bold cursor-pointer">
                              <Play className="w-3 h-3" /> 立即扫描
                            </button>
                          )}
                        </div>
                      )}
                      {catalogOverviews[ds.data_source_id] &&
                        catalogOverviews[ds.data_source_id] !== 'loading' &&
                        catalogOverviews[ds.data_source_id] !== 'error' && (() => {
                          const overview = catalogOverviews[ds.data_source_id] as CatalogOverview;
                          return (
                            <>
                              <div className="flex items-center justify-between">
                                <span className="text-slate-400">
                                  最近扫描：{overview.created_at ? new Date(overview.created_at).toLocaleString() : '未知时间'}
                                </span>
                                {isSystemAdmin && (
                                  <button type="button" onClick={() => handleTriggerScan(ds.data_source_id)}
                                    className="flex items-center gap-1 text-indigo-650 dark:text-indigo-400 font-bold cursor-pointer">
                                    <RefreshCw className="w-3 h-3" /> 刷新元数据
                                  </button>
                                )}
                              </div>
                              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                                <div>
                                  <span className="block text-slate-400">Schema 数</span>
                                  <span className="font-bold text-slate-700 dark:text-slate-300">{overview.schema_count}</span>
                                </div>
                                <div>
                                  <span className="block text-slate-400">表数量</span>
                                  <span className="font-bold text-slate-700 dark:text-slate-300">{overview.table_count}</span>
                                </div>
                                <div>
                                  <span className="block text-slate-400">字段数量</span>
                                  <span className="font-bold text-slate-700 dark:text-slate-300">{overview.column_count}</span>
                                </div>
                                <div>
                                  <span className="block text-slate-400">默认排除表</span>
                                  <span className="font-bold text-slate-700 dark:text-slate-300">{overview.excluded_table_count}</span>
                                </div>
                              </div>
                              {overview.suspected_business_tables.length > 0 && (
                                <div>
                                  <span className="block text-slate-400 mb-1">疑似业务表</span>
                                  <div className="flex flex-wrap gap-1.5">
                                    {overview.suspected_business_tables.slice(0, 12).map(t => (
                                      <span key={t.table_name} className="px-1.5 py-0.5 rounded bg-indigo-50 dark:bg-indigo-950/20 text-indigo-650 dark:text-indigo-400 font-mono">
                                        {t.table_name}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}
                              {overview.excluded_tables.length > 0 && (
                                <div>
                                  <span className="block text-slate-400 mb-1">默认排除表列表</span>
                                  <div className="flex flex-wrap gap-1.5">
                                    {overview.excluded_tables.slice(0, 12).map(t => (
                                      <span key={t.table_name} className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 font-mono" title={t.excluded_reason || ''}>
                                        {t.table_name}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </>
                          );
                        })()}

                      {/* 4. 推荐语义空间 */}
                      {Array.isArray(recommendedSpaces[ds.data_source_id]) && (recommendedSpaces[ds.data_source_id] as SemanticSpace[]).length > 0 && (
                        <div className="pt-3 border-t border-slate-100 dark:border-slate-800/60">
                          <span className="flex items-center gap-1 text-slate-400 mb-1.5 uppercase tracking-wider font-bold">
                            <Sparkles className="w-3 h-3 text-amber-500" /> 推荐语义空间
                          </span>
                          <div className="space-y-1.5">
                            {(recommendedSpaces[ds.data_source_id] as SemanticSpace[]).map(space => (
                              <div key={space.space_id} className="flex justify-between items-center p-2 bg-amber-50/40 dark:bg-amber-950/10 border border-amber-200/50 dark:border-amber-900/30 rounded-lg">
                                <div>
                                  <span className="font-bold text-slate-700 dark:text-slate-300">{space.name}</span>
                                  <span className="text-slate-400 ml-2">
                                    {space.entities.map(e => e.physical_table).join(', ') || '暂无建议表'}
                                  </span>
                                </div>
	                                {isSystemAdmin && (
	                                  <button type="button"
	                                    disabled={creatingRecommendationId === space.space_id}
	                                    onClick={() => handleCreateFromRecommendation(ds.data_source_id, space)}
	                                    className="border border-amber-250 dark:border-amber-900 bg-white dark:bg-slate-950 text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/20 px-3 py-1.5 rounded-lg font-bold transition-colors cursor-pointer shrink-0 ml-2 disabled:opacity-50 disabled:cursor-wait">
	                                    {creatingRecommendationId === space.space_id ? '采纳中…' : '采纳'}
	                                  </button>
	                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>

	                {/* 3. 语义空间概览 */}
	                <div className="border border-slate-100 dark:border-slate-800 rounded-xl overflow-hidden">
	                  <button
	                    type="button"
	                    onClick={() => setExpandedSemanticDsId(expandedSemanticDsId === ds.data_source_id ? null : ds.data_source_id)}
	                    className="w-full flex items-center justify-between px-3 py-2 bg-slate-50/20 dark:bg-slate-900/10 hover:bg-slate-50 dark:hover:bg-slate-900/30 transition-colors cursor-pointer"
	                  >
	                    <span className="flex items-center gap-1.5 text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
	                      <Sparkles className="w-3.5 h-3.5 text-amber-500" />
	                      语义空间概览
	                    </span>
	                    <span className="flex items-center gap-2">
	                      <span className="text-[10px] text-slate-400 font-semibold">{semanticSummary.total} 个空间</span>
	                      {expandedSemanticDsId === ds.data_source_id
	                        ? <ChevronUp className="w-3.5 h-3.5 text-slate-400" />
	                        : <ChevronDown className="w-3.5 h-3.5 text-slate-400" />}
	                    </span>
	                  </button>

	                  {expandedSemanticDsId === ds.data_source_id && (
	                    <div className="p-3 border-t border-slate-100 dark:border-slate-800 text-[10px] space-y-3">
	                      <div className="flex items-center justify-between gap-3">
	                        <span className="text-slate-400">业务描述、表范围、字段确认和版本发布集中在语义空间内维护。</span>
	                        {isSystemAdmin && (
	                          <button
	                            type="button"
	                            onClick={() => openCreateSpaceForm(ds.data_source_id)}
	                            className="text-indigo-650 hover:text-indigo-800 dark:text-indigo-400 dark:hover:text-indigo-300 font-bold flex items-center gap-1 cursor-pointer shrink-0"
	                          >
	                            + 新增语义空间
	                          </button>
	                        )}
	                      </div>

	                      {deletingSpace?.dsId === ds.data_source_id && (
	                        <div className="p-4 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900 rounded-xl space-y-3">
	                          <div className="flex gap-2 text-red-700 dark:text-red-400">
	                            <ShieldAlert className="w-5 h-5 shrink-0" />
	                            <div className="space-y-1">
	                              <span className="font-bold">删除不可逆！</span>
	                              <p className="text-[11px] opacity-90">
	                                确认删除语义空间 <code>{deletingSpace.space.name}</code>？此操作会删除该空间的字段确认状态和版本记录。
	                              </p>
	                            </div>
	                          </div>
	                          <div className="flex gap-2 pl-7">
	                            <button
	                              type="button"
	                              onClick={() => handleDeleteSpace(deletingSpace.dsId, deletingSpace.space)}
	                              className="bg-red-600 hover:bg-red-700 text-white font-bold px-4 py-2 rounded-lg transition-colors cursor-pointer"
	                            >
	                              确认删除
	                            </button>
	                            <button
	                              type="button"
	                              onClick={() => setDeletingSpace(null)}
	                              className="border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 px-4 py-2 rounded-lg font-semibold hover:bg-slate-50 dark:hover:bg-slate-800/40"
	                            >
	                              取消
	                            </button>
	                          </div>
	                        </div>
	                      )}

	                      <div className="grid grid-cols-2 sm:grid-cols-6 gap-3">
	                        <div>
	                          <span className="block text-slate-400">空间数</span>
	                          <span className="font-bold text-slate-700 dark:text-slate-300">{semanticSummary.total}</span>
	                        </div>
	                        <div>
	                          <span className="block text-slate-400">已启用</span>
	                          <span className="font-bold text-slate-700 dark:text-slate-300">{semanticSummary.enabledCount}</span>
	                        </div>
	                        <div>
	                          <span className="block text-slate-400">配置中</span>
	                          <span className="font-bold text-slate-700 dark:text-slate-300">{semanticSummary.configuringCount}</span>
	                        </div>
	                        <div>
	                          <span className="block text-slate-400">纳入表</span>
	                          <span className="font-bold text-slate-700 dark:text-slate-300">{semanticSummary.tableCount}</span>
	                        </div>
	                        <div>
	                          <span className="block text-slate-400">字段数</span>
	                          <span className="font-bold text-slate-700 dark:text-slate-300">{semanticSummary.fieldCount}</span>
	                        </div>
	                        <div>
	                          <span className="block text-slate-400">待确认</span>
	                          <span className="font-bold text-slate-700 dark:text-slate-300">{semanticSummary.pendingFieldCount}</span>
	                        </div>
	                      </div>

	                      {showCreateSpaceDsId === ds.data_source_id && (
	                        <form onSubmit={handleCreateSpace} className="p-3 bg-white dark:bg-slate-850 border border-slate-200 dark:border-slate-800 rounded-lg space-y-3">
	                          <div className="flex items-center justify-between">
	                            <div className="text-xs font-bold text-slate-850 dark:text-slate-200">新建语义空间</div>
	                            <button
	                              type="button"
	                              onClick={resetCreateSpaceForm}
	                              className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 cursor-pointer"
	                            >
	                              <X className="w-3.5 h-3.5" />
	                            </button>
	                          </div>
	                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
	                            <div>
	                              <label className="block text-[10px] text-slate-400 font-semibold mb-1">空间名称 <span className="text-red-400">*</span></label>
	                              <input required type="text" placeholder="例如：财务审计域" value={newSpaceName}
	                                onChange={e => setNewSpaceName(e.target.value)}
	                                className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500" />
	                            </div>
	                            <div>
	                              <label className="block text-[10px] text-slate-400 font-semibold mb-1">首批纳入表（可选）</label>
	                              <textarea rows={2} placeholder="orders&#10;order_items" value={newSpaceTablesText}
	                                onChange={e => setNewSpaceTablesText(e.target.value)}
	                                className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500 resize-none" />
	                            </div>
	                            <div className="sm:col-span-2">
	                              <label className="block text-[10px] text-slate-400 font-semibold mb-1">业务背景描述 <span className="text-red-400">*</span></label>
	                              <textarea required rows={3} placeholder="说明该空间覆盖的业务、口径边界、常见分析问题。" value={newSpaceDesc}
	                                onChange={e => setNewSpaceDesc(e.target.value)}
	                                className="w-full bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none focus:border-indigo-500 resize-none" />
	                            </div>
	                          </div>
	                          <div className="flex gap-2 justify-end">
	                            <button type="button" onClick={resetCreateSpaceForm}
	                              className="px-3 py-1.5 rounded border border-slate-200 dark:border-slate-750 text-slate-500 dark:text-slate-400 hover:bg-slate-50">
	                              取消
	                            </button>
	                            <button type="submit"
	                              className="bg-indigo-600 hover:bg-indigo-700 text-white font-bold px-4 py-1.5 rounded-lg shadow-sm">
	                              创建语义空间
	                            </button>
	                          </div>
	                        </form>
	                      )}

	                      {spaces.length === 0 && (
	                        <div className="text-center py-3 border border-dashed border-slate-200 dark:border-slate-800 rounded-lg text-slate-400">
	                          暂无语义空间。
	                        </div>
	                      )}

	                      {spaces.length > 0 && (
	                        <div className="space-y-2">
	                          {spaces.map(space => {
	                            const tableCount = space.entities?.length || 0;
	                            const fieldCount = space.entities?.reduce((acc, ent) => acc + (ent.fields?.length || 0), 0) || 0;
	                            const pendingCount = space.entities?.reduce(
	                              (acc, ent) => acc + (ent.fields?.filter(field => (field.status || 'confirmed') === 'pending').length || 0),
	                              0
	                            ) || 0;
	                            const isEnabled = fieldCount > 0;
	                            const updatedAt = space.published_at || space.created_at;

	                            return (
	                              <div
	                                key={space.space_id}
	                                id={`semantic-space-${space.space_id}`}
	                                className={`grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-3 p-3 border rounded-lg transition-all ${
	                                  highlightedSpaceId === space.space_id
	                                    ? 'bg-indigo-50/80 dark:bg-indigo-950/20 border-indigo-400 dark:border-indigo-600 ring-2 ring-indigo-300/60 dark:ring-indigo-500/30 animate-pulse'
	                                    : 'bg-white dark:bg-slate-900 border-slate-250/60 dark:border-slate-800 hover:border-indigo-300 dark:hover:border-indigo-900'
	                                }`}
	                              >
	                                <div className="space-y-2 text-left min-w-0">
	                                  <div className="flex flex-wrap items-center gap-2">
	                                    <span className="font-bold text-slate-800 dark:text-slate-200">{space.name}</span>
	                                    <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 border border-slate-200 dark:border-slate-750">
	                                      v{space.version || 1}
	                                    </span>
	                                    <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
	                                      isEnabled
	                                        ? 'bg-green-50 dark:bg-green-950/30 text-green-700 dark:text-green-400 border border-green-200 dark:border-green-900/30'
	                                        : 'bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-900/30'
	                                    }`}>
	                                      {isEnabled ? '已启用' : '配置中'}
	                                    </span>
	                                  </div>
	                                  <div className="text-[10px] text-slate-550 dark:text-slate-400 leading-relaxed">
	                                    {space.description || '未填写业务背景描述'}
	                                  </div>
	                                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-slate-400">
	                                    <span>{tableCount} 张表</span>
	                                    <span>{fieldCount} 个字段</span>
	                                    {pendingCount > 0 && <span>{pendingCount} 个待确认字段</span>}
	                                    {updatedAt && <span>{new Date(updatedAt).toLocaleString()}</span>}
	                                  </div>
	                                  {space.entities.length > 0 && (
	                                    <div className="flex flex-wrap gap-1.5">
	                                      {space.entities.slice(0, 8).map(entity => (
	                                        <span key={entity.entity_id} className="px-1.5 py-0.5 rounded bg-indigo-50 dark:bg-indigo-950/20 text-indigo-650 dark:text-indigo-400 font-mono">
	                                          {entity.physical_table}
	                                        </span>
	                                      ))}
	                                      {space.entities.length > 8 && (
	                                        <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-400">
	                                          +{space.entities.length - 8}
	                                        </span>
	                                      )}
	                                    </div>
	                                  )}
	                                </div>
	                                <div className="flex sm:flex-col items-center sm:items-end justify-end gap-2">
	                                  <button
	                                    type="button"
	                                    onClick={() => onOpenSpace(ds.data_source_id, space.space_id)}
	                                    className="border border-slate-200 dark:border-slate-750 bg-white dark:bg-slate-950 text-slate-650 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-850 px-3 py-1.5 rounded-lg font-bold transition-all cursor-pointer"
	                                  >
	                                    {isEnabled ? '打开' : '配置'}
	                                  </button>
	                                  {isSystemAdmin && (
	                                    <button
	                                      type="button"
	                                      onClick={() => setDeletingSpace({ dsId: ds.data_source_id, space })}
	                                      className="border border-slate-200 dark:border-slate-750 bg-white dark:bg-slate-950 text-red-500 hover:bg-red-50 dark:hover:bg-red-950/20 px-3 py-1.5 rounded-lg font-bold transition-all cursor-pointer"
	                                    >
	                                      删除
	                                    </button>
	                                  )}
	                                </div>
	                              </div>
	                            );
	                          })}
	                        </div>
	                      )}

	                      {associatedPacks.length > 0 && (
	                        <div className="pt-3 mt-1 border-t border-slate-100 dark:border-slate-800/60">
	                          <span className="block text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-1.5">
	                            受影响领域包
	                          </span>
	                          <div className="flex flex-wrap gap-1.5">
	                            {associatedPacks.map(({ pack, deployments }) => (
	                              <span key={pack.pack_id} className="flex items-center gap-1 px-2 py-1 rounded-full bg-emerald-50 dark:bg-emerald-950/20 text-emerald-655 dark:text-green-400 border border-emerald-250 dark:border-emerald-900 text-[10px] font-medium">
	                                <Package className="w-3 h-3" />
	                                {pack.name}
	                                <span className="opacity-60">· {deployments.length} 个部署</span>
	                              </span>
	                            ))}
	                          </div>
	                        </div>
	                      )}
	                    </div>
	                  )}
	                </div>

              </div>
            );
          })}
        </div>
      ))}
    </ManagementPage>
  );
};
