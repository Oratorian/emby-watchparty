<template>
  <div class="global-search">
    <input
      v-model="query"
      type="search"
      aria-label="Search all libraries"
      placeholder="Search movies, series, episodes, people…"
      autocomplete="off"
      @keydown.enter.prevent="submitNow"
    />
    <button v-if="query" type="button" @click="clear">Clear</button>
    <div v-if="loading" role="status">Searching…</div>
    <div v-else-if="error" role="alert">{{ error }}</div>
    <div v-else-if="submitted && !groups.length" class="empty-search">No results.</div>
    <div v-if="groups.length" class="search-results">
      <section v-for="group in groups" :key="group.id">
        <h3>{{ group.label }}</h3>
        <button
          v-for="item in group.items"
          :key="item.Id"
          type="button"
          :data-item-id="item.Id"
          @click="$emit('select', item)"
        >
          {{ item.Name }}
        </button>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { api, type LibraryItem, type SearchGroup } from '@/api/client'

defineEmits<{ select: [item: LibraryItem] }>()

const query = ref('')
const groups = ref<SearchGroup[]>([])
const loading = ref(false)
const submitted = ref(false)
const error = ref('')
let timer: ReturnType<typeof setTimeout> | null = null
let controller: AbortController | null = null
let requestToken = 0

function cancel() {
  if (timer) clearTimeout(timer)
  timer = null
  controller?.abort()
  controller = null
}

async function search() {
  const value = query.value.trim()
  cancel()
  if (value.length < 2) {
    groups.value = []
    submitted.value = false
    loading.value = false
    return
  }
  const token = ++requestToken
  controller = new AbortController()
  loading.value = true
  submitted.value = true
  error.value = ''
  try {
    const response = await api.groupedSearch(value, controller.signal)
    if (token !== requestToken) return
    groups.value = response.groups
  } catch (cause) {
    if (token !== requestToken || controller?.signal.aborted) return
    groups.value = []
    error.value = cause instanceof Error ? cause.message : 'Search unavailable.'
  } finally {
    if (token === requestToken) loading.value = false
  }
}

watch(query, () => {
  cancel()
  if (query.value.trim().length < 2) {
    groups.value = []
    submitted.value = false
    return
  }
  timer = setTimeout(() => void search(), 300)
})

function submitNow() {
  void search()
}

function clear() {
  cancel()
  query.value = ''
  groups.value = []
  submitted.value = false
  error.value = ''
}

onUnmounted(cancel)
</script>

<style scoped>
.global-search { position: relative; display: flex; gap: .5rem; flex-wrap: wrap; }
.global-search input { flex: 1 1 18rem; }
.global-search button {
  padding: .45rem .75rem;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  background: var(--bg-surface);
  color: var(--text-primary);
  font: 600 .8rem var(--font-sans);
  cursor: pointer;
}
.global-search button:hover { background: var(--bg-surface-hover); border-color: var(--border-hover); }
.global-search button:focus-visible { outline: 2px solid var(--accent-primary); outline-offset: 2px; }
.search-results { flex-basis: 100%; display: grid; gap: .75rem; padding: .75rem; background: var(--bg-surface); border-radius: 8px; }
.search-results section { display: flex; gap: .4rem; align-items: center; flex-wrap: wrap; }
.search-results h3 { width: 7rem; margin: 0; font-size: .9rem; }
</style>
