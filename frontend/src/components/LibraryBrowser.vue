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
          @click="handleItemClick(item)"
        >
          <div class="item-poster">
            <img
              v-if="item.ImageTags?.Primary"
              :src="imageUrl(item.Id)"
              :alt="item.Name"
              loading="lazy"
            />
            <div v-else class="no-poster">{{ item.Name.charAt(0) }}</div>
          </div>
          <div class="item-info">
            <span class="item-name">{{ item.Name }}</span>
            <span v-if="item.ProductionYear" class="item-year">{{ item.ProductionYear }}</span>
            <span class="item-type">{{ item.Type }}</span>
          </div>
        </div>
        <div v-if="hasMore" ref="sentinel" class="sentinel">
          <span v-if="loadingMore">Loading more...</span>
        </div>
      </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { api } from '@/api/client'

interface EmbyItem {
  Id: string
  Name: string
  Type: string
  ImageTags?: { Primary?: string }
  ProductionYear?: number
  Overview?: string
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

function imageUrl(id: string): string {
  return api.imageUrl(id, 'Primary')
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
  await fetchItems(crumb.id)
}

async function fetchLibraries() {
  loading.value = true
  try {
    const data = await api.libraries()
    items.value = data.Items ?? data ?? []
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

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
    const newItems = data.Items ?? data ?? []
    if (append) {
      items.value.push(...newItems)
    } else {
      items.value = newItems
    }
    const totalCount = data.TotalRecordCount ?? newItems.length
    hasMore.value = items.value.length < totalCount
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

onMounted(() => {
  setupObserver()
  fetchLibraries()
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
  gap: 0.25rem;
  font-size: 0.9rem;
  color: var(--text-primary);
}

.crumb {
  cursor: pointer;
  color: var(--cyber-primary);
}

.crumb:hover {
  text-decoration: underline;
}

.crumb.active {
  cursor: default;
  color: var(--text-primary);
}

.crumb.active:hover {
  text-decoration: none;
}

.crumb-sep {
  color: var(--cyber-border);
}

.search-bar {
  display: flex;
  gap: 0.5rem;
}

.search-bar input {
  flex: 1;
  padding: 0.4rem 0.6rem;
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--cyber-border);
  border-radius: 4px;
  outline: none;
}

.search-bar input:focus {
  border-color: var(--cyber-primary);
}

.search-bar button {
  padding: 0.4rem 0.8rem;
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--cyber-border);
  cursor: pointer;
  border-radius: 4px;
}

.search-bar button:hover {
  background: var(--cyber-primary);
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
  background: var(--bg-secondary);
  border: 1px solid var(--cyber-border);
  border-radius: 4px;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.15s;
}

.item-card:hover {
  border-color: var(--cyber-primary);
}

.item-poster {
  aspect-ratio: 2 / 3;
  overflow: hidden;
  background: var(--bg-primary);
}

.item-poster img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.no-poster {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 2rem;
  color: var(--cyber-primary);
}

.item-info {
  padding: 0.4rem 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.item-name {
  font-size: 0.85rem;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-year {
  font-size: 0.75rem;
  color: var(--cyber-border);
}

.item-type {
  font-size: 0.7rem;
  color: var(--cyber-primary);
  text-transform: uppercase;
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
