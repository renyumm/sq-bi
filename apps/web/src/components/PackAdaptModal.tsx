import React, { useEffect, useState } from 'react';
import { CheckCircle, AlertTriangle, Clock, ChevronRight, Database, Plus, RefreshCw, X } from 'lucide-react';
import { api } from '../api';
import type { DataSource, DeploymentListItem, SemanticSpace } from '../api';
import { CandidateScopePreview } from './CandidateScopePreview';

interface PackAdaptModalProps {
  packId: string;
  packName: string;
  dataSources: DataSource[];
  deployments: DeploymentListItem[];
  userContext: any;
  onClose: () => void;
  onSelectDeployment: (deploymentId: string) => void;
  onNotify?: (type: 'success' | 'error' | 'info', message: string) => void;
}

export const PackAdaptModal: React.FC<PackAdaptModalProps> = ({
  packId,
  packName,
  dataSources,
  deployments,
  userContext,
  onClose,
  onSelectDeployment,
  onNotify
}) => {
  const [selectedSourceId, setSelectedSourceId] = useState(dataSources[0]?.data_source_id || '');
  const [availableSpaces, setAvailableSpaces] = useState<SemanticSpace[]>([]);
  const [selectedSpaceIds, setSelectedSpaceIds] = useState<string[]>([]);
  const [isCreating, setIsCreating] = useState(false);
  // Candidate table selection for the implicit-space-creation path (only
  // relevant when availableSpaces.length === 0 for the selected source).
  const [implicitSpaceTables, setImplicitSpaceTables] = useState<string[]>([]);
  const [isScopeLoading, setIsScopeLoading] = useState(false);
  const [projections, setProjections] = useState<Record<string, { runtime_asset_count: number; exclusion_reasons: string[] }>>({});

  useEffect(() => {
    if (deployments.length === 0) return;

    const enrich = async () => {
      const uniquePairs = new Map<string, { data_source_id: string }>();
      deployments.forEach(dep => {
        const key = dep.data_source_id;
        if (!uniquePairs.has(key)) {
          uniquePairs.set(key, { data_source_id: dep.data_source_id });
        }
      });

      const projectionsMap: Record<string, { runtime_asset_count: number; exclusion_reasons: string[] }> = {};

      await Promise.all(
        Array.from(uniquePairs.values()).map(async (pair) => {
          try {
            const proj = await api.getRuntimeAssetProjection({
              data_source_id: pair.data_source_id,
              environment: 'default'
            });
            if (proj.deployments) {
              proj.deployments.forEach(d => {
                projectionsMap[d.deployment_id] = {
                  runtime_asset_count: d.effective_asset_count || 0,
                  exclusion_reasons: d.excluded && d.exclusion_reason ? [d.exclusion_reason] : []
                };
              });
            }
          } catch (err) {
            console.error('Failed to fetch projection for PackAdaptModal:', pair, err);
          }
        })
      );

      setProjections(prev => ({ ...prev, ...projectionsMap }));
    };

    enrich();
  }, [deployments]);

  useEffect(() => {
    if (!selectedSourceId) {
      Promise.resolve().then(() => {
        setAvailableSpaces([]);
        setSelectedSpaceIds([]);
      });
      return;
    }
    api.listSemanticSpaces(selectedSourceId).then(spaces => {
      setAvailableSpaces(spaces);
      // Pack-first default: let the backend build a pack-specific scope from
      // the real scanned catalog. Never silently bind the first unrelated space.
      setSelectedSpaceIds([]);
    }).catch(err => {
      console.error('Failed to list semantic spaces:', err);
      Promise.resolve().then(() => {
        setAvailableSpaces([]);
        setSelectedSpaceIds([]);
      });
    });
  }, [selectedSourceId]);

  const enrichedDeployments = deployments.map(dep => {
    const proj = projections[dep.deployment_id];
    return {
      ...dep,
      runtime_asset_count: proj ? proj.runtime_asset_count : (dep.runtime_asset_count || 0),
      exclusion_reasons: proj ? proj.exclusion_reasons : (dep.exclusion_reasons || [])
    };
  });
  const dataSourceNameById = new Map(dataSources.map(source => [source.data_source_id, source.name]));

  const handleCreate = async () => {
    if (!selectedSourceId) return;
    setIsCreating(true);
    try {
      const res = await api.createDeployment({
        pack_id: packId,
        data_source_id: selectedSourceId,
        confirmed_by: userContext.display_name || userContext.user_id,
        semantic_space_ids: selectedSpaceIds,
        ...(selectedSpaceIds.length === 0 ? { implicit_space_tables: implicitSpaceTables } : {})
      });
      if (res.auto_created_semantic_space_id) {
        onNotify?.('info', '系统已根据领域包的真实字段映射创建专属语义空间。');
      }
      onSelectDeployment(res.deployment.deployment_id);
    } catch (e) {
      onNotify?.('error', '创建适配关系失败：' + (e instanceof Error ? e.message : '未知错误'));
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-xl w-full max-w-md max-h-[85vh] overflow-y-auto p-6 space-y-5">
        <div className="flex justify-between items-start">
          <div>
            <h2 className="text-base font-bold text-slate-900 dark:text-white">适配语义空间</h2>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{packName}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X className="w-4 h-4" />
          </button>
        </div>

        {enrichedDeployments.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-xs font-bold text-slate-700 dark:text-slate-300">已有适配记录</h3>
            <div className="divide-y divide-slate-100 dark:divide-slate-800/60 border border-slate-100 dark:border-slate-800 rounded-lg overflow-hidden">
              {enrichedDeployments.map(dep => {
                const unavailable = dep.binding_status === 'unavailable';
                const spaceLabel = dep.semantic_space_names?.join('、')
                  || dep.unavailable_semantic_space_ids?.map(id => `已删除空间 ${id}`).join('、')
                  || '系统自动范围';
                return (
                <div
                  key={dep.deployment_id}
                  onClick={() => onSelectDeployment(dep.deployment_id)}
                  className={`flex justify-between items-center px-3 py-2.5 cursor-pointer transition-colors ${unavailable ? 'bg-rose-50/60 hover:bg-rose-50 dark:bg-rose-950/10' : 'hover:bg-slate-50/80 dark:hover:bg-slate-850'}`}
                >
                  <div className="flex flex-col text-xs space-y-1">
                    <div className="flex items-center gap-1.5 font-bold text-slate-850 dark:text-slate-200">
                      <Database className="w-3.5 h-3.5 text-indigo-500" />
                      <span>{spaceLabel}</span>
                      <span className="text-[10px] px-1 py-0.2 bg-slate-100 dark:bg-slate-800 rounded font-normal text-slate-500">v{dep.pack_version || '1.0.0'}</span>
                    </div>
                    <span className="text-[10px] text-slate-400 dark:text-slate-500 mt-0.5">
                      数据源：{dataSourceNameById.get(dep.data_source_id) || dep.data_source_id}
                    </span>
                    {unavailable && <span className="text-[10px] font-bold text-rose-600 dark:text-rose-400">历史绑定的语义空间已删除，此适配不可用</span>}
                    {dep.exclusion_reasons && dep.exclusion_reasons.length > 0 && (
                      <span className="text-[9px] text-rose-500 dark:text-rose-400 mt-0.5 font-semibold">
                        不可见原因: {dep.exclusion_reasons.join(', ')}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    <div className="flex flex-col items-end gap-1">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] font-mono text-slate-500">对齐 {Math.round(dep.coverage * 100)}%</span>
                        {dep.validation_status === 'ready' ? (
                          <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[9px] font-bold bg-green-50 dark:bg-green-950/30 text-green-600 dark:text-green-400 border border-green-100 dark:border-green-900/40">
                            <CheckCircle className="w-2.5 h-2.5" />
                            Ready
                          </span>
                        ) : dep.validation_status === 'failed' ? (
                          <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[9px] font-bold bg-rose-50 dark:bg-rose-950/30 text-rose-600 dark:text-rose-400 border border-rose-100 dark:border-rose-900/40">
                            <AlertTriangle className="w-2.5 h-2.5" />
                            Failed
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[9px] font-bold bg-amber-50 dark:bg-amber-950/30 text-amber-600 dark:text-amber-400 border border-amber-100 dark:border-amber-900/40">
                            <Clock className="w-2.5 h-2.5" />
                            待对齐
                          </span>
                        )}

                        {dep.is_active ? (
                          <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[9px] font-bold bg-blue-50 dark:bg-blue-950/30 text-blue-600 dark:text-blue-400 border border-blue-100 dark:border-blue-900/40">
                            已激活
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[9px] font-bold bg-slate-100 dark:bg-slate-800 text-slate-500 border border-slate-200">
                            未激活
                          </span>
                        )}
                        {unavailable && (
                          <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[9px] font-bold bg-rose-100 text-rose-700 dark:bg-rose-950/30 dark:text-rose-300">
                            不可用
                          </span>
                        )}
                      </div>

                      <span className="text-[10px] text-slate-500 dark:text-slate-400">
                        有效资产: <span className="font-bold text-slate-700 dark:text-slate-200">{dep.runtime_asset_count || 0}</span>
                      </span>
                    </div>
                    <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
                  </div>
                </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="space-y-3.5">
          <h3 className="text-xs font-bold text-slate-700 dark:text-slate-300 flex items-center gap-1">
            <Plus className="w-3.5 h-3.5" />
            新增语义空间适配
          </h3>

          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-350 mb-1">数据源</label>
            <select
              value={selectedSourceId}
              onChange={e => setSelectedSourceId(e.target.value)}
              className="w-full bg-slate-50 dark:bg-slate-800 text-xs px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 outline-none text-slate-800 dark:text-slate-200"
            >
              {dataSources.map(ds => (
                <option key={ds.data_source_id} value={ds.data_source_id}>{ds.name} ({ds.database_type})</option>
              ))}
            </select>
          </div>

          {selectedSourceId && (
            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-350 mb-1">适配范围</label>
              <label className="mb-2 flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50/60 dark:border-indigo-900 dark:bg-indigo-950/20 p-2.5 text-xs cursor-pointer">
                <input type="radio" checked={selectedSpaceIds.length === 0} onChange={() => setSelectedSpaceIds([])} />
                <span><strong>自动适配并创建专属语义空间</strong><span className="block mt-0.5 text-[10px] text-slate-500">根据领域包和真实扫描字段新建范围，不复用已删除或不相关空间</span></span>
              </label>
              {selectedSpaceIds.length === 0 && (
                <CandidateScopePreview
                  packId={packId}
                  dataSourceId={selectedSourceId}
                  onSelectionChange={setImplicitSpaceTables}
                  onLoadingChange={setIsScopeLoading}
                />
              )}
              {availableSpaces.length > 0 && (
                <div className="mt-2 space-y-1.5 max-h-32 overflow-y-auto border border-slate-200 dark:border-slate-700 rounded-lg p-2.5 bg-slate-50 dark:bg-slate-800 text-xs">
                  <p className="text-[10px] text-slate-400 mb-1">选择已有语义空间（不会自动扩展其范围）</p>
                  {availableSpaces.map(space => {
                    const isChecked = selectedSpaceIds.includes(space.space_id);
                    return (
                      <label key={space.space_id} className="flex items-center gap-2 cursor-pointer py-0.5 hover:text-indigo-650 text-slate-850 dark:text-slate-250 select-none">
                        <input
                          type="radio"
                          checked={isChecked}
                          onChange={() => setSelectedSpaceIds([space.space_id])}
                          className="rounded text-indigo-600"
                        />
                        <span>{space.name}</span>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-3 pt-2 border-t border-slate-100 dark:border-slate-800">
          <button
            onClick={onClose}
            className="border border-slate-200 dark:border-slate-800 px-4 py-2 rounded-lg text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800"
          >
            取消
          </button>
          <button
            onClick={handleCreate}
            disabled={isCreating || !selectedSourceId || (selectedSpaceIds.length === 0 && isScopeLoading)}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 text-white text-xs font-semibold px-4 py-2 rounded-lg transition-colors flex items-center gap-1"
          >
            {isCreating && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
            启用适配
          </button>
        </div>
      </div>
    </div>
  );
};
