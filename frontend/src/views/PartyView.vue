<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSocketStore } from '@/stores/socket'
import { usePartyStore } from '@/stores/party'
import LibraryBrowser from '@/components/LibraryBrowser.vue'
import VideoPlayer from '@/components/VideoPlayer.vue'
import VideoControls from '@/components/VideoControls.vue'
import EmojiPicker from '@/components/EmojiPicker.vue'
import JoinVoteModal from '@/components/JoinVoteModal.vue'
import JoinWaitingRoom from '@/components/JoinWaitingRoom.vue'
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
const showMobileChat = ref(false)
const videoPlayer = ref<InstanceType<typeof VideoPlayer> | null>(null)
const currentTime = ref(0)
let pendingPauseTimer: ReturnType<typeof setTimeout> | null = null

// True while my own HLS stream is reloading (after change_streams). Used
// to distinguish "I am the user whose stream changed" from "I am an
// observer whose stream is already buffered" when a ready_check_update
// arrives. Set by the watcher on party.myStreamUrl, cleared by
// onStreamReady when the new stream finishes loading.
const myStreamReloading = ref(false)

const STORAGE_KEY = 'emby-watchparty-username'
const versionInfo = ref({ version: '', codename: '' })

onMounted(async () => {
  socket.connect()
  party.setupListeners()

  try {
    const v = await api.version()
    versionInfo.value = { version: v.current_version || v.version || '', codename: v.codename || '' }
  } catch { /* ignore */ }

  // Defensive: clear any previously-registered handlers for the events
  // PartyView listens to, so HMR reloads and Vue Router remounts cannot
  // stack duplicate listeners. Without this, repeated mounts caused a
  // single 'seek' broadcast to fire its addSystemMessage callback once
  // per stacked listener, flooding the chat with phantom seek messages.
  const partyViewEvents = [
    'chat_message', 'play', 'pause', 'seek', 'force_pause_before_seek',
    'ready_check_update', 'drift_correction', 'all_ready', 'sync_state',
    'error', 'join_rejected', 'join_vote_resolved',
  ]
  for (const e of partyViewEvents) socket.off(e)

  socket.on('chat_message', (data: any) => {
    chatMessages.value.push(data)
    nextTick(() => {
      const el = document.querySelector('.chat-messages')
      if (el) el.scrollTop = el.scrollHeight
    })
  })

  // Playback sync handlers -- matching v1.6.0 deduplication
  let lastSyncedTime = 0
  let lastSyncType = ''

  socket.on('play', (data: any) => {
    lastSyncedTime = data.time
    lastSyncType = 'play'
    // Use nextTick to ensure the videoPlayer ref is bound. When the
    // store's play listener fires first and updates reactive state,
    // Vue may still be mid-render and the template ref is not yet
    // populated. Waiting for nextTick guarantees the ref reflects
    // the current DOM state before we call ve.play().
    nextTick(() => {
      const vp = videoPlayer.value
      if (!vp) return
      vp.isSyncing = true
      const ve = vp.videoEl
      const streamTime = toStreamTime(data.time)
      if (ve) {
        // If the server's time differs from our local position, we need
        // to seek. With HLS.js, just setting ve.currentTime may not
        // refresh the buffer at the new position if HLS.js has been
        // pre-fetching segments around the old position. Use stopLoad
        // + startLoad(new_time) to tell HLS.js to flush and reload at
        // the target position. Without this, setting currentTime can
        // leave the video stalled because HLS.js feeds segments for
        // the old position while the media element waits for frames
        // at the new one.
        if (Math.abs(ve.currentTime - streamTime) > 0.3) {
          const hls = vp.getHls?.()
          if (hls) {
            hls.stopLoad()
            ve.currentTime = streamTime
            hls.startLoad(streamTime)
          } else {
            ve.currentTime = streamTime
          }
        }
        ve.play().catch(() => {
          addSystemMessage('Autoplay blocked by browser - click the video to resume')
        })

        // Stall-recovery: some race conditions leave the video element
        // in a "playing" state (paused=false) but with no actual frame
        // progression. After 1s, verify that currentTime has advanced
        // and if not, nudge HLS.js by re-seeking.
        const checkTime = ve.currentTime
        setTimeout(() => {
          if (!vp || !ve) return
          if (ve.paused) return  // user paused manually, don't touch
          if (ve.currentTime > checkTime + 0.1) return  // playing fine
          // Stalled -- nudge it
          const hls = vp.getHls?.()
          if (hls) {
            hls.stopLoad()
            hls.startLoad(ve.currentTime)
          }
          ve.play().catch(() => {})
        }, 1000)
      }
      setTimeout(() => { if (vp) vp.isSyncing = false }, 500)
    })
    if (data.username) addSystemMessage(`${data.username} resumed playback`)
  })

  socket.on('pause', (data: any) => {
    lastSyncedTime = data.time
    lastSyncType = 'pause'
    const vp = videoPlayer.value
    if (!vp) return
    vp.isSyncing = true
    const ve = vp.videoEl
    const streamTime = toStreamTime(data.time)
    if (ve) {
      ve.pause()
      if (Math.abs(ve.currentTime - streamTime) > 0.3) ve.currentTime = streamTime
    }
    setTimeout(() => { if (vp) vp.isSyncing = false }, 500)
    if (data.username) addSystemMessage(`${data.username} paused playback`)
  })

  socket.on('seek', (data: any) => {
    lastSyncedTime = data.time
    lastSyncType = 'seek'
    const vp = videoPlayer.value
    if (!vp) return
    vp.isSyncing = true
    const ve = vp.videoEl
    // Server sends media time, convert to stream-local time for this user
    const streamTime = toStreamTime(data.time)
    if (ve) {
      // Only re-seek if our position actually differs. The backend
      // broadcasts 'seek' to the whole room without skip_sid in the
      // was_playing branch, so the seeker receives their own seek
      // back. ve.currentTime is already at streamTime in that case;
      // assigning it again can fire a phantom 'seeked' event that
      // queues, runs after isSyncing has been released by
      // resumeAfterReadyCheck, and re-emits a seek -- which the
      // backend then broadcasts back, repeating the cycle every
      // ~500ms. The pause handler above already guards this way.
      if (Math.abs(ve.currentTime - streamTime) > 0.3) {
        ve.currentTime = streamTime
      }
      if (data.playing && data.wait_for_ready) {
        // Wait for buffer, then signal ready -- all_ready will trigger play
        const signalReady = () => {
          if (party.partyId) {
            socket.emit('stream_ready', { party_id: party.partyId })
          }
        }
        // Already buffered (seeker) -- signal immediately
        if (ve.readyState >= 3) {
          signalReady()
        } else {
          ve.addEventListener('canplay', signalReady, { once: true })
        }
      } else if (data.playing) {
        setTimeout(() => {
          ve.play().then(() => {
            if (vp) vp.isSyncing = false
          }).catch(() => {
            if (vp) vp.isSyncing = false
            addSystemMessage('Autoplay blocked by browser - click the video to resume')
          })
        }, 500)
      } else {
        ve.pause()
        setTimeout(() => { if (vp) vp.isSyncing = false }, 300)
      }
    }
    if (data.username) addSystemMessage(`${data.username} seeked to ${formatTime(data.time)}`)
  })

  socket.on('force_pause_before_seek', () => {
    const vp = videoPlayer.value
    if (!vp) return
    isForcePausing = true
    vp.isSyncing = true
    const ve = vp.videoEl
    if (ve) ve.pause()
    // Only reset isForcePausing; let the seek handler own isSyncing
    setTimeout(() => { isForcePausing = false }, 2000)
  })

  // Auto-signal ready during a ready check if our video is already
  // buffered and we're not the user triggering a stream reload. Used
  // for select_video (initial load) -- the target user's VideoPlayer
  // is reloading and will emit `ready` when done, everyone else is
  // already buffered and can signal immediately. change_streams does
  // NOT trigger a ready check anymore (silent swap for the target user),
  // so this only runs on select_video / vote-pass restart flows.
  //
  // Must be one-shot per ready-check cycle: the server broadcasts
  // ready_check_update every time a user signals ready, so without a
  // one-shot guard we re-emit stream_ready on every broadcast and
  // create a spam cascade. The flag is reset when a new ready check
  // starts (detected by readyCheckActive going from false to true).
  let autoReadySignaled = false

  watch(() => party.readyCheckActive, (active) => {
    if (active) {
      autoReadySignaled = false
    }
  })

  socket.on('ready_check_update', () => {
    if (autoReadySignaled) return
    const vp = videoPlayer.value
    if (!vp) return
    const ve = vp.videoEl
    if (!ve) return
    // Target user: stream is currently reloading. Skip -- VideoPlayer
    // will fire `ready` via onStreamReady when the new stream is ready.
    if (myStreamReloading.value) return
    // Non-target user: video already loaded, signal once and mark as done.
    if (ve.readyState >= 3 && party.partyId) {
      autoReadySignaled = true
      socket.emit('stream_ready', { party_id: party.partyId })
    }
  })

  socket.on('drift_correction', (data: any) => {
    const vp = videoPlayer.value
    if (!vp) return
    const ve = vp.videoEl
    if (!ve || !ve.src || ve.readyState < 2) return
    if (vp.isSyncing || isUserSeeking) return

    const drift = Math.abs(ve.currentTime - data.time)
    if (drift < 1.0) return

    vp.isSyncing = true
    ve.currentTime = data.time
    setTimeout(() => { if (vp) vp.isSyncing = false }, 500)
  })

  // Heartbeat
  const heartbeatInterval = setInterval(() => {
    const vp = videoPlayer.value
    const ve = vp?.videoEl
    if (!ve || !ve.src || ve.readyState < 2 || ve.paused || ve.ended) return
    if (vp.isSyncing || isUserSeeking) return
    if (party.partyId) {
      socket.emit('heartbeat', { party_id: party.partyId, time: ve.currentTime })
    }
  }, 5000)

  onUnmounted(() => {
    clearInterval(heartbeatInterval)
  })

  // All users buffered after a seek -- resume playback together
  const resumeAfterReadyCheck = (data?: any) => {
    const vp = videoPlayer.value
    if (!vp) return
    const ve = vp.videoEl
    if (ve && data?.time !== undefined) {
      const streamTime = toStreamTime(data.time)
      if (Math.abs(ve.currentTime - streamTime) > 0.1) {
        ve.currentTime = streamTime
      }
    }
    // Only resume if playback is supposed to be playing (seek ready check)
    // Initial video-selection ready check leaves the video paused at 0
    const shouldPlay = data?.playing !== undefined ? !!data.playing : party.playbackState.playing
    if (ve && shouldPlay) {
      ve.play().then(() => {
        if (vp) vp.isSyncing = false
      }).catch(() => {
        if (vp) vp.isSyncing = false
        addSystemMessage('Autoplay blocked by browser - click the video to resume')
      })
    } else if (vp) {
      vp.isSyncing = false
    }
    isForcePausing = false
  }
  socket.on('all_ready', resumeAfterReadyCheck)

  // Safety net: if the ready check overlay is dismissed by the client
  // timeout (15s) instead of a server all_ready, still resume playback
  watch(() => party.readyCheckActive, (active, wasActive) => {
    if (wasActive && !active) {
      resumeAfterReadyCheck()
    }
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

  // Late-joiner rejection: redirect home with a message
  socket.on('join_rejected', (data: any) => {
    const msg = data?.message || 'The party declined your request to join.'
    alert(msg)
    router.push('/')
  })

  // Vote resolved as fail while we were the late joiner: the store
  // already cleared the pending state; here we just redirect.
  socket.on('join_vote_resolved', (data: any) => {
    // The store's listener runs first and sets pendingVote=null. We
    // only handle the redirect case here (late joiner got rejected).
    if (data.result === 'fail' && !party.partyId) {
      // If the store's leave() already ran, party.partyId is null.
      router.push('/')
    }
  })

  // Auto-join with saved username
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) {
    joinWithName(saved)
  }
})

onUnmounted(() => {
  if (pendingPauseTimer) {
    clearTimeout(pendingPauseTimer)
    pendingPauseTimer = null
  }
  party.leave()
})

// Preload all text subtitles as hidden tracks when the video or media
// source changes, and set the default sub to mode='showing' on initial
// load. The browser's CC button and the dropdown both pick from this
// preloaded set by toggling textTrack.mode -- no network roundtrip per
// switch. We also handle "auto-show default" here (instead of having
// VideoControls emit change-text-subtitle on initial fetch) so there is
// no race between the auto-load API call and the dropdown's initial
// selection -- both used to fire in parallel and the dropdown's path
// would create an ad-hoc <track> labelled "Subtitles" before the
// preloaded set landed, leaving the CC menu with a stray duplicate.
let lastSubtitlePreloadKey: string | null = null
watch(() => party.currentVideo, async (video) => {
  if (!video?.item_id || !video?.media_source_id) return

  // Skip re-fire when neither item_id nor media_source_id changed.
  // A PGS pick triggers change_streams which updates currentVideo by
  // reference but keeps both ids stable, so re-running the preload
  // would needlessly clear the user's currently-showing text sub.
  const key = `${video.item_id}:${video.media_source_id}`
  if (key === lastSubtitlePreloadKey) return
  const isNewItem = !lastSubtitlePreloadKey || lastSubtitlePreloadKey.split(':')[0] !== video.item_id
  lastSubtitlePreloadKey = key

  await nextTick()
  const vp = videoPlayer.value
  const ve = vp?.videoEl
  if (!ve) return

  // Clear any tracks left over from a previous video so the CC menu
  // does not accumulate stale entries.
  ve.querySelectorAll('track').forEach((t) => t.remove())

  try {
    const streams = await api.itemStreams(video.item_id)
    const textSubs = (streams.subtitles || []).filter((s: any) => !s.isPGS && s.isTextSubtitleStream)
    // Only auto-show the default sub when the item actually changed.
    // For media-source switches on the same item (e.g. dual-format
    // releases) keep tracks hidden so we do not override a selection
    // the user already made.
    const defaultSub = isNewItem ? textSubs.find((s: any) => s.isDefault) : null
    textSubs.forEach((sub: any) => {
      const track = document.createElement('track')
      track.kind = 'subtitles'
      let label = sub.displayLanguage || sub.language || 'Unknown'
      if (sub.title) label += ` (${sub.title})`
      if (sub.isForced) label += ' [Forced]'
      if (sub.isExternal) label += ' [External]'
      track.label = label
      track.srclang = sub.language || 'und'
      track.src = `/api/subtitles/${video.item_id}/${video.media_source_id}/${sub.index}`
      const isDefault = defaultSub && sub.index === defaultSub.index
      ;(track as any).mode = isDefault ? 'showing' : 'hidden'
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
let isUserSeeking: boolean = false
let hasStarted = false
let isInitialSync = false

// Throttling -- matching v1.6.0
let lastPlayBroadcast = 0
let lastPauseBroadcast = 0
const PLAY_PAUSE_THROTTLE = 300
let seekSettleTimer: ReturnType<typeof setTimeout> | null = null

// Emby's HLS playlists already report segment times relative to the
// full movie (even when StartTimeTicks is set, the playlist uses the
// original segment numbering where segment N = N * segment_duration
// seconds into the media). HLS.js's video.currentTime therefore IS
// the media time, and we don't need any offset translation.
function toMediaTime(streamTime: number): number {
  return streamTime
}

function toStreamTime(mediaTime: number): number {
  return mediaTime
}

function onVideoPlay() {
  if (!party.partyId || isForcePausing || isInitialSync) return
  if (pendingPauseTimer) {
    clearTimeout(pendingPauseTimer)
    pendingPauseTimer = null
  }
  const ve = videoPlayer.value?.videoEl
  if (!ve || ve.ended) return
  if (videoPlayer.value?.isSyncing || isUserSeeking) return

  const now = Date.now()
  if (now - lastPlayBroadcast < PLAY_PAUSE_THROTTLE) return
  lastPlayBroadcast = now

  wasPlayingBeforeSeek = true
  socket.emit('play', { party_id: party.partyId, time: toMediaTime(ve.currentTime) })
  if (!hasStarted) {
    addSystemMessage(`${party.username || 'You'} started playback`)
    hasStarted = true
  } else {
    addSystemMessage(`${party.username || 'You'} resumed playback`)
  }
}

function onVideoPause() {
  if (!party.partyId || isForcePausing || isUserSeeking || isInitialSync) return
  const ve = videoPlayer.value?.videoEl
  if (!ve || ve.ended) return
  if (videoPlayer.value?.isSyncing) return

  if (pendingPauseTimer) clearTimeout(pendingPauseTimer)
  pendingPauseTimer = setTimeout(() => {
    pendingPauseTimer = null
    if (!party.partyId || isForcePausing || isUserSeeking || isInitialSync) return
    if (videoPlayer.value?.isSyncing) return
    const currentVideoEl = videoPlayer.value?.videoEl
    if (!currentVideoEl || currentVideoEl.ended || !currentVideoEl.paused) return

    const now = Date.now()
    if (now - lastPauseBroadcast < PLAY_PAUSE_THROTTLE) return
    lastPauseBroadcast = now

    wasPlayingBeforeSeek = false
    socket.emit('pause', { party_id: party.partyId, time: toMediaTime(currentVideoEl.currentTime) })
    addSystemMessage(`${party.username || 'You'} paused playback`)
  }, 250)
}

function onVideoSeeking() {
  if (pendingPauseTimer) {
    clearTimeout(pendingPauseTimer)
    pendingPauseTimer = null
  }
  wasPlayingBeforeSeek = wasPlayingBeforeSeek || party.playbackState.playing
  isUserSeeking = true
}

function onVideoSeeked(time: number) {
  if (!party.partyId || isInitialSync) return
  if (videoPlayer.value?.isSyncing) return

  // Phantom-seek guard: HLS.js fires 'seeked' events during initial
  // buffer alignment and segment transitions that look identical to
  // user seeks at the DOM level. If the seek target is within ~2s of
  // where natural playback would have advanced to from the last
  // timeupdate, this is almost certainly a phantom event. Real user
  // seeks are normally many seconds away from the previous position
  // (drag the timeline); intra-second adjustments aren't worth
  // broadcasting and are usually corrections HLS.js is making to its
  // own buffer.
  if (lastNaturalAt > 0) {
    const elapsed = (Date.now() - lastNaturalAt) / 1000
    const expected = lastNaturalTime + elapsed
    if (Math.abs(time - expected) < 2.0) {
      return
    }
  }

  // Seek settle timer -- wait 500ms for rapid seeks to settle
  if (seekSettleTimer) clearTimeout(seekSettleTimer)
  seekSettleTimer = setTimeout(() => {
    isUserSeeking = false
    seekSettleTimer = null
    const ve = videoPlayer.value?.videoEl
    if (!ve) return

    const mediaTime = toMediaTime(ve.currentTime)
    socket.emit('seek', {
      party_id: party.partyId,
      time: mediaTime,
      was_playing: wasPlayingBeforeSeek,
    })
    addSystemMessage(`${party.username || 'You'} seeked to ${formatTime(mediaTime)}`)
  }, 500)
}

let lastProgressReport = 0
const PROGRESS_INTERVAL = 10000 // 10 seconds

// Track natural playback progression so onVideoSeeked can distinguish
// real user-initiated seeks from phantom 'seeked' events fired by
// HLS.js during buffer alignment / initial decode.
let lastNaturalTime = 0
let lastNaturalAt = 0

function onVideoTimeUpdate(time: number) {
  // HLS.js reports currentTime as the media position directly, even
  // for late-joiner streams with StartTimeTicks offsets.
  //
  // Throttle updates to the reactive ref to once per second. HLS.js
  // emits `timeupdate` ~4-5 times per second, which causes downstream
  // components (VideoControls with its computed showIntroButton) to
  // re-render that often and made the quality/subtitle dropdowns
  // flicker on some videos. We only need sub-second precision for
  // the intro skip button, and the chat/debug UI does not care.
  if (Math.abs(time - currentTime.value) >= 1) {
    currentTime.value = time
  }
  // Always update the natural-progression tracker. We need this on
  // every timeupdate (not just throttled ones) so phantom seek
  // detection has a fresh reference point.
  lastNaturalTime = time
  lastNaturalAt = Date.now()
  if (!party.partyId || isInitialSync) return
  const ve = videoPlayer.value?.videoEl
  if (!ve || !ve.src || ve.readyState < 2 || ve.paused) return
  const now = Date.now()
  if (now - lastProgressReport >= PROGRESS_INTERVAL) {
    lastProgressReport = now
    socket.emit('report_progress', { party_id: party.partyId, time: toMediaTime(time) })
  }
}

function onStreamReady() {
  if (!party.partyId) return
  // Our stream finished (re)loading -- clear the reloading flag so
  // future ready_check_update events know we are buffered.
  myStreamReloading.value = false
  socket.emit('stream_ready', { party_id: party.partyId })
}

// Whenever myStreamUrl changes (initial load OR a change_streams reload),
// mark our stream as reloading until onStreamReady fires. This is what
// the ready_check_update listener uses to decide whether to auto-signal.
watch(() => party.myStreamUrl, (newUrl, oldUrl) => {
  if (newUrl && newUrl !== oldUrl) {
    myStreamReloading.value = true
  }
})

function stopVideo() {
  if (!party.partyId) return
  socket.emit('stop_video', { party_id: party.partyId })
}

// When the current video clears (anyone clicked Stop Video), pop the
// library open automatically so the next selection is one click away
// instead of two ("Browse Library" -> pick item).
watch(() => party.currentVideo, (newVal, oldVal) => {
  if (oldVal && !newVal) {
    showLibrary.value = true
  }
})

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

  // "None" selected -- disable every track but leave the preloaded set in
  // place so the CC button can still switch back later without a refetch.
  if (payload.index === -1 || !payload.url) {
    for (let i = 0; i < ve.textTracks.length; i += 1) {
      const tt = ve.textTracks[i]
      if (tt) tt.mode = 'disabled'
    }
    return
  }

  // Find the preloaded <track> whose src matches the requested url. The
  // src attribute resolves to an absolute URL but endsWith on the relative
  // path still matches because the suffix is identical.
  const tracks = Array.from(ve.querySelectorAll('track'))
  const target = tracks.find((t) => t.src.endsWith(payload.url!))

  if (target) {
    // Already preloaded -- just flip modes. This is identical to what the
    // browser's CC button does, so the dropdown and CC stay in sync.
    for (let i = 0; i < ve.textTracks.length; i += 1) {
      const tt = ve.textTracks[i]
      if (tt) tt.mode = tt === target.track ? 'showing' : 'disabled'
    }
    return
  }

  // Fallback for ad-hoc subtitles not in the preload set (rare -- the
  // dropdown filter and the auto-load filter use the same criteria).
  const track = document.createElement('track')
  track.kind = 'subtitles'
  track.label = 'Subtitles'
  track.srclang = 'und'
  track.src = payload.url
  track.default = true

  const showTrack = () => {
    for (let i = 0; i < ve.textTracks.length; i += 1) {
      const tt = ve.textTracks[i]
      if (tt) tt.mode = tt === track.track ? 'showing' : 'disabled'
    }
  }

  track.addEventListener('load', showTrack, { once: true })
  ve.appendChild(track)
  showTrack()
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
        <button @click="showMobileChat = true" class="btn btn-small mobile-chat-toggle">Chat</button>
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
          <div v-if="party.readyCheckActive" class="ready-check-overlay">
            <div class="ready-check-box">
              <span class="spinner" />
              <p>Waiting for everyone to load...</p>
              <ul>
                <li v-for="u in party.waitingUsers" :key="u" class="waiting">{{ u }}</li>
                <li v-for="u in party.readyUsers" :key="u" class="ready">{{ u }}</li>
              </ul>
            </div>
          </div>
          <VideoPlayer
            ref="videoPlayer"
            :stream-url="party.myStreamUrl || ''"
            :title="party.currentVideo.title"
            :playing="party.playbackState.playing"
            :stream-offset="party.streamOffset"
            @play="onVideoPlay"
            @pause="onVideoPause"
            @seeking="onVideoSeeking"
            @seeked="onVideoSeeked"
            @timeupdate="onVideoTimeUpdate"
            @ended="() => {}"
            @ready="onStreamReady"
          />
          <VideoControls
            :party-id="party.partyId!"
            :item-id="party.currentVideo.item_id"
            :stream-url="party.myStreamUrl || ''"
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
      <aside class="chat-panel" :class="{ 'chat-mobile-open': showMobileChat }">
        <div class="chat-header" @click="showParticipants = !showParticipants">
          <h3>Chat</h3>
          <div class="chat-header-actions">
            <span class="participant-toggle" :title="showParticipants ? 'Hide participants' : 'Show participants'">
              <span class="participant-count-badge">{{ party.userCount }}</span>
              <span class="participant-arrow" :class="{ open: showParticipants }">&#9662;</span>
            </span>
            <button class="chat-close-btn" @click.stop="showMobileChat = false" title="Close chat">Close</button>
          </div>
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
      <button
        v-if="showMobileChat"
        class="chat-backdrop"
        aria-label="Close chat"
        @click="showMobileChat = false"
      />
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

  <!-- Late-joiner vote modal (existing users) -->
  <JoinVoteModal />

  <!-- Late-joiner waiting room (the joiner themselves) -->
  <JoinWaitingRoom />
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

.mobile-chat-toggle {
  display: none;
}

.party-content {
  display: flex;
  flex: 1;
  overflow: hidden;
  position: relative;
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
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.ready-check-overlay {
  position: absolute;
  inset: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.7);
}

.ready-check-box {
  text-align: center;
  color: #fff;
  padding: var(--space-lg);
}

.ready-check-box .spinner {
  display: inline-block;
  width: 32px;
  height: 32px;
  border: 3px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: var(--space-sm);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.ready-check-box ul {
  list-style: none;
  padding: 0;
  margin-top: var(--space-sm);
}

.ready-check-box li.ready { color: var(--success, #4caf50); }
.ready-check-box li.waiting { color: var(--text-muted, #999); }

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

.chat-header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
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

.chat-close-btn {
  display: none;
  background: var(--bg-surface);
  color: var(--text-secondary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  padding: 0.2rem 0.5rem;
  font-size: 0.75rem;
  cursor: pointer;
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

.chat-backdrop {
  display: none;
}

@media (max-width: 760px) {
  .party-header {
    align-items: flex-start;
    gap: var(--space-sm);
  }

  .header-center {
    display: none;
  }

  .header-left,
  .header-actions {
    flex-wrap: wrap;
    gap: var(--space-sm);
  }

  .mobile-chat-toggle {
    display: inline-flex;
  }

  .party-content {
    overflow: hidden;
  }

  .library-panel {
    width: 100%;
    min-width: 0;
  }

  .chat-panel {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(92vw, 360px);
    max-width: 100vw;
    z-index: 1001;
    transform: translateX(100%);
    transition: transform var(--transition-fast);
    box-shadow: var(--shadow-lg);
  }

  .chat-panel.chat-mobile-open {
    transform: translateX(0);
  }

  .chat-close-btn {
    display: inline-flex;
  }

  .chat-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 1000;
    background: rgba(0, 0, 0, 0.45);
    border: 0;
    padding: 0;
    cursor: pointer;
  }
}
</style>
