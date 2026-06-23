export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = (j && (j.detail as string)) || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, body?: unknown) => request<T>("POST", p, body),
  del: <T>(p: string) => request<T>("DELETE", p),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
};

import type { Settings, SettingsUpdate } from './types';

export const getSettings = (): Promise<Settings> =>
  api.get<Settings>('/api/settings');

export const updateSettings = (payload: SettingsUpdate): Promise<{ updated: string[] }> =>
  api.put<{ updated: string[] }>('/api/settings', payload);

export const testConnection = (service: 'sonarr' | 'radarr' | 'sftp'): Promise<{ ok: boolean; error?: string }> =>
  api.post<{ ok: boolean; error?: string }>(`/api/settings/test/${service}`);
