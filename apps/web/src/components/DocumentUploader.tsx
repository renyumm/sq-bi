import React, { useCallback, useState, useEffect, useRef } from 'react';
import { FileText, UploadCloud, RefreshCw, AlertCircle, CheckCircle, Trash2 } from 'lucide-react';
import { api } from '../api';
import type { DataSourceDocument } from '../api';
import { confirmAction } from '../systemDialog';

interface DocumentUploaderProps {
  dsId: string;
  isAdmin: boolean;
  onUploadSuccess?: () => void;
}

export const DocumentUploader: React.FC<DocumentUploaderProps> = ({
  dsId,
  isAdmin,
  onUploadSuccess
}) => {
  const [documents, setDocuments] = useState<DataSourceDocument[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchDocuments = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const docs = await api.listDataSourceDocuments(dsId);
      setDocuments(docs);
    } catch (err: any) {
      console.error('Failed to load documents:', err);
      setError('无法获取文档列表');
    } finally {
      setIsLoading(false);
    }
  }, [dsId]);

  useEffect(() => {
    void fetchDocuments();
  }, [fetchDocuments]);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    const file = e.target.files[0];
    await uploadFile(file);
  };

  const uploadFile = async (file: File) => {
    setIsUploading(true);
    setError(null);
    try {
      await api.uploadDataSourceDocument(dsId, file);
      await fetchDocuments();
      if (onUploadSuccess) onUploadSuccess();
    } catch (err: any) {
      console.error('Upload failed:', err);
      setError(err?.message || '文件上传失败，请重试');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDelete = async (doc: DataSourceDocument) => {
    if (!await confirmAction(`确认删除文档「${doc.filename}」？`)) return;
    setDeletingId(doc.document_id);
    try {
      await api.deleteDataSourceDocument(dsId, doc.document_id);
      setDocuments(prev => prev.filter(d => d.document_id !== doc.document_id));
    } catch (err: any) {
      setError(err?.message || '删除失败，请重试');
    } finally {
      setDeletingId(null);
    }
  };

  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  return (
    <div className="space-y-2">
      <div className="flex justify-between items-center gap-2">
        <h4 className="text-xs font-bold text-slate-700 dark:text-slate-300 flex items-center gap-1.5 uppercase tracking-wider">
          <FileText className="w-4 h-4 text-indigo-500" />
          辅助文档（可选）
        </h4>
        <div className="flex items-center gap-1.5 shrink-0">
          {isAdmin && (
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploading}
              className="flex items-center gap-1 text-[10px] font-bold text-indigo-650 dark:text-indigo-400 bg-indigo-50 hover:bg-indigo-100 dark:bg-indigo-950/20 border border-indigo-200/50 dark:border-indigo-900/50 px-2.5 py-1 rounded-lg transition-all cursor-pointer disabled:opacity-60"
            >
              {isUploading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <UploadCloud className="w-3 h-3" />}
              {isUploading ? '上传中…' : '上传文档'}
            </button>
          )}
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            className="hidden"
            accept=".xlsx,.xls,.csv,.pdf,.docx,.doc,.txt"
          />
          <button
            onClick={fetchDocuments}
            disabled={isLoading}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
            title="刷新列表"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Error message */}
      {error && (
        <div className="flex items-center gap-1.5 p-3 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900 rounded-lg text-[11px] text-red-600 dark:text-red-400">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Document List */}
      {isLoading && documents.length === 0 ? (
        <div className="text-center py-6 text-slate-400 dark:text-slate-600">
          <RefreshCw className="w-5 h-5 mx-auto animate-spin mb-2" />
          <span className="text-xs">正在加载文档列表...</span>
        </div>
      ) : documents.length === 0 ? (
        <div className="text-center py-4 border border-dashed border-slate-100 dark:border-slate-800/80 rounded-lg text-slate-400 text-xs">
          暂无上传的辅助文档
        </div>
      ) : (
        <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
          {documents.map(doc => (
            <div 
              key={doc.document_id} 
              className="flex justify-between items-center p-2.5 bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800 rounded-lg text-xs"
            >
              <div className="flex items-center gap-2 min-w-0">
                <FileText className="w-4 h-4 text-indigo-400 shrink-0" />
                <div className="min-w-0">
                  <p className="font-semibold text-slate-755 dark:text-slate-200 truncate animate-none" title={doc.filename}>
                    {doc.filename}
                  </p>
                  <p className="text-[10px] text-slate-400 mt-0.5">
                    {formatBytes(doc.byte_size)} • {doc.uploaded_at ? new Date(doc.uploaded_at).toLocaleString() : '未知时间'}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {doc.upload_status === 'ready' ? (
                  <span className="flex items-center gap-1 text-[10px] text-green-650 dark:text-green-400 font-bold bg-green-50 dark:bg-green-950/20 px-1.5 py-0.5 rounded border border-green-200 dark:border-green-900">
                    <CheckCircle className="w-3 h-3" />
                    已就绪
                  </span>
                ) : (
                  <span className="text-[10px] text-slate-500 dark:text-slate-400 bg-slate-150 px-1.5 py-0.5 rounded">
                    {doc.upload_status === 'processing' ? '处理中...' : doc.upload_status}
                  </span>
                )}
                {isAdmin && (
                  <button
                    type="button"
                    onClick={() => handleDelete(doc)}
                    disabled={deletingId === doc.document_id}
                    className="text-slate-350 hover:text-red-500 dark:text-slate-500 dark:hover:text-red-400 transition-colors disabled:opacity-50 cursor-pointer"
                    title="删除文档"
                  >
                    {deletingId === doc.document_id ? (
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="w-3.5 h-3.5" />
                    )}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
