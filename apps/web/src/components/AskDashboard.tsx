import React, { useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Send,
  RefreshCw,
  AlertTriangle
} from 'lucide-react';
import { QueryResultView } from './QueryResultView';
import { HarnessResultView } from './HarnessResultView';
import { api } from '../api';
import type { SemanticField, CallableAsset } from '../api';

interface AskDashboardProps {
  messages: any[];
  userRoleIds: string[];
  fields: SemanticField[];
  darkMode: boolean;

  queryText: string;
  setQueryText: (text: string) => void;
  handleSend: () => void;

  showMetricDropdown: boolean;
  filteredMetrics: CallableAsset[];
  selectMetric: (metric: CallableAsset) => void;

  showSkillDropdown: boolean;
  filteredSkills: CallableAsset[];
  selectSkill: (skill: CallableAsset) => void;

  showReportDropdown: boolean;
  filteredReports: CallableAsset[];
  selectReport: (report: CallableAsset) => void;

  setActiveLineage: (lineage: any) => void;
  setShowLineageDrawer: (show: boolean) => void;
  openMetricDrawerById: (id: string) => void;
  onClarifySubmit?: (interpretation: string) => void;
  onCorrectSubmit?: (correctionText: string) => void;
  onSaveMetric?: (payload: any) => Promise<void>;
  currentUserId?: string;
  onAdoptGap?: (dsId: string, spaceId: string, fieldId: string) => void;

  // Harness Planning Loop props
  isHarnessMode: boolean;
  setIsHarnessMode: (harness: boolean) => void;
  onHarnessClarifySubmit?: (runId: string, clarifyText: string) => void;
  onHarnessConfirmSubmit?: (runId: string, token: string) => void;
  onHarnessCancel?: () => void;
}

