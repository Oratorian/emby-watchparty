import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useSocketStore } from './socket'
import { useAvatarStore } from './avatar'
import { useAuthStore } from './auth'
import { api } from '@/api/client'
import { hideParty } from '@/utils/hiddenParties'

export interface MemberInfo {
  username: string
  avatar_uuid?: string | null
}

const CLIENT_ID_STORAGE_KEY = 'emby-watchparty-client-id'

function getClientId(): string {
  let clientId = localStorage.getItem(CLIENT_ID_STORAGE_KEY)
  if (clientId) return clientId

  clientId = crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`
  localStorage.setItem(CLIENT_ID_STORAGE_KEY, clientId)
  return clientId
}

export { getClientId }

export const usePartyStore = defineStore('party', () => {
  const partyId = ref<string | null>(null)
  const username = ref<string | null>(null)
  const users = ref<string[]>([])
  // Parallel to `users` but carries avatar_uuid per member. Server
  // emits this in user_joined / user_left payloads. Indexed by display
  // name (sufficient because the server enforces unique-ish names per
  // party). Falls back to null when the backend hasn't bound an avatar.
  const members = ref<Record<string, string | null>>({})
  const currentVideo = ref<any>(null)
  const playbackState = ref({ playing: false, time: 0, last_update: '' })
  const myStreamUrl = ref<string | null>(null)
  // Media time at which this user's stream begins. Backend sets
  // StartTimeTicks to this value when the user joins mid-playback, so
  // their HLS stream's currentTime=0 corresponds to media position streamOffset.
  const streamOffset = ref(0)
  const readyCheckActive = ref(false)
  const readyUsers = ref<string[]>([])
  const waitingUsers = ref<string[]>([])

  // Binge-watch state. `available` is the admin master toggle; when
  // false, the control-strip button is hidden entirely. `active` is
  // the host's per-party opt-in (only meaningful when available=true).
  // Both arrive on sync_state at join and on binge_watch_state_changed
  // when the admin or host toggles them.
  const bingeWatch = ref<{ available: boolean; active: boolean }>({
    available: false, active: false,
  })

  // Pending auto-advance modal state. Non-null only between video_ended
  // and the next video_selected / video_stopped, while the countdown
  // is running. timeoutAt is the absolute deadline (ms since epoch);
  // the modal computes "seconds remaining" against that anchor instead
  // of holding its own counter, so clients with drifty clocks land in
  // the same place.
  const pendingAutoAdvance = ref<{
    nextItemId: string
    nextTitle: string
    nextIndexNumber: number | null
    totalEpisodes: number
    timeoutAt: number
    // Total countdown window in seconds (BINGE_WATCH_COUNTDOWN_SECONDS
    // from admin config). Sent by the server so the modal progress bar
    // can size the denominator correctly instead of assuming a hardcoded
    // 4s window.
    countdownSeconds: number | null
  } | null>(null)

  // Late-joiner vote state. Non-null while a vote is in progress.
  // isPending=true means "I am the late joiner being voted on" (waiting room).
  // isPending=false means "I am an existing user voting on a late joiner" (modal).
  const pendingVote = ref<{
    active: boolean
    isPending: boolean
    lateJoinerUsername: string | null
    eligibleVoters: string[]
    votes: Record<string, 'yes' | 'no'>
    myVote: 'yes' | 'no' | null
    timeoutAt: number
    requiredMajority: number
  } | null>(null)

  const userCount = computed(() => users.value.length)

  async function join(id: string, name: string) {
    const socket = useSocketStore()
    const avatar = useAvatarStore()
    const auth = useAuthStore()
    partyId.value = id.toUpperCase()
    username.value = name
    const clientId = getClientId()
    // Load the persisted avatar id (IndexedDB or localStorage) so it
    // can ride along on the join. Safe to call repeatedly.
    if (!avatar.uuid) {
      try { await avatar.load() } catch { /* ignore */ }
    }
    const avatarUuid = avatar.uuid
    // Set the party-bound session cookie before the socket connects.
    // The cookie is what every protected HTTP route and the socket
    // handshake will use to authenticate this caller.
    try {
      await api.joinParty(partyId.value, clientId, name || 'Guest', avatarUuid)
      // The cookie is now bound. Re-read auth state so partyUnlocked
      // and hostUsername reflect this party, not the empty pre-join
      // status. Otherwise late joiners briefly render "Party is
      // locked" until the next host_changed event (which never fires
      // for a party that was already unlocked when they joined).
      try { await auth.refresh() } catch { /* ignore */ }
    } catch {
      // Best-effort: even if the cookie call fails, the socket join
      // event below carries the same identity so we fall back to
      // socket-only auth during the transition.
    }
    socket.emit('join_party', {
      party_id: partyId.value,
      username: name,
      client_id: clientId,
      avatar_uuid: avatarUuid,
    })
  }

  async function leave() {
    if (!partyId.value) return
    const socket = useSocketStore()
    const auth = useAuthStore()
    socket.emit('leave_party', { party_id: partyId.value })
    // Drop the party-bound session cookie too. Without this,
    // /api/auth/status keeps returning the old party_id and the
    // "Back to Party" link on /admin or /version would route the user
    // into a party they just left.
    try { await api.leaveParty() } catch { /* best effort */ }
    try { await auth.refresh() } catch { /* ignore */ }
    partyId.value = null
    users.value = []
    currentVideo.value = null
    myStreamUrl.value = null
    streamOffset.value = 0
    playbackState.value = { playing: false, time: 0, last_update: '' }
    readyCheckActive.value = false
    readyUsers.value = []
    waitingUsers.value = []
    pendingVote.value = null
  }

  function submitVote(vote: 'yes' | 'no') {
    if (!partyId.value || !pendingVote.value) return
    const socket = useSocketStore()
    pendingVote.value.myVote = vote
    socket.emit('join_vote', { party_id: partyId.value, vote })
  }

  function setupListeners() {
    const socket = useSocketStore()

    // Defensive: drop any previously-registered handlers for these events
    // before re-registering. HMR reloads or PartyView remounts call
    // setupListeners again, and without this every cycle would stack
    // duplicate listeners -- a single server emit would then fire the
    // chat-message side effects N times (observed: "Andrew seeked to..."
    // repeating 5-6 times per real seek event after a few HMR cycles).
    const events = [
      'user_joined', 'user_left', 'sync_state', 'video_selected',
      'video_stopped', 'video_ended', 'play', 'pause', 'seek',
      'streams_changed', 'ready_check_update', 'all_ready',
      'join_vote_started', 'join_vote_pending', 'join_vote_update',
      'join_vote_resolved', 'join_rejected',
      'binge_watch_state_changed', 'auto_advance_pending',
      'auto_advance_cancelled', 'auto_advance_fired', 'binge_finished',
    ] as const
    for (const e of events) socket.off(e)
    // Also drop the reconnect listener before re-registering, same
    // reasoning as the event list above.
    socket.off('connect')

    // Auto re-join on socket reconnect. The server evicts us from
    // party["users"] and the Socket.IO room on disconnect (see
    // backend/src/socket_handlers/connection.py:disconnect). Without
    // this, socket.io-client silently reconnects with a new sid that
    // belongs to no party -- pause/play events skip us in both
    // directions, exactly as reported. Because our client_id is stable
    // (localStorage) and lives in party["participants"], re-emitting
    // join_party takes the "known participant" fast path in party.py:
    // _replace_sid migrates state to the new sid, no late-joiner vote
    // fires, and the server sends a fresh sync_state.
    //
    // We use a store-local flag (initialConnectSeen) instead of just
    // "is partyId set?" because join() runs asynchronously after
    // setupListeners() -- if join() sets partyId + emits before the
    // very first `connect` fires, socket.io buffers the emit and then
    // this listener would fire ALSO and produce a duplicate join_party.
    // Skipping exactly one connect avoids that race.
    let initialConnectSeen = false
    socket.on('connect', () => {
      if (!initialConnectSeen) {
        initialConnectSeen = true
        return
      }
      if (!partyId.value || !username.value) return
      const avatar = useAvatarStore()
      const avatarUuid = avatar.uuid
      socket.emit('join_party', {
        party_id: partyId.value,
        username: username.value,
        client_id: getClientId(),
        avatar_uuid: avatarUuid,
      })
    })

    socket.on('user_joined', (data: any) => {
      users.value = data.users
      if (Array.isArray(data.members)) {
        const map: Record<string, string | null> = {}
        for (const m of data.members as MemberInfo[]) {
          map[m.username] = m.avatar_uuid ?? null
        }
        members.value = map
      }
    })

    socket.on('user_left', (data: any) => {
      users.value = data.users || []
      if (Array.isArray(data.members)) {
        const map: Record<string, string | null> = {}
        for (const m of data.members as MemberInfo[]) {
          map[m.username] = m.avatar_uuid ?? null
        }
        members.value = map
      }
    })

    // Avatar updates from anyone in the room: refresh the members map
    // so chat + participant list re-render without a page reload.
    socket.on('members_update', (data: any) => {
      if (Array.isArray(data.members)) {
        const map: Record<string, string | null> = {}
        for (const m of data.members as MemberInfo[]) {
          map[m.username] = m.avatar_uuid ?? null
        }
        members.value = map
      }
    })

    socket.on('sync_state', (data: any) => {
      currentVideo.value = data.current_video
      playbackState.value = data.playback_state
      // Per-user stream URL comes inside current_video for late joiners.
      // The backend offsets the transcode via StartTimeTicks to the current
      // playback time, so we record that offset -- the stream's time 0
      // corresponds to media position streamOffset.
      if (data.current_video?.stream_url) {
        myStreamUrl.value = data.current_video.stream_url
        streamOffset.value = data.playback_state?.time || 0
      } else {
        streamOffset.value = 0
      }
      if (data.binge_watch) {
        bingeWatch.value = {
          available: !!data.binge_watch.available,
          active: !!data.binge_watch.active,
        }
      }
      // Hydrate a running binge countdown so a rejoiner during the
      // countdown window sees the modal (and Cancel button). Without
      // this, the watchdog fires unattended and the selector loses
      // the ability to cancel the advance because the modal never
      // rendered on their client.
      const pa = data.pending_auto_advance
      if (pa && pa.deadline) {
        pendingAutoAdvance.value = {
          nextItemId: pa.next_item_id,
          nextTitle: pa.next_title,
          nextIndexNumber: pa.next_index_number ?? null,
          totalEpisodes: pa.total_episodes ?? 0,
          timeoutAt: new Date(pa.deadline).getTime(),
          countdownSeconds: pa.countdown_seconds ?? null,
        }
      }
    })

    socket.on('video_selected', (data: any) => {
      currentVideo.value = data.video
      // Initial video selection -- stream starts at 0
      streamOffset.value = 0
      // Each user gets their own stream URL
      if (data.video?.stream_url) {
        myStreamUrl.value = data.video.stream_url
      }
    })

    socket.on('video_stopped', () => {
      currentVideo.value = null
      myStreamUrl.value = null
      playbackState.value = { playing: false, time: 0, last_update: '' }
      readyCheckActive.value = false
    })

    socket.on('video_ended', () => {
      playbackState.value = { playing: false, time: 0, last_update: '' }
      readyCheckActive.value = false
    })

    socket.on('play', (data: any) => {
      playbackState.value.playing = true
      if (data.time !== undefined) {
        playbackState.value.time = data.time
      }
    })

    socket.on('pause', (data: any) => {
      playbackState.value.playing = false
      if (data.time !== undefined) {
        playbackState.value.time = data.time
      }
    })

    socket.on('seek', (data: any) => {
      playbackState.value.playing = !!data.playing
      if (data.time !== undefined) {
        playbackState.value.time = data.time
      }
    })

    socket.on('binge_watch_state_changed', (data: any) => {
      bingeWatch.value = {
        available: !!data.available,
        active: !!data.active,
      }
      // If the master toggle was just flipped off, any pending modal
      // is implicitly dismissed. The server also emits its own
      // auto_advance_cancelled in that case, but clearing here too
      // makes the UI safe even if events arrive out of order.
      if (!data.available) pendingAutoAdvance.value = null
    })

    socket.on('auto_advance_pending', (data: any) => {
      const deadline = data.deadline ? Date.parse(data.deadline) : Date.now() + 4000
      pendingAutoAdvance.value = {
        nextItemId: data.next_item_id,
        nextTitle: data.next_title,
        nextIndexNumber: data.next_index_number ?? null,
        totalEpisodes: data.total_episodes,
        timeoutAt: deadline,
        countdownSeconds: data.countdown_seconds ?? null,
      }
    })

    socket.on('auto_advance_cancelled', () => {
      pendingAutoAdvance.value = null
    })

    socket.on('auto_advance_fired', () => {
      // Modal collapses; the upcoming video_selected event will set the
      // new currentVideo and start the next stream.
      pendingAutoAdvance.value = null
    })

    socket.on('binge_finished', () => {
      // End of season -- consumer (PartyView) decides whether to show
      // a system message and reopen the library. The store just clears
      // any leftover pending state.
      pendingAutoAdvance.value = null
    })

    socket.on('streams_changed', (data: any) => {
      // Per-user: only this user receives their updated stream.
      // Backend restarts the transcode with StartTimeTicks=current_time,
      // so the new stream's time 0 maps to current_time media position.
      currentVideo.value = data.video
      if (data.video?.stream_url) {
        myStreamUrl.value = data.video.stream_url
      }
      if (data.current_time !== undefined) {
        playbackState.value.time = data.current_time
        streamOffset.value = data.current_time
      }
      // Preserve the play/pause state across the reload. The stream URL
      // change tears down the old <video> and attaches a new one; the
      // VideoPlayer only auto-resumes on MANIFEST_PARSED when
      // props.playing (bound to playbackState.playing) is true. Without
      // applying was_playing here, an audio/subtitle/quality swap made
      // while playing would reload into a paused player and never resume.
      if (data.was_playing !== undefined) {
        playbackState.value.playing = !!data.was_playing
      }
    })

    let readyCheckTimeout: ReturnType<typeof setTimeout> | null = null

    const clearReadyCheck = () => {
      readyCheckActive.value = false
      readyUsers.value = []
      waitingUsers.value = []
      if (readyCheckTimeout) {
        clearTimeout(readyCheckTimeout)
        readyCheckTimeout = null
      }
    }

    socket.on('ready_check_update', (data: any) => {
      readyCheckActive.value = true
      readyUsers.value = data.ready || []
      waitingUsers.value = data.waiting || []

      // Safety net: if the server never emits all_ready (e.g. a stale
      // user is stuck in expected_sids), dismiss the overlay after 15s
      // so users don't get permanently blocked
      if (readyCheckTimeout) clearTimeout(readyCheckTimeout)
      readyCheckTimeout = setTimeout(() => {
        if (readyCheckActive.value) {
          console.warn('[WP] Ready check timed out after 15s, dismissing overlay')
          clearReadyCheck()
        }
      }, 15000)
    })

    socket.on('all_ready', (data: any) => {
      if (data?.time !== undefined) {
        playbackState.value.time = data.time
      }
      if (data?.playing !== undefined) {
        playbackState.value.playing = !!data.playing
      }
      clearReadyCheck()
    })

    // ---------------------------------------------------------------------
    // Late-joiner vote listeners
    // ---------------------------------------------------------------------

    // Existing user receives the vote modal
    socket.on('join_vote_started', (data: any) => {
      const timeoutSeconds = data.timeout_seconds || 20
      pendingVote.value = {
        active: true,
        isPending: false,
        lateJoinerUsername: data.username || null,
        eligibleVoters: data.eligible_voters || [],
        votes: {},
        myVote: null,
        timeoutAt: Date.now() + timeoutSeconds * 1000,
        requiredMajority: data.required_majority || 1,
      }
    })

    // Late joiner receives the waiting room
    socket.on('join_vote_pending', (data: any) => {
      const timeoutSeconds = data.timeout_seconds || 20
      pendingVote.value = {
        active: true,
        isPending: true,
        lateJoinerUsername: username.value,
        eligibleVoters: data.eligible_voters || [],
        votes: {},
        myVote: null,
        timeoutAt: Date.now() + timeoutSeconds * 1000,
        requiredMajority: data.required_majority || 1,
      }
    })

    // Live vote updates -- everyone in the room receives these
    socket.on('join_vote_update', (data: any) => {
      if (!pendingVote.value) return
      pendingVote.value.votes = data.votes || {}
    })

    // Vote resolved: pass, fail, or cancelled
    socket.on('join_vote_resolved', (data: any) => {
      const wasPending = pendingVote.value?.isPending === true
      const result = data.result
      pendingVote.value = null

      if (result === 'fail' && wasPending) {
        // The late joiner was rejected. Hide this party on the index so
        // they are not repeatedly tempted to re-request it (captured
        // before leave() clears partyId), then clear local party state.
        hideParty(partyId.value)
        leave()
        // Router redirect is handled by the component watching `partyId`
      } else if (result === 'cancelled') {
        // The vote was cancelled (e.g. late joiner left). No action
        // needed for existing users beyond dismissing the modal.
      }
    })

    // Immediate rejection (e.g. another vote already in progress)
    socket.on('join_rejected', (_data: any) => {
      pendingVote.value = null
      // The caller (IndexView or PartyView) should observe this event
      // and show a toast. We just clear the local state here.
      leave()
    })
  }

  function setBingeWatchActive(active: boolean) {
    const socket = useSocketStore()
    if (!partyId.value) return
    socket.emit('set_binge_watch_active', {
      party_id: partyId.value, active,
    })
  }

  function cancelAutoAdvance() {
    const socket = useSocketStore()
    if (!partyId.value || !pendingAutoAdvance.value) return
    socket.emit('auto_advance_cancel', { party_id: partyId.value })
  }

  return {
    partyId, username, users, members, currentVideo, playbackState, userCount,
    myStreamUrl, streamOffset, readyCheckActive, readyUsers, waitingUsers,
    pendingVote,
    bingeWatch, pendingAutoAdvance,
    join, leave, setupListeners, submitVote,
    setBingeWatchActive, cancelAutoAdvance,
  }
})
