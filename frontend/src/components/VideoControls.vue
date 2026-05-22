<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '@/api/client'

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
}>()

const emit = defineEmits<{
  'change-streams': [payload: { audioIndex: number; subtitleIndex: number; quality: string }]
  'change-text-subtitle': [payload: { index: number; url: string | null }]
  'skip-intro': [endTime: number]
}>()

const audioTracks = ref<AudioStream[]>([])
const subtitleTracks = ref<SubtitleStream[]>([])
const selectedAudio = ref<number>(0)
const selectedSubtitle = ref<number>(-1)
const selectedTextSubtitle = ref<number>(-1)
const selectedQuality = ref(props.quality)
const intro = ref<IntroData | null>(null)
const appliedInitialSubtitleKey = ref<string | null>(null)

const qualityPresets = [
  { label: '1080p High (10 Mbps)', value: '1080p-high' },
  { label: '1080p (8 Mbps)', value: '1080p' },
  { label: '720p (5 Mbps)', value: '720p' },
  { label: '480p (2 Mbps)', value: '480p' },
  { label: '360p (1 Mbps)', value: '360p' },
]

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
    const data: StreamsResponse = await api.itemStreams(props.itemId)
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
    const url = `/api/subtitles/${props.itemId}/${props.mediaSourceId}/${idx}`
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
  () => {
    applyInitialSubtitleSelection()
  },
)

onMounted(() => {
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

    <div class="control-group">
      <label for="quality-select">Quality</label>
      <select id="quality-select" v-model="selectedQuality" @change="onQualityChange">
        <option v-for="preset in qualityPresets" :key="preset.value" :value="preset.value">
          {{ preset.label }}
        </option>
      </select>
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
  background: var(--bg-secondary);
  border: 1px solid var(--cyber-border);
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

.control-group select {
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--cyber-border);
  border-radius: 4px;
  padding: 0.3rem 0.5rem;
  font-size: 0.8rem;
  cursor: pointer;
  outline: none;
}

.control-group select:focus {
  border-color: var(--cyber-primary);
}

.skip-intro-btn {
  margin-left: auto;
  padding: 0.35rem 1rem;
  background: var(--cyber-primary);
  color: var(--bg-secondary);
  border: none;
  border-radius: 4px;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}

.skip-intro-btn:hover {
  opacity: 0.85;
}
</style>
