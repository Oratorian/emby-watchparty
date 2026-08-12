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
                  <option v-for="track in streams.audio" :key="track.index" :value="track.index">{{ streamLabel(track) }}</option>
                </select>
              </label>
              <label>
                Subtitles
                <select v-model.number="selectedSubtitle" aria-label="Subtitles">
                  <option :value="-1">Off</option>
                  <option v-for="track in streams.subtitles" :key="track.index" :value="track.index">{{ streamLabel(track) }}</option>
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
      <section v-if="tagNames.length"><h3>Tags</h3><p>{{ tagNames.join(' · ') }}</p></section>
      <!-- One toolbar row, and one popover showing one section at a time.
           Each button used to render its own block underneath, so opening all
           three left all three stacked forever with nothing to close them.
           One toolbar row. These were two stacked sections with their own
           headings, and between the headings, the button row, the two selects
           and the episode count they cost four vertical bands for what is one
           set of controls. -->
      <section
        class="detail-toolbar"
        @mouseleave="scheduleSectionClose"
        @mouseenter="cancelSectionClose"
        @keydown.esc="closeSection"
      >
        <div class="toolbar-group section-buttons">
          <button
            v-for="section in optionalSections"
            :key="section.id"
            type="button"
            :data-section="section.id"
            class="section-btn"
            :class="{ active: openSection === section.id }"
            :aria-expanded="openSection === section.id"
            :aria-controls="`section-panel-${section.id}`"
            @click="toggleSection(section.id)"
          >
            {{ section.label }}
          </button>

          <div
            v-if="openSection"
            :id="`section-panel-${openSection}`"
            class="section-popover"
            role="dialog"
            :aria-label="openSectionLabel"
          >
            <header class="section-popover-head">
              <h4>{{ openSectionLabel }}</h4>
              <button
                type="button"
                class="section-close"
                aria-label="Close"
                @click="closeSection"
              >
                ×
              </button>
            </header>
            <p v-if="sectionErrors[openSection]" role="alert">{{ sectionErrors[openSection] }}</p>
            <p v-else-if="sectionLoading === openSection" role="status">
              Loading {{ openSectionLabel.toLowerCase() }}…
            </p>
            <ul v-else-if="sectionItems[openSection]?.length" class="section-grid">
              <li v-for="item in sectionItems[openSection]" :key="item.Id">
                <button type="button" class="section-item" @click="$emit('open', item)">
                  <span class="section-thumb">
                    <img
                      v-if="item.ImageTags?.Primary"
                      :src="api.imageUrl(item.Id, 'Primary', { maxWidth: 120, maxHeight: 180, quality: 80 })"
                      :alt="''"
                      loading="lazy"
                    />
                    <span v-else class="section-thumb-fallback">{{ item.Name.charAt(0) }}</span>
                  </span>
                  <span class="section-text">
                    <span class="section-name">{{ item.Name }}</span>
                    <span v-if="itemMeta(item)" class="section-meta">{{ itemMeta(item) }}</span>
                  </span>
                </button>
              </li>
            </ul>
            <p v-else class="section-empty">None available.</p>
          </div>
        </div>

        <!-- Same row, divider between. Seasons load with the title, so this
             appears without anyone pressing anything; the button survives only
             as the way back from a failure. The error sits outside the loaded
             branch because a seasons failure leaves seasonsLoaded false, which
             is exactly when it needs to be visible. -->
        <div v-if="details.Type === 'Series'" class="toolbar-group series-group">
          <p v-if="seriesError" class="toolbar-error" role="alert">{{ seriesError }}</p>
          <p v-if="seasonsLoading && !seasonsLoaded" role="status">Loading seasons…</p>
          <button
            v-else-if="!seasonsLoaded"
            type="button"
            data-section="seasons"
            @click="loadSeasons()"
          >
            {{ seriesError ? 'Retry' : 'Load seasons' }}
          </button>
          <div v-else class="series-pickers">
          <label>
            Season
            <select
              v-model="selectedSeason"
              aria-label="Season"
              @change="selectSeason(selectedSeason)"
            >
              <option v-for="season in seasons" :key="season.Id" :value="season.Id">
                {{ season.Name }}
              </option>
            </select>
          </label>

          <label>
            Episode
            <select
              v-model="chosenEpisode"
              aria-label="Episode"
              :disabled="episodesLoading || !episodes.length"
              @change="openChosenEpisode"
            >
              <option value="">
                {{ episodesLoading ? 'Loading…' : episodes.length ? 'Choose an episode…' : 'No episodes' }}
              </option>
              <option
                v-for="episode in episodes"
                :key="episode.Id"
                :value="episode.Id"
                :data-episode-id="episode.Id"
              >
                {{ episodeLabel(episode) }}
              </option>
            </select>
          </label>

            <p v-if="episodes.length" class="series-count">
              {{ episodes.length }} Episode{{ episodes.length === 1 ? '' : 's' }}
            </p>
          </div>
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

