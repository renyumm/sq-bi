import type { DbSettings, DbSettingsUpdate, LlmSettings, LlmSettingsUpdate } from '../api';
import { request } from './core';

export const systemApi = {
  async getHealth() {
    return request<{ status: string }>('/api/v1/health');
  },
  async getVersion() {
    return request<{ version: string }>('/api/v1/version');
  },
  async getLlmSettings() {
    return request<LlmSettings>('/api/v1/settings/llm');
  },
  async updateLlmSettings(payload: LlmSettingsUpdate) {
    return request<LlmSettings>('/api/v1/settings/llm', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },
  async probeLlmSettings() {
    return request<{ healthy: boolean; latency_ms: number; model: string; message: string }>(
      '/api/v1/settings/llm/probe',
      { method: 'POST' },
    );
  },
  async getDbSettings() {
    return request<DbSettings>('/api/v1/settings/db');
  },
  async updateDbSettings(payload: DbSettingsUpdate) {
    return request<DbSettings>('/api/v1/settings/db', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },
};
