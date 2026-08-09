<template>
  <div ref="browserRoot" class="library-browser">
      <div class="panel-header">
        <div class="breadcrumbs">
          <span class="crumb" @click="goToRoot">Libraries</span>
          <template v-for="(crumb, i) in breadcrumbs" :key="crumb.id">
            <span class="crumb-sep">/</span>
            <span
              class="crumb"
              :class="{ active: i === breadcrumbs.length - 1 }"
              @click="goToCrumb(i)"
            >
              {{ crumb.name }}
            </span>
          </template>
        </div>

        <div class="search-bar">
          <input
            v-model="searchQuery"
            type="text"
            placeholder="Search..."
            @keydown.enter="doSearch"
          />
          <button @click="doSearch">Search</button>
          <button v-if="isSearching" @click="clearSearch">Clear</button>
        </div>
      </div>

      <div v-if="currentParentId" class="library-tools">
        <LibraryFilters
          :controls="filterControls"
          :model-value="filterState"
          @update:model-value="applyFilters"
        />
        <label>
          Sort
          <select v-model="sortField" aria-label="Sort titles" @change="applySort">
            <option value="SortName">Title</option>
            <option value="DateCreated">Date added</option>
            <option value="PremiereDate">Release date</option>
            <option value="ProductionYear">Year</option>
            <option value="CommunityRating">Community rating</option>
            <option value="CriticRating">Critic rating</option>
            <option value="Runtime">Runtime</option>
            <option value="Random">Random</option>
          </select>
          <select v-model="sortDirection" aria-label="Sort direction" @change="applySort">
            <option value="Ascending">Ascending</option>
            <option value="Descending">Descending</option>
          </select>
        </label>
      </div>

      <div v-if="loading" class="loading">Loading...</div>

      <div v-else-if="items.length === 0" class="empty">No items found.</div>

      <div v-else class="library-content">
        <div class="items-grid">
          <div v-if="hasPrevious" ref="topSentinel" class="sentinel sentinel-top">
            <span v-if="loadingPrevious">Loading earlier titles...</span>
          </div>
          <div
            v-for="item in items"
            :key="item.Id"
            :data-item-id="item.Id"
            class="item-card"
            :class="{
              'item-card-live': item.Id === playingItemId,
              'item-card-next': item.Id === nextItemId,
            }"
            @click="handleItemClick(item)"
          >
            <div class="item-poster" :style="posterStyle(item)">
              <img
                v-if="item.ImageTags?.Primary"
                :src="imageUrl(item.Id)"
                :alt="item.Name"
                loading="lazy"
              />
              <div v-else class="no-poster">{{ item.Name.charAt(0) }}</div>
              <div v-if="item.Id === playingItemId" class="live-badge" aria-label="Currently playing">
                <span class="eq" aria-hidden="true"><i></i><i></i><i></i></span>
                <span class="live-text">LIVE</span>
              </div>
              <div v-else-if="item.Id === nextItemId" class="next-badge" aria-label="Up next">
                <span class="next-arrow" aria-hidden="true">&#9654;</span>
                <span class="next-text">NEXT</span>
              </div>
              <!-- Played-progress bar at the bottom of the poster.
                   Mirrors Emby's web UI Continue Watching rail: the
                   resume position the host will land on if they pick
                   Resume from the prompt. Driven by
                   UserData.PlayedPercentage which Emby pre-computes,
                   so no arithmetic on our side. Hidden once the item
                   is fully Played to keep the rail focused on
                   "in progress" items. -->
              <div
                v-if="resumePercent(item) > 0"
                class="poster-progress"
                :aria-label="`Watched ${Math.round(resumePercent(item))}%`"
              >
                <div class="poster-progress-fill" :style="{ width: resumePercent(item) + '%' }" />
              </div>
            </div>
            <div class="item-info">
              <span class="item-name">{{ item.Name }}</span>
              <span class="item-meta">
                <span v-if="item.ProductionYear">{{ item.ProductionYear }}</span>
                <span v-if="item.ProductionYear && itemRuntime(item)" class="sep">·</span>
                <span v-if="itemRuntime(item)">{{ itemRuntime(item) }}</span>
                <span v-if="!item.ProductionYear && !itemRuntime(item)" class="item-type">{{ item.Type }}</span>
              </span>
              <span v-if="playedLabel(item)" class="item-played">{{ playedLabel(item) }}</span>
            </div>
          </div>
          <div v-if="hasMore" ref="sentinel" class="sentinel">
            <span v-if="loadingMore">Loading more...</span>
          </div>
        </div>

        <!-- iOS-style prefix jump bar. Availability comes from Emby,
             not the currently loaded page, so every server prefix works
             immediately in a paginated library. -->
        <div v-if="showAlphabetBar" class="alphabet-bar" aria-label="Jump to letter">
          <button
            v-for="letter in displayedPrefixes"
            :key="letter"
            class="alphabet-letter"
            :class="{ dim: !availablePrefixes.has(letter) }"
            :disabled="!availablePrefixes.has(letter)"
            @click="jumpToLetter(letter)"
            :aria-label="`Jump to ${letter}`"
          >
            {{ letter }}
          </button>
        </div>
      </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { api, type FilterControl, type LibraryFilterState, type LibraryQueryRequest } from '@/api/client'
