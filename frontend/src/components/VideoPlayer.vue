<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import Hls from 'hls.js'
import { usePartyStore } from '@/stores/party'

const party = usePartyStore()

const props = defineProps<{
  streamUrl: string
  title: string
  playing: boolean
  // Media time at which this stream begins. For late joiners the backend
  // starts Emby transcoding at this position via StartTimeTicks, so the
  // resulting HLS stream's currentTime=0 corresponds to media position
  // streamOffset. HLS.js should NOT be told to seek to streamOffset --
  // that would double-offset and land at 2x the intended position.
  streamOffset?: number
}>()

const emit = defineEmits<{
  play: []
  pause: []
  seeking: []
  seeked: [currentTime: number]
  timeupdate: [currentTime: number]
  ended: []
  ready: []
  'autoplay-blocked': []
}>()

const videoEl = ref<HTMLVideoElement | null>(null)
const isBuffering = ref(false)
const isSyncing = ref(false)

let hls: Hls | null = null

function destroyHls() {
  if (hls) {
    hls.destroy()
    hls = null
  }
}

function attachStream(url: string) {
  const video = videoEl.value
  if (!video || !url) return

  destroyHls()
  isBuffering.value = true
  readyEmitted = false
  // Suppress outgoing play/pause/seek events until the new stream has
  // loaded and the media element settles. Otherwise native 'seeked'
  // events fired during loadSource/attachMedia bubble up as user seeks
  // and create feedback loops across clients.
  isSyncing.value = true

  // iPhone and iPad always have a native HLS stack. Keep other browsers,
  // including Android Chrome and desktop Safari, on Hls.js whenever their
  // MediaSource support is usable; canPlayType() alone is too broad.
  const prefersNativeHls = /iPad|iPhone/.test(navigator.userAgent)

  if (!prefersNativeHls && Hls.isSupported()) {
    const hlsConfig: Partial<Hls['config']> = {
      enableWorker: true,
      lowLatencyMode: false,
      backBufferLength: 90,
      fragLoadingTimeOut: 20000,
      fragLoadingMaxRetry: 4,
      fragLoadingRetryDelay: 1000,
      manifestLoadingTimeOut: 10000,
      levelLoadingTimeOut: 10000,
      // Subtitle handling lives outside HLS.js. Text subs are preloaded
      // as side-channel <track> elements via /api/subtitles/..., and PGS
      // subs are burned into the video by Emby. The manifest no longer
      // carries subtitle entries (1.6.6 backend backport). Disable HLS.js's
      // native text-track features so it does not subscribe to
      // textTracks 'change' events and try to coordinate with our
      // externally-managed <track> elements -- that coordination caused
      // phantom seeks during playback whenever a sub was set to 'showing'.
      enableWebVTT: false,
      renderTextTracksNatively: false,
    }
    // For late joiners, the backend already offsets the Emby transcode via
    // StartTimeTicks, so the stream's currentTime=0 corresponds to the
    // correct media position. Do NOT set hls.startPosition -- that would
    // double-apply the offset.
    hls = new Hls(hlsConfig)
    hls.attachMedia(video)
    hls.on(Hls.Events.MEDIA_ATTACHED, () => {
      hls!.loadSource(url)
    })
    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      isBuffering.value = false
      emitReadyOnce()
      // Keep isSyncing true until the media element has settled after
      // load (canplay + a short debounce to absorb native seeked events
      // fired during initial frame decode). Also resume playback if the
      // party is in a playing state -- the props.playing watcher doesn't
      // fire when the value stays the same across stream reloads.
      const releaseSync = () => {
        // Only auto-play if the party wants to play AND there is no
        // active ready check. During a ready check, playback is
        // coordinated by the server via all_ready + play events; we
        // must not jump ahead.
        if (props.playing && !party.readyCheckActive) {
          video.play().catch(() => {
            emit('autoplay-blocked')
          })
        }
        setTimeout(() => { isSyncing.value = false }, 500)
      }
      if (video.readyState >= 3) {
        releaseSync()
      } else {
        video.addEventListener('canplay', releaseSync, { once: true })
      }
    })
    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (data.fatal) {
        switch (data.type) {
          case Hls.ErrorTypes.NETWORK_ERROR:
            hls?.startLoad()
            break
          case Hls.ErrorTypes.MEDIA_ERROR:
            hls?.recoverMediaError()
            break
          default:
            destroyHls()
            break
        }
      }
    })
  } else {
    // Native HLS path (Safari/iOS), plus the final fallback when neither
    // native capability probing nor Hls.js reports support. Attaching the
    // playlist is safer than leaving the player without a source.
    video.src = url
    video.addEventListener(
      'loadedmetadata',
      () => {
        isBuffering.value = false
        if (props.playing) {
          video.play().catch(() => {
            emit('autoplay-blocked')
          })
        }
        emitReadyOnce()
        setTimeout(() => { isSyncing.value = false }, 500)
      },
      { once: true },
    )
  }
}

