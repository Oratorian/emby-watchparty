<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSocketStore } from '@/stores/socket'
import { usePartyStore } from '@/stores/party'
import LibraryBrowser from '@/components/LibraryBrowser.vue'
import VideoPlayer from '@/components/VideoPlayer.vue'
import VideoControls from '@/components/VideoControls.vue'
import EmojiPicker from '@/components/EmojiPicker.vue'
import { api } from '@/api/client'
import { avatarUrl } from '@/utils/avatar'

const route = useRoute()
const router = useRouter()
const socket = useSocketStore()
const party = usePartyStore()

const usernameInput = ref('')
const joined = ref(false)
const chatMessages = ref<Array<{ username: string; message: string; timestamp: string; system?: boolean }>>([])
const chatInput = ref('')
const showLibrary = ref(false)
const copyLabel = ref('Copy')
const showVersionModal = ref(false)
const showParticipants = ref(false)
const videoPlayer = ref<InstanceType<typeof VideoPlayer> | null>(null)
const currentTime = ref(0)

const STORAGE_KEY = 'emby-watchparty-username'
const versionInfo = ref({ version: '', codename: '' })

onMounted(async () => {
  socket.connect()
  party.setupListeners()

  try {
    const v = await api.version()
    versionInfo.value = { version: v.current_version || v.version || '', codename: v.codename || '' }
  } catch { /* ignore */ }

  socket.on('chat_message', (data: any) => {
    chatMessages.value.push(data)
    nextTick(() => {
      const el = document.querySelector('.chat-messages')
      if (el) el.scrollTop = el.scrollHeight
    })
  })

  // Playback sync handlers
  socket.on('play', (data: any) => {
    const vp = videoPlayer.value
    if (!vp) return
    vp.isSyncing = true
    const ve = vp.videoEl
    if (ve) {
      if (Math.abs(ve.currentTime - data.time) > 1) ve.currentTime = data.time
      ve.play().catch(() => {
        addSystemMessage('Autoplay blocked by browser - click the video to resume')
      })
    }
    setTimeout(() => { if (vp) vp.isSyncing = false }, 500)
    if (data.username) addSystemMessage(`${data.username} resumed playback`)
  })

  socket.on('pause', (data: any) => {
    const vp = videoPlayer.value
    if (!vp) return
    vp.isSyncing = true
    const ve = vp.videoEl
    if (ve) {
      ve.pause()
      if (Math.abs(ve.currentTime - data.time) > 1) ve.currentTime = data.time
    }
    setTimeout(() => { if (vp) vp.isSyncing = false }, 500)
    if (data.username) addSystemMessage(`${data.username} paused playback`)
  })

  socket.on('seek', (data: any) => {
    const vp = videoPlayer.value
    if (!vp) return
    vp.isSyncing = true
    const ve = vp.videoEl
    if (ve) {
      ve.currentTime = data.time
      if (data.playing) {
        const bufferDelay = data.buffer_delay || 500
        const onSeeked = () => {
          setTimeout(() => {
            ve.play().catch(() => {
              addSystemMessage('Autoplay blocked by browser - click the video to resume')
            })
            setTimeout(() => { if (vp) vp.isSyncing = false }, 2000)
          }, bufferDelay)
          ve.removeEventListener('seeked', onSeeked)
        }
        ve.addEventListener('seeked', onSeeked)
      } else {
        ve.pause()
        setTimeout(() => { if (vp) vp.isSyncing = false }, 2000)
      }
    }
    if (data.username) addSystemMessage(`${data.username} seeked to ${formatTime(data.time)}`)
  })

  socket.on('force_pause_before_seek', (data: any) => {
    const vp = videoPlayer.value
    if (!vp) return
    isForcePausing = true
    vp.isSyncing = true
    const ve = vp.videoEl
    if (ve) ve.pause()
    setTimeout(() => { isForcePausing = false }, 2000)
  })

  socket.on('drift_correction', (data: any) => {
    const vp = videoPlayer.value
    if (!vp) return
    vp.isSyncing = true
    const ve = vp.videoEl
    const hlsInstance = vp.getHls?.()
    if (ve && hlsInstance) {
      hlsInstance.stopLoad()
      ve.currentTime = data.time
      hlsInstance.startLoad(data.time)
      if (data.playing) {
        ve.play().catch(() => {})
      }
    } else if (ve) {
      ve.currentTime = data.time
      if (data.playing) {
        ve.play().catch(() => {})
      }
    }
    setTimeout(() => { if (vp) vp.isSyncing = false }, 500)
  })

  // Heartbeat
  const heartbeatInterval = setInterval(() => {
    const vp = videoPlayer.value
    const ve = vp?.videoEl
    if (ve && party.partyId && !ve.paused && ve.readyState >= 2) {
      socket.emit('heartbeat', { party_id: party.partyId, time: ve.currentTime })
    }
  }, 5000)

  onUnmounted(() => {
    clearInterval(heartbeatInterval)
  })

  // Handle late joiner sync -- suppress emits during initial load
  // Drift correction will bring the late joiner to the right position
  socket.on('sync_state', (data: any) => {
    if (data.current_video) {
      isInitialSync = true
      setTimeout(() => {
        isInitialSync = false
      }, 3000)
    }
  })

  // Error handler -- redirect on invalid party
  socket.on('error', (data: any) => {
    const msg = data?.message || 'Unknown error'
    if (msg.includes('not found')) {
      alert(`Party not found: ${route.params.id}`)
      router.push('/')
      return
    }
    addSystemMessage(`Error: ${msg}`)
  })

  // Auto-join with saved username
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) {
    joinWithName(saved)
  }
})