import { usePartyStore } from '@/stores/party'
import LibraryFilters from './LibraryFilters.vue'

const party = usePartyStore()
// Drives the LIVE badge + EQ animation overlay on the currently-playing
// card. Falls back to null when nothing is selected so the overlay never
// renders accidentally on a stale match.
const playingItemId = computed<string | null>(() => party.currentVideo?.item_id ?? null)
// Pulls the resume percentage off an item's UserData. Emby
// pre-computes PlayedPercentage (0-100, float) on every user-scoped
// item response. The gating is "is there a current resume position",
// NOT "has this ever been played", so we check PlaybackPositionTicks
// rather than the Played flag -- Played goes true on the first
// completion and never goes back to false, even when the user later
// starts a re-watch. Emby clears PlaybackPositionTicks on natural
// completion, so PositionTicks > 0 means "you have a real resume
// point right now" regardless of how many times the item has been
// finished historically.
function resumePercent(item: EmbyItem): number {
  const ud = item.UserData
  if (!ud) return 0
  const positionTicks = Number(ud.PlaybackPositionTicks ?? 0)
  if (positionTicks <= 0) return 0
  const pct = Number(ud.PlayedPercentage ?? 0)
  if (!isFinite(pct) || pct <= 0) return 0
  return Math.min(100, pct)
}

// Drives the NEXT badge on the queued-up episode. Backend pins
// next_item_id on current_video at selection time (precomputed via
// IndexNumber), so the badge can show the moment the host arms binge
// rather than waiting for the auto-advance countdown. Gated on the
// host having opted in via the Binge ON/OFF pill -- otherwise no
// auto-advance is going to happen and the badge would mislead.
const nextItemId = computed<string | null>(() => {
  if (!party.bingeWatch.active) return null
  return party.currentVideo?.next_item_id ?? null
})

// iOS-style A-Z jump bar (rendered on lists with >=30 items so short
// folders / seasons don't sprout a sidebar for no reason). `#` covers
// everything starting with a digit, symbol, or non-Latin glyph so the
// total column height stays constant at 27 buttons regardless of what
// the library contains.
const ALPHABET = ['#', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M',
                  'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z']
const ALPHABET_BAR_MIN_ITEMS = 30

interface EmbyItem {
  Id: string
  Name: string
  Type: string
  ImageTags?: { Primary?: string }
  PrimaryImageAspectRatio?: number
  ProductionYear?: number
  Overview?: string
  RunTimeTicks?: number
  SortName?: string
  UserData?: {
    PlaybackPositionTicks?: number
    PlayedPercentage?: number
    Played?: boolean
  }
}

// Emby returns RunTimeTicks as 100-nanosecond units. Format as the
// library card "Xh Ym" shorthand used by the mockup. Returns null when
// the item has no runtime so the meta row can drop the separator.
function itemRuntime(item: EmbyItem): string | null {
  const ticks = item.RunTimeTicks
  if (!ticks || ticks <= 0) return null
  return ticksToShort(ticks)
}

