import type {
  CreateManagedUserRequest,
  LoginResponse,
  ManagedUser,
  UpdateManagedUserRequest,
  UserContext,
} from '../api';
import { getSessionId, request, setSessionId } from './core';

export const authApi = {
  async getCurrentUser() {
    return request<UserContext>('/api/v1/auth/session');
  },
  async login(username: string, password: string): Promise<LoginResponse> {
    const response = await request<LoginResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
    setSessionId(response.session_id);
    return response;
  },
  async logout(): Promise<void> {
    try {
      await request('/api/v1/auth/logout', { method: 'POST' });
    } finally {
      setSessionId(null);
    }
  },
  async ensureLocalSession(): Promise<UserContext | null> {
    if (!getSessionId()) return null;
    try {
      return await authApi.getCurrentUser();
    } catch {
      setSessionId(null);
      return null;
    }
  },
  async listManagedUsers() {
    return request<ManagedUser[]>('/api/v1/admin/users');
  },
  async createManagedUser(payload: CreateManagedUserRequest) {
    return request<ManagedUser>('/api/v1/admin/users', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  async updateManagedUser(username: string, payload: UpdateManagedUserRequest) {
    return request<ManagedUser>(`/api/v1/admin/users/${encodeURIComponent(username)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },
  async deleteManagedUser(username: string) {
    return request<{ status: string }>(`/api/v1/admin/users/${encodeURIComponent(username)}`, {
      method: 'DELETE',
    });
  },
};