onUnmounted(() => {
  party.leave()
})

// Preload all text subtitles as hidden tracks when video changes
watch(() => party.currentVideo, async (video) => {
  if (!video?.item_id || !video?.media_source_id) return
  await nextTick()
  const vp = videoPlayer.value
  const ve = vp?.videoEl
  if (!ve) return

  try {
    const streams = await api.itemStreams(video.item_id)
    const textSubs = (streams.subtitles || []).filter((s: any) => !s.isPGS && s.isTextSubtitleStream)
    textSubs.forEach((sub: any) => {
      const track = document.createElement('track')
      track.kind = 'subtitles'
      track.label = sub.displayLanguage || sub.language || 'Unknown'
      track.srclang = sub.language || 'und'
      track.src = `/api/subtitles/${video.item_id}/${video.media_source_id}/${sub.index}`
      track.mode = 'hidden'
      ve.appendChild(track)
    })
  } catch { /* ignore */ }
})

function addSystemMessage(msg: string) {
  chatMessages.value.push({ username: 'System', message: msg, timestamp: new Date().toISOString(), system: true })
}

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  const pad = (n: number) => n < 10 ? '0' + n : '' + n
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
}

function joinWithName(name: string) {
  const id = route.params.id as string
  if (!name) name = ''
  party.join(id, name)
  if (name) localStorage.setItem(STORAGE_KEY, name)
  // joined=true is set when server confirms via user_joined
}

// Confirm join when server acknowledges
watch(() => party.users, (users) => {
  if (users.length > 0 && !joined.value) {
    joined.value = true
  }
}, { deep: true })

function submitJoin() {
  joinWithName(usernameInput.value.trim())
}

function sendChat() {
  if (!chatInput.value.trim() || !party.partyId) return
  socket.emit('chat_message', {
    party_id: party.partyId,
    message: chatInput.value.trim(),
  })
  chatInput.value = ''
}

function insertEmoji(emoji: string) {
  chatInput.value += emoji
}

function copyPartyId() {
  const id = (route.params.id as string) || ''
  navigator.clipboard.writeText(id).then(() => {
    copyLabel.value = 'Copied!'
    setTimeout(() => { copyLabel.value = 'Copy' }, 2000)
  }).catch(() => {
    copyLabel.value = 'Failed'
    setTimeout(() => { copyLabel.value = 'Copy' }, 2000)
  })
}

function leaveParty() {
  party.leave()
  router.push('/')
}

