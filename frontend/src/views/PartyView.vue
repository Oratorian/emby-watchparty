<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSocketStore } from '@/stores/socket'
import { usePartyStore, getClientId } from '@/stores/party'
import VideoPlayer from '@/components/VideoPlayer.vue'
import VideoControls from '@/components/VideoControls.vue'

// Async-loaded so they don't ship in the initial PartyView bundle.
// LibraryBrowser pulls in the full library tree + thumbnail helpers,
// EmojiPicker has its emoji table inline, and the modals are only
// opened on demand. hls.js is also large but lives inside VideoPlayer,
// which we deliberately keep sync so the video can start as soon as
// the route is mounted.
const LibraryBrowser = defineAsyncComponent(
  () => import('@/components/LibraryBrowser.vue'),
)
const EmojiPicker = defineAsyncComponent(
  () => import('@/components/EmojiPicker.vue'),
)
const JoinVoteModal = defineAsyncComponent(
  () => import('@/components/JoinVoteModal.vue'),
)
const JoinWaitingRoom = defineAsyncComponent(
  () => import('@/components/JoinWaitingRoom.vue'),
)
const EmbyLoginModal = defineAsyncComponent(
  () => import('@/components/EmbyLoginModal.vue'),
)
const AvatarSetupModal = defineAsyncComponent(
  () => import('@/components/AvatarSetupModal.vue'),
)
const VersionPickerModal = defineAsyncComponent(
  () => import('@/components/VersionPickerModal.vue'),
)
const AutoAdvanceModal = defineAsyncComponent(
  () => import('@/components/AutoAdvanceModal.vue'),
)
const ResumePromptModal = defineAsyncComponent(
  () => import('@/components/ResumePromptModal.vue'),
)
const AdminPanel = defineAsyncComponent(
  () => import('@/components/AdminPanel.vue'),
)
import { api } from '@/api/client'
import type { LibraryItem } from '@/api/client'
import type { ServerToClientPayloads } from '@/types/socket.generated'
import { withPrefix } from '@/utils/appPrefix'
import { avatarUrl as fallbackAvatarUrl } from '@/utils/avatar'
import { copyToClipboard } from '@/utils/clipboard'
import { useAuthStore } from '@/stores/auth'
import { useAvatarStore } from '@/stores/avatar'
import { usePartyChat } from '@/composables/usePartyChat'
// Brand mark asset. Vite resolves this to a hashed URL at build time
// (and inlines small assets), so the WebP ships with cache-busting and
// no runtime path drift. Sits on top of the cyan->magenta gradient
// tile in `.brand-mark` -- the tile colour identity comes from CSS,
// the silhouette comes from this file.
import brandMarkUrl from '@/assets/brand-mark.webp'

const route = useRoute()
const router = useRouter()
const socket = useSocketStore()
const party = usePartyStore()
const auth = useAuthStore()
const avatar = useAvatarStore()
const {
  messages: chatMessages,
  input: chatInput,
  showParticipants,
  showMobileChat,
  attach: attachChat,
  dispose: disposeChat,
  send: sendChat,
  insertEmoji,
  addSystemMessage,
} = usePartyChat(socket, party)

const showBecomeHostModal = ref(false)
const becomeHostBusy = ref(false)
const becomeHostError = ref<string | null>(null)
const showAvatarModal = ref(false)

/**
 * Resolve a member's avatar image source.
 *
 * Order of precedence:
 * 1. The member has a stored avatar (uploaded or gravatar) -> /api/avatar/{uuid}
 * 2. The member is the current host of this party AND no stored avatar -> /api/avatar/host/{party_id}
 * 3. Generated monsterid keyed off display name (legacy default).
 */
function avatarSrc(name: string): string {
  const uuid = party.members[name]
  if (uuid) return api.avatarSrc(uuid)
  if (auth.hostUsername && name === auth.hostUsername && party.partyId) {
    return api.hostAvatarSrc(party.partyId)
  }
  return fallbackAvatarUrl(name)
}

/**
 * Pick the avatar URL for a chat message bubble. Prefers the
 * `avatar_uuid` snapshot the server attached at emit time so a sender
 * who has since left the party still renders with their chosen
 * avatar.
 */
function chatAvatarSrc(msg: { username: string; avatar_uuid?: string | null }): string {
  if (msg.avatar_uuid) return api.avatarSrc(msg.avatar_uuid)
  return avatarSrc(msg.username)
}

const STORAGE_KEY = 'emby-watchparty-username'
const usernameInput = ref('')
const joined = ref(false)
// We only need the username modal when we have nothing to auto-join with.
// Without this flag, the modal flashes on every mount before the socket
// confirms the auto-join, even when localStorage has a saved name.
const awaitingAutoJoin = ref(!!localStorage.getItem(STORAGE_KEY))
const showLibrary = ref(false)
const copyLabel = ref('Copy')
const showVersionModal = ref(false)
const showAdminModal = ref(false)
const adminTriggerBtn = ref<HTMLButtonElement | null>(null)
const adminModalShellRef = ref<HTMLElement | null>(null)
const videoPlayer = ref<InstanceType<typeof VideoPlayer> | null>(null)
const currentTime = ref(0)
let pendingPauseTimer: ReturnType<typeof setTimeout> | null = null
let heartbeatInterval: ReturnType<typeof setInterval> | null = null

// True while my own HLS stream is reloading (after change_streams). Used
// to distinguish "I am the user whose stream changed" from "I am an
// observer whose stream is already buffered" when a ready_check_update
// arrives. Set by the watcher on party.myStreamUrl, cleared by
// onStreamReady when the new stream finishes loading.
const myStreamReloading = ref(false)

const versionInfo = ref({ version: '', codename: '' })

function onAdminEscKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && showAdminModal.value) {
    showAdminModal.value = false
  }
}

// Document-level ESC listener works even when focus is inside admin
// inputs. Focus moves into the modal shell on open and back to the
// gear trigger on close.
watch(showAdminModal, (open, prev) => {
  if (open) {
    document.addEventListener('keydown', onAdminEscKey)
    nextTick(() => {
      adminModalShellRef.value?.focus()
    })
  } else {
    document.removeEventListener('keydown', onAdminEscKey)
    if (prev) {
      nextTick(() => {
        adminTriggerBtn.value?.focus()
      })
    }
  }
})

// Auto-close the admin modal when a vote or ready check arrives, so
// the admin doesn't miss party-blocking prompts stacked underneath.
watch(() => party.pendingVote, (v) => {
  if (v && showAdminModal.value) showAdminModal.value = false
})
watch(() => party.readyCheckActive, (active) => {
  if (active && showAdminModal.value) showAdminModal.value = false
})

