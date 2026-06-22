/**
 * API client for communicating with the FastAPI backend.
 *
 * Every backend route is mounted under APP_PREFIX on the server, so
 * the browser-side fetch URL must carry that prefix too. The Vite dev
 * proxy targets `/api`, `/hls`, and `/socket.io` at root; when running
 * dev with a non-empty APP_PREFIX the proxy config in vite.config.ts
 * would need updating to match, but the default (no prefix) "just
 * works" because withPrefix() is a no-op.
 */
import { withPrefix } from '@/utils/appPrefix'

export async function apiFetch<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(withPrefix(path), {
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
  // mediaSourceId optionally scopes the response to one alternate
  // version. When omitted, the audio/subtitle arrays describe Emby's
  // default source and `versions` still lists every alternate.
  itemStreams: (id: string, mediaSourceId?: string) => {
    const qs = mediaSourceId ? `?media_source_id=${encodeURIComponent(mediaSourceId)}` : ''
    return apiFetch(`/api/item/${id}/streams${qs}`)
  },

  // Media
  intro: (id: string) => apiFetch(`/api/intro/${id}`),
  imageUrl: (
    id: string,
    type = 'Primary',
    opts?: { maxWidth?: number; maxHeight?: number; quality?: number },
  ) => {
    const params = new URLSearchParams({ type })
    if (opts?.maxWidth) params.set('maxWidth', String(opts.maxWidth))
    if (opts?.maxHeight) params.set('maxHeight', String(opts.maxHeight))
    if (opts?.quality) params.set('quality', String(opts.quality))
    return withPrefix(`/api/image/${id}?${params.toString()}`)
  },

  // Quality
  qualityOptions: () => apiFetch('/api/quality-options'),

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
  listParties: () => apiFetch('/api/party/list'),
  partyExists: (party_id: string) => apiFetch(`/api/party/${party_id}/exists`),
  partyInfo: (id: string) => apiFetch(`/api/party/${id}/info`),

  // Avatar
  avatarUpload: async (file: File) => {
    const fd = new FormData()
    fd.append('image', file)
    // Direct fetch (bypasses apiFetch) because we need multipart/form-data,
    // not JSON. Prefix is applied manually so this honours APP_PREFIX
    // the same way the JSON endpoints do.
    const resp = await fetch(withPrefix('/api/avatar/upload'), {
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
  avatarSrc: (uuid: string) => withPrefix(`/api/avatar/${uuid}`),
  hostAvatarSrc: (party_id: string) => withPrefix(`/api/avatar/host/${party_id}`),

  // Admin
  adminLogin: (username: string, password: string) =>
    apiFetch('/api/admin/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  adminLogout: () => apiFetch('/api/admin/logout', { method: 'POST' }),
  adminGetConfig: () => apiFetch('/api/admin/config'),
  adminUpdateConfig: (data: Record<string, any>) =>
    apiFetch('/api/admin/config', { method: 'PUT', body: JSON.stringify(data) }),
}
