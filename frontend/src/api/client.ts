/**
 * API client for communicating with the FastAPI backend
 */

const API_BASE = ''  // Same origin, Vite proxy handles dev

export async function apiFetch<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  return resp.json()
}

export const api = {
  // Auth
  login: (username: string, password: string) =>
    apiFetch('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  logout: () => apiFetch('/api/auth/logout', { method: 'POST' }),
  authStatus: () => apiFetch('/api/auth/status'),
  version: () => apiFetch('/api/version'),

  // Library
  libraries: () => apiFetch('/api/libraries'),
  items: (params: Record<string, any>) => {
    const qs = new URLSearchParams(params).toString()
    return apiFetch(`/api/items?${qs}`)
  },
  search: (q: string) => apiFetch(`/api/search?q=${encodeURIComponent(q)}`),
  itemDetails: (id: string) => apiFetch(`/api/item/${id}`),
  itemStreams: (id: string) => apiFetch(`/api/item/${id}/streams`),

  // Media
  intro: (id: string) => apiFetch(`/api/intro/${id}`),
  imageUrl: (id: string, type = 'Primary') => `/api/image/${id}?type=${type}`,

  // Party
  createParty: () => apiFetch('/api/party/create', { method: 'POST' }),
  partyInfo: (id: string) => apiFetch(`/api/party/${id}/info`),

  // Admin
  adminLogin: (username: string, password: string) =>
    apiFetch('/api/admin/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  adminLogout: () => apiFetch('/api/admin/logout', { method: 'POST' }),
  adminGetConfig: () => apiFetch('/api/admin/config'),
  adminUpdateConfig: (data: Record<string, any>) =>
    apiFetch('/api/admin/config', { method: 'PUT', body: JSON.stringify(data) }),
}
