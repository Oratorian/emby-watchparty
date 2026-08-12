<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
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
  versions: Array<{ id: string; name: string; container: string | null; run_time_ticks: number | null }>
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
  // Optional total runtime in seconds. Used to clamp the
  // jump-to-timestamp input so a typo can't seek past the end of
  // media. When null the popover still works but the validation
  // only blocks negative / unparseable values.
  runTimeSeconds?: number | null
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
  'change-streams': [payload: { audioIndex: number; subtitleIndex: number; quality: string; mediaSourceId?: string }]
  'change-text-subtitle': [payload: { index: number; url: string | null }]
  'skip-intro': [endTime: number]
  // Relative jump in seconds. Sign indicates direction (-30, -10, +10,
  // +30). PartyView computes the target media time and routes through
  // the party seek path so everyone moves together.
  'jump': [seconds: number]
  // Absolute jump-to in media seconds. Emitted by the Jump/Seek
  // popover when the host commits a timestamp; PartyView routes it
  // through the same `seek` socket path as the relative jump so the
  // server-broadcast drives everyone's <video>.
  'seek-to': [absoluteSeconds: number]
  'toggle-binge': []
}>()

const audioTracks = ref<AudioStream[]>([])
const subtitleTracks = ref<SubtitleStream[]>([])
const selectedAudio = ref<number>(0)
const selectedSubtitle = ref<number>(-1)
const selectedQuality = ref(props.quality)
const versions = ref<StreamsResponse['versions']>([])
const selectedVersion = ref(props.mediaSourceId || '')
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