function selectVideo(item: any) {
  if (!party.partyId) return
  hasStarted = false
  socket.emit('select_video', {
    party_id: party.partyId,
    item_id: item.Id,
    item_name: item.Name,
    item_overview: item.Overview || '',
    quality: '1080p-high',
  })
  showLibrary.value = false
}

let wasPlayingBeforeSeek = false

let isForcePausing = false
let isUserSeeking = false
let hasStarted = false
let isInitialSync = false

function onVideoPlay() {
  if (!party.partyId || isForcePausing || isInitialSync) return
  const ve = videoPlayer.value?.videoEl
  wasPlayingBeforeSeek = true
  socket.emit('play', { party_id: party.partyId, time: ve?.currentTime || 0 })
  if (!hasStarted) {
    addSystemMessage(`${party.username || 'You'} started playback`)
    hasStarted = true
  } else {
    addSystemMessage(`${party.username || 'You'} resumed playback`)
  }
}

function onVideoPause() {
  if (!party.partyId || isForcePausing || isUserSeeking || isInitialSync) return
  wasPlayingBeforeSeek = false
  socket.emit('pause', { party_id: party.partyId, time: videoPlayer.value?.videoEl?.currentTime || 0 })
  addSystemMessage(`${party.username || 'You'} paused playback`)
}

function onVideoSeeked(time: number) {
  if (!party.partyId || isInitialSync) return
  isUserSeeking = false
  socket.emit('seek', {
    party_id: party.partyId,
    time,
    was_playing: wasPlayingBeforeSeek,
  })
  addSystemMessage(`${party.username || 'You'} seeked to ${formatTime(time)}`)
}

let lastProgressReport = 0
const PROGRESS_INTERVAL = 10000 // 10 seconds

function onVideoTimeUpdate(time: number) {
  currentTime.value = time
  if (!party.partyId || isInitialSync) return
  const now = Date.now()
  if (now - lastProgressReport >= PROGRESS_INTERVAL) {
    lastProgressReport = now
    socket.emit('report_progress', { party_id: party.partyId, time })
  }
}

function stopVideo() {
  if (!party.partyId) return
  socket.emit('stop_video', { party_id: party.partyId })
}

function onChangeStreams(opts: { audioIndex?: number; subtitleIndex?: number; quality?: string }) {
  if (!party.partyId) return
  socket.emit('change_streams', {
    party_id: party.partyId,
    audio_index: opts.audioIndex,
    subtitle_index: opts.subtitleIndex,
    quality: opts.quality,
  })
}

function onChangeTextSubtitle(payload: { index: number; url: string | null }) {
  const vp = videoPlayer.value
  const ve = vp?.videoEl
  if (!ve) return

  // Remove existing text tracks
  const existingTracks = ve.querySelectorAll('track')
  existingTracks.forEach((t) => t.remove())

  if (payload.index === -1 || !payload.url) return

  // Add new text track
  const track = document.createElement('track')
  track.kind = 'subtitles'
  track.label = 'Subtitles'
  track.srclang = 'und'
  track.src = payload.url
  track.default = true
  ve.appendChild(track)

  // Activate the track
  if (ve.textTracks.length > 0) {
    ve.textTracks[0].mode = 'showing'
  }
}

function onSkipIntro(endTime: number) {
  const vp = videoPlayer.value
  if (!vp?.videoEl) return
  vp.isSyncing = true
  vp.videoEl.currentTime = endTime
  socket.emit('seek', {
    party_id: party.partyId,
    time: endTime,
    was_playing: !vp.videoEl.paused,
  })
  setTimeout(() => { if (vp) vp.isSyncing = false }, 500)
}

function toggleLibrary() {
  showLibrary.value = !showLibrary.value
  if (showLibrary.value) {
    socket.emit('toggle_library', { party_id: party.partyId, show: true })
  } else {
    socket.emit('toggle_library', { party_id: party.partyId, show: false })
  }
}
</script>

