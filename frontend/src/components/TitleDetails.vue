<template>
  <article class="title-details">
    <button class="back-to-library" type="button" @click="$emit('back')">← Back</button>
    <div v-if="loading" role="status">Loading title…</div>
    <div v-else-if="error" role="alert">{{ error }}</div>
    <template v-else-if="details">
      <header
        class="detail-hero"
        :style="details.BackdropImageTags?.length ? { backgroundImage: `url(${backdropUrl})` } : {}"
      >
        <img
          v-if="details.ImageTags?.Primary"
          class="detail-poster"
          :src="api.imageUrl(details.Id, 'Primary', { maxWidth: 480, maxHeight: 720, quality: 90 })"
          :alt="`${details.Name} poster`"
        />
        <div>
          <h2>{{ details.Name }}</h2>
          <p v-if="tagline" class="tagline">{{ tagline }}</p>
          <p class="facts">
            <span v-if="details.ProductionYear">{{ details.ProductionYear }}</span>
            <span v-if="runtime">{{ runtime }}</span>
            <span v-if="details.OfficialRating">{{ details.OfficialRating }}</span>
            <span v-if="details.CommunityRating">★ {{ details.CommunityRating }}</span>
            <span v-if="details.CriticRating">Critics {{ details.CriticRating }}%</span>
          </p>
          <p v-if="details.Genres?.length">{{ details.Genres.join(' · ') }}</p>
          <div class="primary-actions">
            <button
              v-if="playable"
              class="play-title"
              type="button"
              @click="$emit('play', details)"
            >
              Play
            </button>
            <button v-if="browsable" type="button" @click="$emit('browse', details)">
              Browse {{ details.Type === 'Series' ? 'seasons' : 'titles' }}
            </button>
          </div>
          <div v-if="isHost" aria-label="Personal actions" class="personal-actions">
            <button type="button" @click="$emit('favorite', details)">
              {{ details.UserData?.IsFavorite ? 'Remove favorite' : 'Favorite' }}
            </button>
            <button type="button" @click="$emit('played', details)">
              Mark {{ details.UserData?.Played ? 'unplayed' : 'played' }}
            </button>
            <button type="button" @click="$emit('playlist', details)">Add to playlist</button>
          </div>
        </div>
      </header>

      <section v-if="details.Overview"><h3>Overview</h3><p>{{ details.Overview }}</p></section>
      <section v-if="details.People?.length">
        <h3>Cast & crew</h3>
        <p>{{ details.People.map((person) => person.Name).filter(Boolean).join(' · ') }}</p>
      </section>
      <section v-if="details.Studios?.length"><h3>Studios</h3><p>{{ details.Studios.map((studio) => studio.Name).join(' · ') }}</p></section>
      <section v-if="details.Tags?.length"><h3>Tags</h3><p>{{ details.Tags.join(' · ') }}</p></section>
    </template>
  </article>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { api, type LibraryItem } from '@/api/client'

const props = defineProps<{ item: LibraryItem; isHost: boolean }>()
defineEmits<{
  back: []
  play: [item: LibraryItem]
  browse: [item: LibraryItem]
  favorite: [item: LibraryItem]
  played: [item: LibraryItem]
  playlist: [item: LibraryItem]
}>()

const details = ref<LibraryItem | null>(null)
const loading = ref(false)
const error = ref('')
let controller: AbortController | null = null

const playable = computed(() => ['Movie', 'Episode', 'Video'].includes(details.value?.Type || ''))
const browsable = computed(() => ['Series', 'Season', 'BoxSet'].includes(details.value?.Type || ''))
const tagline = computed(() => details.value?.Tagline || details.value?.Taglines?.[0] || '')
const runtime = computed(() => {
  const ticks = details.value?.RunTimeTicks
  if (!ticks) return ''
  const minutes = Math.round(ticks / 600_000_000)
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`
})
const backdropUrl = computed(() => details.value
  ? api.imageUrl(details.value.Id, 'Backdrop', { maxWidth: 1600, maxHeight: 900, quality: 85 })
  : '')

async function load() {
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  error.value = ''
  try {
    details.value = await api.itemDetails(props.item.Id, controller.signal)
  } catch (cause) {
    if (controller.signal.aborted) return
    error.value = cause instanceof Error ? cause.message : 'Title details unavailable.'
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}

watch(() => props.item.Id, () => void load(), { immediate: true })
onUnmounted(() => controller?.abort())
</script>

<style scoped>
.title-details { display: grid; gap: 1rem; }
.back-to-library { justify-self: start; }
.detail-hero { display: grid; grid-template-columns: minmax(9rem, 15rem) 1fr; gap: 1.5rem; padding: 1.5rem; border-radius: 12px; background-size: cover; background-position: center; background-color: var(--bg-surface); background-blend-mode: multiply; }
.detail-poster { width: 100%; border-radius: 8px; }
.facts, .primary-actions, .personal-actions { display: flex; gap: .65rem; flex-wrap: wrap; }
.tagline { font-style: italic; }
@media (max-width: 640px) { .detail-hero { grid-template-columns: 1fr; } .detail-poster { max-width: 14rem; } }
</style>