onMounted(async () => {
  socket.connect()
  party.setupListeners()
  auth.attachSocketListeners()

  try {
    await auth.refresh()
  } catch { /* ignore */ }

  try {
    const v = await api.version()
    versionInfo.value = { version: v.current_version || v.version || '', codename: v.codename || '' }
  } catch { /* ignore */ }

  // Defensive: clear any previously-registered handlers for the events
  // PartyView listens to, so HMR reloads and Vue Router remounts cannot
  // stack duplicate listeners. Without this, repeated mounts caused a
  // single 'seek' broadcast to fire its addSystemMessage callback once
  // per stacked listener, flooding the chat with phantom seek messages.
  // NOTE: do NOT include 'sync_state' or 'join_vote_resolved' here. The
  // party store owns both. sync_state populates currentVideo; off()ing it
  // would strip the store handler and late joiners never receive the video.
  // join_vote_resolved is the listener that clears pendingVote (dismisses
  // the vote modal) -- our handler below only adds the late-joiner redirect
  // and explicitly relies on the store's handler running. off()ing it here
  // removed the store's dismissal, so a passed vote left the modal open
  // forever. The two listeners coexist safely on the same socket; the store
  // re-offs these on every setupListeners() call, so they do not stack.
  const partyViewEvents = [
    'play', 'pause', 'seek', 'force_pause_before_seek',
    'ready_check_update', 'drift_correction', 'all_ready',
    'error', 'join_rejected', 'toggle_library',
  ] as const
  for (const e of partyViewEvents) socket.off(e)

  attachChat()

  // Playback sync handlers -- matching v1.6.0 deduplication
  socket.on('play', (data: ServerToClientPayloads['play']) => {
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
          // Stalled -- nudge it. CRITICAL: this fires at 1000ms, but the
          // isSyncing set above was already released at 500ms, so the
          // stopLoad()/startLoad() re-seek here dispatches a native
          // `seeking` event that VideoPlayer would forward as a user
          // seek -> onVideoSeeked broadcasts 'seek' -> the server's
          // "seek during playback" path force-pauses the WHOLE room.
          // That is the "pauses right after play" loop. Re-assert
          // isSyncing around the nudge so VideoPlayer swallows the
          // synthetic seeking/seeked events (its onSeeking/onSeeked only
          // emit when isSyncing is false).
          vp.isSyncing = true
          const hls = vp.getHls?.()
          if (hls) {
            hls.stopLoad()
            hls.startLoad(ve.currentTime)
          }
          ve.play().catch(() => {})
          setTimeout(() => { if (vp) vp.isSyncing = false }, 500)
        }, 1000)
      }
      setTimeout(() => { if (vp) vp.isSyncing = false }, 500)
    })
    if (data.username) {
      // Each client tracks its own hasStarted, reset on every new
      // video selection. The first play we witness for this video
      // is "started"; subsequent plays are "resumed". Consistent
      // across all clients without server-side state because the
      // broadcast lands in roughly the same order everywhere.
      if (!hasStarted) {
        addSystemMessage(`${data.username} started playback`)
        hasStarted = true
      } else {
        addSystemMessage(`${data.username} resumed playback`)
      }
    }
  })

  socket.on('pause', (data: ServerToClientPayloads['pause']) => {
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

  socket.on('seek', (data: ServerToClientPayloads['seek']) => {
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

  socket.on('drift_correction', (data: ServerToClientPayloads['drift_correction']) => {
    const vp = videoPlayer.value
    if (!vp) return
    const ve = vp.videoEl
    if (!ve || !ve.src || ve.readyState < 2) return
    if (vp.isSyncing || isUserSeeking) return

    const drift = Math.abs(ve.currentTime - data.time)
    if (drift < 1.0) return

    vp.isSyncing = true
    ve.currentTime = data.time
    // If the party is playing but our element is paused (e.g. a pause
    // emit was lost, or the browser paused us on tab-suspend), resume
    // together with the time correction. Wrapped in isSyncing so the
    // resulting native play event is swallowed and not re-broadcast.
    if (party.playbackState.playing && ve.paused && !ve.ended) {
      ve.play().catch(() => {})
    }
    setTimeout(() => { if (vp) vp.isSyncing = false }, 500)
  })

  // Heartbeat + local resync safety net. The party clock is
  // democratic: anyone can play/pause/seek and it broadcasts to all.
  // But a broadcast can still be missed (dropped emit, tab suspended,
  // OS media key that pauses the element without our handler firing),
  // leaving this client's <video> out of step with playbackState. The
  // props.playing watcher only fires on CHANGE, so a "party keeps
  // playing while we sit locally paused" state is never corrected by
  // it. This tick re-asserts the authoritative play/pause state each
  // interval, wrapped in isSyncing so the corrective play()/pause()
  // never re-emits and flaps.
  heartbeatInterval = setInterval(() => {
    const vp = videoPlayer.value
    const ve = vp?.videoEl
    if (!ve || !ve.src || ve.readyState < 2 || ve.ended) return
    if (vp.isSyncing || isUserSeeking || party.readyCheckActive) return
    // Do NOT correct while a local play/pause is still propagating: a
    // legitimate user pause debounces for 250ms in onVideoPause before
    // it emits, and playbackState.playing only flips once the server
    // broadcast lands (~another round-trip). During that window
    // playbackState.playing is STALE, so force-resuming here would undo
    // the user's own pause. pendingPauseTimer!=null means a pause is in
    // flight; skip this tick and let the broadcast settle the state.
    if (pendingPauseTimer) return

    // Re-assert playback ONLY in the one safe direction: the party is
    // playing but our element is paused (a dropped pause->play, a
    // tab-suspend, a stall the browser paused on). Force-resume, wrapped
    // in isSyncing so the resulting native play event is not re-emitted.
    //
    // We deliberately do NOT force-PAUSE in the other direction here.
    // Right after a local play there is a sub-second window where our
    // <video> is playing but playbackState.playing has not yet flipped
    // to true (the play broadcast is still in flight); a force-pause on
    // that stale state would fight the user's own play. Democratic
    // control means a real pause propagates on its own, so a "party
    // paused, we are playing" desync self-corrects via the pause
    // broadcast without needing a local force here.
    const shouldPlay = party.playbackState.playing
    if (shouldPlay && ve.paused) {
      vp.isSyncing = true
      ve.play().catch(() => {}).finally(() => {
        setTimeout(() => { if (vp) vp.isSyncing = false }, 300)
      })
      return
    }

    // In sync and playing -> report position for drift correction.
    if (!ve.paused && party.partyId) {
      socket.emit('heartbeat', { party_id: party.partyId, time: ve.currentTime })
    }
  }, 5000)

  // All users buffered after a seek -- resume playback together
  const resumeAfterReadyCheck = (data?: ServerToClientPayloads['all_ready']) => {
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
  socket.on('sync_state', (data: ServerToClientPayloads['sync_state']) => {
    if (data.current_video) {
      isInitialSync = true
      setTimeout(() => {
        isInitialSync = false
      }, 3000)
    }
  })

  // Error handler -- redirect on invalid party
  socket.on('error', (data: ServerToClientPayloads['error']) => {
    const msg = data?.message || 'Unknown error'
    if (msg.includes('not found')) {
      alert(`Party not found: ${route.params.id}`)
      router.push('/')
      return
    }
    // An error during auto-join means we should fall back to the manual
    // name prompt; otherwise the spinner sits forever.
    awaitingAutoJoin.value = false
    addSystemMessage(`Error: ${msg}`)
  })

  // Binge-watching: end of season. Backend sent this after video_ended
  // for an episode that has no next episode in its season. Open the
  // library so the host can pick another season/series; everyone else
  // gets the system message so they understand why the player went
  // back to the lobby state.
  socket.on('binge_finished', () => {
    addSystemMessage('Season finished -- pick another from the library.')
    if (auth.isHost) showLibrary.value = true
  })

  // Cancel announcements -- the modal closes itself off the store
  // state, but a system message keeps the chat history coherent.
  socket.on('auto_advance_cancelled', (data: ServerToClientPayloads['auto_advance_cancelled']) => {
    const by = data?.by_username
    if (by) {
      addSystemMessage(`${by} cancelled auto-advance`)
    }
  })

  // Late-joiner rejection: redirect home with a message
  socket.on('join_rejected', (data: ServerToClientPayloads['join_rejected']) => {
    const msg = data?.message || 'The party declined your request to join.'
    alert(msg)
    router.push('/')
  })

  // Party was dissolved server-side (e.g. an admin disabled static
  // sessions while we were inside one). Clean up and redirect home.
  socket.on('party_dissolved', async () => {
    alert('This party has been closed by an administrator.')
    await party.leave()
    router.push('/')
  })

  // Host toggled the shared library panel. The server broadcasts
  // toggle_library to the whole room (host-only on the emit side) so
  // every client's panel follows the host's Hide/Show button. The Vue
  // rewrite dropped this listener while keeping the server broadcast,
  // so the host's button silently did nothing for other clients --
  // this restores the v1.x behaviour. Idempotent for the host: their
  // local toggleLibrary() already set showLibrary, and re-applying the
  // same boolean here is a no-op.
  socket.on('toggle_library', (data: ServerToClientPayloads['toggle_library']) => {
    showLibrary.value = !!data.show
  })

  // Vote resolved as fail while we were the late joiner: the store
  // already cleared the pending state; here we just redirect.
  socket.on('join_vote_resolved', (data: ServerToClientPayloads['join_vote_resolved']) => {
    // The store's listener runs first and sets pendingVote=null. We
    // only handle the redirect case here (late joiner got rejected).
    if (data.result === 'fail' && !party.partyId) {
      // If the store's leave() already ran, party.partyId is null.
      router.push('/')
    }
  })

  // Resolve any persisted avatar uuid BEFORE registering the watcher
  // below. Without this, the IndexedDB-driven null -> uuid transition
  // would be the first watcher firing, and we'd have to gate it --
  // which previously caused first-time recover/upload events to never
  // broadcast (the user's first ever uuid change got eaten by the
  // "skip the initial load" guard).
  try { await avatar.load() } catch { /* ignore */ }

  // Now any change is a real user action (upload, gravatar, recover).
  // Tell the room so everyone re-renders without a page refresh.
  watch(() => avatar.uuid, (newUuid) => {
    if (!party.partyId) return
    socket.emit('update_avatar', {
      party_id: party.partyId!,
      avatar_uuid: newUuid,
    })
  })

  // Auto-join with saved username
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) {
    joinWithName(saved)
  }
})

onUnmounted(() => {
  disposeChat()
  if (heartbeatInterval) {
    clearInterval(heartbeatInterval)
    heartbeatInterval = null
  }
  if (pendingPauseTimer) {
    clearTimeout(pendingPauseTimer)
    pendingPauseTimer = null
  }
  document.removeEventListener('keydown', onAdminEscKey)
  // Do NOT call party.leave() here. PartyView unmounts on every
  // navigation (e.g. clicking the Admin or Version links), and a full
  // leave would emit leave_party to the backend AND clear the session
  // cookie -- both of which kick the user out of the party for what is
  // really just a temporary view change. They should remain a party
  // member until they explicitly click "Leave" or the party is
  // dissolved server-side. Tab close / browser exit is handled by the
  // socket disconnect handler on the backend, which cleans up sids
  // naturally.
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
// User's currently-selected text subtitle index. Survives stream
// reattach (quality change) so the watcher below can re-apply
// mode='showing' to the matching <track> after HLS resets the media
// element. Updated when the user picks from the dropdown or when the
// auto-show default sub fires on a new item. null = None or PGS.
const selectedTextSubIndex = ref<number | null>(null)

// We trigger on (item_id, media_source_id, myStreamUrl) because Emby
// keeps media_source_id stable across transcode sessions for the same
// item -- a quality change only mints a new stream URL. Without
// myStreamUrl in the key, the watcher would early-out on quality change
// and HLS reattach would reset every textTrack.mode to 'disabled' (the
// element default), which unloads the cues. Toggling back to 'showing'
// after that doesn't reliably reload the cues in Chromium (see the
// comment in onChangeTextSubtitle below), so we MUST rebuild the
// <track> elements when the stream changes.
let lastSubtitlePreloadKey: string | null = null
watch(
  () => {
    const v = party.currentVideo
    return [v?.item_id, v?.media_source_id, party.myStreamUrl] as const
  },
  async ([itemId, mediaSourceId, streamUrl]) => {
    if (!itemId || !mediaSourceId || !streamUrl) return

    const key = `${itemId}:${mediaSourceId}:${streamUrl}`
    if (key === lastSubtitlePreloadKey) return
    const prevItemId = lastSubtitlePreloadKey ? lastSubtitlePreloadKey.split(':')[0] : null
    const isNewItem = prevItemId !== itemId
    lastSubtitlePreloadKey = key

    if (isNewItem) {
      // Fresh item -- drop any sticky selection from the previous one.
      // The default sub (resolved below) will reseed this ref.
      selectedTextSubIndex.value = null
    }

    await nextTick()
    const vp = videoPlayer.value
    const ve = vp?.videoEl
    if (!ve) return

    // Clear any tracks left over from a previous video so the CC menu
    // does not accumulate stale entries. We rebuild on every stream
    // change (not just media-source change) because HLS reattach
    // unloads cues for any track left at mode='disabled', and we can't
    // recover those without creating fresh <track> elements.
    ve.querySelectorAll('track').forEach((t) => t.remove())

    try {
      const streams = await api.itemStreams(itemId)
      const textSubs = (streams.subtitles || []).filter(
        (stream) => !stream.isPGS && stream.isTextSubtitleStream,
      )
      // Fresh item: auto-show the default text sub AND remember it as
      // the active selection so a later quality switch restores it.
      // Same item: keep whatever the user picked last.
      if (isNewItem) {
        const defaultSub = textSubs.find((stream) => stream.isDefault)
        if (defaultSub) selectedTextSubIndex.value = defaultSub.index
      }
      const targetIndex = selectedTextSubIndex.value

      textSubs.forEach((sub) => {
        const track = document.createElement('track')
        track.kind = 'subtitles'
        let label = sub.displayLanguage || sub.language || 'Unknown'
        if (sub.title) label += ` (${sub.title})`
        if (sub.isForced) label += ' [Forced]'
        if (sub.isExternal) label += ' [External]'
        track.label = label
        track.srclang = sub.language || 'und'
        track.src = withPrefix(`/api/subtitles/${itemId}/${mediaSourceId}/${sub.index}`)
        ve.appendChild(track)
        // The mode lives on the TextTrack interface (track.track.mode),
        // not on the HTMLTrackElement itself. track.track is null until
        // the element is attached to a <video>, so this must come after
        // appendChild.
        const targetMode: TextTrackMode =
          targetIndex !== null && sub.index === targetIndex ? 'showing' : 'hidden'
        if (track.track) {
          track.track.mode = targetMode
        }
      })

      // Belt-and-suspenders: VideoPlayer's streamUrl watcher runs in
      // parallel with this one. attachStream() calls hls.attachMedia
      // which sets media.src to an MSE blob URL -- that implicit
      // media.load() resets every textTrack.mode we just set back to
      // 'disabled'. Re-apply once the media has settled.
      if (targetIndex !== null) {
        const reapply = () => {
          for (const tEl of Array.from(ve.querySelectorAll('track'))) {
            if (!tEl.track) continue
            const m = tEl.src.match(/\/api\/subtitles\/[^/]+\/[^/]+\/(\d+)/)
            const idx = m && m[1] ? parseInt(m[1], 10) : null
            tEl.track.mode = idx === targetIndex ? 'showing' : 'hidden'
          }
        }
        ve.addEventListener('loadeddata', reapply, { once: true })
      }
    } catch {
      /* ignore */
    }
  },
)

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
    awaitingAutoJoin.value = false
  }
}, { deep: true })

function submitJoin() {
  joinWithName(usernameInput.value.trim())
}

async function copyPartyId() {
  const id = (route.params.id as string) || ''
  const ok = await copyToClipboard(id)
  copyLabel.value = ok ? 'Copied!' : 'Failed'
  setTimeout(() => { copyLabel.value = 'Copy' }, 2000)
}

async function leaveParty() {
  // Await so the session-clear request lands before any subsequent
  // navigation to /admin or /version reads /api/auth/status.
  await party.leave()
  router.push('/')
}

// Modal state for the multi-version picker (issue #43). When the
// library item the host clicked has more than one Emby alternate
// source, we open the modal and stall the select_video emit until
// the host picks. `pendingSelection` holds the original item so we
// can finish the emit once the modal resolves.
interface PendingVersionPick {
  item: LibraryItem
  startSeconds: number
  versions: Array<{
    id: string
    name: string
    container: string | null
    run_time_ticks: number | null
  }>
}
const versionPickerState = ref<PendingVersionPick | null>(null)

// Resume prompt state. Populated when the host clicks a library item
// that has UserData.PlaybackPositionTicks > 0 and Played === false.
// User picks Resume (start_seconds = position) or Start over
// (start_seconds = 0); either way we then fall through to the
// multi-version picker (or directly to the emit if there's only one).
const resumePromptState = ref<{
  item: LibraryItem
  resumeSeconds: number
  runTimeSeconds: number | null
} | null>(null)

function emitSelectVideo(item: LibraryItem, mediaSourceId?: string, startSeconds = 0) {
  if (!party.partyId) return
  hasStarted = false
  socket.emit('select_video', {
    party_id: party.partyId,
    item_id: item.Id,
    item_name: item.Name,
    item_overview: item.Overview || '',
    quality: '1080p-high',
    media_source_id: mediaSourceId,
    start_seconds: startSeconds,
  })
  showLibrary.value = false
}

// Continues the select flow after the resume prompt has been answered.
// Same body as the second half of selectVideo: probe for alternate
// versions, route through the version picker if needed, otherwise
// emit directly.
async function continueSelectAfterResume(item: LibraryItem, startSeconds: number) {
  let versions: PendingVersionPick['versions'] = []
  try {
    const streams = await api.itemStreams(item.Id)
    versions = streams.versions || []
  } catch {
    // If the lookup fails fall through to the legacy path -- backend
    // will pick Emby's default source on its own. Better to play
    // something than to block the host on a transient probe error.
  }

  if (versions.length > 1) {
    versionPickerState.value = { item, versions, startSeconds }
    return
  }

  emitSelectVideo(item, undefined, startSeconds)
}

async function selectVideo(item: LibraryItem) {
  if (!party.partyId) return

  // Resume check first: if Emby reports a current resume position
  // for this item (UserData.PlaybackPositionTicks > 0), ask the host
  // whether to resume or start over before picking a version /
  // emitting. We deliberately don't gate on UserData.Played -- that
  // flag is "this item has been completed in history" and stays true
  // forever after the first completion, but Emby still tracks
  // PlaybackPositionTicks for re-watches. Emby's own thresholds
  // already gate small positions (under ~5%) to zero, so any
  // positive PositionTicks here represents a real resume point.
  const ud = item?.UserData
  const positionTicks = Number(ud?.PlaybackPositionTicks ?? 0)
  if (positionTicks > 0) {
    const runTimeSeconds = item.RunTimeTicks
      ? Number(item.RunTimeTicks) / 10_000_000
      : null
    resumePromptState.value = {
      item,
      resumeSeconds: positionTicks / 10_000_000,
      runTimeSeconds,
    }
    return
  }

  await continueSelectAfterResume(item, 0)
}

function onResume() {
  const pending = resumePromptState.value
  resumePromptState.value = null
  if (!pending) return
  continueSelectAfterResume(pending.item, pending.resumeSeconds)
}

function onStartOver() {
  const pending = resumePromptState.value
  resumePromptState.value = null
  if (!pending) return
  continueSelectAfterResume(pending.item, 0)
}

function onResumeCancel() {
  resumePromptState.value = null
}

function onVersionPick(mediaSourceId: string) {
  const pending = versionPickerState.value
  versionPickerState.value = null
  if (!pending) return
  // Clamp the resume seconds against the PICKED version's runtime.
  // The prompt was built from the item's aggregate RunTimeTicks (the
  // default version); if the host picks a shorter alternate cut, the
  // stored position can exceed the picked version's length. Backend
  // clamps to (runtime - 5s) silently, landing mid-credits instead
  // of where the modal promised. Recompute here so the emitted
  // start_seconds matches the actual picked-version geometry.
  let startSeconds = pending.startSeconds
  const picked = pending.versions.find((v) => v.id === mediaSourceId)
  if (picked?.run_time_ticks && startSeconds > 0) {
    const versionRuntime = Number(picked.run_time_ticks) / 10_000_000
    const maxResume = Math.max(0, versionRuntime - 5)
    if (startSeconds > maxResume) {
      console.debug(
        '[PartyView] clamping resume position for alternate version',
        { original: startSeconds, clamped: maxResume, versionRuntime },
      )
      startSeconds = 0
    }
  }
  emitSelectVideo(pending.item, mediaSourceId, startSeconds)
}

function onVersionPickCancel() {
  versionPickerState.value = null
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
  // Skip when our own stream is mid-reload. After change_streams the
  // <video> element's src is replaced, which fires a synthetic play
  // once HLS.js auto-plays the new manifest. Broadcasting that to the
  // party would be a no-op at best and a "Andrew started playback"
  // chat spam at worst.
  if (!party.partyId || isForcePausing || isInitialSync || myStreamReloading.value) return
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
  // Chat message comes from the server-broadcast handler (socket.on
  // 'play'), which fires for every client including the sender. This
  // is the single source of truth for play/pause/seek system
  // messages -- a local fire here would double-print the line once
  // the broadcast lands.
  hasStarted = true
}

function onVideoPause() {
  // Same guard as onVideoPlay: change_streams replaces the <video>
  // src, which fires a native pause event. Without this check the
  // 250ms debounce would broadcast a real "pause" to the party,
  // pausing every other watcher because one user switched to PGS subs.
  if (!party.partyId || isForcePausing || isUserSeeking || isInitialSync || myStreamReloading.value) return
  const ve = videoPlayer.value?.videoEl
  if (!ve || ve.ended) return
  if (videoPlayer.value?.isSyncing) return

  if (pendingPauseTimer) clearTimeout(pendingPauseTimer)
  pendingPauseTimer = setTimeout(() => {
    pendingPauseTimer = null
    if (!party.partyId || isForcePausing || isUserSeeking || isInitialSync || myStreamReloading.value) return
    if (videoPlayer.value?.isSyncing) return
    const currentVideoEl = videoPlayer.value?.videoEl
    if (!currentVideoEl || currentVideoEl.ended || !currentVideoEl.paused) return

    // Do NOT broadcast a pause that came from BUFFERING / a stall rather
    // than a real user action. When HLS.js runs out of buffered data the
    // browser fires a native `pause`, and readyState drops below
    // HAVE_FUTURE_DATA (3). Under the democratic control model any such
    // stray pause now propagates to the WHOLE room, so a single client's
    // buffering hiccup right after play would pause everyone -- the
    // "something keeps pausing right after anyone hits play" loop. A
    // genuine user pause leaves the element fully buffered (readyState
    // >= 3) and not in the buffering overlay. Suppress the emit
    // otherwise; the local stall recovers on its own and the heartbeat
    // resync re-asserts play state if the party is still playing.
    if (videoPlayer.value?.isBuffering || currentVideoEl.readyState < 3) return

    const now = Date.now()
    if (now - lastPauseBroadcast < PLAY_PAUSE_THROTTLE) return
    lastPauseBroadcast = now

    wasPlayingBeforeSeek = false
    socket.emit('pause', { party_id: party.partyId, time: toMediaTime(currentVideoEl.currentTime) })
    // Chat message handled by socket.on('pause') broadcast handler.
  }, 250)
}

function onVideoSeeking() {
  if (pendingPauseTimer) {
    clearTimeout(pendingPauseTimer)
    pendingPauseTimer = null
  }
  // VideoPlayer's INTERNAL isSyncing gate already suppresses the
  // 'seeking' emit during synthetic seeks (HLS source swap, drift
  // correction, etc.), so we won't get called for those. Any seeking
  // event reaching this handler is a real user-initiated seek -- set
  // the flag unconditionally. The earlier guard on
  // `videoPlayer.value?.isSyncing` here was wrong: it tried to gate
  // again on the *parent-side* view of isSyncing, which can stay
  // truthy briefly after various sync events and ended up silently
  // blocking legitimate progress-bar drags.
  //
  // The stuck-flag risk is handled in onVideoSeeked, which always
  // schedules a 500ms clearSeekingFlag regardless of which early
  // return triggers.
  wasPlayingBeforeSeek = wasPlayingBeforeSeek || party.playbackState.playing
  isUserSeeking = true
}

function onVideoSeeked(_time: number) {
  // Always schedule clearing isUserSeeking, even on the early-return
  // paths below, so the flag can't get stuck across phantom or
  // synthetic seeks. The broadcast logic at the bottom only runs for
  // real user-initiated seeks.
  const clearSeekingFlag = () => {
    isUserSeeking = false
    seekSettleTimer = null
  }
  if (seekSettleTimer) clearTimeout(seekSettleTimer)
  seekSettleTimer = setTimeout(clearSeekingFlag, 500)

  if (!party.partyId || isInitialSync) return

  // Phantom-seek guard. The reliable signal is whether onVideoSeeking
  // ran before this -- it only runs when VideoPlayer's internal
  // isSyncing was false (player not in attachStream / source-swap)
  // AND the browser actually dispatched a `seeking` event. Both
  // conditions together mean this is a user-initiated seek. Anything
  // else is a phantom from HLS.js segment alignment / drift correction.
  //
  // Earlier this used a delta-vs-lastNaturalTime comparison, which
  // was fragile: it depended on the browser firing `seeking` before
  // `timeupdate`. Chromium tends to fire timeupdate first with the
  // seek target, which clobbered lastNaturalTime and made the guard
  // reject every real seek.
  if (!isUserSeeking) return

  // Real user seek: extend the settle window and broadcast when it
  // expires. clearSeekingFlag still runs at the end so the flag clears
  // either way. The setTimeout debounces rapid scrubs (drag the
  // timeline a few times in a row) into one broadcast per pause.
  if (seekSettleTimer) clearTimeout(seekSettleTimer)
  seekSettleTimer = setTimeout(() => {
    clearSeekingFlag()
    const ve = videoPlayer.value?.videoEl
    if (!ve) return

    const mediaTime = toMediaTime(ve.currentTime)
    socket.emit('seek', {
      party_id: party.partyId!,
      time: mediaTime,
      was_playing: wasPlayingBeforeSeek,
    })
    // Chat message handled by socket.on('seek') broadcast handler.
  }, 500)
}

let lastProgressReport = 0
const PROGRESS_INTERVAL = 10000 // 10 seconds

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
  // Close the library for EVERY client when a video becomes active, not
  // just the selector. emitSelectVideo() only hides it locally on the
  // picker; this watcher fires symmetrically on all clients via the
  // store's video_selected handler, so spectators who had the library
  // open when someone picked a video get it closed too. Guard on the
  // item_id transition so re-selecting the same video (or metadata-only
  // updates) don't fight a user who just reopened the library.
  if (newVal?.item_id && newVal?.item_id !== oldVal?.item_id) {
    showLibrary.value = false
  }
  // Reset hasStarted whenever the video changes (any client, not just
  // the selector). Previously emitSelectVideo set hasStarted=false
  // only for the emitter, so on B/C the first play of the new video
  // announced "resumed" instead of "started". Watching the video id
  // on the store lands on every client symmetrically via the
  // video_selected broadcast the store applies.
  if (newVal?.item_id !== oldVal?.item_id) {
    hasStarted = false
  }
})

