<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type Hls from 'hls.js'
import { api } from '@/api/client'
import { t } from '@/i18n'

const props = withDefaults(defineProps<{ seriesId: string; active?: boolean }>(), { active: true })
type State = 'idle' | 'loading' | 'playing' | 'paused' | 'blocked' | 'finished' | 'failed'
const state = ref<State>('idle')
const root = ref<HTMLElement | null>(null)
const video = ref<HTMLVideoElement | null>(null)
const muted = ref(true)
const showVideo = ref(false)
const inView = ref(false)
const visible = ref(document.visibilityState !== 'hidden')
const reducedMotion = ref(false)
const saveData = ref(false)
const eligible = computed(() => props.active && inView.value && visible.value)
let observer: IntersectionObserver | undefined
let motion: MediaQueryList | undefined
let connection: (EventTarget & { saveData?: boolean }) | undefined
let hls: Hls | null = null
let request: AbortController | null = null
let lease: string | null = null
let generation = 0
let disposed = false
let attempted = false
let manuallyStarted = false
let autoTimer: ReturnType<typeof setTimeout> | undefined
let loadTimer: ReturnType<typeof setTimeout> | undefined
let expiryTimer: ReturnType<typeof setTimeout> | undefined
let clipStart: number | null = null
let duration = 120
const released = new Set<string>()

function release(id: string, keepalive = false) {
  if (released.has(id)) return
  released.add(id)
  void api.stopShowPreview(id, { keepalive }).catch(() => { /* The backend lease also expires. */ })
}

function cancelTimers() {
  clearTimeout(autoTimer)
  clearTimeout(loadTimer)
  clearTimeout(expiryTimer)
  autoTimer = loadTimer = expiryTimer = undefined
}

function stop(next: State = 'idle', keepalive = false) {
  generation += 1
  cancelTimers()
  request?.abort()
  request = null
  const previous = lease
  lease = null
  hls?.destroy()
  hls = null
  const element = video.value
  element?.pause()
  if (element?.hasAttribute('src')) {
    element.removeAttribute('src')
    element.load()
  }
  clipStart = null
  showVideo.value = false
  state.value = next
  if (previous) release(previous, keepalive)
}

function fail() {
  if (lease || request) stop('failed')
}

async function tryPlay() {
  const element = video.value
  if (!element || !lease || !eligible.value) return
  const current = generation
  element.muted = muted.value
  hls?.startLoad()
  try {
    await element.play()
  } catch (error) {
    if (current !== generation || disposed) return
    if (!(error && typeof error === 'object' && 'name' in error && error.name === 'NotAllowedError')) {
      stop('failed')
      return
    }
    // Some browsers still require a gesture for muted autoplay. Keep the
    // backdrop visible and offer an explicit Play action in that case.
    clearTimeout(loadTimer)
    hls?.stopLoad()
    state.value = 'blocked'
  }
}

async function start(manual = false) {
  if (!eligible.value || disposed) return
  attempted = true
  manuallyStarted = manual
  stop()
  muted.value = true
  state.value = 'loading'
  const current = generation
  const controller = new AbortController()
  request = controller
  loadTimer = setTimeout(() => stop('failed'), 18_000)
  try {
    const { default: HlsPlayer } = await import('hls.js')
    if (current !== generation || disposed) return
    const element = video.value
    if (!element) return
    const nativeHls = /iPad|iPhone/.test(navigator.userAgent)
      && Boolean(element.canPlayType('application/vnd.apple.mpegurl'))
    const useHls = !nativeHls && HlsPlayer.isSupported()
    if (!useHls && !element.canPlayType('application/vnd.apple.mpegurl')) {
      stop('failed')
      return
    }
    const response = await api.startShowPreview(props.seriesId, { signal: controller.signal })
    if (current !== generation || disposed || !eligible.value) {
      release(response.preview_id, disposed || !visible.value)
      return
    }
    lease = response.preview_id
    request = null
    duration = Math.min(120, Math.max(1, response.duration_seconds))
    expiryTimer = setTimeout(() => stop('finished'), Math.max(1, response.expires_in) * 1000)
    element.muted = muted.value
    if (useHls) {
      const player = new HlsPlayer({
        enableWorker: true,
        lowLatencyMode: false,
        maxBufferLength: 10,
        maxMaxBufferLength: 20,
        backBufferLength: 0,
        manifestLoadingTimeOut: 8000,
        fragLoadingTimeOut: 10_000,
        fragLoadingMaxRetry: 1,
        enableWebVTT: false,
        renderTextTracksNatively: false,
      })
      hls = player
      player.once(HlsPlayer.Events.MEDIA_ATTACHED, () => {
        if (current === generation && !disposed) player.loadSource(response.url)
      })
      player.once(HlsPlayer.Events.MANIFEST_PARSED, () => {
        if (current === generation && !disposed) void tryPlay()
      })
      player.on(HlsPlayer.Events.ERROR, (_event, data) => {
        if (current === generation && !disposed && data.fatal) fail()
      })
      player.attachMedia(element)
    } else {
      element.src = response.url
      element.load()
      void tryPlay()
    }
  } catch {
    if (current === generation && !disposed) stop('failed')
  }
}