const props = defineProps<{ item: LibraryItem; isHost: boolean; selectedSeasonId?: string | null }>()
const emit = defineEmits<{
  back: []
  play: [selection: PlaybackSelection]
  browse: [item: LibraryItem]
  open: [item: LibraryItem]
}>()

const details = ref<LibraryItem | null>(null)
const loading = ref(false)
const error = ref('')
let controller: AbortController | null = null
const sectionControllers = new Map<ItemSection, AbortController>()

function streamLabel(track: { title: string; displayLanguage: string; language: string }): string {
  const base = track.displayLanguage || track.language || 'Unknown'
  return track.title && track.title !== base ? `${base} (${track.title})` : track.title || base
}
const optionalSections: Array<{ id: ItemSection; label: string }> = [
  { id: 'related', label: 'Related titles' },
  { id: 'extras', label: 'Extras' },
  { id: 'trailers', label: 'Trailers' },
]
const sectionItems = ref<Partial<Record<ItemSection, LibraryItem[]>>>({})
const sectionErrors = ref<Partial<Record<ItemSection, string>>>({})
const sectionLoading = ref<ItemSection | null>(null)

// Which optional section is showing. Exactly one, or none.
const openSection = ref<ItemSection | null>(null)
const openSectionLabel = computed(
  () => optionalSections.find((section) => section.id === openSection.value)?.label ?? '',
)
let sectionCloseTimer: ReturnType<typeof setTimeout> | null = null

function cancelSectionClose() {
  if (sectionCloseTimer) clearTimeout(sectionCloseTimer)
  sectionCloseTimer = null
}

function closeSection() {
  cancelSectionClose()
  openSection.value = null
}

/**
 * Close shortly after the pointer leaves, not instantly.
 *
 * The grace period matters because the popover sits below its button: moving
 * diagonally towards it briefly exits the group, and closing on that would
 * make the thing impossible to actually use.
 */
function scheduleSectionClose() {
  cancelSectionClose()
  sectionCloseTimer = setTimeout(closeSection, 400)
}

