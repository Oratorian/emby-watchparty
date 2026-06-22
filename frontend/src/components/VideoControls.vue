<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '@/api/client'
import { withPrefix } from '@/utils/appPrefix'

interface AudioStream {
  index: number
  language: string
  displayLanguage: string
  codec: string
  channels: number
  isDefault: boolean
  title: string
}

interface SubtitleStream {
  index: number
  language: string
  displayLanguage: string
  codec: string
  isDefault: boolean
  isForced: boolean
  isExternal: boolean
  isPGS: boolean
  title: string
}

interface StreamsResponse {
  audio: AudioStream[]
  subtitles: SubtitleStream[]
  media_source_id: string | null
  // `versions` is still in the response shape (issue #43) but the
  // version picker now lives in the library, not in this controls
  // strip -- the host locks the version at select_video time. We
  // ignore the field here intentionally.
}

interface IntroData {
  start: number
  end: number
}

const props = defineProps<{
  partyId: string
  itemId: string
  streamUrl: string
  quality: string
  currentTime: number
  mediaSourceId?: string
  // Binge-watching surface: shown only when the admin's master switch
  // is on (bingeAvailable), the current item is an Episode, and the
  // viewer is the host (PartyView gates this -- this component does
  // not check it again). bingeActive reflects the host's per-party
  // opt-in. When the modal fires the host (or any user) cancels via
  // a separate path; this button only toggles the master per-party
  // active flag.
  bingeAvailable?: boolean
  bingeActive?: boolean
  bingeVisible?: boolean
}>()

const emit = defineEmits<{
  'change-streams': [payload: { audioIndex: number; subtitleIndex: number; quality: string }]
  'change-text-subtitle': [payload: { index: number; url: string | null }]
  'skip-intro': [endTime: number]
  // Relative jump in seconds. Sign indicates direction (-30, -10, +10,
  // +30). PartyView computes the target media time and routes through
  // the party seek path so everyone moves together.
  'jump': [seconds: number]
  'toggle-binge': []
}>()

const audioTracks = ref<AudioStream[]>([])
const subtitleTracks = ref<SubtitleStream[]>([])
const selectedAudio = ref<number>(0)
const selectedSubtitle = ref<number>(-1)
const selectedTextSubtitle = ref<number>(-1)
const selectedQuality = ref(props.quality)
const intro = ref<IntroData | null>(null)
const appliedInitialSubtitleKey = ref<string | null>(null)

// Quality options are fetched from /api/quality-options on mount so the
// dropdown mirrors Emby's per-resolution table and respects the admin's
// ENABLED_QUALITY_OPTIONS / FORCE_TRANSCODE settings. See
// backend/src/quality.py for the source of truth.
interface QualityOption {
  id: string
  label: string
  resolution: string | null
  width: number | null
  height: number | null
  bitrate_kbps: number | null
}
const qualityOptions = ref<QualityOption[]>([])
const qualityDefaultId = ref<string>('auto')

async function loadQualityOptions() {
  try {
    const data = await api.qualityOptions()
    qualityOptions.value = data.options || []
    qualityDefaultId.value = data.default_id || 'auto'
    // If our currently-selected id isn't in the new option set (admin
    // tweaked the enabled list, or FORCE_TRANSCODE flipped Auto off),
    // snap to the server-provided default so the dropdown never opens
    // on a value it can't render.
    const valid = new Set(qualityOptions.value.map((o) => o.id))
    if (!valid.has(selectedQuality.value)) {
      selectedQuality.value = qualityDefaultId.value
    }
  } catch {
    // Leave the dropdown empty on failure; the controls strip still
    // works (audio / subtitle / skip-intro are independent).
  }
}

function formatAudioLabel(track: AudioStream): string {
  const lang = track.displayLanguage || track.language || 'Unknown'
  const codec = (track.codec || '').toUpperCase()
  const ch = track.channels
  let channelLabel = `${ch}ch`
  if (ch === 2) channelLabel = '2.0'
  else if (ch === 6) channelLabel = '5.1'
  else if (ch === 8) channelLabel = '7.1'
  const def = track.isDefault ? ' *' : ''
  return `${lang} - ${codec} ${channelLabel}${def}`
}

