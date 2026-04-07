<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import Hls from 'hls.js'

const props = defineProps<{
  streamUrl: string
  title: string
  playing: boolean
  startTime?: number
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

  if (Hls.isSupported()) {
    const hlsConfig: any = {
      enableWorker: true,
      lowLatencyMode: false,
      backBufferLength: 90,
      fragLoadingTimeOut: 20000,
      fragLoadingMaxRetry: 4,
      fragLoadingRetryDelay: 1000,
      manifestLoadingTimeOut: 10000,
      levelLoadingTimeOut: 10000,
      subtitleDisplay: true,
      enableWebVTT: true,
      renderTextTracksNatively: true,
    }
    // Late joiner: tell HLS.js to start buffering from the
    // party's current position instead of segment 0
    const hasStartPos = props.startTime && props.startTime > 1
    if (hasStartPos) {
      hlsConfig.startPosition = props.startTime
    }
    hls = new Hls(hlsConfig)
    hls.attachMedia(video)
    hls.on(Hls.Events.MEDIA_ATTACHED, () => {
      hls!.loadSource(url)
    })
    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      isBuffering.value = false
      // Match v1.5.2: only reset to 0 when NOT a late joiner
      if (!isSyncing.value && !hasStartPos) {
        video.currentTime = 0
      }
      if (isSyncing.value) {
        isSyncing.value = false
      }
      emit('ready')
    })
    // Late joiner: seek to exact position after metadata is available
    // This is separate from MANIFEST_PARSED (matching v1.5.2 flow)
    if (hasStartPos) {
      isSyncing.value = true
      video.addEventListener('loadedmetadata', () => {
        video.currentTime = props.startTime!
        if (props.playing) {
          video.play().then(() => {
            setTimeout(() => { isSyncing.value = false }, 100)
          }).catch(() => {
            setTimeout(() => { isSyncing.value = false }, 100)
            emit('autoplay-blocked')
          })
        } else {
          setTimeout(() => { isSyncing.value = false }, 100)
        }
      }, { once: true })
    }
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
  } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
    // Native HLS support (Safari)
    video.src = url
    video.addEventListener(
      'loadedmetadata',
      () => {
        isBuffering.value = false
        if (props.playing) {
          video.play().catch(() => {})
        }
      },
      { once: true },
    )
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
  destroyHls()
})

defineExpose({ videoEl, isSyncing, getHls: () => hls })
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
  background: #000;
}

video {
  display: block;
  width: 100%;
  max-height: calc(100vh - 180px);
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