function onChangeStreams(opts: { audioIndex?: number; subtitleIndex?: number; quality?: string }) {
  if (!party.partyId) return
  // The alternate Emby version (issue #43) is locked at select_video
  // time on the backend (current_video.media_source_id), so this emit
  // never needs to carry it -- audio/subtitle/quality changes always
  // resolve to the same version automatically.
  socket.emit('change_streams', {
    party_id: party.partyId,
    audio_index: opts.audioIndex,
    subtitle_index: opts.subtitleIndex,
    quality: opts.quality,
  })
}

function onChangeTextSubtitle(payload: { index: number; url: string | null }) {
  // Remember the selection so the currentVideo/streamUrl watcher can
  // restore mode='showing' on the matching <track> after a quality
  // change rebuilds the track set. A positive index pins this text
  // sub; -1 (None) or a PGS pick (url=null) clears it.
  selectedTextSubIndex.value = payload.index >= 0 && payload.url ? payload.index : null

  const vp = videoPlayer.value
  const ve = vp?.videoEl
  if (!ve) return

  // "None" selected -- mark every preloaded track as hidden (NOT
  // disabled). 'disabled' unloads the cues, and toggling back to
  // 'showing' afterwards doesn't reliably reload them in Chromium,
  // which surfaced as "after None I can't turn subs back on". 'hidden'
  // keeps the cues loaded but invisible, so switching back is a
  // single mode flip.
  if (payload.index === -1 || !payload.url) {
    for (let i = 0; i < ve.textTracks.length; i += 1) {
      const tt = ve.textTracks[i]
      if (tt) tt.mode = 'hidden'
    }
    return
  }

  // Find the preloaded <track> whose src matches the requested url. The
  // src attribute resolves to an absolute URL but endsWith on the relative
  // path still matches because the suffix is identical.
  const tracks = Array.from(ve.querySelectorAll('track'))
  const target = tracks.find((t) => t.src.endsWith(payload.url!))

  if (target) {
    // Already preloaded -- flip the target to 'showing' and the rest
    // back to 'hidden' (not 'disabled' -- same reason as above, we
    // want them preloaded for future switches without a refetch).
    for (let i = 0; i < ve.textTracks.length; i += 1) {
      const tt = ve.textTracks[i]
      if (tt) tt.mode = tt === target.track ? 'showing' : 'hidden'
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

function onVideoEnded() {
  // The selector is the authoritative timekeeper for the party; they
  // also signal end-of-video so the backend gets exactly one ended
  // event per playthrough rather than one per user as each independent
  // stream finishes. The backend uses this as the trigger to stop all
  // per-user transcodes and (when binge-watching is on) queue the
  // auto-advance to the next episode.
  if (!party.partyId || !party.currentVideo) return
  const myClientId = getClientId()
  if (party.currentVideo.selected_by !== myClientId) return
  socket.emit('video_ended', { party_id: party.partyId })
}

function toggleBingeWatch() {
  if (!party.bingeWatch.available) return
  party.setBingeWatchActive(!party.bingeWatch.active)
}

function onJump(seconds: number) {
  // Same flow as Skip Intro: compute the absolute media time we want,
  // emit, let the server broadcast the seek back to everyone including
  // us. Never set ve.currentTime locally first -- that double-flushes
  // HLS and risks a restart-from-zero (see comment in onSkipIntro).
  if (!party.partyId) return
  const ve = videoPlayer.value?.videoEl
  if (!ve) return
  const runtime = party.currentVideo?.run_time_seconds
  const target = Math.max(
    0,
    runtime ? Math.min(runtime, toMediaTime(ve.currentTime) + seconds) : toMediaTime(ve.currentTime) + seconds,
  )
  socket.emit('seek', {
    party_id: party.partyId,
    time: target,
    was_playing: !ve.paused,
  })
}

function onSeekTo(absoluteSeconds: number) {
  // Absolute jump-to: VideoControls' Jump/Seek popover already
  // clamped to the runtime range. Route through the same seek
  // socket path as Skip Intro and the +/- jump buttons so the
  // server-broadcast moves everyone's <video> together; never set
  // ve.currentTime locally first (see onSkipIntro for why).
  if (!party.partyId) return
  const ve = videoPlayer.value?.videoEl
  socket.emit('seek', {
    party_id: party.partyId,
    time: absoluteSeconds,
    was_playing: ve ? !ve.paused : true,
  })
}

function onSkipIntro(endTime: number) {
  // Match the 1.x flow: emit the seek and let the server-broadcast
  // drive the actual seek for everyone (including us). Doing a local
  // ve.currentTime = endTime *before* the emit caused two back-to-back
  // HLS buffer flushes -- one from the local seek and one from the
  // server's seek event -- which in some buffer states made HLS.js
  // bail and re-attach the stream from currentTime=0.
  if (!party.partyId) return
  const ve = videoPlayer.value?.videoEl
  socket.emit('seek', {
    party_id: party.partyId,
    time: endTime,
    was_playing: ve ? !ve.paused : true,
  })
}

function toggleLibrary() {
  showLibrary.value = !showLibrary.value
  if (showLibrary.value) {
    socket.emit('toggle_library', { party_id: party.partyId!, show: true })
  } else {
    socket.emit('toggle_library', { party_id: party.partyId!, show: false })
  }
}

function libraryButtonAction() {
  if (auth.partyUnlocked) {
    toggleLibrary()
  } else {
    becomeHostError.value = null
    showBecomeHostModal.value = true
  }
}

async function submitBecomeHost(payload: { username: string; password: string }) {
  becomeHostBusy.value = true
  becomeHostError.value = null
  try {
    const data = await auth.becomeHost(payload.username, payload.password)
    if (data.success) {
      showBecomeHostModal.value = false
      // Caller is now host. Pop the library open so they can pick.
      showLibrary.value = true
    } else {
      becomeHostError.value = data.message || 'Login failed'
    }
  } finally {
    becomeHostBusy.value = false
  }
}
</script>

<template>
  <!-- Auto-join spinner: shown when we have a saved username and are
       waiting on the socket to confirm the join. Suppresses the name
       modal flash-of-stale-UI on every mount / refresh. -->
  <div v-if="!joined && awaitingAutoJoin" class="modal-overlay">
    <div class="modal-card join-spinner">
      <span class="spinner" />
      <p>Joining party…</p>
    </div>
  </div>

  <!-- Username modal -->
  <div v-else-if="!joined" class="modal-overlay">
    <div class="modal-card">
      <h2>Join Watch Party</h2>
      <p>Enter your name (or leave blank for random name):</p>
      <input v-model="usernameInput" @keypress.enter="submitJoin" placeholder="Your name (optional)" type="text" autofocus />
      <button @click="submitJoin" class="btn btn-primary">Join</button>
    </div>
  </div>

  <!-- Party room -->
  <div v-if="joined" class="party-container">
    <!-- Reconnecting banner: shown when the socket has dropped and
         socket.io-client is attempting to reconnect. Without this, a
         mid-party disconnect looks identical to a healthy connection
         (playback keeps rolling but pause/play events silently no-op).
         Only shows AFTER we've been connected at least once, so it
         does not flash during the initial handshake. -->
    <div
      v-if="socket.reconnecting"
      class="reconnect-banner"
      role="status"
      aria-live="polite"
    >
      <span class="spinner spinner-inline" />
      Reconnecting to party…
    </div>
    <header class="party-header">
      <div class="header-left">
        <button
          v-if="versionInfo.version"
          class="brand"
          @click="showVersionModal = true"
          :title="`Watch Party ${versionInfo.codename || ''}`.trim()"
        >
          <span class="brand-mark" aria-hidden="true">
            <img :src="brandMarkUrl" alt="" class="brand-mark-img" />
          </span>
          <span class="brand-name">Watch Party<span class="brand-subtle">by <a href="https://github.com/oratorian" target="_blank" rel="noopener noreferrer">Oratorian</a></span></span>
        </button>
        <button
          class="party-pill"
          @click="copyPartyId"
          :title="copyLabel === 'Copy' ? 'Copy party code' : copyLabel"
        >
          <span class="party-pill-label">Code</span>
          <code class="party-pill-code">{{ route.params.id }}</code>
          <span class="party-pill-copy" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
          </span>
        </button>
        <span v-if="auth.hostUsername" class="host-badge" :title="`Host: ${auth.hostUsername}`">
          Host: {{ auth.hostUsername }}
        </span>
      </div>
      <div class="header-actions">
        <div class="viewer-chip" :title="`${party.userCount} ${party.userCount === 1 ? 'person' : 'people'} watching`">
          <span class="viewer-dot" aria-hidden="true"></span>
          <span>{{ party.userCount }} watching</span>
          <div class="viewer-avatars">
            <img
              v-for="user in party.users.slice(0, 3)"
              :key="user"
              :src="avatarSrc(user)"
              :alt="user"
              class="av"
            />
            <span v-if="party.userCount > 3" class="av av-more">+{{ party.userCount - 3 }}</span>
          </div>
        </div>
        <button @click="libraryButtonAction" class="chip-btn">
          <template v-if="auth.partyUnlocked">
            {{ showLibrary ? 'Hide Library' : 'Browse Library' }}
          </template>
          <template v-else>Login to Become Host</template>
        </button>
        <button v-if="party.currentVideo" @click="stopVideo" class="chip-btn chip-btn-warn">Stop Video</button>
        <button
          v-if="auth.isAdmin"
          ref="adminTriggerBtn"
          type="button"
          class="ico-btn"
          title="Open the admin panel (Emby admin policy required)"
          aria-label="Admin"
          @click="showAdminModal = true"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09a1.65 1.65 0 00-1-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09a1.65 1.65 0 001.51-1 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06a1.65 1.65 0 001.82.33h0a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51h0a1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82v0a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
        </button>
        <button @click="showMobileChat = true" class="chip-btn mobile-chat-toggle">Chat</button>
        <button @click="leaveParty" class="btn-leave" title="Leave party">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/></svg>
          Leave
        </button>
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
          <template v-if="auth.partyUnlocked">
            <h2>No video selected</h2>
            <p>Browse the library and select a video to start watching together</p>
            <button @click="toggleLibrary" class="btn btn-primary">Browse Library</button>
          </template>
          <template v-else>
            <h2>Party is locked</h2>
            <p>An Emby login is needed before anyone can browse the library. Any party member can do it.</p>
            <button @click="libraryButtonAction" class="btn btn-primary">Login to Become Host</button>
          </template>
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
            @ended="onVideoEnded"
            @ready="onStreamReady"
          />
          <!-- Auto-advance countdown overlays the video, centered.
               Lives inside video-wrapper so it pins to the player
               element and never bleeds onto the chat / topbar / seekbar. -->
          <AutoAdvanceModal />

          <VideoControls
            :party-id="party.partyId!"
            :item-id="party.currentVideo.item_id"
            :stream-url="party.myStreamUrl || ''"
            :quality="party.currentVideo.quality || '1080p-high'"
            :current-time="currentTime"
            :media-source-id="party.currentVideo.media_source_id ?? undefined"
            :run-time-seconds="party.currentVideo.run_time_seconds ?? undefined"
            :binge-available="party.bingeWatch.available"
            :binge-active="party.bingeWatch.active"
            :binge-visible="auth.isHost && party.currentVideo.item_type === 'Episode'"
            @change-streams="onChangeStreams"
            @change-text-subtitle="onChangeTextSubtitle"
            @skip-intro="onSkipIntro"
            @jump="onJump"
            @seek-to="onSeekTo"
            @toggle-binge="toggleBingeWatch"
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
          <div class="participant-actions">
            <button class="btn btn-ghost btn-small" @click.stop="showAvatarModal = true">
              My avatar
            </button>
          </div>
          <div
            v-for="user in party.users"
            :key="user"
            class="participant-item"
            :class="{ 'participant-self': user === party.username }"
          >
            <img :src="avatarSrc(user)" class="avatar avatar-sm" :alt="user" />
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
              <div class="sys-msg">
                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>
                <span>{{ msg.message }}</span>
              </div>
            </template>
            <template v-else>
              <div class="msg-bubble-row" :class="{ 'msg-self': msg.username === party.username }">
                <img v-if="msg.username !== party.username" :src="chatAvatarSrc(msg)" class="avatar avatar-chat" :alt="msg.username" />
                <div class="msg-bubble" :class="msg.username === party.username ? 'bubble-self' : 'bubble-other'">
                  <strong>{{ msg.username }}</strong>
                  <span>{{ msg.message }}</span>
                </div>
                <img v-if="msg.username === party.username" :src="chatAvatarSrc(msg)" class="avatar avatar-chat" :alt="msg.username" />
              </div>
            </template>
          </div>
        </div>
        <div class="chat-input">
          <div class="chat-composer">
            <EmojiPicker @select="insertEmoji" />
            <input
              v-model="chatInput"
              @keypress.enter="sendChat"
              placeholder="Type a message..."
              class="chat-composer-input"
            />
            <button @click="sendChat" class="chat-composer-send" title="Send" aria-label="Send message">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            </button>
          </div>
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

  <!-- Avatar setup / recovery -->
  <AvatarSetupModal
    v-if="showAvatarModal"
    @close="showAvatarModal = false"
  />

  <!-- Multi-version picker. Pops up only when the host clicked a
       library item with more than one Emby alternate source. -->
  <VersionPickerModal
    v-if="versionPickerState"
    :item-name="versionPickerState.item.Name"
    :versions="versionPickerState.versions"
    @select="onVersionPick"
    @cancel="onVersionPickCancel"
  />

  <!-- Resume-from-last-position prompt. Pops up when the host clicked
       a library item that has UserData.PlaybackPositionTicks > 0 and
       Played === false; intercepts the select flow long enough for
       the host to choose Resume vs Start over before the multi-version
       picker (if any) and the actual select_video emit. -->
  <ResumePromptModal
    v-if="resumePromptState"
    :title="resumePromptState.item.Name"
    :resume-seconds="resumePromptState.resumeSeconds"
    :run-time-seconds="resumePromptState.runTimeSeconds"
    @resume="onResume"
    @start-over="onStartOver"
    @cancel="onResumeCancel"
  />

  <!-- Become host (any party member can promote themselves) -->
  <EmbyLoginModal
    v-if="showBecomeHostModal"
    title="Login to Become Host"
    description="Any party member can log in with valid Emby credentials. The host's library becomes browsable for everyone in the room."
    submit-label="Become Host"
    :busy="becomeHostBusy"
    :error-message="becomeHostError"
    @submit="submitBecomeHost"
    @cancel="showBecomeHostModal = false"
  />

  <!-- Admin panel modal. Mounted over PartyView so the router does NOT
       unmount VideoPlayer / the HLS.js instance, which would otherwise
       restart the local stream from the transcode's original offset.
       See onUnmounted comment above for the sibling rationale. -->
  <div
    v-if="showAdminModal"
    class="admin-modal-backdrop"
    @click.self="showAdminModal = false"
  >
    <div
      ref="adminModalShellRef"
      class="admin-modal-shell glass"
      role="dialog"
      aria-modal="true"
      aria-label="Admin Panel"
      tabindex="-1"
    >
      <div class="admin-modal-header">
        <h2>Admin Panel</h2>
        <button
          type="button"
          class="btn btn-small btn-ghost"
          aria-label="Close admin panel"
          @click="showAdminModal = false"
        >Close</button>
      </div>
      <div class="admin-modal-body">
        <AdminPanel @unauthorized="showAdminModal = false" />
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

/* ─── Auto-join Spinner ─── */
.join-spinner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-xl);
}

.join-spinner .spinner {
  width: 32px;
  height: 32px;
  border: 3px solid rgba(255, 255, 255, 0.2);
  border-top-color: var(--accent-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.join-spinner p {
  color: var(--text-secondary);
  font-size: 0.9rem;
  margin: 0;
}

/* ─── Reconnect Banner ─── */
.reconnect-banner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  background: rgba(255, 170, 0, 0.15);
  color: #ffcf6b;
  border-bottom: 1px solid rgba(255, 170, 0, 0.35);
  font-size: 0.9rem;
  font-weight: 500;
  z-index: 100;
}

.spinner-inline {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 207, 107, 0.3);
  border-top-color: #ffcf6b;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

/* ─── Party Layout ─── */
.party-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh;
  background: var(--bg-primary);
}

.party-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: env(safe-area-inset-top)
    max(var(--space-md), env(safe-area-inset-right)) 0
    max(var(--space-md), env(safe-area-inset-left));
  height: 80px;
  background: rgba(11, 14, 28, 0.5);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-bottom: 1px solid var(--border-subtle);
  position: relative;
  z-index: 10;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* Brand: cyan->magenta gradient mark + name. Click opens the version
   modal, replacing the old centred "Watch Party | codename" pair. */
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  background: none;
  border: 0;
  padding: 0;
  cursor: pointer;
  color: inherit;
  font: inherit;
}

