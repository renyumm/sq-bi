import React, { useEffect, useState } from 'react';
import { RefreshCw, CheckCircle, AlertTriangle, TableProperties } from 'lucide-react';
import { api } from '../api';
import type { ScanStatus, ScanPhase } from '../api';

interface SchemaScanProgressProps {
  dsId: string;
  initialScan: ScanStatus;
  onComplete?: (scan: ScanStatus) => void;
  onViewProfile?: () => void;
}

const PHASE_CONFIGS: Record<ScanPhase, { title: string; progress: number; color: string; desc: string }> = {
  pending: {
    title: '初始化扫描',
    progress: 10,
    color: 'bg-indigo-500',
    desc: '准备建立安全的数据库连接...'
  },
  phase_one: {
    title: '第一阶段：元数据内省',
    progress: 35,
    color: 'bg-indigo-500',
    desc: '正在快速读取所有表结构、列信息、约束以及注释信息...'
  },
  phase_two: {
    title: '第二阶段：数据采样与特征提取',
    progress: 65,
    color: 'bg-indigo-650',
    desc: '仅对AI候选表读取脱敏样本、枚举值分布、唯一性与时效分析...'
  },
  discovering: {
    title: '第三阶段：AI 语义发现与分类',
    progress: 88,
    color: 'bg-violet-600 animate-pulse',
    desc: 'AI 引擎正在分析物理结构并将其聚类为业务“语义空间”...'
  },
  done: {
    title: '扫描分析完成',
    progress: 100,
    color: 'bg-green-600',
    desc: '数据库语义图谱生成成功，已存储至 SQLite 语义库中。'
  },
  failed: {
    title: '扫描失败',
    progress: 100,
    color: 'bg-red-650',
    desc: '数据库连接中断或模型计算超时，请检查配置。'
  }
};

export const SchemaScanProgress: React.FC<SchemaScanProgressProps> = ({
  dsId,
  initialScan,
  onComplete,
  onViewProfile
}) => {
  const [scan, setScan] = useState<ScanStatus>(initialScan);
  const currentPhase = scan.phase || 'pending';
  const config = PHASE_CONFIGS[currentPhase];

  useEffect(() => {
    setScan(initialScan);
  }, [initialScan]);

  useEffect(() => {
    if (currentPhase === 'done' || currentPhase === 'failed') {
      if (onComplete) onComplete(scan);
      return;
    }

    const interval = setInterval(async () => {
      try {
        const updated = await api.getScanStatus(dsId, scan.scan_id);
        setScan(updated);
        if (updated.phase === 'done' || updated.phase === 'failed') {
          clearInterval(interval);
          if (onComplete) onComplete(updated);
        }
      } catch (err) {
        console.error('Failed to poll scan status:', err);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [currentPhase, dsId, onComplete, scan]);

  return (
    <div className="bg-slate-50 dark:bg-slate-900/50 border border-slate-200/80 dark:border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
      <div className="flex justify-between items-start">
        <div className="space-y-1">
          <h4 className="text-xs font-bold text-slate-800 dark:text-slate-250 flex items-center gap-1.5">
            {currentPhase !== 'done' && currentPhase !== 'failed' && (
              <RefreshCw className="w-3.5 h-3.5 text-indigo-500 animate-spin" />
            )}
            {currentPhase === 'done' && <CheckCircle className="w-3.5 h-3.5 text-green-500" />}
            {currentPhase === 'failed' && <AlertTriangle className="w-3.5 h-3.5 text-red-500" />}
            {config.title}
          </h4>
          <p className="text-[10px] text-slate-400 dark:text-slate-500">
            扫描 ID: <span className="font-mono">{scan.scan_id}</span>
          </p>
        </div>
        {currentPhase === 'done' && onViewProfile && (
          <button
            onClick={onViewProfile}
            className="bg-indigo-600 hover:bg-indigo-700 text-white text-[10px] font-bold px-3 py-1.5 rounded-lg transition-colors shadow-sm cursor-pointer"
          >
            查看语义图谱
          </button>
        )}
      </div>

      {/* Progress bar */}
      <div className="space-y-1.5">
        <div className="w-full bg-slate-200 dark:bg-slate-800 h-2 rounded-full overflow-hidden">
          <div 
            className={`h-full transition-all duration-500 rounded-full ${config.color}`}
            style={{ width: `${config.progress}%` }}
          />
        </div>
        <p className="text-[11px] text-slate-650 dark:text-slate-400">
          {scan.progress_message || config.desc}
        </p>
      </div>

      {/* Results summary when completed */}
      {currentPhase === 'done' && (
        <div className="pt-3 border-t border-slate-200 dark:border-slate-800 grid grid-cols-1 sm:grid-cols-4 gap-3 text-center">
          <div className="bg-white dark:bg-slate-850 p-2.5 rounded-lg border border-slate-100 dark:border-slate-800/60 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
            <span className="block text-[10px] text-slate-400 mb-0.5">内省表总数</span>
            <span className="text-sm font-bold text-slate-855 dark:text-slate-200 flex items-center justify-center gap-1">
              <TableProperties className="w-3.5 h-3.5 text-indigo-400" />
              {scan.table_count}
            </span>
          </div>
          
          <div className="bg-white dark:bg-slate-850 p-2.5 rounded-lg border border-slate-105 dark:border-slate-800/60 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
            <span className="block text-[10px] text-green-550 dark:text-green-500 font-semibold mb-0.5">推荐纳入 (AI)</span>
            <span className="text-sm font-bold text-green-600 dark:text-green-400">
              {scan.recommendation_counts?.recommended_include || 0}
            </span>
          </div>

          <div className="bg-white dark:bg-slate-850 p-2.5 rounded-lg border border-slate-105 dark:border-slate-800/60 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
            <span className="block text-[10px] text-amber-550 dark:text-amber-500 font-semibold mb-0.5">可能相关</span>
            <span className="text-sm font-bold text-amber-600 dark:text-amber-400">
              {scan.recommendation_counts?.possibly_relevant || 0}
            </span>
          </div>

          <div className="bg-white dark:bg-slate-850 p-2.5 rounded-lg border border-slate-105 dark:border-slate-800/60 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
            <span className="block text-[10px] text-slate-405 mb-0.5">噪声排除</span>
            <span className="text-sm font-bold text-slate-500 dark:text-slate-400">
              {scan.recommendation_counts?.not_relevant || 0}
            </span>
          </div>
        </div>
      )}

      {currentPhase === 'failed' && scan.error && (
        <div className="p-3 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900 rounded-lg text-xs text-red-650 dark:text-red-400">
          <strong>错误详情:</strong> {scan.error}
        </div>
      )}
    </div>
  );
};
