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
import type {
  CatalogFiltersV2,
  CatalogQueryV2,
  GroupedSearchV2,
  IntroSegmentV2,
  MediaItemDetailsV2,
  MediaItemV2,
  MediaPageV2,
  MediaSectionV2,
  MediaServerInfoV2,
  PrefixesV2,
  StreamCatalogV2,
} from '@/types/api.generated'

export type JsonPrimitive = string | number | boolean | null
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[]
export interface JsonObject { [key: string]: JsonValue }

function isJsonObject(value: JsonValue | undefined): value is JsonObject {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly body: JsonValue | undefined,
    public readonly code?: string,
    public readonly retryAfter?: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function readResponseBody(resp: Response): Promise<JsonValue | undefined> {
  const text = await resp.text()
  if (!text) return undefined
  try {
    return JSON.parse(text) as JsonValue
  } catch {
    return text
  }
}

function responseError(resp: Response, body: JsonValue | undefined): ApiError {
  const record = isJsonObject(body) ? body : undefined
  // A non-JSON body may be a short sentence from a proxy worth showing
  // ("Upload too large" for an nginx client_max_body_size 413), or it may be
  // an entire HTML error page. Promoting it unconditionally rendered the
  // latter verbatim in the UI. Take it only when it reads like one line of
  // prose; the full text stays on `ApiError.body` either way.
  const rawBody = typeof body === 'string' ? body.trim() : ''
  const readableBody =
    rawBody && rawBody.length <= 200 && !rawBody.includes('\n') && !/[<>]/.test(rawBody)
      ? rawBody
      : ''
  const message = [record?.detail, record?.error, record?.message]
    .find((value): value is string => typeof value === 'string')
    || readableBody
    || resp.statusText
    || `Request failed (${resp.status})`
  const code = typeof record?.code === 'string' ? record.code : undefined
  const bodyRetry = record?.retry_after
  const headerRetry = Number.parseInt(resp.headers.get('Retry-After') || '', 10)
  const retryAfter = typeof bodyRetry === 'number' && Number.isFinite(bodyRetry)
    ? Math.max(0, Math.ceil(bodyRetry))
    : Number.isFinite(headerRetry) ? Math.max(0, headerRetry) : undefined
  return new ApiError(resp.status, message, body, code, retryAfter)
}

export interface SuccessResponse { success?: boolean; message?: string }
export interface AuthResponse extends SuccessResponse {
  authenticated?: boolean
  username?: string | null
  is_admin?: boolean
  is_host?: boolean
  require_login?: boolean
  party_id?: string | null
  host_username?: string | null
  party_unlocked?: boolean
  media_server_type?: 'emby' | 'jellyfin'
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
  // Nullable, matching the backend contract. Emby does return rows with no
  // Type, and declaring it a plain string here was a lie the compiler then
  // enforced on every consumer: LibraryBrowser guards `it.Type &&` in one
  // place and omits the guard in its neighbour, which only reads as safe
  // because the type claimed it could not be null.
  Type: string | null
  CollectionType?: string
  Overview?: string
  RunTimeTicks?: number
  SortName?: string
  ProductionYear?: number
  Tagline?: string
  Taglines?: string[]
  CommunityRating?: number
  CriticRating?: number
  OfficialRating?: string
  Genres?: string[]
  // Emby 4.9.5.0 sends TagItems, never a flat Tags array; confirmed against
  // every captured detail response. The Tags section read the field that does
  // not arrive, so it never rendered for any title.
  TagItems?: Array<{ Id?: string; Name?: string }>
  People?: Array<{ Id?: string; Name?: string; Type?: string; Role?: string }>
  Studios?: Array<{ Id?: string; Name?: string }>
  ImageTags?: Record<string, string>
  BackdropImageTags?: string[]
  LogoImageTag?: string
  PrimaryImageAspectRatio?: number
  MediaSources?: JsonObject[]
  MediaStreams?: JsonObject[]
  MediaSourceCount?: number
  // Episode and season linkage. The backend has always sent these; the
  // frontend type never declared them, so components that needed the parent
  // series had to reach for a locally redeclared shape instead. The
  // contract assertion in types/contract.assertions.ts now catches that.
  SeriesId?: string
  SeriesName?: string
  SeasonId?: string
  SeasonName?: string
  ParentId?: string
  ServerId?: string
  IsFolder?: boolean
  IndexNumber?: number
  ParentIndexNumber?: number
  UserData?: {
    PlaybackPositionTicks?: number
    PlayedPercentage?: number
    Played?: boolean
    IsFavorite?: boolean
  }
}
export interface LibraryResponse {
  Items: LibraryItem[]
  TotalRecordCount?: number
  StartIndex?: number
}

const legacyItemKinds: Record<string, string> = {
  collection_folder: 'CollectionFolder',
  episode: 'Episode',
  folder: 'Folder',
  movie: 'Movie',
  music_video: 'MusicVideo',
  person: 'Person',
  playlist: 'Playlist',
  season: 'Season',
  series: 'Series',
  trailer: 'Trailer',
}

function projectMediaItem(item: MediaItemV2): LibraryItem {
  return {
    Id: item.id,
    Name: item.name,
    Type: legacyItemKinds[item.kind] ?? 'Other',
    CollectionType: item.collection_kind ?? undefined,
    Overview: item.overview,
    RunTimeTicks: item.runtime_seconds === null ? undefined : item.runtime_seconds * 10_000_000,
    ProductionYear: item.production_year ?? undefined,
    ParentId: item.parent_id ?? undefined,
    SeriesId: item.series_id ?? undefined,
    SeriesName: item.series_name ?? undefined,
    SeasonId: item.season_id ?? undefined,
    SeasonName: item.season_name ?? undefined,
    IndexNumber: item.index_number ?? undefined,
    ParentIndexNumber: item.parent_index_number ?? undefined,
    IsFolder: item.is_folder,
    ImageTags: item.has_primary_image ? { Primary: 'available' } : {},
    BackdropImageTags: Array.from({ length: item.backdrop_count }, (_, index) => String(index)),
    PrimaryImageAspectRatio: item.primary_image_aspect_ratio ?? undefined,
    UserData: {
      PlaybackPositionTicks: item.user_state.playback_position_seconds * 10_000_000,
      PlayedPercentage: item.user_state.played_percentage ?? undefined,
      Played: item.user_state.played,
      IsFavorite: item.user_state.favorite,
    },
    MediaSourceCount: item.media_source_count,
  }
}

function projectMediaPage(page: MediaPageV2): LibraryResponse {
  return {
    Items: page.items.map(projectMediaItem),
    TotalRecordCount: page.total ?? undefined,
    StartIndex: page.start,
  }
}

function projectMediaDetails(item: MediaItemDetailsV2): LibraryItem {
  return {
    ...projectMediaItem(item),
    Tagline: item.tagline ?? undefined,
    Genres: item.genres,
    TagItems: item.tags.map(name => ({ Name: name })),
    People: item.people.map(person => ({
      Id: person.id,
      Name: person.name,
      Type: person.kind,
    })),
    Studios: item.studios.map(Name => ({ Name })),
    OfficialRating: item.official_rating ?? undefined,
    CommunityRating: item.community_rating ?? undefined,
    CriticRating: item.critic_rating ?? undefined,
  }
}
export interface LibraryPrefixesResponse {
  Prefixes: string[]
}
export interface FilterOption { value: string; label: string }
export interface FilterControl {
  id: string
  label: string
  kind: 'select' | 'multi' | 'toggle'
  values: FilterOption[]
}
export interface FilterOptionsResponse { controls: FilterControl[] }
export type LibraryFilterState = Record<string, string | string[]>
export interface LibraryQueryRequest {
  scope: {
    parent_id: string | null
    include_item_types: string[]
    media_types: string[]
    recursive: boolean
  }
  page: { start_index: number; limit: number }
  sort: {
    field: 'SortName' | 'DateCreated' | 'PremiereDate' | 'ProductionYear'
      | 'CommunityRating' | 'CriticRating' | 'Runtime' | 'Random'
    direction: 'Ascending' | 'Descending'
  }
  filters: CatalogFiltersV2 & Record<
    string, string | number | string[] | number[] | boolean | null | undefined
  >
  search_term?: string | null
  anchor_prefix?: string | null
}

const v2SortFields: Record<LibraryQueryRequest['sort']['field'], NonNullable<CatalogQueryV2['sort']>['field']> = {
  SortName: 'name',
  DateCreated: 'date_created',
  PremiereDate: 'premiere_date',
  ProductionYear: 'year',
  CommunityRating: 'community_rating',
  CriticRating: 'critic_rating',
  Runtime: 'runtime',
  Random: 'random',
}

function toCatalogQueryV2(query: LibraryQueryRequest): CatalogQueryV2 {
  return {
    scope: {
      parent_id: query.scope.parent_id,
      include_kinds: query.scope.include_item_types.map(kind => kind.replace(
        /([a-z0-9])([A-Z])/g, '$1_$2',
      ).toLowerCase()),
      media_kinds: query.scope.media_types.map(kind => kind.toLowerCase()),
      recursive: query.scope.recursive,
    },
    page: { start: query.page.start_index, limit: query.page.limit },
    sort: {
      field: v2SortFields[query.sort.field],
      direction: query.sort.direction.toLowerCase() === 'descending' ? 'descending' : 'ascending',
    },
    filters: query.filters,
    search_term: query.search_term,
    anchor_prefix: query.anchor_prefix,
  }
}
export interface SearchGroup {
  id: 'movies' | 'series' | 'episodes' | 'people' | 'collections' | 'other'
  label: string
  items: LibraryItem[]
}
export interface GroupedSearchResponse { query: string; groups: SearchGroup[] }
export type ItemSection = 'related' | 'trailers' | 'extras'
export interface ItemSectionResponse { section: ItemSection; items: LibraryItem[] }
export interface PlaylistListResponse { items: LibraryItem[] }
export interface ItemChildrenResponse { items: LibraryItem[] }
export interface PlaybackSelection {
  item: LibraryItem
  mediaSourceId?: string
  quality: string
  audioIndex: number | null
  subtitleIndex: number | null
  startSeconds: number
  resumeMode: 'resume' | 'start_over'
  binge?: boolean
}
export interface PartyResponse extends SuccessResponse {
  party_id?: string
  url?: string
  is_host?: boolean
  party_unlocked?: boolean
}
export interface PartyVideo {
  item_id: string
  title: string
  overview: string
  stream_url_base?: string | null
  audio_index?: number | null
  subtitle_index?: number | null
  media_source_id?: string | null
  play_session_id?: string | null
  run_time_seconds?: number | null
  selected_by?: string | null
  quality: string
}
export interface PartyInfoResponse {
  id: string
  users: string[]
  current_video: PartyVideo | null
  playback_state: {
    playing: boolean
    time: number
    last_update: string
  }
}
export interface AvatarResponse extends SuccessResponse {
  uuid?: string
  code?: string
}
export interface AdminConfig {
  BINGE_WATCH_COUNTDOWN_SECONDS: number
  BINGE_WATCH_ENABLED: boolean
  CONSOLE_LOG_LEVEL: string
  ENABLED_QUALITY_OPTIONS: Record<string, number[]>
  ENABLE_RATE_LIMITING: boolean
  FORCE_TRANSCODE: boolean
  HLS_TOKEN_EXPIRY: number
  LATE_JOIN_VOTE_COOLDOWN_SECONDS: number
  LATE_JOIN_VOTE_ENABLED: boolean
  LATE_JOIN_VOTE_TIMEOUT_SECONDS: number
  LOG_FILE: string
  LOG_FORMAT: string
  LOG_LEVEL: string
  LOG_MAX_SIZE: number
  LOG_TO_FILE: boolean
  MAX_USERS_PER_PARTY: number
  RATE_LIMIT_API_CALLS: string
  RATE_LIMIT_AVATAR_RECOVERY: string
  RATE_LIMIT_CHAT: string
  RATE_LIMIT_LOGIN: string
  RATE_LIMIT_PARTY_CREATION: string
  RATE_LIMIT_SOCKET_CONNECTIONS: string
  REQUIRE_LOGIN: boolean
  STATIC_SESSION_ENABLED: boolean
  STATIC_SESSION_ID: string
  error?: string
}
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
export interface ConfigUpdateResponse {
  success: boolean
  changed: string[]
  rejected: Array<{ key: string; reason: string }>
  restart_required: string[]
  config?: AdminConfig
  error?: string
}

export async function apiFetch<T = JsonValue>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(withPrefix(path), {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    credentials: 'same-origin',
    ...options,
  })
  const body = await readResponseBody(resp)

  if (!resp.ok) {
    throw responseError(resp, body)
  }

  return body as T
}

