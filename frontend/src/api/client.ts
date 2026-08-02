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

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly body: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export interface SuccessResponse { success?: boolean; message?: string }
export interface AuthResponse extends SuccessResponse {
  authenticated?: boolean
  username?: string
  is_admin?: boolean
  is_host?: boolean
  require_login?: boolean
  party_id?: string
  host_username?: string | null
  party_unlocked?: boolean
}
export interface VersionResponse {
  version?: string
  current_version: string
  codename: string
  latest_version: string | null
  update_available: boolean
  release_url: string | null
}
export interface LibraryItem {
  Id: string
  Name: string
  Type: string
  Overview?: string
  RunTimeTicks?: number
  MediaSourceCount?: number
  UserData?: {
    PlaybackPositionTicks?: number
    PlayedPercentage?: number
    Played?: boolean
  }
}
export interface LibraryResponse {
  Items: LibraryItem[]
  TotalRecordCount?: number
}
export interface PartyResponse extends SuccessResponse {
  party_id?: string
  url?: string
  is_host?: boolean
  party_unlocked?: boolean
}
export interface AvatarResponse extends SuccessResponse {
  uuid?: string
  code?: string
}
export type JsonRecord = Record<string, unknown>
export interface PartyListResponse {
  require_login: boolean
  parties: Array<{
    code: string
    title: string | null
    user_count: number
    playing: boolean
    locked: boolean
  }>
}
export interface AudioStream {
  index: number
  language: string
  displayLanguage: string
  codec: string
  channels: number
  isDefault: boolean
  title: string
}
export interface SubtitleStream {
  index: number
  language: string
  displayLanguage: string
  codec: string
  isDefault: boolean
  isForced: boolean
  isExternal: boolean
  isPGS: boolean
  isTextSubtitleStream: boolean
  title: string
}
export interface MediaVersion {
  id: string
  name: string
  container: string | null
  run_time_ticks: number | null
}
export interface StreamsResponse {
  audio: AudioStream[]
  subtitles: SubtitleStream[]
  media_source_id: string | null
  versions: MediaVersion[]
}
export interface IntroResponse {
  hasIntro: boolean
  start?: number
  end?: number
  duration?: number
}
export interface QualityOptionsResponse {
  options: Array<{
    id: string
    label: string
    resolution: string | null
    width: number | null
    height: number | null
    bitrate_kbps: number | null
  }>
  default_id: string
}
export interface ConfigUpdateResponse extends JsonRecord {
  success: boolean
  changed: string[]
  rejected: Array<{ key: string; reason: string }>
  restart_required: string[]
  config?: JsonRecord
  error?: string
}

export async function apiFetch<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(withPrefix(path), {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    credentials: 'same-origin',
    ...options,
  })
  const text = await resp.text()
  let body: unknown = undefined
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = text
    }
  }

  if (!resp.ok) {
    const record = body && typeof body === 'object'
      ? body as Record<string, unknown>
      : undefined
    const message = [record?.detail, record?.error, record?.message]
      .find((value): value is string => typeof value === 'string')
      || resp.statusText
      || `Request failed (${resp.status})`
    throw new ApiError(resp.status, message, body)
  }

  return body as T
}