<template>
  <!-- Username modal -->
  <div v-if="!joined" class="modal-overlay">
    <div class="modal-card">
      <h2>Join Watch Party</h2>
      <p>Enter your name (or leave blank for random name):</p>
      <input v-model="usernameInput" @keypress.enter="submitJoin" placeholder="Your name (optional)" type="text" autofocus />
      <button @click="submitJoin" class="btn btn-primary">Join</button>
    </div>
  </div>

  <!-- Party room -->
  <div v-else class="party-container">
    <header class="party-header">
      <div class="header-left">
        <strong>Party: {{ route.params.id }}</strong>
        <button @click="copyPartyId" class="btn-copy" title="Copy party code">
          {{ copyLabel }}
        </button>
        <span class="user-count">{{ party.userCount }} users</span>
      </div>
      <div class="header-center" v-if="versionInfo.version" @click="showVersionModal = true">
        <span class="header-title">Watch Party</span>
        <span class="header-codename">{{ versionInfo.codename }}</span>
      </div>
      <div class="header-actions">
        <button @click="toggleLibrary" class="btn btn-small">
          {{ showLibrary ? 'Hide Library' : 'Browse Library' }}
        </button>
        <button v-if="party.currentVideo" @click="stopVideo" class="btn btn-small btn-warning">Stop Video</button>
        <button @click="leaveParty" class="btn btn-small btn-danger">Leave</button>
      </div>
    </header>

    <div class="party-content">
      <!-- Library panel -->
      <LibraryBrowser
        v-if="showLibrary"
        class="library-panel"
        @select-video="selectVideo"
      />

      <!-- Video area -->
      <main class="video-area">
        <div v-if="!party.currentVideo" class="no-video">
          <h2>No video selected</h2>
          <p>Browse the library and select a video to start watching together</p>
          <button @click="toggleLibrary" class="btn btn-primary">Browse Library</button>
        </div>
        <div v-else class="video-wrapper">
          <VideoPlayer
            ref="videoPlayer"
            :stream-url="party.currentVideo.stream_url"
            :title="party.currentVideo.title"
            :playing="party.playbackState.playing"
            :start-time="party.playbackState.time"
            @play="onVideoPlay"
            @pause="onVideoPause"
            @seeking="isUserSeeking = true"
            @seeked="onVideoSeeked"
            @timeupdate="onVideoTimeUpdate"
            @ended="() => {}"
          />
          <VideoControls
            :party-id="party.partyId!"
            :item-id="party.currentVideo.item_id"
            :stream-url="party.currentVideo.stream_url"
            :quality="party.currentVideo.quality || '1080p-high'"
            :current-time="currentTime"
            :media-source-id="party.currentVideo.media_source_id"
            @change-streams="onChangeStreams"
            @change-text-subtitle="onChangeTextSubtitle"
            @skip-intro="onSkipIntro"
          />
          <div class="video-info">
            <h3>{{ party.currentVideo.title }}</h3>
            <p v-if="party.currentVideo.overview" class="video-overview">{{ party.currentVideo.overview }}</p>
          </div>
        </div>
      </main>

      <!-- Chat -->
      <aside class="chat-panel">
        <div class="chat-header" @click="showParticipants = !showParticipants">
          <h3>Chat</h3>
          <span class="participant-toggle" :title="showParticipants ? 'Hide participants' : 'Show participants'">
            <span class="participant-count-badge">{{ party.userCount }}</span>
            <span class="participant-arrow" :class="{ open: showParticipants }">&#9662;</span>
          </span>
        </div>
        <div v-if="showParticipants" class="participant-list">
          <div
            v-for="user in party.users"
            :key="user"
            class="participant-item"
            :class="{ 'participant-self': user === party.username }"
          >
            <img :src="avatarUrl(user)" class="avatar avatar-sm" :alt="user" />
            <span>{{ user }}</span>
            <span v-if="user === party.username" class="you-label">(you)</span>
          </div>
        </div>
        <div class="chat-messages">
          <div
            v-for="(msg, i) in chatMessages"
            :key="i"
            :class="['chat-msg', { 'system-msg': msg.system }]"
          >
            <template v-if="msg.system">
              <em>{{ msg.message }}</em>
            </template>
            <template v-else>
              <div class="msg-bubble-row" :class="{ 'msg-self': msg.username === party.username }">
                <img v-if="msg.username !== party.username" :src="avatarUrl(msg.username)" class="avatar avatar-chat" :alt="msg.username" />
                <div class="msg-bubble" :class="msg.username === party.username ? 'bubble-self' : 'bubble-other'">
                  <strong>{{ msg.username }}</strong>
                  <span>{{ msg.message }}</span>
                </div>
                <img v-if="msg.username === party.username" :src="avatarUrl(msg.username)" class="avatar avatar-chat" :alt="msg.username" />
              </div>
            </template>
          </div>
        </div>
        <div class="chat-input">
          <input v-model="chatInput" @keypress.enter="sendChat" placeholder="Type a message..." />
          <EmojiPicker @select="insertEmoji" />
          <button @click="sendChat" class="btn btn-small btn-primary">Send</button>
        </div>
      </aside>
    </div>
  </div>

  <!-- Version Modal -->
  <div v-if="showVersionModal" class="modal-overlay" @click.self="showVersionModal = false">
    <div class="version-modal glass">
      <div class="version-modal-header">
        <h2>Emby Watch Party</h2>
        <button @click="showVersionModal = false" class="btn btn-ghost btn-small">Close</button>
      </div>
      <div class="version-modal-body">
        <div class="version-number">v{{ versionInfo.version }}</div>
        <div class="version-codename-display">"{{ versionInfo.codename }}"</div>
      </div>
      <div class="version-modal-links">
        <a href="https://github.com/Oratorian/emby-watchparty" target="_blank" rel="noopener">GitHub</a>
        <span class="dot">&middot;</span>
        <a href="https://discord.gg/RWUpxq9xsA" target="_blank" rel="noopener">Discord</a>
        <span class="dot">&middot;</span>
        <a href="https://ko-fi.com/jedziah" target="_blank" rel="noopener">Ko-fi</a>
        <span class="dot">&middot;</span>
        <router-link to="/version" @click="showVersionModal = false">Full Version Info</router-link>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ─── Join Modal ─── */