function formatSubtitleLabel(track: SubtitleStream): string {
  // Keep this in sync with the <track> label construction in
  // PartyView.vue's auto-load watcher so the dropdown and the browser's
  // native CC button menu show the same text for the same subtitle.
  let label = track.displayLanguage || track.language || 'Unknown'
  if (track.title) label += ` (${track.title})`
  if (track.isForced) label += ' [Forced]'
  if (track.isExternal) label += ' [External]'
  if (track.isPGS) label += ' (burned in)'
  if (track.isDefault) label += ' *'
  return label
}

const showIntroButton = computed(() => {
  if (!intro.value) return false
  return props.currentTime >= intro.value.start && props.currentTime < intro.value.end
})

function selectedBurnedSubtitleIndex(): number {
  const track = subtitleTracks.value.find((t) => t.index === selectedSubtitle.value)
  return track?.isPGS ? track.index : -1
}

function applyInitialSubtitleSelection() {
  // Only auto-apply the default selection for PGS / image subs, which
  // need a backend stream restart with SubtitleMethod=Encode. Text-sub
  // auto-show is handled by PartyView's auto-load watcher, which sets
  // textTrack.mode='showing' on the default <track> as it preloads --
  // routing text subs through this path raced the auto-load and left
  // a stray ad-hoc 'Subtitles' track in the CC menu.
  const idx = selectedSubtitle.value
  const track = subtitleTracks.value.find((t) => t.index === idx)
  if (!track || !track.isPGS) return
  const key = `${props.itemId}:${idx}:burned`
  if (appliedInitialSubtitleKey.value === key) return
  onSubtitleChange()
  appliedInitialSubtitleKey.value = key
}

async function fetchStreams() {
  if (!props.itemId) return
  try {
    // Scope to the current version so audio/subtitle dropdowns reflect
    // the stream that's actually playing. The version itself is locked
    // at select_video time and chosen via the library picker -- this
    // strip never switches versions, it just describes the source the
    // party is on.
    const data: StreamsResponse = await api.itemStreams(
      props.itemId,
      props.mediaSourceId,
    )
    audioTracks.value = data.audio || []
    subtitleTracks.value = data.subtitles || []

    const defaultAudio = audioTracks.value.find((t) => t.isDefault)
    if (defaultAudio) selectedAudio.value = defaultAudio.index

    const defaultSub = subtitleTracks.value.find((t) => t.isDefault)
    selectedSubtitle.value = defaultSub ? defaultSub.index : -1
    appliedInitialSubtitleKey.value = null
    applyInitialSubtitleSelection()
  } catch {
    audioTracks.value = []
    subtitleTracks.value = []
    appliedInitialSubtitleKey.value = null
  }
}

async function fetchIntro() {
  if (!props.itemId) return
  try {
    const data = await api.intro(props.itemId)
    if (data && data.start !== undefined && data.end !== undefined) {
      intro.value = { start: data.start, end: data.end }
    } else {
      intro.value = null
    }
  } catch {
    intro.value = null
  }
}

function onAudioChange() {
  emit('change-streams', {
    audioIndex: selectedAudio.value,
    subtitleIndex: selectedBurnedSubtitleIndex(),
    quality: selectedQuality.value,
  })
}

// Track whether the previously-selected subtitle was a burned (PGS)
// one. If it was, a switch to None or to a text sub needs to rebuild
// the transcode to remove the burn. If it wasn't, we only need the
// client-side text-track flip and must NOT touch the stream URL --
// rebuilding the stream re-attaches HLS, which clears the cached cues
// in the preloaded <track> elements and surfaced as "after None the
// subs don't come back."
let wasBurnedSub = false