export const api = {
  // Auth (become host of current party)
  login: (username: string, password: string, signal?: AbortSignal) =>
    apiFetch<AuthResponse>('/api/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }), signal,
    }),
  logout: (signal?: AbortSignal) => apiFetch<SuccessResponse>(
    '/api/auth/logout', { method: 'POST', signal },
  ),
  authStatus: (signal?: AbortSignal) => apiFetch<AuthResponse>('/api/auth/status', { signal }),
  version: (signal?: AbortSignal) => apiFetch<VersionResponse>('/api/version', { signal }),

  // Library
  libraries: (signal?: AbortSignal) => apiFetch<LibraryResponse>('/api/libraries', { signal }),
  items: (params: Record<string, string | number | boolean>, signal?: AbortSignal) => {
    const qs = new URLSearchParams(
      Object.entries(params).map(([key, value]) => [key, String(value)]),
    ).toString()
    return apiFetch<LibraryResponse>(`/api/items?${qs}`, { signal })
  },
  search: (q: string, signal?: AbortSignal) => apiFetch<LibraryResponse>(
    `/api/search?q=${encodeURIComponent(q)}`, { signal },
  ),
  itemDetails: (id: string, signal?: AbortSignal) => apiFetch<LibraryItem>(
    `/api/item/${id}`, { signal },
  ),
  // mediaSourceId optionally scopes the response to one alternate
  // version. When omitted, the audio/subtitle arrays describe Emby's
  // default source and `versions` still lists every alternate.
  itemStreams: (id: string, mediaSourceId?: string, signal?: AbortSignal) => {
    const qs = mediaSourceId ? `?media_source_id=${encodeURIComponent(mediaSourceId)}` : ''
    return apiFetch<StreamsResponse>(`/api/item/${id}/streams${qs}`, { signal })
  },

  // Media
  intro: (id: string, signal?: AbortSignal) => apiFetch<IntroResponse>(`/api/intro/${id}`, { signal }),
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
  qualityOptions: (signal?: AbortSignal) => apiFetch<QualityOptionsResponse>(
    '/api/quality-options', { signal },
  ),

  // Party
  createParty: (body?: { client_id?: string; display_name?: string; username?: string; password?: string }, signal?: AbortSignal) =>
    apiFetch<PartyResponse>('/api/party/create', {
      method: 'POST',
      body: JSON.stringify(body || {}),
      signal,
    }),
  joinParty: (
    party_id: string,
    client_id: string,
    display_name: string,
    avatar_uuid?: string | null, signal?: AbortSignal,
  ) =>
    apiFetch<PartyResponse>(`/api/party/${party_id}/join`, {
      method: 'POST',
      body: JSON.stringify({ client_id, display_name, avatar_uuid }),
      signal,
    }),
  leaveParty: (signal?: AbortSignal) => apiFetch<SuccessResponse>('/api/party/leave', { method: 'POST', signal }),
  listParties: (signal?: AbortSignal) => apiFetch<PartyListResponse>('/api/party/list', { signal }),
  partyExists: (party_id: string, signal?: AbortSignal) => apiFetch<{ exists: boolean }>(`/api/party/${party_id}/exists`, { signal }),
  partyInfo: (id: string, signal?: AbortSignal) => apiFetch<JsonRecord>(`/api/party/${id}/info`, { signal }),

  // Avatar
  avatarUpload: async (file: File, signal?: AbortSignal): Promise<AvatarResponse> => {
    const fd = new FormData()
    fd.append('image', file)
    // Direct fetch (bypasses apiFetch) because we need multipart/form-data,
    // not JSON. Prefix is applied manually so this honours APP_PREFIX
    // the same way the JSON endpoints do.
    const resp = await fetch(withPrefix('/api/avatar/upload'), {
      method: 'POST',
      body: fd,
      credentials: 'same-origin',
      signal,
    })
    return resp.json() as Promise<AvatarResponse>
  },
  avatarGravatar: (email: string, signal?: AbortSignal) =>
    apiFetch<AvatarResponse>('/api/avatar/gravatar', {
      method: 'POST',
      body: JSON.stringify({ email }),
      signal,
    }),
  avatarRecover: (code: string, signal?: AbortSignal) =>
    apiFetch<AvatarResponse>('/api/avatar/recover', {
      method: 'POST',
      body: JSON.stringify({ code }),
      signal,
    }),
  avatarSrc: (uuid: string) => withPrefix(`/api/avatar/${uuid}`),
  hostAvatarSrc: (party_id: string) => withPrefix(`/api/avatar/host/${party_id}`),

  // Admin
  adminLogin: (username: string, password: string, signal?: AbortSignal) =>
    apiFetch<SuccessResponse>('/api/admin/login', {
      method: 'POST', body: JSON.stringify({ username, password }), signal,
    }),
  adminLogout: (signal?: AbortSignal) => apiFetch<SuccessResponse>(
    '/api/admin/logout', { method: 'POST', signal },
  ),
  adminGetConfig: (signal?: AbortSignal) => apiFetch<JsonRecord>('/api/admin/config', { signal }),
  adminUpdateConfig: (data: JsonRecord, signal?: AbortSignal) =>
    apiFetch<ConfigUpdateResponse>('/api/admin/config', {
      method: 'PUT', body: JSON.stringify(data), signal,
    }),
}
