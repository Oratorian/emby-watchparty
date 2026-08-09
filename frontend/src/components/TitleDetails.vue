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
              @click="openPlaybackOptions"
            >
              Play
            </button>
            <button v-if="browsable" type="button" @click="$emit('browse', details)">
              Browse {{ details.Type === 'Series' ? 'seasons' : 'titles' }}
            </button>
          </div>
          <div v-if="isHost" aria-label="Personal actions" class="personal-actions">
            <button
              class="favorite-action"
              type="button"
              :disabled="busyActions.has('favorite')"
              @click="toggleFavorite"
            >
              {{ details.UserData?.IsFavorite ? 'Remove favorite' : 'Favorite' }}
            </button>
            <button
              class="played-action"
              type="button"
              :disabled="busyActions.has('played')"
              @click="togglePlayed"
            >
              Mark {{ details.UserData?.Played ? 'unplayed' : 'played' }}
            </button>
            <button type="button" :disabled="busyActions.has('playlists')" @click="openPlaylists">
              Add to playlist
            </button>
          </div>
          <p v-if="mutationError" class="inline-error" role="alert">{{ mutationError }}</p>
          <div v-if="showPlaylists" class="playlist-picker">
            <label>
              Playlist
              <select v-model="selectedPlaylist" aria-label="Playlist">
                <option value="">Choose…</option>
                <option v-for="playlist in playlists" :key="playlist.Id" :value="playlist.Id">
                  {{ playlist.Name }}
                </option>
              </select>
            </label>
            <button type="button" :disabled="!selectedPlaylist || busyActions.has('playlist-add')" @click="addToPlaylist">
              Add
            </button>
            <label>
              New playlist
              <input v-model="newPlaylistName" aria-label="New playlist name" />
            </label>
            <button type="button" :disabled="!newPlaylistName.trim() || busyActions.has('playlist-create')" @click="createAndAddPlaylist">
              Create and add
            </button>
          </div>
          <div v-if="showPlaybackOptions" class="playback-options" aria-label="Playback options">
            <p v-if="playbackLoading" role="status">Loading playback options…</p>
            <p v-else-if="playbackError" role="alert">{{ playbackError }}</p>
            <template v-else>
              <label v-if="streams.versions.length > 1">
                Version
                <select v-model="selectedMediaSource" aria-label="Version" @change="reloadVersionStreams">
                  <option v-for="version in streams.versions" :key="version.id" :value="version.id">
                    {{ version.name }}
                  </option>
                </select>
              </label>
              <label>
                Quality
                <select v-model="selectedQuality" aria-label="Quality">
                  <option v-for="option in qualities" :key="option.id" :value="option.id">{{ option.label }}</option>
                </select>
              </label>
              <label v-if="streams.audio.length">
                Audio
                <select v-model.number="selectedAudio" aria-label="Audio">
                  <option v-for="track in streams.audio" :key="track.index" :value="track.index">{{ track.title }}</option>
                </select>
              </label>
              <label>
                Subtitles
                <select v-model.number="selectedSubtitle" aria-label="Subtitles">
                  <option :value="-1">Off</option>
                  <option v-for="track in streams.subtitles" :key="track.index" :value="track.index">{{ track.title }}</option>
                </select>
              </label>
              <label v-if="resumeSeconds > 0">
                Start
                <select v-model="resumeMode" aria-label="Start position">
                  <option value="resume">Resume at {{ formatTime(resumeSeconds) }}</option>
                  <option value="start_over">Start over</option>
                </select>
              </label>
              <label v-if="isHost && details.Type === 'Episode'">
                <input v-model="binge" type="checkbox" /> Binge next episodes
              </label>
              <button class="start-playback" type="button" @click="startPlayback">Start watch party</button>
            </template>
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
      <section class="optional-sections">
        <h3>More</h3>
        <button
          v-for="section in optionalSections"
          :key="section.id"
          type="button"
          :data-section="section.id"
          @click="loadSection(section.id)"
        >
          {{ section.label }}
        </button>
        <div v-for="section in optionalSections" :key="`${section.id}-content`">
          <p v-if="sectionErrors[section.id]" role="alert">{{ sectionErrors[section.id] }}</p>
          <p v-else-if="sectionLoading === section.id" role="status">Loading {{ section.label.toLowerCase() }}…</p>
          <ul v-else-if="sectionItems[section.id]">
            <li v-for="item in sectionItems[section.id]" :key="item.Id">{{ item.Name }}</li>
            <li v-if="!sectionItems[section.id]?.length">None available.</li>
          </ul>
        </div>
      </section>
    </template>
  </article>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import {
  api,
  type ItemSection,
  type LibraryItem,
  type PlaybackSelection,
  type QualityOptionsResponse,
  type StreamsResponse,
} from '@/api/client'