function onSubtitleChange() {
  const idx = selectedSubtitle.value
  const track = subtitleTracks.value.find((t) => t.index === idx)

  if (idx === -1 || !track) {
    // None selected. Clear the text sub locally. Only rebuild the
    // stream if the previous selection was a burned (PGS) sub --
    // otherwise we'd needlessly destroy/re-attach HLS.
    emit('change-text-subtitle', { index: -1, url: null })
    if (wasBurnedSub) {
      emit('change-streams', {
        audioIndex: selectedAudio.value,
        subtitleIndex: -1,
        quality: selectedQuality.value,
      })
    }
    wasBurnedSub = false
  } else if (track.isPGS) {
    // Image-based sub -- needs burn-in via stream change.
    emit('change-text-subtitle', { index: -1, url: null })
    emit('change-streams', {
      audioIndex: selectedAudio.value,
      subtitleIndex: idx,
      quality: selectedQuality.value,
    })
    wasBurnedSub = true
  } else {
    // Text-based sub -- load locally per user. Only rebuild the
    // stream if leaving a burned sub (to remove the burn).
    if (!props.mediaSourceId) return
    const url = withPrefix(`/api/subtitles/${props.itemId}/${props.mediaSourceId}/${idx}`)
    emit('change-text-subtitle', { index: idx, url })
    if (wasBurnedSub) {
      emit('change-streams', {
        audioIndex: selectedAudio.value,
        subtitleIndex: -1,
        quality: selectedQuality.value,
      })
    }
    wasBurnedSub = false
  }
}

function onQualityChange() {
  emit('change-streams', {
    audioIndex: selectedAudio.value,
    subtitleIndex: selectedBurnedSubtitleIndex(),
    quality: selectedQuality.value,
  })
}

function onSkipIntro() {
  if (intro.value) {
    emit('skip-intro', intro.value.end)
  }
}

function onJump(seconds: number) {
  emit('jump', seconds)
}

watch(
  () => props.itemId,
  () => {
    intro.value = null
    appliedInitialSubtitleKey.value = null
    fetchStreams()
    fetchIntro()
  },
)

watch(
  () => props.quality,
  (val) => {
    selectedQuality.value = val
  },
)

watch(
  () => props.mediaSourceId,
  (newId, oldId) => {
    // A media_source_id change while the item_id stays put means
    // either (a) a different alternate version was picked, or (b) the
    // host's own PlaySessionId rotated (same source, new transcode).
    // For (a) the audio/subtitle dropdowns need to be re-fetched so
    // they describe the new file. For (b) the lists are identical but
    // an extra fetch is cheap and avoids needing to distinguish the
    // cases. fetchStreams() also refreshes `selectedVersion` so the
    // version dropdown lands on the right entry.
    if (newId && newId !== oldId) {
      fetchStreams()
    }
    applyInitialSubtitleSelection()
  },
)

onMounted(() => {
  loadQualityOptions()
  if (props.itemId) {
    fetchStreams()
    fetchIntro()
  }
})
</script>

<template>
  <div class="video-controls">
    <div class="control-group" v-if="audioTracks.length">
      <label for="audio-select">Audio</label>
      <select id="audio-select" v-model="selectedAudio" @change="onAudioChange">
        <option v-for="track in audioTracks" :key="track.index" :value="track.index">
          {{ formatAudioLabel(track) }}
        </option>
      </select>
    </div>

    <div class="control-group" v-if="subtitleTracks.length">
      <label for="subtitle-select">Subtitles</label>
      <select id="subtitle-select" v-model="selectedSubtitle" @change="onSubtitleChange">
        <option :value="-1">None</option>
        <option v-for="track in subtitleTracks" :key="track.index" :value="track.index">
          {{ formatSubtitleLabel(track) }}
        </option>
      </select>
    </div>

    <div class="control-group" v-if="qualityOptions.length">
      <label for="quality-select">Quality</label>
      <select id="quality-select" v-model="selectedQuality" @change="onQualityChange">
        <option v-for="option in qualityOptions" :key="option.id" :value="option.id">
          {{ option.label }}
        </option>
      </select>
    </div>

    <button
      v-if="bingeVisible && bingeAvailable"
      class="binge-btn"
      :class="{ active: bingeActive }"
      :title="bingeActive ? 'Binge-watch: ON (auto-advance enabled). Click to turn off.' : 'Binge-watch: OFF. Click to auto-play the next episode when this one ends.'"
      @click="emit('toggle-binge')"
    >
      <span class="binge-dot" />
      Binge {{ bingeActive ? 'ON' : 'OFF' }}
    </button>

    <div class="jump-group">
      <button class="jump-btn" @click="onJump(-30)" title="Back 30 seconds">−30s</button>
      <button class="jump-btn" @click="onJump(-10)" title="Back 10 seconds">−10s</button>
      <label class="jump-label">Jump/Seek</label>
      <button class="jump-btn" @click="onJump(10)" title="Forward 10 seconds">+10s</button>
      <button class="jump-btn" @click="onJump(30)" title="Forward 30 seconds">+30s</button>
    </div>

    <button v-show="showIntroButton" class="skip-intro-btn" @click="onSkipIntro">
      Skip Intro
    </button>
  </div>
