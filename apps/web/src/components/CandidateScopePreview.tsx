import React, { useEffect, useState } from 'react';
import { CheckCircle, AlertTriangle, XCircle, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react';
import { api } from '../api';
import type { ScopeCandidateTable } from '../api';

interface CandidateScopePreviewProps {
  packId: string;
  dataSourceId: string;
  // Fired whenever the final table selection changes (recommended tier +
  // any ambiguous tables the admin has opted back in). Pass a stable
  // setState function from the parent.
  onSelectionChange: (tables: string[]) => void;
  // Fired whenever the recommendation fetch starts/stops, so the parent can
  // disable the submit button until a real selection is known.
  onLoadingChange?: (loading: boolean) => void;
}

// Preview/confirm step shown when a data source has zero existing semantic
// spaces: instead of silently sweeping every scanned table into a blunt
// implicit space, show the pack-aware candidate scope and let the admin
// confirm the "ambiguous" tier before committing (recommended tier is
// auto-included; excluded tier is collapsed out of the way by default).
export const CandidateScopePreview: React.FC<CandidateScopePreviewProps> = ({
  packId,
  dataSourceId,
  onSelectionChange,
  onLoadingChange
}) => {
  const [loading, setLoading] = useState(true);
  const [candidates, setCandidates] = useState<ScopeCandidateTable[]>([]);
  const [ambiguousOn, setAmbiguousOn] = useState<Set<string>>(new Set());
  const [showExcluded, setShowExcluded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    onLoadingChange?.(true);
    setCandidates([]);
    setAmbiguousOn(new Set());
    setShowExcluded(false);
    api.recommendScope(packId, dataSourceId)
      .then(res => {
        if (cancelled) return;
        setCandidates(res);
      })
      .catch(err => {
        console.error('Failed to load candidate scope:', err);
        if (!cancelled) setCandidates([]);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
        onLoadingChange?.(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [packId, dataSourceId]);

  useEffect(() => {
    const recommended = candidates.filter(c => c.tier === 'recommended').map(c => c.table_name);
    const ambiguousSelected = candidates
      .filter(c => c.tier === 'ambiguous' && ambiguousOn.has(c.table_name))
      .map(c => c.table_name);
    onSelectionChange([...recommended, ...ambiguousSelected]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidates, ambiguousOn]);

  if (loading) {
    return (
      <div className="flex items-center gap-1.5 text-[11px] text-slate-400 border border-dashed border-slate-200 dark:border-slate-700 rounded-lg p-2.5 justify-center">
        <RefreshCw className="w-3 h-3 animate-spin" />
        正在根据领域包生成候选范围…
      </div>
    );
  }

  if (candidates.length === 0) {
    return (
      <div className="text-[11px] text-slate-400 border border-dashed border-slate-200 dark:border-slate-700 rounded-lg p-2.5 text-center">
        该数据源尚无业务语义空间，点击「启用适配」将自动创建一个覆盖该连接的默认语义空间，无需提前手动创建。
      </div>
    );
  }

  const recommended = candidates.filter(c => c.tier === 'recommended');
  const ambiguous = candidates.filter(c => c.tier === 'ambiguous');
  const excluded = candidates.filter(c => c.tier === 'excluded');

  return (
    <div className="space-y-2">
      <p className="text-[10px] text-slate-400 leading-relaxed">
        系统已根据领域包字段证据生成候选范围：推荐表将自动纳入，存疑表请确认是否加入。
      </p>
      <div className="max-h-40 overflow-y-auto border border-slate-200 dark:border-slate-700 rounded-lg divide-y divide-slate-100 dark:divide-slate-800/60 bg-slate-50 dark:bg-slate-800">
        {recommended.map(c => (
          <div key={c.table_name} title={c.reason} className="flex flex-col gap-0.5 px-2.5 py-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-xs font-mono text-slate-800 dark:text-slate-200 truncate">
                <CheckCircle className="w-3 h-3 text-green-500 shrink-0" />
                {c.table_name}
              </span>
              <span className="shrink-0 text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-green-50 dark:bg-green-950/30 text-green-600 dark:text-green-400 border border-green-100 dark:border-green-900/40">
                推荐
              </span>
            </div>
            <p className="text-[10px] text-slate-400 truncate pl-4">{c.reason}</p>
          </div>
        ))}
        {ambiguous.map(c => {
          const checked = ambiguousOn.has(c.table_name);
          return (
            <label
              key={c.table_name}
              title={c.reason}
              className="flex flex-col gap-0.5 px-2.5 py-1.5 cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-850 select-none"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-xs font-mono text-slate-800 dark:text-slate-200 truncate">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => {
                      setAmbiguousOn(prev => {
                        const next = new Set(prev);
                        if (next.has(c.table_name)) {
                          next.delete(c.table_name);
                        } else {
                          next.add(c.table_name);
                        }
                        return next;
                      });
                    }}
                    className="rounded text-indigo-600 shrink-0"
                  />
                  <AlertTriangle className="w-3 h-3 text-amber-500 shrink-0" />
                  {c.table_name}
                </span>
                <span className="shrink-0 text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-amber-50 dark:bg-amber-950/30 text-amber-600 dark:text-amber-400 border border-amber-100 dark:border-amber-900/40">
                  存疑
                </span>
              </div>
              <p className="text-[10px] text-slate-400 truncate pl-5">{c.reason}</p>
            </label>
          );
        })}
      </div>
      {excluded.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setShowExcluded(s => !s)}
            className="flex items-center gap-0.5 text-[10px] text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
          >
            {showExcluded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            {showExcluded ? '收起' : '展开'}已排除表 ({excluded.length})
          </button>
          {showExcluded && (
            <div className="mt-1 max-h-24 overflow-y-auto border border-slate-100 dark:border-slate-800 rounded-lg divide-y divide-slate-100 dark:divide-slate-800/60">
              {excluded.map(c => (
                <div
                  key={c.table_name}
                  title={c.reason}
                  className="flex items-center gap-1.5 px-2.5 py-1 text-[10px] text-slate-400"
                >
                  <XCircle className="w-3 h-3 text-rose-400 shrink-0" />
                  <span className="font-mono truncate">{c.table_name}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
