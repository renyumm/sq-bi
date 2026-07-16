import type { ChatMessageRecord, ChatSessionRecord } from '../api';
import { request } from './core';

export const chatApi = {
  getChatSessions(userId: string) {
    return request<ChatSessionRecord[]>(`/api/v1/chat/sessions?user_id=${encodeURIComponent(userId)}`);
  },
  createChatSession(payload: { user_id: string; title?: string | null }) {
    return request<ChatSessionRecord>('/api/v1/chat/sessions', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  archiveChatSession(sessionId: string, payload: { user_id: string }) {
    return request<ChatSessionRecord>(`/api/v1/chat/sessions/${sessionId}/archive`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },
  getChatMessages(userId: string, sessionId?: string | null) {
    const params = new URLSearchParams({ user_id: userId });
    if (sessionId) params.set('session_id', sessionId);
    return request<ChatMessageRecord[]>(`/api/v1/chat/messages?${params.toString()}`);
  },
  createChatMessage(payload: {
    user_id: string;
    text: string;
    session_id?: string | null;
    sender?: 'user' | 'assistant' | 'system';
    payload?: Record<string, unknown>;
  }) {
    return request<ChatMessageRecord>('/api/v1/chat/messages', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  archiveChatMessage(messageId: string, payload: { user_id: string }) {
    return request<ChatMessageRecord>(`/api/v1/chat/messages/${messageId}/archive`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },
};