export const AskDashboard: React.FC<AskDashboardProps> = ({
  messages,
  userRoleIds,
  fields,
  darkMode,
  queryText,
  setQueryText,
  handleSend,
  showMetricDropdown,
  filteredMetrics,
  selectMetric,
  showSkillDropdown,
  filteredSkills,
  selectSkill,
  showReportDropdown,
  filteredReports,
  selectReport,
  setActiveLineage,
  setShowLineageDrawer,
  openMetricDrawerById,
  onClarifySubmit,
  onCorrectSubmit,
  onSaveMetric,
  currentUserId,
  onAdoptGap,
  isHarnessMode,
  setIsHarnessMode,
  onHarnessClarifySubmit,
  onHarnessConfirmSubmit,
  onHarnessCancel
}) => {
  void isHarnessMode;
  void setIsHarnessMode;
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-slate-50 dark:bg-slate-950 text-left">
      {/* Message History flow */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Dashboard Home Banner when no custom queries */}
        {messages.length === 1 && (
          <div className="max-w-3xl mx-auto my-6 space-y-6">
            <div className="bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 p-6 rounded-2xl shadow-sm text-center space-y-2">
              <h2 className="text-lg font-bold text-slate-855 dark:text-white">欢迎进入 SQ-BI 精准问数平台</h2>
              <p className="text-xs text-slate-500 dark:text-slate-400 max-w-lg mx-auto leading-relaxed">
                本系统严格保障财务与指标计算逻辑的确定性，屏蔽大模型直接生成 SQL 的幻觉风险。所有数据均出自官方指标或认证 Skill，并强加 RLS 行级隔离。
              </p>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-6 text-left pt-4">
                <div className="bg-slate-50 dark:bg-slate-800/40 p-4 rounded-xl border border-slate-100 dark:border-slate-800/80">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-indigo-650 dark:text-indigo-400 mb-2">🔥 热门指标推荐</h3>
                  <ul className="text-xs space-y-2 text-slate-600 dark:text-slate-350">
                    <li><span className="text-slate-400 font-mono">@发货申请量</span> 运单发货申请总数</li>
                    <li><span className="text-slate-400 font-mono">@准时到货率</span> 承运商准时送达百分比</li>
                    <li><span className="text-slate-400 font-mono">@未签收单量</span> 仍处于在途状态的运单数</li>
                  </ul>
                </div>

                <div className="bg-slate-50 dark:bg-slate-800/40 p-4 rounded-xl border border-slate-100 dark:border-slate-800/80">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-indigo-650 dark:text-indigo-400 mb-2">⚡ 快速调用技能</h3>
                  <ul className="text-xs space-y-2 text-slate-600 dark:text-slate-350">
                    <li><span className="text-slate-400 font-mono">/物流风险扫描</span> 进行厂区级发货延迟诊断</li>
                    <li><span className="text-slate-400 font-mono">/承运商履约分析</span> 生成承运商时效对齐分析表</li>
                    <li><span className="text-slate-400 font-mono">/项目延期分析</span> 统计未完成配送的原因排查</li>
                  </ul>
                </div>
              </div>
            </div>

            <div className="px-2 text-[10px] text-slate-400 dark:text-gray-500">
              <span>当前用户角色：{userRoleIds.join(', ')}</span>
            </div>
          </div>
        )}

        {/* Messages rendering */}
        <div className="max-w-3xl mx-auto space-y-5">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div className={`max-w-full sm:max-w-2xl rounded-2xl p-4 shadow-sm leading-relaxed ${
                msg.sender === 'user'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-800 dark:text-slate-250'
              }`}>
                {/* Message Text */}
                {msg.sender === 'assistant' ? (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      h1: ({ children }) => <h1 className="mb-2 mt-1 text-base font-bold">{children}</h1>,
                      h2: ({ children }) => <h2 className="mb-1.5 mt-3 text-sm font-bold">{children}</h2>,
                      h3: ({ children }) => <h3 className="mb-1 mt-2 text-xs font-bold">{children}</h3>,
                      p: ({ children }) => <p className="my-0 text-xs leading-relaxed">{children}</p>,
                      ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5 text-xs leading-5">{children}</ul>,
                      ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5 text-xs leading-5">{children}</ol>,
                      strong: ({ children }) => <strong className="font-bold text-slate-950 dark:text-white">{children}</strong>,
                      blockquote: ({ children }) => <blockquote className="my-2 border-l-2 border-indigo-300 pl-3 text-slate-500 dark:border-indigo-700 dark:text-slate-400">{children}</blockquote>,
                      code: ({ children, className }) => className ? <code className={`${className} block overflow-x-auto rounded-lg bg-slate-950 p-3 text-[11px] text-slate-100`}>{children}</code> : <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px] text-indigo-700 dark:bg-slate-800 dark:text-indigo-300">{children}</code>,
                      table: ({ children }) => <div className="my-2 overflow-x-auto"><table className="w-full border-collapse text-[11px]">{children}</table></div>,
                      th: ({ children }) => <th className="border border-slate-200 bg-slate-50 px-2 py-1.5 text-left font-bold dark:border-slate-700 dark:bg-slate-800">{children}</th>,
                      td: ({ children }) => <td className="border border-slate-200 px-2 py-1.5 dark:border-slate-700">{children}</td>,
                      a: ({ children, href }) => <a href={href} target="_blank" rel="noreferrer" className="font-medium text-indigo-600 underline underline-offset-2 dark:text-indigo-400">{children}</a>,
                    }}
                  >
                    {String(msg.text || '')}
                  </ReactMarkdown>
                ) : <div className="whitespace-pre-wrap text-xs leading-5">{msg.text}</div>}
                {msg.reportArtifact && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-200/70 pt-3 dark:border-slate-700">
                    <span className="text-[11px] font-bold">{msg.reportArtifact.filename}</span>
                    {msg.reportArtifact.view_url && <a href={msg.reportArtifact.view_url} target="_blank" rel="noreferrer" className="rounded-lg border border-indigo-200 px-3 py-1.5 text-[11px] font-bold text-indigo-700 hover:bg-indigo-50 dark:border-indigo-800 dark:text-indigo-300">预览</a>}
                    <a href={msg.reportArtifact.download_url} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-[11px] font-bold text-white hover:bg-indigo-700">下载</a>
                  </div>
                )}

                {/* Loading indicator */}
                {msg.loading && (
                  <div className="flex items-center gap-2 text-xs text-slate-400 mt-2">
                    <RefreshCw className="w-3.5 h-3.5 animate-spin text-indigo-500" />
                    <span>查询规划执行中...</span>
                  </div>
                )}

                {/* Error box */}
                {msg.error && (
                  <div className="mt-3 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 rounded-lg p-3 text-xs text-red-700 dark:text-red-400 flex gap-2">
                    <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                    <div>
                      <strong>意图执行阻断：</strong>
                      <p className="mt-1 font-mono">{msg.error}</p>
                    </div>
                  </div>
                )}

                {/* Query Result Section - Unified QueryResultView */}
                {msg.queryResult && (
                  <div className="mt-4 border-t border-slate-100 dark:border-slate-800/80 pt-4">
                    <QueryResultView
                      result={msg.queryResult}
                      fields={fields}
                      darkMode={darkMode}
                      onMetricClick={openMetricDrawerById}
                      onShareClick={async () => {
                        try {
                          const exportJob = await api.createExportJob({
                            user_id: currentUserId || 'anonymous',
                            export_format: 'pdf',
                            query_snapshots: [msg.queryResult!],
                          });
                          await api.waitForExportJob(exportJob.export_job_id);
                          const share = await api.createShare({
                            user_id: currentUserId || 'anonymous',
                            export_job_id: exportJob.export_job_id,
                            allowed_user_ids: [currentUserId || 'anonymous'],
                          });
                          const shareUrl = `${window.location.origin}/api/v1/shares/${share.share_id}`;
                          await navigator.clipboard.writeText(shareUrl);
                          alert('安全分享链接已复制到剪贴板！该链接已附加您的行级 RLS 安全策略拦截防护。');
                        } catch (err: unknown) {
                          alert(`创建分享链接失败: ${err instanceof Error ? err.message : '未知错误'}`);
                        }
                      }}
                      onLineageClick={(lineage) => {
                        setActiveLineage(lineage);
                        setShowLineageDrawer(true);
                      }}
                      onClarifySubmit={onClarifySubmit}
                      onCorrectSubmit={onCorrectSubmit}
                      onSaveMetric={onSaveMetric}
                      currentUserId={currentUserId}
                      onAdoptGap={onAdoptGap}
                    />
                  </div>
                )}

                {/* Harness Result Section - Unified HarnessResultView */}
                {msg.harnessResult && (
                  <div className="mt-2">
                    <HarnessResultView
                      harnessResult={msg.harnessResult}
                      fields={fields}
                      darkMode={darkMode}
                      onClarifySubmit={onHarnessClarifySubmit}
                      onConfirmSubmit={onHarnessConfirmSubmit}
                      onCancel={onHarnessCancel}
                    />
                  </div>
                )}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Chat input box */}
      <div className="relative bg-slate-50 px-4 pb-7 pt-3 dark:bg-slate-950">
        {/* Metric Autocomplete Dropdown */}
        {showMetricDropdown && (
          <div className="absolute bottom-full left-1/2 z-20 mb-2 max-h-48 w-[calc(100%-2rem)] max-w-3xl -translate-x-1/2 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-lg dark:border-slate-800 dark:bg-slate-900">
            <div className="px-3 py-1.5 text-[9px] font-bold text-slate-400 dark:text-gray-500 uppercase tracking-wider border-b border-slate-100 dark:border-slate-800">
              选择要引用的数据指标
            </div>
            {filteredMetrics.length === 0 && (
              <div className="px-4 py-4 text-center text-[11px] text-slate-400">
                暂无可调用的已激活指标
              </div>
            )}
            {filteredMetrics.map(m => (
              <button
                key={m.asset_id}
                onClick={() => selectMetric(m)}
                className="w-full px-4 py-2 text-left text-xs hover:bg-slate-50 dark:hover:bg-slate-800 flex items-center justify-between"
              >
                <div>
                  <span className="font-bold text-slate-800 dark:text-slate-200">@{m.name}</span>
                  <span className="text-[10px] text-slate-400 ml-2 font-mono">({m.code})</span>
                </div>
                <span className="max-w-40 truncate text-[10px] text-slate-400">{m.data_source_id}</span>
              </button>
            ))}
          </div>
        )}

        {/* Skill Autocomplete Dropdown */}
        {showSkillDropdown && (
          <div className="absolute bottom-full left-1/2 z-20 mb-2 max-h-48 w-[calc(100%-2rem)] max-w-3xl -translate-x-1/2 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-lg dark:border-slate-800 dark:bg-slate-900">
            <div className="px-3 py-1.5 text-[9px] font-bold text-slate-400 dark:text-gray-500 uppercase tracking-wider border-b border-slate-100 dark:border-slate-800">
              选择并运行报表技能 Skill
            </div>
            {filteredSkills.length === 0 && (
              <div className="px-4 py-4 text-center text-[11px] text-slate-400">
                暂无可调用的已激活技能
              </div>
            )}
            {filteredSkills.map(s => (
              <button
                key={s.asset_id}
                onClick={() => selectSkill(s)}
                className="w-full px-4 py-2 text-left text-xs hover:bg-slate-50 dark:hover:bg-slate-800 flex items-center justify-between"
              >
                <div>
                  <span className="font-bold text-indigo-650 dark:text-indigo-400">/{s.name}</span>
                  <span className="text-[10px] text-slate-400 ml-2 font-mono">({s.code})</span>
                </div>
                <p className="text-[10px] text-slate-400 truncate max-w-xs">{s.data_source_id}</p>
              </button>
            ))}
          </div>
        )}

        {/* Report Autocomplete Dropdown */}
        {showReportDropdown && (
          <div className="absolute bottom-full left-1/2 z-20 mb-2 max-h-48 w-[calc(100%-2rem)] max-w-3xl -translate-x-1/2 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-lg dark:border-slate-800 dark:bg-slate-900">
            <div className="border-b border-slate-100 px-3 py-1.5 text-[9px] font-bold uppercase tracking-wider text-slate-400 dark:border-slate-800 dark:text-gray-500">
              选择要生成的报表
            </div>
            {filteredReports.length === 0 && (
              <div className="px-4 py-4 text-center text-[11px] text-slate-400">
                暂无可调用的已激活报表
              </div>
            )}
            {filteredReports.map(report => (
              <button
                key={report.asset_id}
                onClick={() => selectReport(report)}
                className="flex w-full items-center justify-between px-4 py-2 text-left text-xs hover:bg-slate-50 dark:hover:bg-slate-800"
              >
                <div className="min-w-0">
                  <span className="font-bold text-indigo-650 dark:text-indigo-400">#{report.name}</span>
                  <span className="ml-2 font-mono text-[10px] text-slate-400">({report.code})</span>
                </div>
                <p className="ml-4 max-w-xs truncate text-[10px] text-slate-400">{report.data_source_id}</p>
              </button>
            ))}
          </div>
        )}

        <div className="max-w-3xl mx-auto flex gap-3 items-end">
          <textarea
            ref={inputRef}
            rows={1}
            value={queryText}
            onChange={(e) => setQueryText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入问题，@ 调用指标，/ 调用技能，# 调用报表..."
            className="flex-1 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl px-4 py-2.5 text-xs outline-none text-slate-800 dark:text-slate-200 resize-none max-h-24"
          />
          <button
            onClick={handleSend}
            disabled={!queryText.trim()}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white p-2.5 rounded-xl transition-colors shrink-0"
          >
            <Send className="w-4.5 h-4.5" />
          </button>
        </div>
      </div>
    </div>
  );
};
