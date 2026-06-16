<template>
  <div class="library-browser">
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

      <div v-if="loading" class="loading">Loading...</div>

      <div v-else-if="items.length === 0" class="empty">No items found.</div>

      <div v-else class="items-grid">
        <div
          v-for="item in items"
          :key="item.Id"
          class="item-card"
          :class="{ 'item-card-live': item.Id === playingItemId }"
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
          </div>
          <div class="item-info">
            <span class="item-name">{{ item.Name }}</span>
            <span class="item-meta">
              <span v-if="item.ProductionYear">{{ item.ProductionYear }}</span>
              <span v-if="item.ProductionYear && itemRuntime(item)" class="sep">·</span>
              <span v-if="itemRuntime(item)">{{ itemRuntime(item) }}</span>
              <span v-if="!item.ProductionYear && !itemRuntime(item)" class="item-type">{{ item.Type }}</span>
            </span>
          </div>
        </div>
        <div v-if="hasMore" ref="sentinel" class="sentinel">
          <span v-if="loadingMore">Loading more...</span>
        </div>
      </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { api } from '@/api/client'
import { usePartyStore } from '@/stores/party'

const party = usePartyStore()
// Drives the LIVE badge + EQ animation overlay on the currently-playing
// card. Falls back to null when nothing is selected so the overlay never
// renders accidentally on a stale match.
const playingItemId = computed<string | null>(() => party.currentVideo?.item_id ?? null)

interface EmbyItem {
  Id: string
  Name: string
  Type: string
  ImageTags?: { Primary?: string }
  PrimaryImageAspectRatio?: number
  ProductionYear?: number
  Overview?: string
  RunTimeTicks?: number
}

// Emby returns RunTimeTicks as 100-nanosecond units. Format as the
// library card "Xh Ym" shorthand used by the mockup. Returns null when
// the item has no runtime so the meta row can drop the separator.
function itemRuntime(item: EmbyItem): string | null {
  const ticks = item.RunTimeTicks
  if (!ticks || ticks <= 0) return null
  const totalSeconds = Math.floor(ticks / 10_000_000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m`
  return null
}

interface Breadcrumb {
  id: string
  name: string
}

const emit = defineEmits<{
  'select-video': [item: EmbyItem]
}>()

const loading = ref(false)
const loadingMore = ref(false)
const items = ref<EmbyItem[]>([])
const breadcrumbs = ref<Breadcrumb[]>([])
const searchQuery = ref('')
const isSearching = ref(false)
const hasMore = ref(false)
const currentParentId = ref<string | null>(null)
const PAGE_SIZE = 50

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
    return parsed as LibraryState
  } catch {
    return null
  }
}

function imageUrl(id: string): string {
  return api.imageUrl(id, 'Primary')
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
  breadcrumbs.value = []
  isSearching.value = false
  searchQuery.value = ''
  hasMore.value = false
  currentParentId.value = null
  await fetchLibraries()
}

async function goToCrumb(index: number) {
  const crumb = breadcrumbs.value[index]
  breadcrumbs.value = breadcrumbs.value.slice(0, index + 1)
  isSearching.value = false
  searchQuery.value = ''
  await fetchItems(crumb!.id)
}

async function fetchLibraries() {
  loading.value = true
  try {
    const data = await api.libraries()
    items.value = data.Items ?? data ?? []
    clearLibraryState()
  } catch {
    items.value = []
  } finally {
    loading.value = false
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

async function fetchItems(parentId: string, append = false) {
  if (append) {
    loadingMore.value = true
  } else {
    loading.value = true
    items.value = []
    currentParentId.value = parentId
  }
  try {
    const startIndex = append ? items.value.length : 0
    const data = await api.items({ parentId, startIndex, limit: PAGE_SIZE })
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
    if (append) {
      items.value.push(...newItems)
    } else {
      items.value = newItems
    }
    const totalCount = data.TotalRecordCount ?? newItems.length
    hasMore.value = items.value.length < totalCount
    if (!append && !isSearching.value) saveLibraryState()
  } catch {
    if (!append) items.value = []
    hasMore.value = false
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

function loadMore() {
  if (loadingMore.value || !hasMore.value || !currentParentId.value) return
  fetchItems(currentParentId.value, true)
}

async function doSearch() {
  const q = searchQuery.value.trim()
  if (!q) return
  loading.value = true
  isSearching.value = true
  breadcrumbs.value = []
  try {
    const data = await api.search(q)
    items.value = data.Items ?? data ?? []
  } catch {
    items.value = []
  } finally {
    loading.value = false
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
    breadcrumbs.value.push({ id: item.Id, name: item.Name })
    await fetchItems(item.Id)
  }
}

const sentinel = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

function setupObserver() {
  if (observer) observer.disconnect()
  observer = new IntersectionObserver((entries) => {
    if (entries[0]?.isIntersecting && hasMore.value && !loadingMore.value) {
      loadMore()
    }
  }, { rootMargin: '200px' })
}

watch(sentinel, (el) => {
  if (observer) observer.disconnect()
  if (el && observer) observer.observe(el)
})

watch(hasMore, async (val) => {
  if (val) {
    await nextTick()
    if (sentinel.value && observer) observer.observe(sentinel.value)
  }
})

async function restoreOrFetchRoot() {
  const saved = loadLibraryState()
  if (!saved) {
    await fetchLibraries()
    return
  }
  // Optimistically restore the breadcrumb chain so the header reflects
  // the saved depth while items load. If the parent no longer exists,
  // fetchItems comes back empty -- in that case fall back to the root
  // and clear the stale state.
  breadcrumbs.value = saved.breadcrumbs
  await fetchItems(saved.parentId)
  if (items.value.length === 0) {
    clearLibraryState()
    breadcrumbs.value = []
    currentParentId.value = null
    await fetchLibraries()
  }
}

onMounted(() => {
  setupObserver()
  restoreOrFetchRoot()
})

onUnmounted(() => {
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

.items-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 0.75rem;
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

.sentinel {
  grid-column: 1 / -1;
  text-align: center;
  padding: var(--space-md);
  color: var(--text-muted);
  font-size: 0.85rem;
  overflow-anchor: none;
}
</style>