function onPlaying() {
  if (!lease || !eligible.value) return
  clearTimeout(loadTimer)
  clipStart ??= video.value?.currentTime ?? 0
  state.value = 'playing'
  showVideo.value = true
}

function onTimeUpdate() {
  if (lease && clipStart !== null && video.value
    && video.value.currentTime - clipStart >= duration) stop('finished')
}

function pause() {
  video.value?.pause()
  hls?.stopLoad()
  state.value = 'paused'
}

function onPause() {
  if (lease && state.value === 'playing') {
    hls?.stopLoad()
    state.value = 'paused'
  }
}

function play() {
  if (lease && (state.value === 'paused' || state.value === 'blocked')) void tryPlay()
  else void start(true)
}

function toggleMute() {
  muted.value = !muted.value
  if (video.value) video.value.muted = muted.value
}

function scheduleAutomatic() {
  clearTimeout(autoTimer)
  if (eligible.value && !attempted && !reducedMotion.value && !saveData.value) {
    autoTimer = setTimeout(() => { void start() }, 800)
  }
}

function updatePreferences() {
  reducedMotion.value = motion?.matches ?? false
  saveData.value = connection?.saveData ?? false
  if ((reducedMotion.value || saveData.value) && !manuallyStarted && (lease || request)) stop()
  scheduleAutomatic()
}

function onVisibilityChange() {
  visible.value = document.visibilityState !== 'hidden'
}

function onPageHide() {
  visible.value = false
  stop('idle', true)
}

watch(eligible, (allowed) => {
  if (allowed) scheduleAutomatic()
  else stop('idle', !visible.value)
}, { flush: 'sync' })
watch(() => props.seriesId, () => {
  stop()
  attempted = false
  scheduleAutomatic()
})

onMounted(async () => {
  motion = window.matchMedia?.('(prefers-reduced-motion: reduce)')
  connection = (navigator as Navigator & { connection?: EventTarget & { saveData?: boolean } }).connection
  motion?.addEventListener('change', updatePreferences)
  connection?.addEventListener('change', updatePreferences)
  document.addEventListener('visibilitychange', onVisibilityChange)
  window.addEventListener('pagehide', onPageHide)
  updatePreferences()
  await nextTick()
  if (disposed) return
  if (typeof IntersectionObserver !== 'undefined' && root.value) {
    observer = new IntersectionObserver((entries) => {
      inView.value = entries.some(entry => entry.isIntersecting && entry.intersectionRatio >= 0.15)
    }, { threshold: 0.15 })
    observer.observe(root.value)
  } else inView.value = true
})

onBeforeUnmount(() => {
  disposed = true
  stop('idle', true)
  observer?.disconnect()
  motion?.removeEventListener('change', updatePreferences)
  connection?.removeEventListener('change', updatePreferences)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  window.removeEventListener('pagehide', onPageHide)
})
</script>

<template>
  <div ref="root" class="show-background-preview" role="group" :aria-label="t('library.preview_label')">
    <video
      ref="video"
      class="show-preview-video"
      :class="{ 'is-playing': showVideo }"
      :muted="muted"
      aria-hidden="true"
      tabindex="-1"
      playsinline
      disablepictureinpicture
      preload="none"
      @playing="onPlaying"
      @pause="onPause"
      @timeupdate="onTimeUpdate"
      @ended="stop('finished')"
      @error="fail"
    />
    <div class="show-preview-shade" aria-hidden="true" />
    <div v-if="active" class="show-preview-controls">
      <span v-if="state === 'loading'" class="show-preview-loading" role="status">{{ t('library.preview_loading') }}</span>
      <button v-else-if="state === 'playing'" type="button" @click="pause">{{ t('library.preview_pause') }}</button>
      <button v-else type="button" @click="play">{{ t('library.preview_play') }}</button>
      <button v-if="state === 'playing' || state === 'paused' || state === 'blocked'" type="button" :aria-pressed="muted" @click="toggleMute">
        {{ t(muted ? 'library.preview_unmute' : 'library.preview_mute') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.show-background-preview { position: absolute; inset: 0; pointer-events: none; }
.show-preview-video { position: absolute; inset: 0; z-index: 0; width: 100%; height: 100%; object-fit: cover; opacity: 0; }
.show-preview-video.is-playing { opacity: 1; }
.show-preview-shade { position: absolute; inset: 0; z-index: 0; background: var(--detail-backdrop-shade, rgba(8, 9, 14, .75)); }
.show-preview-controls { position: absolute; right: 12px; bottom: 12px; z-index: 2; display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; max-width: calc(100% - 24px); pointer-events: auto; }
.show-preview-controls button, .show-preview-loading { padding: 6px 9px; border: 1px solid var(--border-subtle); border-radius: 8px; background: rgba(8, 9, 14, .9); color: var(--text-primary); font: 500 12px var(--font-sans); }
.show-preview-controls button { cursor: pointer; }
.show-preview-controls button:focus-visible { outline: 2px solid var(--accent-primary); outline-offset: 2px; }
.show-preview-controls button:hover { border-color: var(--border-accent); }
</style>