/** Year, runtime and type, whichever the row actually carries. */
function itemMeta(item: LibraryItem): string {
  const parts: string[] = []
  if (item.ProductionYear) parts.push(String(item.ProductionYear))
  const ticks = item.RunTimeTicks
  if (ticks) {
    const minutes = Math.round(ticks / 600_000_000)
    parts.push(minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`)
  }
  // Only when it adds something: a Related list is mostly Movies, and
  // repeating "Movie" on every row is noise.
  if (item.Type && item.Type !== 'Movie') parts.push(item.Type)
  return parts.join(' · ')
}

function toggleSection(section: ItemSection) {
  cancelSectionClose()
  if (openSection.value === section) {
    closeSection()
    return
  }
  openSection.value = section
  // Cached after the first fetch, so reopening is instant.
  void loadSection(section)
}
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
const seasons = ref<LibraryItem[]>([])
const episodes = ref<LibraryItem[]>([])
const seasonsLoaded = ref(false)
const seasonsLoading = ref(false)
const selectedSeason = ref('')
const seriesError = ref('')
// Bound to the episode select. Held separately from `episodes` so the control
// resets to its placeholder after opening one, rather than showing a stale
// selection for a title the user has already navigated away from.
const chosenEpisode = ref('')
const episodesLoading = ref(false)

/** "3. The Threat", falling back to the name when Emby gives no number. */
function episodeLabel(episode: LibraryItem): string {
  const number = episode.IndexNumber
  return number === undefined || number === null
    ? episode.Name
    : `${number}. ${episode.Name}`
}

function openChosenEpisode() {
  const episode = episodes.value.find((candidate) => candidate.Id === chosenEpisode.value)
  chosenEpisode.value = ''
  if (episode) emit('open', episode)
}

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
const tagNames = computed(() => (details.value?.TagItems ?? [])
  .map((tag) => tag.Name)
  .filter((name): name is string => Boolean(name)))

function resetForNewItem() {
  // Every piece of per-item state, not just `details`.
  //
  // This component is reused across item navigation rather than re-created,
  // so anything left behind belongs to the previous title. loadSection
  // early-returns when a section is already populated, which meant an episode
  // opened from a series rendered the SERIES' Related, Extras and Trailers and
  // could never refetch its own. The season list and episode list persisted
  // the same way.
  sectionControllers.forEach((sectionController) => sectionController.abort())
  sectionControllers.clear()
  sectionItems.value = {}
  sectionErrors.value = {}
  sectionLoading.value = null
  closeSection()
  seasons.value = []
  seasonsLoaded.value = false
  seasonsLoading.value = false
  episodes.value = []
  selectedSeason.value = ''
  chosenEpisode.value = ''
  episodesLoading.value = false
  seriesError.value = ''
}

async function load() {
  controller?.abort()
  controller = new AbortController()
  resetForNewItem()
  loading.value = true
  error.value = ''
  try {
    details.value = await api.itemDetails(props.item.Id, controller.signal)
    if (details.value.Type === 'Series') {
      await loadSeasons(props.selectedSeasonId ?? undefined)
    }
  } catch (cause) {
    if (controller.signal.aborted) return
    error.value = cause instanceof Error ? cause.message : 'Title details unavailable.'
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}

async function loadSeasons(initialSeason?: string) {
  if (!details.value) return
  seriesError.value = ''
  seasonsLoading.value = true
  try {
    seasons.value = (await api.seriesSeasons(details.value.Id)).items
    seasonsLoaded.value = true
    const seasonId = initialSeason || selectedSeason.value || seasons.value[0]?.Id
    if (seasonId) await selectSeason(seasonId)
  } catch (cause) {
    seriesError.value = cause instanceof Error ? cause.message : 'Seasons unavailable.'
  } finally {
    seasonsLoading.value = false
  }
}

async function selectSeason(seasonId: string) {
  if (!details.value) return
  selectedSeason.value = seasonId
  seriesError.value = ''
  // Cleared before the fetch, not after: leaving the previous season's list in
  // place would let someone pick an episode that belongs to the season they
  // just navigated away from.
  episodes.value = []
  chosenEpisode.value = ''
  episodesLoading.value = true
  try {
    episodes.value = (await api.seriesEpisodes(details.value.Id, seasonId)).items
  } catch (cause) {
    episodes.value = []
    seriesError.value = cause instanceof Error ? cause.message : 'Episodes unavailable.'
  } finally {
    episodesLoading.value = false
  }
}

async function loadSection(section: ItemSection) {
  if (sectionItems.value[section] || sectionControllers.has(section)) return
  const sectionController = new AbortController()
  sectionControllers.set(section, sectionController)
  sectionLoading.value = section
  delete sectionErrors.value[section]
  try {
    const response = await api.itemSection(props.item.Id, section, sectionController.signal)
    sectionItems.value[section] = response.items
  } catch (cause) {
    if (sectionController.signal.aborted) return
    sectionErrors.value[section] = cause instanceof Error ? cause.message : `${section} unavailable.`
  } finally {
    sectionControllers.delete(section)
    if (sectionLoading.value === section) sectionLoading.value = null
  }
}

watch(() => props.item.Id, () => void load(), { immediate: true })
onUnmounted(() => {
  cancelSectionClose()
  controller?.abort()
  sectionControllers.forEach((sectionController) => sectionController.abort())
  sectionControllers.clear()
})
</script>

<style scoped>
.title-details { display: grid; gap: 1rem; }
.title-details button {
  padding: .5rem .8rem;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  background: var(--bg-surface);
  color: var(--text-primary);
  font: 600 .8rem var(--font-sans);
  cursor: pointer;
}
.title-details button:hover:not(:disabled) { background: var(--bg-surface-hover); border-color: var(--border-hover); }
.title-details button:focus-visible { outline: 2px solid var(--accent-primary); outline-offset: 2px; }
.title-details button:disabled { cursor: wait; opacity: .6; }
.back-to-library { justify-self: start; }
.detail-hero { display: grid; grid-template-columns: minmax(9rem, 15rem) 1fr; gap: 1.5rem; padding: 1.5rem; border-radius: 12px; background-size: cover; background-position: center; background-color: var(--bg-surface); background-blend-mode: multiply; }
.detail-poster { width: 100%; border-radius: 8px; }
.facts, .primary-actions, .personal-actions { display: flex; gap: .65rem; flex-wrap: wrap; }
.play-title, .start-playback { background: var(--accent-primary) !important; border-color: transparent !important; color: var(--bg-deep) !important; }
.playlist-picker, .playback-options { display: flex; align-items: end; gap: .65rem; flex-wrap: wrap; margin-top: .85rem; }
.playlist-picker label, .playback-options label { display: grid; gap: .25rem; color: var(--text-secondary); font-size: .8rem; }
/* One row for both control groups. Two stacked sections with their own
   headings cost four vertical bands for a single set of controls, on a page
   whose whole complaint was that it kept extending downwards. */
.detail-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .75rem 1.25rem;
  padding: .5rem 0;
}

.toolbar-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .4rem .6rem;
}

/* A divider rather than a heading: it separates the groups without adding a
   line of its own. Dropped once the row wraps, where it would sit sideways. */
.series-group {
  border-left: 1px solid var(--border-subtle);
  padding-left: 1.25rem;
}

/* Anchor for the absolutely-positioned popover, so it floats relative to the
   button row rather than the page. */
.section-buttons { position: relative; }

.toolbar-error { margin: 0; color: var(--color-danger, #ff6b6b); font-size: .85rem; }

.section-btn { margin: 0; }
.section-btn.active {
  border-color: var(--color-accent-cyan, #00e0ff);
  box-shadow: 0 0 0 2px rgba(0, 224, 255, .2);
}

.section-popover {
  position: absolute;
  /* Upwards. This section sits low in the detail view, so a downward panel
     opened into the page fold and pushed everything after it out of sight. */
  bottom: calc(100% + 10px);
  left: 0;
  z-index: 50;
  /* One wide panel rather than a narrow strip: these are poster rows, and at
     15rem they wrapped into an unreadable column. Bounded and internally
     scrolled so it still cannot grow the page. */
  width: min(46rem, calc(100vw - 3rem));
  max-height: min(24rem, 60vh);
  overflow-y: auto;
  background: var(--bg-secondary, #181820);
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  padding: .75rem .9rem .9rem;
  box-shadow: 0 18px 42px rgba(0, 0, 0, .6),
              0 0 0 1px rgba(0, 224, 255, .1) inset;
}

.section-popover-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  /* Sticky so the title and the close control stay reachable while the list
     scrolls, which matters once a Related list runs past the panel height. */
  position: sticky;
  top: 0;
  margin: -.75rem -.9rem .6rem;
  padding: .6rem .9rem .5rem;
  background: var(--bg-secondary, #181820);
  border-bottom: 1px solid var(--border-subtle);
}
.section-popover-head h4 {
  margin: 0;
  font-size: .95rem;
  letter-spacing: .02em;
}
.section-close {
  background: none;
  border: none;
  color: var(--text-secondary, #9aa0aa);
  font-size: 1.25rem;
  line-height: 1;
  padding: 0 .25rem;
  cursor: pointer;
}
.section-close:hover, .section-close:focus-visible { color: var(--text-primary); }

.section-popover ul { list-style: none; margin: 0; padding: 0; }

.section-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
  gap: .35rem .5rem;
}

.section-item {
  display: flex;
  align-items: center;
  gap: .6rem;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  color: var(--text-primary);
  padding: .35rem .4rem;
  border-radius: 8px;
  cursor: pointer;
  font: inherit;
}
.section-item:hover,
.section-item:focus-visible { background: var(--bg-surface, rgba(255, 255, 255, .06)); }

.section-thumb {
  flex: 0 0 auto;
  width: 2.25rem;
  height: 3.25rem;
  border-radius: 4px;
  overflow: hidden;
  background: var(--bg-surface, rgba(255, 255, 255, .06));
  display: grid;
  place-items: center;
}
.section-thumb img { width: 100%; height: 100%; object-fit: cover; }
.section-thumb-fallback { color: var(--text-secondary, #9aa0aa); font-size: .9rem; }

.section-text { display: flex; flex-direction: column; gap: .1rem; min-width: 0; }
.section-name {
  /* Long titles truncate rather than reflowing the whole grid row. */
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.section-meta { font-size: .78rem; color: var(--text-secondary, #9aa0aa); }

.section-empty { margin: 0; color: var(--text-secondary, #9aa0aa); }

.series-pickers {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .4rem .75rem;
}
/* Label beside the control, not above it: stacking them added a second line
   to a row that exists to be one line. */
.series-pickers label { display: flex; align-items: center; gap: .4rem; }
.series-pickers select { min-width: 9rem; max-width: 18rem; }
.series-count { margin: 0; color: var(--text-secondary, #9aa0aa); font-size: .82rem; }

@media (max-width: 720px) {
  .series-group { border-left: none; padding-left: 0; }
}

@media (max-width: 640px) {
  .section-popover { width: calc(100vw - 2rem); }
  .section-grid { grid-template-columns: 1fr; }
}
.tagline { font-style: italic; }
@media (max-width: 640px) { .detail-hero { grid-template-columns: 1fr; } .detail-poster { max-width: 14rem; } }
</style>