/* The custom brand logo carries its own background, colour, and
   silhouette, so the gradient frame the original play-arrow tile used
   gets dropped. The rounded corners + soft cyan-tinted shadow stay on
   the wrapper so the mark sits in the same visual idiom as the other
   rounded chips in the header. Sized to 64px inside the 80px topbar
   (8px breathing room top/bottom) so the logo reads as the dominant
   identity element. */
.brand-mark {
  width: 64px;
  height: 64px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  box-shadow: 0 4px 8px rgba(34, 211, 238, 0.2);
  flex-shrink: 0;
  overflow: hidden;
}

.brand-mark-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
  pointer-events: none;
}

.brand-name {
  font-weight: 600;
  font-size: 14px;
  letter-spacing: -0.02em;
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  white-space: nowrap;
}

.brand-subtle {
  color: var(--text-muted);
  font-weight: 400;
}

/* Party-code pill: surface bg, cyan code text, copy icon on the right.
   The whole pill is clickable, copy icon is a visual hint only. */
.party-pill {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 7px 7px 7px 14px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-full);
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast);
  font-family: var(--font-sans);
}

.party-pill:hover {
  background: var(--bg-surface-hover);
  border-color: var(--border-hover);
}

.party-pill-label {
  color: var(--text-muted);
  font-size: 12px;
}