.modal-overlay {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(8px);
  z-index: 1000;
}

.modal-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: var(--space-xl);
  text-align: center;
  max-width: 400px;
  width: 90%;
  box-shadow: var(--shadow-lg);
}

.modal-card h2 {
  margin-bottom: var(--space-sm);
}

.modal-card p {
  margin-bottom: var(--space-md);
  font-size: 0.9rem;
}

.modal-card input {
  margin-bottom: var(--space-md);
  text-align: center;
}

/* ─── Party Layout ─── */
.party-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg-primary);
}

.party-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-sm) var(--space-md);
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-subtle);
  position: relative;
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-md);
}

.header-left strong {
  font-size: 0.95rem;
  letter-spacing: 0.05em;
}

.btn-copy {
  background: var(--bg-surface);
  color: var(--text-secondary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  padding: 0.15rem 0.5rem;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all var(--transition-fast);
  font-family: var(--font-sans);
}

.btn-copy:hover {
  color: var(--accent-primary);
  border-color: var(--accent-primary);
}

.user-count {
  color: var(--accent-secondary);
  font-size: 0.85rem;
  font-weight: 500;
}

.header-center {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  line-height: 1.2;
  cursor: pointer;
  pointer-events: auto;
  transition: opacity var(--transition-fast);
}

.header-center:hover {
  opacity: 0.8;
}

.header-title {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-primary);
}

.header-codename {
  font-size: 0.7rem;
  color: var(--accent-secondary);
  font-style: italic;
}

.header-actions {
  display: flex;
  gap: var(--space-sm);
}

.party-content {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ─── Library Panel ─── */
.library-panel {
  width: 350px;
  min-width: 300px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-subtle);
  overflow-y: auto;
  padding: var(--space-md);
  overflow-anchor: auto;
}

/* ─── Video Area ─── */
.video-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: auto;
  background: var(--bg-deep);
}

.no-video {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-md);
  padding: var(--space-2xl) var(--space-md);
}

.no-video h2 {
  color: var(--text-secondary);
  font-weight: 400;
}

.no-video p {
  color: var(--text-muted);
}

.video-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.video-info {
  padding: var(--space-sm) var(--space-md);
  background: var(--bg-secondary);
  border-top: 1px solid var(--border-subtle);
}