const props = defineProps<{ item: LibraryItem; isHost: boolean }>()
const emit = defineEmits<{
  back: []
  play: [selection: PlaybackSelection]
  browse: [item: LibraryItem]
}>()

const details = ref<LibraryItem | null>(null)
const loading = ref(false)
const error = ref('')
let controller: AbortController | null = null
let sectionController: AbortController | null = null
const optionalSections: Array<{ id: ItemSection; label: string }> = [
  { id: 'related', label: 'Related titles' },
  { id: 'extras', label: 'Extras' },
  { id: 'trailers', label: 'Trailers' },
]
const sectionItems = ref<Partial<Record<ItemSection, LibraryItem[]>>>({})
const sectionErrors = ref<Partial<Record<ItemSection, string>>>({})
const sectionLoading = ref<ItemSection | null>(null)
const busyActions = ref(new Set<string>())
const mutationError = ref('')
const showPlaylists = ref(false)
const playlists = ref<LibraryItem[]>([])
const selectedPlaylist = ref('')
const newPlaylistName = ref('')
const showPlaybackOptions = ref(false)
const playbackLoading = ref(false)
const playbackError = ref('')
const streams = ref<StreamsResponse>({ audio: [], subtitles: [], media_source_id: null, versions: [] })
const qualities = ref<QualityOptionsResponse['options']>([])
const selectedMediaSource = ref('')
const selectedQuality = ref('auto')
const selectedAudio = ref<number | null>(null)
const selectedSubtitle = ref<number | null>(-1)
const resumeMode = ref<'resume' | 'start_over'>('start_over')
const binge = ref(false)
const resumeSeconds = computed(() => Number(details.value?.UserData?.PlaybackPositionTicks ?? 0) / 10_000_000)

function setBusy(action: string, busy: boolean) {
  const next = new Set(busyActions.value)
  if (busy) next.add(action)
  else next.delete(action)
  busyActions.value = next
}

async function toggleFavorite() {
  if (!details.value || busyActions.value.has('favorite')) return
  const previous = !!details.value.UserData?.IsFavorite
  details.value.UserData ??= {}
  details.value.UserData.IsFavorite = !previous
  mutationError.value = ''
  setBusy('favorite', true)
  try {
    await api.setFavorite(details.value.Id, !previous)
  } catch (cause) {
    details.value.UserData.IsFavorite = previous
    mutationError.value = cause instanceof Error ? cause.message : 'Favorite update failed.'
  } finally {
    setBusy('favorite', false)
  }
}

async function togglePlayed() {
  if (!details.value || busyActions.value.has('played')) return
  const previous = !!details.value.UserData?.Played
  details.value.UserData ??= {}
  details.value.UserData.Played = !previous
  mutationError.value = ''
  setBusy('played', true)
  try {
    await api.setPlayed(details.value.Id, !previous)
  } catch (cause) {
    details.value.UserData.Played = previous
    mutationError.value = cause instanceof Error ? cause.message : 'Played update failed.'
  } finally {
    setBusy('played', false)
  }
}

async function openPlaylists() {
  if (busyActions.value.has('playlists')) return
  showPlaylists.value = true
  mutationError.value = ''
  setBusy('playlists', true)
  try {
    playlists.value = (await api.playlists()).items
  } catch (cause) {
    mutationError.value = cause instanceof Error ? cause.message : 'Playlists unavailable.'
  } finally {
    setBusy('playlists', false)
  }
}