.party-pill-code {
  font-family: var(--font-mono);
  color: var(--accent-primary);
  font-weight: 600;
  font-size: 13px;
  letter-spacing: 0.05em;
}

.party-pill-copy {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-secondary);
  transition: background var(--transition-fast), color var(--transition-fast);
}

.party-pill:hover .party-pill-copy {
  background: var(--bg-surface-hover);
  color: var(--accent-primary);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* Viewer chip: live green dot + count + overlapping avatars. The
   pill itself is non-interactive (no click target), just a visual
   summary of who's watching with you. */
.viewer-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-full);
  font-size: 12px;
  color: var(--text-primary);
}

.viewer-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-green);
  box-shadow: 0 0 8px var(--accent-green);
  flex-shrink: 0;
}

.viewer-avatars {
  display: flex;
  margin-left: 4px;
}

.viewer-avatars .av {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: 2px solid var(--bg-primary);
  margin-left: -8px;
  display: grid;
  place-items: center;
  font-size: 10px;
  font-weight: 600;
  object-fit: cover;
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
}

.viewer-avatars .av:first-child {
  margin-left: 0;
}

.viewer-avatars .av-more {
  background: linear-gradient(135deg, var(--accent-violet), var(--accent-primary));
  color: var(--text-primary);
  font-size: 9px;
}