// Fallback: emit 'ready' when the video element itself reports enough data.
// This catches cases where HLS.js's MANIFEST_PARSED fired before listeners
// were attached, or where the initial 'ready' emit got lost.
let readyEmitted = false
function emitReadyOnce() {
  if (!readyEmitted) {
    readyEmitted = true
    emit('ready')
  }
}

function onPlay() {
  if (!isSyncing.value) emit('play')
}

function onPause() {
  if (!isSyncing.value) emit('pause')
}

function onSeeking() {
  if (!isSyncing.value) emit('seeking')
}

function onSeeked() {
  if (!isSyncing.value && videoEl.value) emit('seeked', videoEl.value.currentTime)
}

function onTimeupdate() {
  if (!isSyncing.value && videoEl.value) {
    emit('timeupdate', videoEl.value.currentTime)
  }
}

function onEnded() {
  emit('ended')
}

function onWaiting() {
  isBuffering.value = true
}

function onCanPlay() {
  isBuffering.value = false
  // Safety net: if MANIFEST_PARSED fired before listeners were attached
  // (or for whatever reason didn't emit), ensure ready is signaled when
  // the video element reaches HAVE_FUTURE_DATA
  emitReadyOnce()
}

watch(
  () => props.streamUrl,
  (url) => {
    attachStream(url)
  },
)

watch(
  () => props.playing,
  (shouldPlay) => {
    const video = videoEl.value
    if (!video) return
    // Don't force play during a ready check -- the server coordinates
    // playback via all_ready + play events, we must not jump ahead.
    if (party.readyCheckActive) return
    if (shouldPlay) {
      video.play().catch(() => {
        emit('autoplay-blocked')
      })
    } else {
      video.pause()
    }
  },
)

onMounted(() => {
  if (props.streamUrl) {
    attachStream(props.streamUrl)
  }
})

onBeforeUnmount(() => {
  isSyncing.value = true
  destroyHls()
  const video = videoEl.value
  if (video?.hasAttribute('src')) {
    video.removeAttribute('src')
    video.load()
  }
})

defineExpose({ videoEl, isSyncing, isBuffering, getHls: () => hls })
</script>

<template>
  <div class="video-player">
    <video
      id="videoElement"
      ref="videoEl"
      :title="title"
      controls
      playsinline
      @play="onPlay"
      @pause="onPause"
      @seeking="onSeeking"
      @seeked="onSeeked"
      @timeupdate="onTimeupdate"
      @ended="onEnded"
      @waiting="onWaiting"
      @canplay="onCanPlay"
    />
    <div v-if="isBuffering" class="loading-overlay">
      <span class="spinner" />
    </div>
  </div>
</template>

<style scoped>
.video-player {
  position: relative;
  width: 100%;
  /* Fill the height left in .video-wrapper after the controls bar and
     info block; min-height:0 lets it shrink below the video's intrinsic
     height instead of forcing overflow (which clipped the top). */
  flex: 1;
  min-height: 0;
  background: #000;
}

video {
  display: block;
  width: 100%;
  height: 100%;
  /* contain letterboxes the frame to the slot, so the video always fits
     the available space regardless of header/controls/info heights. */
  object-fit: contain;
  background: #000;
}

.loading-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.4);
  pointer-events: none;
}

.spinner {
  width: 48px;
  height: 48px;
  border: 4px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