async function fetchStreams(mediaSourceId = props.mediaSourceId) {
  if (!props.itemId) return
  try {
    // Scope to the current version so audio/subtitle dropdowns reflect
    // the stream that's actually playing. The version itself is locked
    // at select_video time and chosen via the library picker -- this
    // strip never switches versions, it just describes the source the
    // party is on.
    const data: StreamsResponse = await api.itemStreams(
      props.itemId,
      mediaSourceId,
    )
    audioTracks.value = data.audio || []
    subtitleTracks.value = data.subtitles || []
    versions.value = data.versions || []
    selectedVersion.value = data.media_source_id || mediaSourceId || data.versions?.[0]?.id || ''

    const defaultAudio = audioTracks.value.find((t) => t.isDefault)
    if (defaultAudio) selectedAudio.value = defaultAudio.index

    const defaultSub = subtitleTracks.value.find((t) => t.isDefault)
    selectedSubtitle.value = defaultSub ? defaultSub.index : -1
    appliedInitialSubtitleKey.value = null
    applyInitialSubtitleSelection()
  } catch {
    audioTracks.value = []
    subtitleTracks.value = []
    versions.value = []
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
    mediaSourceId: selectedVersion.value || undefined,
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
        mediaSourceId: selectedVersion.value || undefined,
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
      mediaSourceId: selectedVersion.value || undefined,
    })
    wasBurnedSub = true
  } else {
    // Text-based sub -- load locally per user. Only rebuild the
    // stream if leaving a burned sub (to remove the burn).
    if (!selectedVersion.value) return
    const url = withPrefix(`/api/subtitles/${props.itemId}/${selectedVersion.value}/${idx}`)
    emit('change-text-subtitle', { index: idx, url })
    if (wasBurnedSub) {
      emit('change-streams', {
        audioIndex: selectedAudio.value,
        subtitleIndex: -1,
        quality: selectedQuality.value,
        mediaSourceId: selectedVersion.value || undefined,
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
    mediaSourceId: selectedVersion.value || undefined,
  })
}

async function onVersionChange() {
  await fetchStreams(selectedVersion.value)
  emit('change-streams', {
    audioIndex: selectedAudio.value,
    subtitleIndex: selectedBurnedSubtitleIndex(),
    quality: selectedQuality.value,
    mediaSourceId: selectedVersion.value || undefined,
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

// ----- Jump-to-timestamp popover ------------------------------------
// Clicking the "Jump/Seek" label opens a small popover with a single
// input. The host types a timestamp + Enter (or clicks Go) to seek
// the whole party to that absolute media position. Routes through the
// same `seek` socket path as the +/- buttons via the seek-to emit, so
// the server broadcast is what actually moves everyone's video.
const seekPopoverOpen = ref(false)
const seekInput = ref('')
const seekInputEl = ref<HTMLInputElement | null>(null)
const seekRoot = ref<HTMLDivElement | null>(null)

function parseTimestampInput(input: string): number | null {
  const trimmed = input.trim()
  if (!trimmed) return null

  // Colon-separated: H:M:S, M:S, or S. Each part must be a non-
  // negative integer. Sum into seconds.
  if (trimmed.includes(':')) {
    const parts = trimmed.split(':')
    if (parts.length < 1 || parts.length > 3) return null
    const nums: number[] = []
    for (const p of parts) {
      if (!/^\d+$/.test(p)) return null
      nums.push(parseInt(p, 10))
    }
    if (nums.length === 3) return nums[0]! * 3600 + nums[1]! * 60 + nums[2]!
    if (nums.length === 2) return nums[0]! * 60 + nums[1]!
    return nums[0]!
  }

  // Digit-only: pad to even length on the left, then split into
  // 2-digit chunks from the right. "104" -> "0104" -> 1:04. Matches
  // how a digital alarm-clock entry feels. The pairs become
  // [HH, MM, SS] or [MM, SS] or [SS]. Anything longer than 3 pairs
  // sums day*86400 + h*3600 + m*60 + s so very long inputs still
  // resolve to a deterministic seconds value before the runtime
  // clamp clips them.
  if (!/^\d+$/.test(trimmed)) return null
  const padded = trimmed.length % 2 === 0 ? trimmed : '0' + trimmed
  const pairs: number[] = []
  for (let i = 0; i < padded.length; i += 2) {
    pairs.push(parseInt(padded.slice(i, i + 2), 10))
  }
  if (pairs.length === 1) return pairs[0]!
  if (pairs.length === 2) return pairs[0]! * 60 + pairs[1]!
  if (pairs.length === 3) return pairs[0]! * 3600 + pairs[1]! * 60 + pairs[2]!
  if (pairs.length === 4) {
    return pairs[0]! * 86400 + pairs[1]! * 3600 + pairs[2]! * 60 + pairs[3]!
  }
  return null
}

const parsedSeekSeconds = computed<number | null>(() => parseTimestampInput(seekInput.value))

const seekPreview = computed<string>(() => {
  const s = parsedSeekSeconds.value
  if (s === null || s < 0) return ''
  const clamped = clampSeekTarget(s)
  return formatSeconds(clamped)
})

const seekValid = computed<boolean>(() => {
  const s = parsedSeekSeconds.value
  return s !== null && s >= 0
})

function clampSeekTarget(seconds: number): number {
  let v = Math.max(0, seconds)
  if (props.runTimeSeconds && props.runTimeSeconds > 5) {
    v = Math.min(v, props.runTimeSeconds - 5)
  }
  return v
}

function formatSeconds(total: number): string {
  const s = Math.max(0, Math.floor(total))
  const hh = Math.floor(s / 3600)
  const mm = Math.floor((s % 3600) / 60)
  const ss = s % 60
  if (hh > 0) {
    return `${hh}:${mm.toString().padStart(2, '0')}:${ss.toString().padStart(2, '0')}`
  }
  return `${mm}:${ss.toString().padStart(2, '0')}`
}

async function openSeekPopover() {
  seekPopoverOpen.value = true
  seekInput.value = ''
  await nextTick()
  seekInputEl.value?.focus()
}

function closeSeekPopover() {
  seekPopoverOpen.value = false
  seekInput.value = ''
}

function commitSeek() {
  if (!seekValid.value) return
  const target = clampSeekTarget(parsedSeekSeconds.value!)
  emit('seek-to', target)
  closeSeekPopover()
}

function onSeekKey(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    e.preventDefault()
    commitSeek()
  } else if (e.key === 'Escape') {
    e.preventDefault()
    closeSeekPopover()
  }
}

function onDocClick(e: MouseEvent) {
  if (!seekPopoverOpen.value) return
  if (seekRoot.value && !seekRoot.value.contains(e.target as Node)) {
    closeSeekPopover()
  }
}
onMounted(() => document.addEventListener('mousedown', onDocClick))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocClick))

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
    <div class="control-group" v-if="versions.length > 1">
      <label for="version-select">Version</label>
      <select id="version-select" v-model="selectedVersion" @change="onVersionChange">
        <option v-for="version in versions" :key="version.id" :value="version.id">{{ version.name }}</option>
      </select>
    </div>
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

    <div class="jump-group" ref="seekRoot">
      <button class="jump-btn" @click="onJump(-30)" title="Back 30 seconds">−30s</button>
      <button class="jump-btn" @click="onJump(-10)" title="Back 10 seconds">−10s</button>
      <button
        class="jump-label-btn"
        :class="{ open: seekPopoverOpen }"
        :title="seekPopoverOpen ? 'Close timestamp jump' : 'Jump to a specific timestamp'"
        @click="seekPopoverOpen ? closeSeekPopover() : openSeekPopover()"
      >
        Jump/Seek
      </button>
      <button class="jump-btn" @click="onJump(10)" title="Forward 10 seconds">+10s</button>
      <button class="jump-btn" @click="onJump(30)" title="Forward 30 seconds">+30s</button>

      <div v-if="seekPopoverOpen" class="seek-popover" role="dialog" aria-label="Jump to timestamp">
        <input
          ref="seekInputEl"
          v-model="seekInput"
          type="text"
          inputmode="numeric"
          placeholder="1:04:07 or 10407"
          class="seek-input"
          @keydown="onSeekKey"
        />
        <div class="seek-preview" v-if="seekPreview">→ {{ seekPreview }}</div>
        <div class="seek-actions">
          <button class="seek-go" :disabled="!seekValid" @click="commitSeek">Go</button>
          <button class="seek-cancel" @click="closeSeekPopover">Cancel</button>
        </div>
      </div>
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
  /* Anchor for the absolute-positioned seek popover so it floats
     above the strip relative to this row, not the viewport. */
  position: relative;
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

/* The static "Jump/Seek" label became a clickable chip that opens
   the timestamp-entry popover. Same colour family as the static
   label was -- no harsh accent until hovered / open -- so users
   who don't know it's interactive still read it as a section heading. */
.jump-label-btn {
  font-size: 12px;
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid transparent;
  white-space: nowrap;
  padding: 4px 8px;
  border-radius: 8px;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: color var(--transition-fast), border-color var(--transition-fast), background var(--transition-fast);
}

.jump-label-btn:hover,
.jump-label-btn.open {
  color: var(--text-primary);
  border-color: var(--border-subtle);
  background: var(--bg-surface);
}

.jump-label-btn.open {
  border-color: var(--color-accent-cyan, #00e0ff);
}

/* Popover floats just above the jump-group so the host can type
   without losing context. Surface-bg + subtle border match the other
   chip dropdowns; cyan accent on the active state marks "this is
   intercepting your input now". */
.seek-popover {
  position: absolute;
  bottom: calc(100% + 8px);
  right: 0;
  min-width: 260px;
  background: var(--bg-secondary, #181820);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 12px 14px;
  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.55),
              0 0 0 1px rgba(0, 224, 255, 0.1) inset;
  z-index: 50;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.seek-input {
  width: 100%;
  background: var(--bg-surface);
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 13px;
  font-family: 'Monaco', 'Consolas', monospace;
  font-variant-numeric: tabular-nums;
  outline: none;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.seek-input:focus {
  border-color: var(--color-accent-cyan, #00e0ff);
  box-shadow: 0 0 0 2px rgba(0, 224, 255, 0.2);
}

.seek-preview {
  font-size: 12px;
  color: var(--color-accent-cyan, #00e0ff);
  font-family: 'Monaco', 'Consolas', monospace;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

.seek-actions {
  display: flex;
  gap: 8px;
}

.seek-go,
.seek-cancel {
  flex: 1;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-sans);
  cursor: pointer;
  border: 1px solid var(--border-subtle);
  transition: background var(--transition-fast), border-color var(--transition-fast), filter var(--transition-fast);
}

.seek-go {
  background: linear-gradient(90deg, rgba(0, 224, 255, 0.22), rgba(255, 62, 214, 0.22));
  color: var(--text-primary);
  border-color: rgba(0, 224, 255, 0.55);
}

.seek-go:hover:not(:disabled) {
  filter: brightness(1.1);
}

.seek-go:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  filter: none;
}

.seek-cancel {
  background: var(--bg-surface);
  color: var(--text-secondary);
}

.seek-cancel:hover {
  color: var(--text-primary);
  border-color: var(--border-hover);
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
