interface ApiErrorPayload {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

interface ApiEnvelope<T> {
  data?: T;
  error?: ApiErrorPayload;
  message?: string;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
const API_BASE_LABEL = API_BASE || 'same-origin /api proxy';
const SESSION_STORAGE_KEY = 'sqbi.session_id';

let currentSessionId: string | null =
  typeof window !== 'undefined' ? window.localStorage.getItem(SESSION_STORAGE_KEY) : null;

export function getSessionId(): string | null {
  return currentSessionId;
}

export function setSessionId(id: string | null): void {
  currentSessionId = id;
  if (typeof window === 'undefined') return;
  if (id) window.localStorage.setItem(SESSION_STORAGE_KEY, id);
  else window.localStorage.removeItem(SESSION_STORAGE_KEY);
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  try {
    const isFormData = typeof FormData !== 'undefined' && options?.body instanceof FormData;
    const response = await fetch(url, {
      ...options,
      headers: {
        ...(!isFormData ? { 'Content-Type': 'application/json' } : {}),
        ...(currentSessionId ? { 'X-Session-Id': currentSessionId } : {}),
        ...(options?.headers || {}),
      },
    });
    if (!response.ok) {
      if (response.status === 401 && currentSessionId) {
        setSessionId(null);
        if (typeof window !== 'undefined') window.location.reload();
        throw new Error('登录会话已失效，请重新登录后继续。');
      }
      const text = await response.text();
      let errorPayload: ApiEnvelope<unknown>;
      try {
        errorPayload = JSON.parse(text);
      } catch {
        throw new Error(`HTTP Error ${response.status}: ${text || response.statusText}`);
      }
      if (errorPayload.error) throw errorPayload.error;
      throw new Error(errorPayload.message || `HTTP Error ${response.status}`);
    }
    const envelope = (await response.json()) as ApiEnvelope<T>;
    if (envelope.error) throw envelope.error;
    return envelope.data as T;
  } catch (error: unknown) {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw {
        code: 'UNKNOWN_ERROR',
        message: `Failed to connect to backend service via ${API_BASE_LABEL}. Please ensure the SQ-BI services are started.`,
        details: { offline: true, api_base: API_BASE },
      } satisfies ApiErrorPayload;
    }
    throw error;
  }
}