async function addToPlaylist() {
  if (!details.value || !selectedPlaylist.value || busyActions.value.has('playlist-add')) return
  mutationError.value = ''
  setBusy('playlist-add', true)
  try {
    await api.addPlaylistItem(selectedPlaylist.value, details.value.Id)
    showPlaylists.value = false
  } catch (cause) {
    mutationError.value = cause instanceof Error ? cause.message : 'Playlist add failed.'
  } finally {
    setBusy('playlist-add', false)
  }
}

async function createAndAddPlaylist() {
  if (!details.value || !newPlaylistName.value.trim() || busyActions.value.has('playlist-create')) return
  mutationError.value = ''
  setBusy('playlist-create', true)
  try {
    const created = await api.createPlaylist(newPlaylistName.value.trim())
    await api.addPlaylistItem(created.id, details.value.Id)
    showPlaylists.value = false
    newPlaylistName.value = ''
  } catch (cause) {
    mutationError.value = cause instanceof Error ? cause.message : 'Playlist creation failed.'
  } finally {
    setBusy('playlist-create', false)
  }
}

function applyStreams(response: StreamsResponse) {
  streams.value = response
  selectedMediaSource.value = response.media_source_id || response.versions[0]?.id || ''
  selectedAudio.value = response.audio.find((track) => track.isDefault)?.index
    ?? response.audio[0]?.index
    ?? null
  selectedSubtitle.value = response.subtitles.find((track) => track.isDefault)?.index ?? -1
}

async function openPlaybackOptions() {
  if (!details.value || playbackLoading.value) return
  showPlaybackOptions.value = true
  playbackLoading.value = true
  playbackError.value = ''
  try {
    const [streamResponse, qualityResponse] = await Promise.all([
      api.itemStreams(details.value.Id),
      api.qualityOptions(),
    ])
    applyStreams(streamResponse)
    qualities.value = qualityResponse.options
    selectedQuality.value = qualityResponse.default_id
    resumeMode.value = resumeSeconds.value > 0 ? 'resume' : 'start_over'
  } catch (cause) {
    playbackError.value = cause instanceof Error ? cause.message : 'Playback options unavailable.'
  } finally {
    playbackLoading.value = false
  }
}

async function reloadVersionStreams() {
  if (!details.value || !selectedMediaSource.value) return
  playbackLoading.value = true
  try {
    applyStreams(await api.itemStreams(details.value.Id, selectedMediaSource.value))
  } catch (cause) {
    playbackError.value = cause instanceof Error ? cause.message : 'Version unavailable.'
  } finally {
    playbackLoading.value = false
  }
}

function formatTime(seconds: number): string {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remaining = Math.floor(seconds % 60)
  return [hours, minutes, remaining].map((value) => String(value).padStart(2, '0')).join(':')
}

function startPlayback() {
  if (!details.value) return
  emit('play', {
    item: details.value,
    mediaSourceId: selectedMediaSource.value || undefined,
    quality: selectedQuality.value,
    audioIndex: selectedAudio.value,
    subtitleIndex: selectedSubtitle.value,
    startSeconds: resumeMode.value === 'resume' ? resumeSeconds.value : 0,
    resumeMode: resumeMode.value,
    binge: props.isHost && details.value.Type === 'Episode' ? binge.value : undefined,
  })
}

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

async function loadSection(section: ItemSection) {
  if (sectionItems.value[section] || sectionLoading.value === section) return
  sectionController?.abort()
  sectionController = new AbortController()
  sectionLoading.value = section
  delete sectionErrors.value[section]
  try {
    const response = await api.itemSection(props.item.Id, section, sectionController.signal)
    sectionItems.value[section] = response.items
  } catch (cause) {
    if (sectionController.signal.aborted) return
    sectionErrors.value[section] = cause instanceof Error ? cause.message : `${section} unavailable.`
  } finally {
    if (!sectionController.signal.aborted) sectionLoading.value = null
  }
}

watch(() => props.item.Id, () => void load(), { immediate: true })
onUnmounted(() => {
  controller?.abort()
  sectionController?.abort()
})
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