</template>

<style scoped>
.video-controls {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.5rem 0.75rem;
  /* Match the topbar / library / chat glass treatment so the strip
     reads as part of the same surface stack. The blur over the body
     gradient lets the atmospheric cyan/magenta bleed through subtly. */
  background: rgba(11, 14, 28, 0.55);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid var(--border-subtle);
  border-top: none;
  flex-wrap: wrap;
}

.control-group {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.control-group label {
  font-size: 0.8rem;
  color: var(--text-primary);
  white-space: nowrap;
}

/* Local overrides for the in-strip selects: tighter than the global
   12px because the strip is dense, but the focus ring + colour palette
   inherit from base.css. */
.control-group select {
  padding: 5px 24px 5px 10px;
  font-size: 12px;
  border-radius: 8px;
  background-position: right 6px center;
}

.jump-group {
  margin-left: auto;
  display: flex;
  gap: 6px;
  align-items: center;
}

/* When the binge button is in the strip it takes the right-anchor;
   the jump-group sits inline next to it without re-pushing right. */
.binge-btn + .jump-group {
  margin-left: 0;
}

/* Binge button sits between the dropdowns and the jump-group, pushed
   right by margin-left:auto so it's anchored to the right side of the
   strip together with Jump/Skip. Active state gets the cyan-magenta
   gradient that's used for the LIVE badge -- "currently armed". */
.binge-btn {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  background: var(--bg-surface);
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-sans);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}

.binge-btn:hover {
  background: var(--bg-surface-hover);
  border-color: var(--border-hover);
}

.binge-btn.active {
  background: linear-gradient(90deg, rgba(0, 224, 255, 0.18), rgba(255, 62, 214, 0.18));
  border-color: rgba(0, 224, 255, 0.6);
  color: var(--text-primary);
  box-shadow: 0 0 12px rgba(0, 224, 255, 0.25);
}

.binge-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-secondary);
}

.binge-btn.active .binge-dot {
  background: var(--color-accent-cyan, #00e0ff);
  box-shadow: 0 0 6px var(--color-accent-cyan, #00e0ff);
}

.jump-label {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  margin-right: 4px;
}

/* Jump pills: match the .btn-small chip language with tabular numerals
   so -10s / +10s / -30s / +30s line up vertically. */
.jump-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 5px 10px;
  background: var(--bg-surface);
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  font-family: var(--font-sans);
  line-height: 1.2;
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}

.jump-btn:hover {
  background: var(--bg-surface-hover);
  border-color: var(--border-hover);
}

.jump-btn:active {
  transform: translateY(1px);
}

/* Skip Intro is a one-shot CTA when the intro window is active, so it
   gets the same solid-cyan treatment as .btn-primary with a subtle
   glow. Slightly taller than the chip rows to read as "primary". */
.skip-intro-btn {
  padding: 6px 14px;
  background: var(--accent-primary);
  color: var(--bg-deep);
  border: none;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-sans);
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(34, 211, 238, 0.25);
  transition: background var(--transition-fast), box-shadow var(--transition-fast);
}

.skip-intro-btn:hover {
  background: #67e8f9;
  box-shadow: 0 0 18px var(--accent-primary-glow);
}
</style>
