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

      <div v-else class="library-content">
        <div class="items-grid">
          <div
            v-for="item in displayedItems"
            :key="item.Id"
            :data-item-id="item.Id"
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

        <!-- iOS-style A-Z jump bar. Only renders when the list is long
             enough that scrolling becomes a chore (>=30 items). Dimmed
             letters have no matching items and are not clickable.
             Left-click jumps to the letter; right-click toggles a
             filter that hides everything except items starting with
             that letter (right-click the same letter again to clear). -->
        <div v-if="showAlphabetBar" class="alphabet-bar" aria-label="Jump to letter">
          <button
            v-for="letter in ALPHABET"
            :key="letter"
            class="alphabet-letter"
            :class="{
              dim: !alphabetIndex.has(letter),
              active: filteredLetter === letter,
            }"
            :disabled="!alphabetIndex.has(letter)"
            @click="jumpToLetter(letter)"
            @contextmenu="toggleFilterLetter(letter, $event)"
            :aria-label="filteredLetter === letter
              ? `Showing only ${letter}; right-click to clear`
              : `Jump to ${letter}; right-click to show only ${letter}`"
          >
            {{ letter }}
          </button>
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

// First letter of each item's Name, bucketed for the A-Z jump bar.
// Returns '#' for digits/symbols so they cluster under one button
// rather than spreading across letters that don't exist. Articles are
// already stripped server-side via Emby's SortName (`The Matrix` is
// sorted as `Matrix`) so the on-screen card order matches the letter
// the user reaches for.
function bucketLetter(name: string): string {
  const first = (name || '').trim().charAt(0).toUpperCase()
  return /^[A-Z]$/.test(first) ? first : '#'
}

// Map letter -> first item Id starting with that letter. Always built
// against the FULL items list (not the filtered view below) so the
// jump bar can navigate to any letter even while a filter is active.
const alphabetIndex = computed(() => {
  const map = new Map<string, string>()
  for (const item of items.value) {
    const letter = bucketLetter(item.Name)
    if (!map.has(letter)) {
      map.set(letter, item.Id)
    }
  }
  return map
})

const showAlphabetBar = computed(() => items.value.length >= ALPHABET_BAR_MIN_ITEMS)

// Right-click on a letter restricts the visible grid to items whose
// names start with that letter. null = no filter, show everything.
// Cleared automatically whenever the underlying items list is replaced
// (folder navigation, fresh search, etc.) so a filter never carries
// over into an unrelated view.
const filteredLetter = ref<string | null>(null)

const displayedItems = computed(() => {
  if (!filteredLetter.value) return items.value
  return items.value.filter((item) => bucketLetter(item.Name) === filteredLetter.value)
})

function jumpToLetter(letter: string) {
  // Left-click always shows the full list and jumps to the letter --
  // otherwise scrolling to letter "A" while filtered to "M" would
  // silently no-op because A's first item is currently filtered out.
  filteredLetter.value = null
  const targetId = alphabetIndex.value.get(letter)
  if (!targetId) return
  // Defer the scroll one tick so any DOM updates from clearing the
  // filter have flushed before we look up the target card.
  nextTick(() => {
    const el = document.querySelector(`[data-item-id="${targetId}"]`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  })
}

function toggleFilterLetter(letter: string, event: MouseEvent) {
  // Block the native browser context menu -- right-click on the
  // alphabet bar is "filter" in this UI, not "inspect element".
  event.preventDefault()
  if (!alphabetIndex.value.has(letter)) return
  filteredLetter.value = filteredLetter.value === letter ? null : letter
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
    filteredLetter.value = null
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
    // A fresh navigation means a fresh A-Z scope; the previous
    // letter-filter shouldn't carry over into an unrelated view.
    filteredLetter.value = null
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
  // After the FIRST page returns, if the library is large enough to
  // want the alphabet bar, cascade-load the remaining pages in the
  // background so the bar's dim/active state reflects the whole
  // library rather than just whichever 50 items happened to land
  // first. The IntersectionObserver-driven scroll loader still wins
  // races thanks to the loadingMore gate -- the background loop just
  // makes sure pagination doesn't stall on a list the user never has
  // a reason to scroll (search results, top-level libraries, etc.).
  if (!append && hasMore.value && items.value.length >= ALPHABET_BAR_MIN_ITEMS) {
    void cascadeLoadAll()
  }
}

async function cascadeLoadAll() {
  // Walk subsequent pages sequentially until Emby says we're done.
  // Sequential (not parallel) so we don't dogpile a slow Emby with
  // 20 concurrent /api/items hits on a fresh library mount.
  while (hasMore.value && !loadingMore.value && currentParentId.value) {
    await fetchItems(currentParentId.value, true)
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
  filteredLetter.value = null
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
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
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
  height: 16px;
  display: grid;
  place-items: center;
  font-size: 10px;
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

/* Active state when the right-click filter is pinned to this letter.
   Inverted colour so it reads as "this is what's currently selected"
   at a glance even on a dense column of letters. Adds a glow pulse so
   the active letter visibly draws the eye -- ~1.2s breathing cycle,
   slow enough not to read as a strobe but fast enough to be noticeable
   in peripheral vision while the user is scanning cards. */
.alphabet-letter.active {
  background: var(--accent-primary);
  color: var(--bg-deep);
  animation: alphabet-pulse 1.2s ease-in-out infinite;
}

@keyframes alphabet-pulse {
  0%, 30% {
    box-shadow: 0 0 0 0 var(--accent-primary-glow);
    background: var(--accent-primary);
  }
  100% {
    box-shadow: 0 0 6px 2px var(--accent-primary-glow);
    background: #67e8f9;
  }
}

/* Respect users who disabled motion in their OS -- show the active
   state as a static glow without the looping animation. */
@media (prefers-reduced-motion: reduce) {
  .alphabet-letter.active {
    animation: none;
    box-shadow: 0 0 6px 2px var(--accent-primary-glow);
  }
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