/* Header chip buttons. Same pill language as viewer-chip but
   interactive. Used for Browse Library, Stop Video, mobile Chat. */
.chip-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast), color var(--transition-fast);
  font-family: var(--font-sans);
}

.chip-btn:hover {
  background: var(--bg-surface-hover);
  border-color: var(--border-hover);
}

.chip-btn-warn {
  background: var(--accent-amber-dim);
  border-color: rgba(251, 191, 36, 0.25);
  color: var(--accent-amber);
}

.chip-btn-warn:hover {
  background: rgba(251, 191, 36, 0.22);
  border-color: rgba(251, 191, 36, 0.4);
}

/* Square icon button -- used for Admin gear. */
.ico-btn {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast), color var(--transition-fast);
}

.ico-btn:hover {
  background: var(--bg-surface-hover);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

/* Leave: red-tinted to clearly read as a destructive action. */
.btn-leave {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 500;
  background: rgba(244, 63, 94, 0.1);
  color: #fb7185;
  border: 1px solid rgba(244, 63, 94, 0.2);
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast);
  font-family: var(--font-sans);
}

.btn-leave:hover {
  background: rgba(244, 63, 94, 0.15);
  border-color: rgba(244, 63, 94, 0.3);
}

.host-badge {
  font-size: 0.75rem;
  color: var(--accent-amber);
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-full);
  padding: 0.2rem 0.6rem;
  white-space: nowrap;
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
  /* Match the topbar's glass treatment so the panel reads as part of
     the same surface stack instead of a solid block. Vertical fade
     darkens the bottom slightly. */
  background: linear-gradient(180deg, rgba(11, 14, 28, 0.6) 0%, rgba(6, 7, 13, 0.6) 100%);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
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
  overflow: hidden;
  min-height: 0;
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
  min-height: 0;
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
  /* Same glass surface as the controls strip directly above and the
     library / chat / topbar on either side. */
  background: rgba(11, 14, 28, 0.55);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
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
  /* Mirror the library panel's glass surface so left/right shoulders
     of the layout share the same backdrop treatment as the topbar. */
  background: linear-gradient(180deg, rgba(11, 14, 28, 0.6) 0%, rgba(6, 7, 13, 0.6) 100%);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
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
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 5px 10px;
  font-size: 12px;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}