.video-info h3 {
  margin: 0 0 var(--space-xs);
  font-size: 1rem;
}

.video-overview {
  font-size: 0.9rem;
  color: var(--text-primary);
  opacity: 0.75;
  margin: 0;
  max-height: 2.5em;
  overflow: hidden;
  line-height: 1.4;
}

/* ─── Chat Panel ─── */
.chat-panel {
  width: 320px;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  border-left: 1px solid var(--border-subtle);
}

.chat-header {
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.chat-header {
  cursor: pointer;
  user-select: none;
}

.chat-header:hover {
  background: var(--bg-surface-hover);
}

.chat-header h3 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 500;
}

.participant-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}

.participant-count-badge {
  background: var(--accent-primary-dim);
  color: var(--accent-primary);
  padding: 0.1rem 0.55rem;
  border-radius: var(--radius-full);
  font-size: 0.75rem;
  font-weight: 600;
}

.participant-arrow {
  font-size: 0.7rem;
  color: var(--text-muted);
  transition: transform var(--transition-fast);
}

.participant-arrow.open {
  transform: rotate(180deg);
}

.participant-list {
  border-bottom: 1px solid var(--border-subtle);
  padding: var(--space-xs) var(--space-md);
  background: var(--bg-surface);
}

.participant-item {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-xs) 0;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.participant-self {
  color: var(--accent-primary);
  font-weight: 600;
}

.you-label {
  font-weight: 400;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-sm) var(--space-md);
  font-size: 0.85rem;
  line-height: 1.5;
}

.chat-msg {
  margin-bottom: var(--space-xs);
  padding: var(--space-xs) 0;
}

.msg-bubble-row {
  display: flex;
  align-items: flex-end;
  gap: var(--space-sm);
}

.msg-bubble-row.msg-self {
  justify-content: flex-end;
}

.msg-bubble {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-sm) var(--space-md);
  border-radius: var(--radius-md);
  max-width: 75%;
  min-width: 0;
  word-break: break-word;
  font-size: 0.85rem;
}

.bubble-other {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-bottom-left-radius: var(--radius-sm);
}

.bubble-self {
  background: var(--accent-primary-dim);
  border: 1px solid var(--border-accent);
  border-bottom-right-radius: var(--radius-sm);
}

.msg-bubble strong {
  font-size: 0.75rem;
  font-weight: 600;
}

.bubble-other strong {
  color: var(--accent-primary);
}

.bubble-self strong {
  color: var(--accent-secondary);
}

/* Avatars */
.avatar {
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.avatar-sm {
  width: 22px;
  height: 22px;
}

.avatar-chat {
  width: 28px;
  height: 28px;
  margin-top: 1px;
}

.system-msg {
  color: var(--text-muted);
  font-size: 0.8rem;
  font-style: italic;
  padding: var(--space-xs) 0;
  border-left: 2px solid var(--border-subtle);
  padding-left: var(--space-sm);
}

.chat-input {
  display: flex;
  padding: var(--space-sm);
  gap: var(--space-sm);
  border-top: 1px solid var(--border-subtle);
}

.chat-input input {
  flex: 1;
  padding: var(--space-sm);
  font-size: 0.85rem;
}

/* ─── Version Modal ─── */
.version-modal {
  max-width: 420px;
  width: 90%;
  padding: var(--space-xl);
  text-align: center;
}

.version-modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-md);
}

.version-modal-header h2 {
  font-size: 1.1rem;
  margin: 0;
}

.version-modal-body {
  padding: var(--space-md) 0;
}

.version-number {
  font-size: 2rem;
  font-weight: 700;
  font-family: var(--font-mono);
}

.version-codename-display {
  color: var(--accent-secondary);
  font-size: 1rem;
  margin-top: var(--space-xs);
}

.version-modal-links {
  margin-top: var(--space-md);
  padding-top: var(--space-md);
  border-top: 1px solid var(--border-subtle);
  font-size: 0.85rem;
  display: flex;
  justify-content: center;
  gap: var(--space-sm);
  flex-wrap: wrap;
}

.version-modal-links .dot {
  color: var(--text-muted);
}
</style>