export const api = {
  // Auth (become host of current party)
  login: (username: string, password: string, signal?: AbortSignal) =>
    apiFetch<AuthResponse>('/api/v2/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }), signal,
    }),
  logout: (signal?: AbortSignal) => apiFetch<SuccessResponse>(
    '/api/v2/auth/logout', { method: 'POST', signal },
  ),
  authStatus: (signal?: AbortSignal) => apiFetch<AuthResponse>('/api/v2/auth/status', { signal }),
  mediaServerInfo: (signal?: AbortSignal) => apiFetch<MediaServerInfoV2>(
    '/api/v2/media-server', { signal },
  ),
  version: (signal?: AbortSignal) => apiFetch<VersionResponse>('/api/version', { signal }),

  // Library
  libraries: async (signal?: AbortSignal) => projectMediaPage(
    await apiFetch<MediaPageV2>('/api/v2/libraries', { signal }),
  ),
  items: async (
    params: Record<string, string | number | boolean>, signal?: AbortSignal,
  ) => projectMediaPage(await apiFetch<MediaPageV2>('/api/v2/items/query', {
    method: 'POST',
    body: JSON.stringify({
      scope: {
        parent_id: typeof params.parentId === 'string' ? params.parentId : null,
        include_kinds: typeof params.type === 'string'
          ? params.type.split(',').filter(Boolean).map(kind => kind.replace(
              /([a-z0-9])([A-Z])/g, '$1_$2',
            ).toLowerCase())
          : [],
        media_kinds: [],
        recursive: params.recursive === true || params.recursive === 'true',
      },
      page: {
        start: typeof params.startIndex === 'number' ? params.startIndex : 0,
        limit: typeof params.limit === 'number' ? params.limit : 50,
      },
      sort: { field: 'name', direction: 'ascending' },
      filters: {},
      anchor_prefix: typeof params.anchorPrefix === 'string' ? params.anchorPrefix : undefined,
    } satisfies CatalogQueryV2),
    signal,
  })),
  itemPrefixes: async (parentId: string, signal?: AbortSignal) => {
    const response = await apiFetch<PrefixesV2>('/api/v2/items/prefixes', {
      method: 'POST',
      body: JSON.stringify({ scope: { parent_id: parentId } } satisfies CatalogQueryV2),
      signal,
    })
    return { Prefixes: response.prefixes }
  },
  filterOptions: (
    params: { parentId?: string; includeItemTypes?: string; mediaTypes?: string },
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams()
    if (params.parentId) query.set('parent_id', params.parentId)
    if (params.includeItemTypes) {
      query.set('include_kinds', params.includeItemTypes.split(',').map(kind => kind.replace(
        /([a-z0-9])([A-Z])/g, '$1_$2',
      ).toLowerCase()).join(','))
    }
    if (params.mediaTypes) query.set('media_kinds', params.mediaTypes.toLowerCase())
    return apiFetch<FilterOptionsResponse>(`/api/v2/items/filter-options?${query}`, { signal })
  },
  queryItems: async (query: LibraryQueryRequest, signal?: AbortSignal) => projectMediaPage(
    await apiFetch<MediaPageV2>('/api/v2/items/query', {
      method: 'POST', body: JSON.stringify(toCatalogQueryV2(query)), signal,
    }),
  ),
  queryPrefixes: async (query: LibraryQueryRequest, signal?: AbortSignal) => {
    const response = await apiFetch<PrefixesV2>('/api/v2/items/prefixes', {
      method: 'POST', body: JSON.stringify(toCatalogQueryV2(query)), signal,
    })
    return { Prefixes: response.prefixes }
  },
  search: async (q: string, signal?: AbortSignal) => projectMediaPage(
    await apiFetch<MediaPageV2>(`/api/v2/items/search?q=${encodeURIComponent(q)}`, { signal }),
  ),
  groupedSearch: async (q: string, signal?: AbortSignal): Promise<GroupedSearchResponse> => {
    const response = await apiFetch<GroupedSearchV2>(
      `/api/v2/items/search/groups?q=${encodeURIComponent(q)}`, { signal },
    )
    const groupIds = new Set<SearchGroup['id']>([
      'movies', 'series', 'episodes', 'people', 'collections', 'other',
    ])
    return {
      query: response.query,
      groups: response.groups.map(group => ({
        id: groupIds.has(group.id as SearchGroup['id'])
          ? group.id as SearchGroup['id']
          : 'other',
        label: group.label,
        items: group.items.map(projectMediaItem),
      })),
    }
  },
  itemDetails: async (id: string, signal?: AbortSignal) => projectMediaDetails(
    await apiFetch<MediaItemDetailsV2>(`/api/v2/items/${id}`, { signal }),
  ),
  itemSection: async (
    id: string, section: ItemSection, signal?: AbortSignal,
  ): Promise<ItemSectionResponse> => {
    const response = await apiFetch<MediaSectionV2>(
      `/api/v2/items/${id}/sections/${section}`, { signal },
    )
    return { section: response.section, items: response.items.map(projectMediaItem) }
  },
  seriesSeasons: async (id: string, signal?: AbortSignal): Promise<ItemChildrenResponse> => ({
    items: projectMediaPage(
      await apiFetch<MediaPageV2>(`/api/v2/items/${id}/seasons`, { signal }),
    ).Items,
  }),
  seriesEpisodes: async (
    id: string, seasonId?: string, signal?: AbortSignal,
  ): Promise<ItemChildrenResponse> => {
    const query = seasonId ? `?season_id=${encodeURIComponent(seasonId)}` : ''
    const page = await apiFetch<MediaPageV2>(`/api/v2/items/${id}/episodes${query}`, { signal })
    return { items: projectMediaPage(page).Items }
  },
  setFavorite: (id: string, favorite: boolean, signal?: AbortSignal) =>
    apiFetch<{ success: boolean; favorite: boolean }>(`/api/v2/items/${id}/favorite`, {
      method: 'PUT', body: JSON.stringify({ favorite }), signal,
    }),
  setPlayed: (id: string, played: boolean, signal?: AbortSignal) =>
    apiFetch<{ success: boolean; played: boolean }>(`/api/v2/items/${id}/played`, {
      method: 'PUT', body: JSON.stringify({ played }), signal,
    }),
  playlists: async (signal?: AbortSignal): Promise<PlaylistListResponse> => ({
    items: projectMediaPage(await apiFetch<MediaPageV2>('/api/v2/playlists', { signal })).Items,
  }),
  createPlaylist: (name: string, signal?: AbortSignal) =>
    apiFetch<{ id: string; name: string }>('/api/v2/playlists', {
      method: 'POST', body: JSON.stringify({ name }), signal,
    }),
  addPlaylistItem: (playlistId: string, itemId: string, signal?: AbortSignal) =>
    apiFetch<{ success: boolean }>(`/api/v2/playlists/${playlistId}/items`, {
      method: 'POST', body: JSON.stringify({ item_id: itemId }), signal,
    }),
  // mediaSourceId optionally scopes the response to one alternate
  // version. When omitted, the audio/subtitle arrays describe Emby's
  // default source and `versions` still lists every alternate.
  itemStreams: async (id: string, mediaSourceId?: string, signal?: AbortSignal) => {
    const qs = mediaSourceId ? `?media_source_id=${encodeURIComponent(mediaSourceId)}` : ''
    const streams = await apiFetch<StreamCatalogV2>(`/api/v2/items/${id}/streams${qs}`, { signal })
    return {
      audio: streams.audio.map(stream => ({
        index: stream.index,
        language: stream.language,
        displayLanguage: stream.display_language,
        codec: stream.codec,
        channels: stream.channels,
        isDefault: stream.is_default,
        title: stream.title,
      })),
      subtitles: streams.subtitles.map(stream => ({
        index: stream.index,
        language: stream.language,
        displayLanguage: stream.display_language,
        codec: stream.codec,
        isDefault: stream.is_default,
        isForced: stream.is_forced,
        isExternal: stream.is_external,
        isPGS: stream.is_image,
        isTextSubtitleStream: stream.is_text,
        title: stream.title,
      })),
      media_source_id: streams.media_source_id,
      versions: streams.versions.map(version => ({
        id: version.id,
        name: version.name,
        container: version.container,
        run_time_ticks: version.runtime_seconds === null
          ? null
          : version.runtime_seconds * 10_000_000,
      })),
    } satisfies StreamsResponse
  },

  // Media
  intro: async (id: string, signal?: AbortSignal): Promise<IntroResponse> => {
    const intro = await apiFetch<IntroSegmentV2>(`/api/v2/items/${id}/intro`, { signal })
    return {
      hasIntro: intro.has_intro,
      start: intro.start_seconds ?? undefined,
      end: intro.end_seconds ?? undefined,
      duration: intro.duration_seconds ?? undefined,
    }
  },
  imageUrl: (
    id: string,
    type = 'Primary',
    opts?: { index?: number; maxWidth?: number; maxHeight?: number; quality?: number },
  ) => {
    const params = new URLSearchParams()
    if (opts?.index !== undefined) params.set('index', String(opts.index))
    if (opts?.maxWidth) params.set('max_width', String(opts.maxWidth))
    if (opts?.maxHeight) params.set('max_height', String(opts.maxHeight))
    if (opts?.quality) params.set('quality', String(opts.quality))
    return withPrefix(`/api/v2/items/${id}/images/${type.toLowerCase()}?${params.toString()}`)
  },
  subtitleUrl: (id: string, mediaSourceId: string, subtitleIndex: number) => withPrefix(
    `/api/v2/items/${id}/subtitles/${mediaSourceId}/${subtitleIndex}`,
  ),

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
  partyInfo: (id: string, signal?: AbortSignal) => apiFetch<PartyInfoResponse>(
    `/api/party/${id}/info`, { signal },
  ),

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
    const responseBody = await readResponseBody(resp)
    if (!resp.ok) throw responseError(resp, responseBody)
    if (!isJsonObject(responseBody)) {
      throw new ApiError(resp.status, 'Invalid avatar response', responseBody)
    }
    return {
      success: typeof responseBody.success === 'boolean' ? responseBody.success : undefined,
      message: typeof responseBody.message === 'string' ? responseBody.message : undefined,
      uuid: typeof responseBody.uuid === 'string' ? responseBody.uuid : undefined,
      code: typeof responseBody.code === 'string' ? responseBody.code : undefined,
    }
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
  adminGetConfig: (signal?: AbortSignal) => apiFetch<AdminConfig>('/api/admin/config', { signal }),
  adminUpdateConfig: (data: AdminConfig, signal?: AbortSignal) =>
    apiFetch<ConfigUpdateResponse>('/api/admin/config', {
      method: 'PUT', body: JSON.stringify(data), signal,
    }),
}