.chat-close-btn:hover {
  background: var(--bg-surface-hover);
  border-color: var(--border-hover);
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

/* System message: centered pill bubble with a cyan icon. The outer
   .chat-msg row is normally left-aligned for user messages; the inline
   flex on .sys-msg + align-self:center inside a flex column keeps the
   pill centred within the message stream regardless. */
.system-msg {
  display: flex;
  justify-content: center;
  padding: var(--space-xs) 0;
}

.sys-msg {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-full);
  color: var(--text-muted);
  font-size: 0.75rem;
  font-weight: 500;
  max-width: 100%;
  text-align: center;
}

.sys-msg svg {
  color: var(--accent-primary);
  flex-shrink: 0;
}

.chat-input {
  padding: var(--space-sm) var(--space-md);
  border-top: 1px solid var(--border-subtle);
}

/* Unified composer pill: emoji trigger on the left, bare input in the
   middle, gradient send button on the right. Focus-within lifts the
   surface and adds a cyan ring so the whole pill reads as one focused
   element rather than three competing controls. */
.chat-composer {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 6px 5px 8px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  transition: background var(--transition-fast), border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.chat-composer:focus-within {
  background: var(--bg-surface-hover);
  border-color: rgba(34, 211, 238, 0.4);
  box-shadow: 0 0 0 3px rgba(34, 211, 238, 0.08);
}

.chat-composer-input {
  flex: 1;
  min-width: 0;
  /* Override the global input chip styling -- the surface/border live
     on the composer pill now, the input itself is bare. */
  padding: 6px 4px;
  background: none;
  border: 0;
  border-radius: 0;
  font-size: 13px;
  color: var(--text-primary);
}

.chat-composer-input:focus {
  background: none;
  border: 0;
  box-shadow: none;
}

.chat-composer-send {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, var(--accent-primary), var(--accent-violet));
  color: var(--bg-deep);
  border: 0;
  box-shadow: 0 2px 8px rgba(34, 211, 238, 0.3);
  cursor: pointer;
  flex-shrink: 0;
  transition: transform var(--transition-fast), box-shadow var(--transition-fast);
}

.chat-composer-send:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(34, 211, 238, 0.4);
}

.chat-composer-send:active {
  transform: translateY(0);
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

  .brand-name {
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
    padding-bottom: env(safe-area-inset-bottom);
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

/* Admin Panel Modal. z-index 10000 sits above every existing modal
   (JoinWaitingRoom at 9500 is the current ceiling) and leaves the
   10000-19999 band reserved for admin-context sub-modals. */
.admin-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-lg);
  z-index: 10000;
}

.admin-modal-shell {
  position: relative;
  width: 100%;
  max-width: 1100px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  border-radius: var(--radius-lg);
  outline: none;
}

.admin-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-md) var(--space-lg);
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.admin-modal-header h2 {
  margin: 0;
}

.admin-modal-body {
  padding: var(--space-lg);
  overflow-y: auto;
  flex: 1 1 auto;
}
</style>
