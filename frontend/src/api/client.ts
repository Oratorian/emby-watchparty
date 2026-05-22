/**
 * API client for communicating with the FastAPI backend
 */

const API_BASE = ''  // Same origin, Vite proxy handles dev

export async function apiFetch<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    credentials: 'same-origin',
    ...options,
  })
  return resp.json()
}

export const api = {
  // Auth (become host of current party)
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
  createParty: (body?: { client_id?: string; display_name?: string; username?: string; password?: string }) =>
    apiFetch('/api/party/create', {
      method: 'POST',
      body: JSON.stringify(body || {}),
    }),
  joinParty: (
    party_id: string,
    client_id: string,
    display_name: string,
    avatar_uuid?: string | null,
  ) =>
    apiFetch(`/api/party/${party_id}/join`, {
      method: 'POST',
      body: JSON.stringify({ client_id, display_name, avatar_uuid }),
    }),
  leaveParty: () => apiFetch('/api/party/leave', { method: 'POST' }),
  partyExists: (party_id: string) => apiFetch(`/api/party/${party_id}/exists`),
  partyInfo: (id: string) => apiFetch(`/api/party/${id}/info`),

  // Avatar
  avatarUpload: async (file: File) => {
    const fd = new FormData()
    fd.append('image', file)
    const resp = await fetch('/api/avatar/upload', {
      method: 'POST',
      body: fd,
      credentials: 'same-origin',
    })
    return resp.json()
  },
  avatarGravatar: (email: string) =>
    apiFetch('/api/avatar/gravatar', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),
  avatarRecover: (code: string) =>
    apiFetch('/api/avatar/recover', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),
  avatarSrc: (uuid: string) => `/api/avatar/${uuid}`,
  hostAvatarSrc: (party_id: string) => `/api/avatar/host/${party_id}`,

  // Admin
  adminLogin: (username: string, password: string) =>
    apiFetch('/api/admin/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  adminLogout: () => apiFetch('/api/admin/logout', { method: 'POST' }),
  adminGetConfig: () => apiFetch('/api/admin/config'),
  adminUpdateConfig: (data: Record<string, any>) =>
    apiFetch('/api/admin/config', { method: 'PUT', body: JSON.stringify(data) }),
}