function ticksToShort(ticks: number): string {
  const totalSeconds = Math.floor(ticks / 10_000_000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m`
  return '<1m'
}

// "Played: 1h 2m (41%) of 2h 34m" -- mirrors Emby's Continue Watching
// card text so users coming from Emby get the same readout. Returns
// null when there's no resume position worth surfacing (either fully
// played, never played, or Emby gated it below its threshold).
function playedLabel(item: EmbyItem): string | null {
  const pct = resumePercent(item)
  if (pct <= 0) return null
  const ud = item.UserData
  const playedTicks = Number(ud?.PlaybackPositionTicks ?? 0)
  const totalTicks = item.RunTimeTicks ?? 0
  if (!playedTicks || !totalTicks) return null
  return `Played: ${ticksToShort(playedTicks)} (${Math.round(pct)}%) of ${ticksToShort(totalTicks)}`
}

interface Breadcrumb {
  id: string
  name: string
  type?: string
}

const emit = defineEmits<{
  'select-video': [item: EmbyItem]
  'navigation-change': [label: string]
}>()

const browserRoot = ref<HTMLElement | null>(null)
const loading = ref(false)
const loadingMore = ref(false)
const loadingPrevious = ref(false)
const items = ref<EmbyItem[]>([])
const breadcrumbs = ref<Breadcrumb[]>([])
const searchQuery = ref('')
const isSearching = ref(false)
const hasMore = ref(false)
const hasPrevious = ref(false)
const loadedStartIndex = ref(0)
const totalRecordCount = ref(0)
const currentParentId = ref<string | null>(null)
const currentParentType = ref<string | null>(null)
const PAGE_SIZE = 50
const filterControls = ref<FilterControl[]>([])
const filterState = ref<LibraryFilterState>({})
const sortField = ref<LibraryQueryRequest['sort']['field']>('SortName')
const sortDirection = ref<LibraryQueryRequest['sort']['direction']>('Ascending')
let configuredParentId: string | null = null

const FILTER_FIELDS: Record<string, string> = {
  genre: 'genres',
  official_rating: 'official_ratings',
  studio: 'studios',
  tag: 'tags',
  year: 'years',
  container: 'containers',
  video_codec: 'video_codecs',
  video_type: 'video_types',
  resolution: 'resolutions',
  audio_codec: 'audio_codecs',
  audio_layout: 'audio_layouts',
  audio_language: 'audio_languages',
  subtitle_codec: 'subtitle_codecs',
  subtitle_language: 'subtitle_languages',
}

function filterStorageKey(parentId: string): string {
  return `emby-watchparty-library-filters:${parentId}`
}

function configureFilters(parentId: string) {
  if (configuredParentId === parentId) return
  configuredParentId = parentId
  try {
    const saved = JSON.parse(localStorage.getItem(filterStorageKey(parentId)) || '{}')
    filterState.value = saved.filters && typeof saved.filters === 'object' ? saved.filters : {}
    sortField.value = saved.sortField || 'SortName'
    sortDirection.value = saved.sortDirection || 'Ascending'
  } catch {
    filterState.value = {}
  }
  api.filterOptions({ parentId }, navigationSignal())
    .then((response) => {
      if (configuredParentId === parentId) filterControls.value = response.controls
    })
    .catch(() => {
      if (configuredParentId === parentId) filterControls.value = []
    })
}

function persistFilters() {
  if (!currentParentId.value) return
  try {
    localStorage.setItem(filterStorageKey(currentParentId.value), JSON.stringify({
      filters: filterState.value,
      sortField: sortField.value,
      sortDirection: sortDirection.value,
    }))
  } catch { /* ignore disabled storage */ }
}

function applyFilters(value: LibraryFilterState) {
  filterState.value = value
  persistFilters()
  if (!currentParentId.value) return
  bumpNavToken('applyFilters')
  void fetchItems(currentParentId.value)
}

function applySort() {
  persistFilters()
  if (!currentParentId.value) return
  bumpNavToken('applySort')
  void fetchItems(currentParentId.value)
}

function queryFilters(): LibraryQueryRequest['filters'] {
  const result: LibraryQueryRequest['filters'] = {}
  for (const [id, value] of Object.entries(filterState.value)) {
    const target = FILTER_FIELDS[id] || id
    if (id === 'favorite' || id === 'duplicates' || id === 'is_3d') {
      result[target] = value === 'true'
    } else if (id === 'year') {
      result[target] = (Array.isArray(value) ? value : [value]).map(Number)
    } else {
      result[target] = value
    }
  }
  return result
}

// Per-tab nav token. Bumped on every navigation (root, breadcrumb,
// folder click, search). Every async fetch captures the token at
// start and drops its result on resolve if the token has moved on,
// so a late page-1 from a folder we already navigated away from
// can't paint over the new view (xyxxyxxy: "shows libraries AND
// movies in the list" after fast back-nav on a large library).
let navToken = 0
let navigationController: AbortController | null = null
function bumpNavToken(reason: string): number {
  navigationController?.abort()
  navigationController = new AbortController()
  navToken += 1
  console.debug('[LibraryBrowser] navToken bump', { token: navToken, reason })
  return navToken
}

function navigationSignal(): AbortSignal {
  navigationController ??= new AbortController()
  return navigationController.signal
}

const browsableTypes = new Set(['CollectionFolder', 'Folder', 'Series', 'Season'])
const playableTypes = new Set(['Movie', 'Episode'])

// Persist the user's browsing position so they don't have to
// re-navigate from the root after a refresh, party rejoin, or
// app restart. Search state and root view are intentionally not
// saved -- those are transient or default.
const LIBRARY_STATE_KEY = 'emby-watchparty-library-state'

interface LibraryState {
  breadcrumbs: Breadcrumb[]
  parentId: string
}

function saveLibraryState() {
  if (!currentParentId.value) return
  try {
    const state: LibraryState = {
      breadcrumbs: [...breadcrumbs.value],
      parentId: currentParentId.value,
    }
    localStorage.setItem(LIBRARY_STATE_KEY, JSON.stringify(state))
  } catch {
    /* ignore quota / disabled storage */
  }
}

function clearLibraryState() {
  try {
    localStorage.removeItem(LIBRARY_STATE_KEY)
  } catch {
    /* ignore */
  }
}

function loadLibraryState(): LibraryState | null {
  try {
    const raw = localStorage.getItem(LIBRARY_STATE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed?.parentId || !Array.isArray(parsed?.breadcrumbs)) return null
    const breadcrumbs = parsed.breadcrumbs as Breadcrumb[]

    // Saved states written before breadcrumb types were persisted contain
    // only the top-level library id/name. That location is necessarily an
    // Emby CollectionFolder, so migrate it instead of silently disabling
    // alphabetical mode (and therefore the entire prefix rail). Deeper
    // untyped paths are ambiguous (Folder, Series, or Season); discard those
    // restore targets rather than applying alphabetical ordering to episodes.
    const rootBreadcrumb = breadcrumbs[0]
    if (breadcrumbs.length === 1 && rootBreadcrumb && !rootBreadcrumb.type) {
      breadcrumbs[0] = { ...rootBreadcrumb, type: 'CollectionFolder' }
    }
    if (!breadcrumbs.at(-1)?.type) return null

    return { parentId: parsed.parentId, breadcrumbs }
  } catch {
    return null
  }
}

// Card grid is auto-fill from 140px-wide minmax, so cards are ~140-200px
// at CSS pixels and need ~280-400px on a 2x display. 320x480 keeps posters
// crisp at retina while letting Emby downscale + re-encode server-side
// (the proxy used to forward full-resolution images, which made the grid
// crawl on throttled connections -- xyxxyxxy, beta12).
function imageUrl(id: string): string {
  return api.imageUrl(id, 'Primary', { maxWidth: 320, maxHeight: 480, quality: 90 })
}

const availablePrefixes = ref<Set<string>>(new Set())
const alphabeticalMode = computed(() => (
  currentParentType.value === 'CollectionFolder' || currentParentType.value === 'Folder'
))
const displayedPrefixes = computed(() => {
  const extras = [...availablePrefixes.value]
    .filter((prefix) => !ALPHABET.includes(prefix))
    .sort((a, b) => a.localeCompare(b))
  return [...ALPHABET, ...extras]
})
const showAlphabetBar = computed(() => (
  alphabeticalMode.value
  && sortField.value === 'SortName'
  && sortDirection.value === 'Ascending'
  && Object.keys(filterState.value).length === 0
  && totalRecordCount.value >= ALPHABET_BAR_MIN_ITEMS
  && availablePrefixes.value.size > 0
))

async function jumpToLetter(letter: string) {
  if (!currentParentId.value || !availablePrefixes.value.has(letter)) return
  bumpNavToken(`jumpToLetter:${letter}`)
  await fetchItems(currentParentId.value, false, false, letter)
  await nextTick()
  const firstItem = items.value[0]
  if (!firstItem) return
  browserRoot.value
    ?.querySelector<HTMLElement>(`[data-item-id="${CSS.escape(firstItem.Id)}"]`)
    // A smooth scroll races the top sentinel: it can prepend several pages
    // while the animation is still moving, leaving the viewport before (or
    // halfway through) the selected prefix. Land synchronously so prepend
    // scroll-height compensation keeps this exact first item pinned.
    ?.scrollIntoView({ behavior: 'auto', block: 'start' })
}

// Compute the card's aspect ratio from Emby's PrimaryImageAspectRatio.
// Emby returns this as a float (width/height): 0.667 for 2:3 portrait,
// 1.778 for 16:9 landscape, ~4.0 for ultra-wide custom banners. By
// applying it inline per card, each image fits its native aspect with
// no cropping and no awkward letterboxing. The grid arranges cards of
// varying heights via auto-fill; rows accommodate the tallest card in
// the row, and short cards just take less vertical space.
//
// Clamped to [0.4, 4.0] so absurd source aspects do not produce
// unreadable cards (e.g. an extremely tall thumbnail or a 10:1
// banner). Falls back to 2:3 portrait when Emby does not provide a
// ratio, matching the typical movie/episode poster shape.
function posterStyle(item: EmbyItem): Record<string, string> {
  let ratio = item.PrimaryImageAspectRatio
  if (!ratio || !isFinite(ratio) || ratio <= 0) {
    ratio = 2 / 3
  } else {
    ratio = Math.min(4.0, Math.max(0.4, ratio))
  }
  return { aspectRatio: String(ratio) }
}

async function goToRoot() {
  bumpNavToken('goToRoot')
  breadcrumbs.value = []
  isSearching.value = false
  searchQuery.value = ''
  hasMore.value = false
  hasPrevious.value = false
  loadedStartIndex.value = 0
  totalRecordCount.value = 0
  availablePrefixes.value = new Set()
  currentParentId.value = null
  currentParentType.value = null
  emit('navigation-change', 'Libraries')
  await fetchLibraries()
}

async function goToCrumb(index: number) {
  bumpNavToken(`goToCrumb:${index}`)
  const crumb = breadcrumbs.value[index]
  breadcrumbs.value = breadcrumbs.value.slice(0, index + 1)
  currentParentType.value = crumb?.type ?? null
  isSearching.value = false
  searchQuery.value = ''
  emit('navigation-change', crumb?.name ?? 'Libraries')
  await fetchItems(crumb!.id)
}

async function fetchLibraries() {
  const myToken = navToken
  loading.value = true
  try {
    const data = await api.libraries(navigationSignal())
    if (myToken !== navToken) {
      console.debug('[LibraryBrowser] fetchLibraries STALE — dropping result', { startedAt: myToken, current: navToken })
      return
    }
    items.value = data.Items ?? data ?? []
    totalRecordCount.value = data.TotalRecordCount ?? items.value.length
    loadedStartIndex.value = 0
    hasPrevious.value = false
    hasMore.value = false
    clearLibraryState()
    availablePrefixes.value = new Set()
  } catch {
    if (myToken !== navToken) return
    items.value = []
  } finally {
    if (myToken === navToken) loading.value = false
  }
}

// Types we render as cards. Generic `Folder` is intentionally
// excluded: Emby's /emby/Items endpoint can return raw filesystem
// folder entries that shadow the same physical paths as proper Movie
// or Episode items. Showing both produces broken-looking duplicates
// (filename as Name, single-character placeholder image) alongside
// the metadata-rich originals. 1.x's library.js filter does the
// same thing -- it kept only Movie / Series / Video at the library
// level. This filter generalises that to any depth of navigation.
const displayableTypes = new Set([
  'CollectionFolder', 'BoxSet',
  'Movie', 'Series', 'Season', 'Episode', 'Video',
  'MusicAlbum', 'MusicArtist', 'Audio',
])

async function fetchPrefixes(parentId: string) {
  if (!alphabeticalMode.value) {
    availablePrefixes.value = new Set()
    return
  }
  try {
    const data = await api.itemPrefixes(parentId, navigationSignal())
    availablePrefixes.value = new Set(
      (data.Prefixes ?? []).map((prefix) => prefix.trim().toUpperCase()).filter(Boolean),
    )
  } catch {
    availablePrefixes.value = new Set()
  }
}

async function fetchItems(
  parentId: string,
  append = false,
  prepend = false,
  anchorPrefix?: string,
): Promise<'ok' | 'stale' | 'error'> {
  // Append-paths inherit the current nav token (they're a continuation
  // of the same nav); fresh navigations get a new token via the caller
  // (handleItemClick / goToCrumb / etc.) before fetchItems runs.
  const myToken = navToken
  if (prepend) {
    loadingPrevious.value = true
  } else if (append) {
    loadingMore.value = true
  } else {
    loading.value = true
    items.value = []
    currentParentId.value = parentId
    configureFilters(parentId)
    hasPrevious.value = false
    hasMore.value = false
  }
  try {
    const previousPanel = browserRoot.value?.closest<HTMLElement>('.library-panel')
    const previousScrollHeight = previousPanel?.scrollHeight ?? 0
    const startIndex = prepend
      ? Math.max(0, loadedStartIndex.value - PAGE_SIZE)
      : append
        ? loadedStartIndex.value + items.value.length
        : 0
    const params: Record<string, string | number | boolean> = {
      parentId,
      startIndex,
      limit: PAGE_SIZE,
      sortMode: alphabeticalMode.value ? 'alphabetical' : 'default',
    }
    if (anchorPrefix) params.anchorPrefix = anchorPrefix
    const useQuery = Object.keys(filterState.value).length > 0
      || sortField.value !== 'SortName'
      || sortDirection.value !== 'Ascending'
    const data = useQuery
      ? await api.queryItems({
          scope: {
            parent_id: parentId,
            include_item_types: [],
            media_types: [],
            recursive: false,
          },
          page: { start_index: startIndex, limit: PAGE_SIZE },
          sort: { field: sortField.value, direction: sortDirection.value },
          filters: queryFilters(),
        }, navigationSignal())
      : await api.items(params, navigationSignal())
    if (myToken !== navToken) {
      console.debug('[LibraryBrowser] fetchItems STALE — dropping result', { startedAt: myToken, current: navToken, parentId, append })
      return 'stale'
    }
    const rawItems: EmbyItem[] = data.Items ?? data ?? []
    // Only filter raw Folder items when the response also contains
    // other displayable types -- in that case the Folders are
    // shadowing entries (Jeslyn's flat layout: Movies/Blade.mkv
    // returns both a Movie and a Folder pointing at the same path).
    // When the response is ENTIRELY Folder-typed, the library is
    // folder-organised and those Folders ARE the navigable content
    // (Oratorian's folder-per-movie layout: Movies/Blade/Blade.mkv
    // returns only Folder items at the library root, the actual
    // Movie items are one level deeper). Filtering everything out
    // would leave the view empty in that case.
    const hasDisplayable = rawItems.some(
      (it) => it.Type && displayableTypes.has(it.Type),
    )
    const newItems = hasDisplayable
      ? rawItems.filter((it) => displayableTypes.has(it.Type))
      : rawItems
    const responseStart = data.StartIndex ?? startIndex
    if (prepend) {
      items.value.unshift(...newItems)
      loadedStartIndex.value = responseStart
      await nextTick()
      if (previousPanel) {
        previousPanel.scrollTop += previousPanel.scrollHeight - previousScrollHeight
      }
    } else if (append) {
      items.value.push(...newItems)
    } else {
      items.value = newItems
      loadedStartIndex.value = responseStart
    }
    totalRecordCount.value = data.TotalRecordCount ?? newItems.length
    hasPrevious.value = loadedStartIndex.value > 0
    hasMore.value = loadedStartIndex.value + items.value.length < totalRecordCount.value
    // Only pin the current location as the restore target when the
    // response actually contained items. An empty response is ambiguous
    // with a mid-scan Emby state (files replaced, indexer hasn't caught
    // up yet). Pinning an empty parent_id would then re-hydrate the
    // empty grid on every reload until the user manually navigates
    // elsewhere. In-session navigation into an empty folder still
    // works -- it just doesn't get persisted.
    if (!append && !prepend && !isSearching.value && newItems.length > 0) saveLibraryState()
    if (!append && !prepend && !anchorPrefix) await fetchPrefixes(parentId)
  } catch {
    if (myToken !== navToken) return 'stale'
    if (!append && !prepend) items.value = []
    return 'error'
  } finally {
    if (myToken === navToken) {
      loading.value = false
      loadingMore.value = false
      loadingPrevious.value = false
    }
  }
  return 'ok'
}

function loadMore() {
  if (loadingMore.value || !hasMore.value || !currentParentId.value) return
  fetchItems(currentParentId.value, true)
}

function loadPrevious() {
  if (loadingPrevious.value || !hasPrevious.value || !currentParentId.value) return
  fetchItems(currentParentId.value, false, true)
}

async function doSearch() {
  const q = searchQuery.value.trim()
  if (!q) return
  const myToken = bumpNavToken(`doSearch:${q}`)
  loading.value = true
  isSearching.value = true
  breadcrumbs.value = []
  hasMore.value = false
  hasPrevious.value = false
  availablePrefixes.value = new Set()
  currentParentId.value = null
  currentParentType.value = null
  emit('navigation-change', 'Search results')
  try {
    const data = await api.search(q, navigationSignal())
    if (myToken !== navToken) {
      console.debug('[LibraryBrowser] doSearch STALE — dropping result', { startedAt: myToken, current: navToken, q })
      return
    }
    items.value = data.Items ?? data ?? []
    totalRecordCount.value = data.TotalRecordCount ?? items.value.length
    loadedStartIndex.value = 0
  } catch {
    if (myToken !== navToken) return
    items.value = []
  } finally {
    if (myToken === navToken) loading.value = false
  }
}

function clearSearch() {
  isSearching.value = false
  searchQuery.value = ''
  goToRoot()
}

async function handleItemClick(item: EmbyItem) {
  if (playableTypes.has(item.Type)) {
    emit('select-video', item)
    return
  }

  if (browsableTypes.has(item.Type)) {
    bumpNavToken(`handleItemClick:${item.Type}:${item.Id}`)
    breadcrumbs.value.push({ id: item.Id, name: item.Name, type: item.Type })
    currentParentType.value = item.Type
    emit('navigation-change', item.Name)
    await fetchItems(item.Id)
  }
}

const topSentinel = ref<HTMLElement | null>(null)
const sentinel = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

function setupObserver() {
  if (observer) observer.disconnect()
  observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue
      if (entry.target === topSentinel.value) {
        loadPrevious()
      } else if (entry.target === sentinel.value) {
        loadMore()
      }
    }
  }, { rootMargin: '200px' })
}

watch([topSentinel, sentinel], ([top, bottom]) => {
  if (!observer) return
  observer.disconnect()
  if (top) observer.observe(top)
  if (bottom) observer.observe(bottom)
})

watch([hasPrevious, hasMore], async () => {
  await nextTick()
  if (!observer) return
  observer.disconnect()
  if (topSentinel.value) observer.observe(topSentinel.value)
  if (sentinel.value) observer.observe(sentinel.value)
})

async function restoreOrFetchRoot() {
  bumpNavToken('restoreOrFetchRoot')
  const saved = loadLibraryState()
  if (!saved) {
    await fetchLibraries()
    return
  }
  // Optimistically restore the breadcrumb chain so the header reflects
  // the saved depth while items load. Only fall back to root when the
  // fetch actually errored (parent gone, network fail). A legitimately
  // empty folder (Season with 0 visible Episodes, empty BoxSet) is a
  // valid destination and used to wipe the LibraryState on every
  // mount here, silently discarding the user's browsing position.
  breadcrumbs.value = saved.breadcrumbs
  currentParentType.value = saved.breadcrumbs.at(-1)?.type ?? null
  emit('navigation-change', saved.breadcrumbs.at(-1)?.name ?? 'Libraries')
  const status = await fetchItems(saved.parentId)
  if (status === 'error') {
    bumpNavToken('restoreOrFetchRoot:fallback')
    clearLibraryState()
    breadcrumbs.value = []
    currentParentId.value = null
    currentParentType.value = null
    emit('navigation-change', 'Libraries')
    await fetchLibraries()
  }
}

defineExpose({ goToRoot })

onMounted(() => {
  setupObserver()
  restoreOrFetchRoot()
})

onUnmounted(() => {
  navigationController?.abort()
  if (observer) observer.disconnect()
})
</script>

<style scoped>
.library-browser {
  width: 100%;
}

.panel-header {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.breadcrumbs {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.4rem;
  font-size: 13px;
  color: var(--text-secondary);
}

.crumb {
  cursor: pointer;
  color: var(--accent-primary);
  padding: 4px 8px;
  border-radius: 6px;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.crumb:hover {
  background: var(--bg-surface);
}

.crumb.active {
  cursor: default;
  color: var(--text-primary);
  background: var(--bg-surface-hover);
}

.crumb.active:hover {
  background: var(--bg-surface-hover);
}

.crumb-sep {
  color: var(--text-muted);
  opacity: 0.6;
}

.search-bar {
  display: flex;
  gap: 0.5rem;
}

.search-bar input {
  flex: 1;
  /* Inherits the global input chip styling (10px padding, 10px radius,
     cyan focus glow) -- no local overrides needed. */
}

.search-bar button {
  padding: 7px 14px;
  background: var(--bg-surface);
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  font-size: 13px;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast);
  white-space: nowrap;
}

.search-bar button:hover {
  background: var(--bg-surface-hover);
  border-color: var(--border-hover);
}

.loading,
.empty {
  text-align: center;
  padding: 2rem;
  color: var(--text-primary);
}

/* Flex row that puts the A-Z bar to the right of the grid. The grid
   gets flex:1 + min-width:0 so it can shrink to make room for the bar
   without forcing horizontal scroll on the panel. */
.library-content {
  display: flex;
  gap: 0.75rem;
  align-items: flex-start;
}

.items-grid {
  flex: 1;
  min-width: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 0.75rem;
}

/* The bar is sticky inside the scrolling library panel so it follows
   the user down the list without being absolutely positioned (which
   would have required hard-coded scroll-container coordinates).
   `top: 0` pins it to the top of the visible viewport within the
   panel; the panel's own padding takes care of breathing room. */
.alphabet-bar {
  position: sticky;
  top: 0;
  display: grid;
  grid-auto-flow: row;
  grid-auto-rows: minmax(0, 1fr);
  align-items: center;
  gap: clamp(0px, 0.15dvh, 1px);
  height: min(467px, calc(100dvh - 200px));
  min-height: 0;
  padding: 4px 2px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  user-select: none;
  flex-shrink: 0;
  align-self: flex-start;
}

.alphabet-letter {
  background: none;
  border: 0;
  padding: 0;
  width: 18px;
  height: 100%;
  min-height: 0;
  display: grid;
  place-items: center;
  font-size: clamp(7px, 1.2dvh, 10px);
  font-weight: 600;
  color: var(--accent-primary);
  font-family: var(--font-sans);
  border-radius: 3px;
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.alphabet-letter:hover:not(:disabled) {
  background: var(--accent-primary-dim);
}

.alphabet-letter.dim,
.alphabet-letter:disabled {
  color: var(--text-muted);
  opacity: 0.4;
  cursor: default;
}

.item-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  overflow: hidden;
  cursor: pointer;
  transition: border-color var(--transition-fast), background var(--transition-fast), transform var(--transition-fast);
}

.item-card:hover {
  background: var(--bg-surface-hover);
  border-color: var(--border-hover);
}

.item-card-live {
  /* Subtle cyan-tinted border + faint glow on the active item so it
     reads immediately when the library opens over the playing video. */
  border-color: var(--border-accent);
  background: linear-gradient(180deg, rgba(34, 211, 238, 0.06), transparent);
  box-shadow: 0 0 0 1px var(--border-accent), 0 0 24px rgba(34, 211, 238, 0.08);
}

.item-card-next {
  /* Magenta-tinted glow on the queued-up episode so the user can see
     at a glance what binge-watching is about to fire. Distinct hue
     from .item-card-live (cyan) so the two states never blur into
     each other when the library is open during the countdown. */
  border-color: rgba(255, 62, 214, 0.55);
  background: linear-gradient(180deg, rgba(255, 62, 214, 0.06), transparent);
  box-shadow: 0 0 0 1px rgba(255, 62, 214, 0.55), 0 0 24px rgba(255, 62, 214, 0.1);
}

.item-poster {
  /* aspect-ratio is set inline via posterStyle() from each item's
     PrimaryImageAspectRatio so each card matches its image. The
     fallback 2/3 here applies only if inline style fails to attach. */
  aspect-ratio: 2 / 3;
  overflow: hidden;
  background: var(--bg-primary);
  position: relative;
}

.item-poster img {
  width: 100%;
  height: 100%;
  /* `cover` is safe again now that the card's aspect ratio matches
     the source image's. No cropping happens when source and container
     match. */
  object-fit: cover;
}

.no-poster {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 2rem;
  color: var(--accent-primary);
}

/* LIVE overlay: positioned top-right of the poster so it stays visible
   when the card title wraps. The animated EQ bars communicate "live"
   without auto-playing video thumbnails. */
.live-badge {
  position: absolute;
  top: 8px;
  right: 8px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px 3px 7px;
  background: rgba(6, 7, 13, 0.7);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--border-accent);
  border-radius: var(--radius-full);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--accent-primary);
  pointer-events: none;
}

.live-badge .eq {
  display: inline-flex;
  align-items: flex-end;
  gap: 1.5px;
  height: 8px;
}

.live-badge .eq i {
  width: 1.5px;
  background: var(--accent-primary);
  border-radius: 1px;
  animation: lib-eq 1s infinite ease-in-out;
}

.live-badge .eq i:nth-child(1) { height: 60%; animation-delay: 0s; }
.live-badge .eq i:nth-child(2) { height: 100%; animation-delay: 0.2s; }
.live-badge .eq i:nth-child(3) { height: 40%; animation-delay: 0.4s; }

@keyframes lib-eq {
  0%, 100% { transform: scaleY(0.4); }
  50%      { transform: scaleY(1); }
}

/* NEXT overlay: same chip shape and position as .live-badge so they
   read as members of the same family, but a magenta accent (matching
   the AutoAdvanceModal progress bar gradient) and a tiny play-arrow
   glyph in place of the EQ animation. Static rather than animated
   because the countdown itself already provides the urgency cue --
   doubling up with another pulsing element would just feel busy. */
.next-badge {
  position: absolute;
  top: 8px;
  right: 8px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px 3px 7px;
  background: rgba(6, 7, 13, 0.7);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 62, 214, 0.6);
  border-radius: var(--radius-full);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--color-accent-magenta, #ff3ed6);
  pointer-events: none;
}

.next-badge .next-arrow {
  font-size: 8px;
  line-height: 1;
}

/* Played-progress overlay across the bottom edge of the poster.
   Matches Emby's web UI Continue Watching rail visually so users
   coming from Emby read it instantly. Cyan -> magenta gradient
   matches the AutoAdvanceModal + ResumePromptModal accent so the
   "you'll resume from here" affordance is consistent across the
   surfaces that surface it. */
.poster-progress {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 3px;
  background: rgba(0, 0, 0, 0.55);
  pointer-events: none;
}

.poster-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #00e0ff, #ff3ed6);
  transition: width 300ms ease-out;
}

.item-info {
  padding: 0.5rem 0.6rem 0.6rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.item-name {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-meta {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.72rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.item-meta .sep {
  opacity: 0.5;
}

.item-type {
  font-size: 0.7rem;
  color: var(--accent-primary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

/* "Played: 1h 2m (41%) of 2h 34m" -- sits on its own line under the
   year/runtime meta row. Cyan tint signals "this is the resume info"
   without competing with the poster's progress bar visually. Hidden
   unless there's a real resume position (helper returns null). */
.item-played {
  display: block;
  margin-top: 2px;
  font-size: 0.72rem;
  color: var(--color-accent-cyan, #00e0ff);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.01em;
}

.sentinel {
  grid-column: 1 / -1;
  text-align: center;
  padding: var(--space-md);
  color: var(--text-muted);
  font-size: 0.85rem;
  overflow-anchor: none;
}

.library-tools {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 1rem;
  align-items: start;
  margin-bottom: 1rem;
}

.library-tools select { margin-left: .35rem; }

@media (max-width: 700px) {
  .library-tools { grid-template-columns: 1fr; }
}

@media (max-width: 760px) {
  .library-browser,
  .panel-header,
  .search-bar,
  .library-content,
  .items-grid {
    min-width: 0;
    max-width: 100%;
  }

  .panel-header {
    margin-bottom: var(--space-sm);
  }

  .search-bar input {
    min-width: 0;
  }

  .search-bar button {
    flex-shrink: 0;
    padding-inline: 10px;
  }

  .library-content {
    gap: 6px;
  }

  .items-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.5rem;
  }

  .alphabet-bar {
    right: 0;
    height: min(521px, calc(100dvh - 180px - env(safe-area-inset-top)));
    max-height: none;
    overflow: hidden;
    scrollbar-width: none;
  }

  .alphabet-bar::-webkit-scrollbar {
    display: none;
  }

  .alphabet-letter {
    width: 20px;
    height: 100%;
  }
}
</style>
