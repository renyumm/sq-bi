import { request } from './core';
import type { QueryResult } from '../api';

interface ExportJob {
  export_job_id: string;
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'canceled';
  artifact?: { filename: string; content_type: string; byte_size: number } | null;
  integration_gaps?: string[];
}

export const deliveryApi = {
  createExportJob(payload: {
    user_id: string;
    export_format: 'pdf';
    query_snapshots: QueryResult[];
    template_id?: string | null;
  }) {
    return request<ExportJob>('/api/v1/exports', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  getExportJob(jobId: string) {
    return request<ExportJob>(`/api/v1/exports/${jobId}`);
  },
  async waitForExportJob(jobId: string, timeoutMs = 15_000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const job = await deliveryApi.getExportJob(jobId);
      if (job.status === 'succeeded') return job;
      if (job.status === 'failed' || job.status === 'canceled') {
        throw new Error(job.integration_gaps?.join('；') || `导出任务${job.status === 'failed' ? '失败' : '已取消'}。`);
      }
      await new Promise(resolve => window.setTimeout(resolve, 250));
    }
    throw new Error('导出任务仍在处理中，请稍后重试。');
  },
  createShare(payload: {
    user_id: string;
    export_job_id: string;
    expires_at?: string | null;
    password?: string | null;
    allowed_user_ids?: string[];
  }) {
    return request<{ share_id: string; export_job_id: string; requires_password: boolean }>('/api/v1/shares', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  createSubscription(payload: {
    owner_user_id: string;
    report_skill_id: string;
    cron: string;
    channels: string[];
    export_format?: 'pdf';
    template_id?: string | null;
    service_principal_id?: string | null;
    enabled?: boolean;
  }) {
    return request<{ subscription_id: string; next_run_at?: string | null }>('/api/v1/subscriptions', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
};
