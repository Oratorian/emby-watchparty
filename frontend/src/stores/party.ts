import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useSocketStore } from './socket'
import { useAvatarStore } from './avatar'
import { useAuthStore } from './auth'
import { ApiError, api } from '@/api/client'
import type { ServerToClientPayloads } from '@/types/socket.generated'
import { detectVideoCodecs } from '@/utils/videoCodecs'

export interface MemberInfo {
  username: string
  avatar_uuid?: string | null
}

type VideoInfo = ServerToClientPayloads['video_selected']['video']
type PendingVideoSelection = NonNullable<ServerToClientPayloads['sync_state']['pending_video_selection']>

const CLIENT_ID_STORAGE_KEY = 'emby-watchparty-client-id'
const TAB_CLIENT_ID_STORAGE_KEY = 'emby-watchparty-tab-client-id'
const IDENTITY_IN_USE_MESSAGE = 'Participant identity is already in use'

// The session cookie holds exactly one party id, and cookies are shared
// across every tab in a browser profile. So a second tab joining a
// *different* party silently repoints it, and the first tab's requests
// start failing: 401 once its cookie's party stops matching the stream
// token's, or 423 while the newly joined party has no host token yet.
// The video simply stops with nothing on screen to explain it.
// Announcing the binding lets the superseded tab say so instead.
const PARTY_BINDING_CHANNEL = 'emby-watchparty-party-binding'

function getClientId(): string {
  const tabClientId = sessionStorage.getItem(TAB_CLIENT_ID_STORAGE_KEY)
  if (tabClientId) return tabClientId
  let clientId = localStorage.getItem(CLIENT_ID_STORAGE_KEY)
  if (clientId) return clientId

  clientId = crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`
  localStorage.setItem(CLIENT_ID_STORAGE_KEY, clientId)
  return clientId
}

function rotateClientIdForTab(): string {
  const clientId = crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`
  sessionStorage.setItem(TAB_CLIENT_ID_STORAGE_KEY, clientId)
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
  const currentVideo = ref<VideoInfo | null>(null)
  const pendingVideoSelection = ref<PendingVideoSelection | null>(null)
  const videoSelectionIssue = ref<{
    message: string
    failedUsers: string[]
    affected: boolean
    selectionId: string
  } | null>(null)
  const playbackState = ref({ playing: false, time: 0, last_update: '' })
  const myStreamUrl = ref<string | null>(null)
  // Media time at which this user's stream begins. Backend sets
  // StartTimeTicks to this value when the user joins mid-playback, so
  // their HLS stream's currentTime=0 corresponds to media position streamOffset.
  const streamOffset = ref(0)
  const readyCheckActive = ref(false)
  const readyUsers = ref<string[]>([])
  const waitingUsers = ref<string[]>([])

  // Non-null when the party-bound session cookie could not be minted.
  // Every protected HTTP route depends on that cookie, /hls included, so
  // without it playback 401s on every segment while chat and the
  // participant list keep working over the socket -- i.e. the party
  // looks healthy and only the video is dead. That used to be swallowed
  // silently; surfacing it is the difference between a self-service
  // retry and an unreproducible "video won't load for one person".
  const sessionError = ref<string | null>(null)
  // Set only when the server confirms the party is gone, which is a different
  // situation from "could not authenticate" and needs a different answer.
  // Retrying a party that no longer exists can never succeed, so offering a
  // Retry button leaves the viewer pressing it forever. A restarted server and
  // a pasted stale link both land here.
  const partyMissing = ref(false)
  const sessionRetrying = ref(false)
  const sessionRetryAfter = ref(0)
  let sessionRetryTimer: ReturnType<typeof setInterval> | null = null

  function clearSessionRetryCountdown() {
    if (sessionRetryTimer) clearInterval(sessionRetryTimer)
    sessionRetryTimer = null
    sessionRetryAfter.value = 0
  }

  function startSessionRetryCountdown(seconds: number) {
    clearSessionRetryCountdown()
    sessionRetryAfter.value = Math.max(1, Math.ceil(seconds))
    sessionRetryTimer = setInterval(() => {
      sessionRetryAfter.value = Math.max(0, sessionRetryAfter.value - 1)
      if (sessionRetryAfter.value === 0) clearSessionRetryCountdown()
    }, 1000)
  }

  // Set to the other party's code when a different tab in this browser
  // takes over the session cookie. See PARTY_BINDING_CHANNEL above.
  const supersededBy = ref<string | null>(null)
  let bindingChannel: BroadcastChannel | null = null

  /**
   * Announce which party this tab is bound to, and listen for others.
   *
   * A tab never receives its own postMessage, so hearing a party_id that
   * differs from ours means another tab has just repointed the shared
   * cookie and this tab's playback is about to start failing.
   *
   * Degrades silently where BroadcastChannel is unavailable: the tab
   * behaves exactly as it did before this existed.
   */
  function announceBinding(id: string) {
    if (typeof BroadcastChannel === 'undefined') return
    if (!bindingChannel) {
      bindingChannel = new BroadcastChannel(PARTY_BINDING_CHANNEL)
      bindingChannel.onmessage = (event) => {
        const other = event.data?.partyId
        // Same party in two tabs is fine, both point the cookie at the
        // same place. Only a different party is a takeover.
        if (other && partyId.value && other !== partyId.value) {
          supersededBy.value = other
        }
      }
    }
    bindingChannel.postMessage({ partyId: id })
  }

  // Binge-watch state. `available` is the admin master toggle; when
  // false, the control-strip button is hidden entirely. `active` is
  // the host's per-party opt-in (only meaningful when available=true).
  // Both arrive on sync_state at join and on binge_watch_state_changed
  // when the admin or host toggles them.
  const bingeWatch = ref<{ available: boolean; active: boolean }>({
    available: false, active: false,
  })

  // Whether this party is kept off the public index listing. Unlisted, not
  // private: the code still works for anyone who has it.
  const hidden = ref(false)

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
    const normalisedId = id.toUpperCase()
    partyId.value = normalisedId
    username.value = name
    // Cleared before the first await, not just on a successful bind:
    // going straight from a dead party to a live one would otherwise leave
    // the "no longer exists" card up for the whole join, avatar load
    // included -- and leave it frozen, since the countdown watcher fires on
    // the transition into missing, which already happened.
    partyMissing.value = false
    let clientId = getClientId()
    // Load the persisted avatar id (IndexedDB or localStorage) so it
    // can ride along on the join. Safe to call repeatedly.
    if (!avatar.uuid) {
      try { await avatar.load() } catch { /* ignore */ }
    }
    const avatarUuid = avatar.uuid
    supersededBy.value = null
    // Announce only once the cookie is actually bound. A tab that failed
    // to bind never repointed anything, so it must not make a healthy
    // tab believe it has been superseded.
    let bound = await bindSession(clientId, name, avatarUuid)
    if (!bound && sessionError.value === IDENTITY_IN_USE_MESSAGE) {
      clientId = rotateClientIdForTab()
      bound = await bindSession(clientId, name, avatarUuid)
    }
    if (bound) {
      announceBinding(normalisedId)
      socket.emit('join_party', {
        party_id: partyId.value,
        username: name,
        client_id: clientId,
        avatar_uuid: avatarUuid,
        video_codecs: detectVideoCodecs(),
      })
    }
  }

  // Remembered so retrySession() can re-run the join without the caller
  // having to thread the original arguments back through the UI.
  let lastJoinArgs: { clientId: string; name: string; avatarUuid: string | null } | null = null

  /**
   * Mint the party-bound session cookie.
   *
   * The cookie authenticates every protected HTTP route and the socket
   * handshake. One transient retry covers the common case (a blip while
   * the tab is waking, a server still coming up); anything past that is
   * surfaced rather than swallowed, because socket-only auth is no
   * longer enough to play video.
   */
  /**
   * Ask the server whether the party is actually gone.
   *
   * A join can fail for reasons that are worth retrying (a blip, a rate
   * limit, a server still coming up) and for one that never is. Only the
   * server can tell them apart, and a failure to reach it is not evidence
   * either way, so anything other than a definite "no" leaves the normal
   * retry path in place.
   */
  function setHidden(next: boolean) {
    if (!partyId.value) return
    // Optimistic, then corrected by the broadcast. The server is the
    // authority; a refused toggle (non-host) simply never echoes back.
    hidden.value = next
    useSocketStore().emit('set_party_hidden', { party_id: partyId.value, hidden: next })
  }

  async function checkPartyMissing() {
    if (!partyId.value) return
    try {
      const { exists } = await api.partyExists(partyId.value)
      partyMissing.value = !exists
    } catch {
      // Could not ask. Assume it is still there rather than sending someone
      // back to the index over a network blip.
      partyMissing.value = false
    }
  }

  async function bindSession(clientId: string, name: string, avatarUuid: string | null) {
    lastJoinArgs = { clientId, name, avatarUuid }
    const auth = useAuthStore()
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const result = await api.joinParty(partyId.value!, clientId, name || 'Guest', avatarUuid)
        if (!result.success) {
          sessionError.value = result.message || 'Could not join the party.'
          // Asked rather than inferred from the message text, which is prose
          // the server may reword at any time. This endpoint exists to answer
          // exactly this question.
          await checkPartyMissing()
          return false
        }
        // The cookie is now bound. Re-read auth state so partyUnlocked
        // and hostUsername reflect this party, not the empty pre-join
        // status. Otherwise late joiners briefly render "Party is
        // locked" until the next host_changed event (which never fires
        // for a party that was already unlocked when they joined).
        try { await auth.refresh() } catch { /* ignore */ }
        sessionError.value = null
        partyMissing.value = false
        clearSessionRetryCountdown()
        return true
      } catch (e: unknown) {
        if (e instanceof ApiError && e.code === 'rate_limited') {
          sessionError.value = e.message
          startSessionRetryCountdown(e.retryAfter || 1)
          break
        }
        if (attempt === 0) {
          await new Promise((r) => setTimeout(r, 600))
          continue
        }
        // Only an ApiError carries a message the server wrote for a human.
        // A fetch-layer failure gives "Failed to fetch", which explains
        // nothing to a viewer and displaces the banner's own guidance.
        sessionError.value = e instanceof ApiError ? e.message : 'Could not reach the server.'
        await checkPartyMissing()
      }
    }
    return false
  }

  /** Re-attempt the session cookie after a visible failure. */
  async function retrySession() {
    if (
      !lastJoinArgs || !partyId.value || sessionRetrying.value
      || sessionRetryAfter.value > 0
    ) return false
    sessionRetrying.value = true
    try {
      const { clientId, name, avatarUuid } = lastJoinArgs
      const ok = await bindSession(clientId, name, avatarUuid)
      if (ok) {
        // The cookie now points here, so other tabs need to know.
        announceBinding(partyId.value)
        // Re-announce over the socket so the server re-binds this sid
        // and re-issues a stream URL against the now-valid session.
        useSocketStore().emit('join_party', {
          party_id: partyId.value,
          username: name,
          client_id: clientId,
          avatar_uuid: avatarUuid,
          video_codecs: detectVideoCodecs(),
        })
      }
      return ok
    } finally {
      sessionRetrying.value = false
    }
  }

  async function leave() {
    if (!partyId.value) return
    const socket = useSocketStore()
    const auth = useAuthStore()
    socket.emit('leave_party', { party_id: partyId.value })
    // Drop the party-bound session cookie too. Without this,
    // /api/v2/auth/status keeps returning the old party_id and the
    // "Back to Party" link on /admin or /version would route the user
    // into a party they just left.
    try { await api.leaveParty() } catch { /* best effort */ }
    try { await auth.refresh() } catch { /* ignore */ }
    partyId.value = null
    users.value = []
    currentVideo.value = null
    pendingVideoSelection.value = null
    videoSelectionIssue.value = null
    myStreamUrl.value = null
    streamOffset.value = 0
    playbackState.value = { playing: false, time: 0, last_update: '' }
    readyCheckActive.value = false
    readyUsers.value = []
    waitingUsers.value = []
    pendingVote.value = null
    sessionError.value = null
    clearSessionRetryCountdown()
    supersededBy.value = null
    // This store outlives PartyView. Left set, the next party the viewer
    // opens renders the "no longer exists" card on mount -- and renders it
    // frozen, because the watcher that drives the countdown only fires on a
    // transition into `missing`, which already happened.
    partyMissing.value = false
    hidden.value = false
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
      'video_selection_started', 'video_selection_failed', 'video_selection_cancelled',
      'video_stopped', 'video_ended', 'play', 'pause', 'seek',
      'streams_changed', 'members_update', 'ready_check_update', 'all_ready',
      'binge_watch_state_changed', 'party_visibility_changed', 'auto_advance_pending',
      'auto_advance_cancelled', 'auto_advance_fired', 'binge_finished',
    ] as const
    for (const e of events) socket.off(e)
    socket.on('user_joined', (data: ServerToClientPayloads['user_joined']) => {
      users.value = data.users ?? []
      if (Array.isArray(data.members)) {
        const map: Record<string, string | null> = {}
        for (const m of data.members as MemberInfo[]) {
          map[m.username] = m.avatar_uuid ?? null
        }
        members.value = map
      }
    })

    socket.on('user_left', (data: ServerToClientPayloads['user_left']) => {
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
    socket.on('members_update', (data: ServerToClientPayloads['members_update']) => {
      if (Array.isArray(data.members)) {
        const map: Record<string, string | null> = {}
        for (const m of data.members as MemberInfo[]) {
          map[m.username] = m.avatar_uuid ?? null
        }
        members.value = map
      }
    })

    socket.on('sync_state', (data: ServerToClientPayloads['sync_state']) => {
      currentVideo.value = data.current_video ?? null
      pendingVideoSelection.value = data.pending_video_selection ?? null
      videoSelectionIssue.value = null
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
      hidden.value = !!data.hidden
      // Hydrate a running binge countdown so a rejoiner during the
      // countdown window sees the modal (and Cancel button). Without
      // this, the watchdog fires unattended and the selector loses
      // the ability to cancel the advance because the modal never
      // rendered on their client.
      const pa = data.pending_auto_advance
      if (pa && pa.deadline) {
        pendingAutoAdvance.value = {
          nextItemId: pa.next_item_id ?? '',
          nextTitle: pa.next_title ?? 'Next episode',
          nextIndexNumber: pa.next_index_number ?? null,
          totalEpisodes: pa.total_episodes ?? 0,
          timeoutAt: new Date(pa.deadline).getTime(),
          countdownSeconds: pa.countdown_seconds ?? null,
        }
      }
    })

    socket.on('video_selected', (data: ServerToClientPayloads['video_selected']) => {
      currentVideo.value = data.video
      pendingVideoSelection.value = null
      videoSelectionIssue.value = null
      // Initial video selection -- stream starts at 0
      streamOffset.value = 0
      // Each user gets their own stream URL
      if (data.video?.stream_url) {
        myStreamUrl.value = data.video.stream_url
      }
    })

    socket.on('video_selection_started', (data: ServerToClientPayloads['video_selection_started']) => {
      pendingVideoSelection.value = data.selection
      videoSelectionIssue.value = null
    })

    socket.on('video_selection_failed', (data: ServerToClientPayloads['video_selection_failed']) => {
      videoSelectionIssue.value = {
        message: data.message,
        failedUsers: data.failed_users || [],
        affected: data.affected !== false,
        selectionId: data.selection.selection_id,
      }
      if (data.affected) pendingVideoSelection.value = data.selection
    })

    socket.on('video_selection_cancelled', () => {
      pendingVideoSelection.value = null
      videoSelectionIssue.value = null
      currentVideo.value = null
      myStreamUrl.value = null
      playbackState.value = { playing: false, time: 0, last_update: '' }
      readyCheckActive.value = false
    })

    socket.on('video_stopped', () => {
      currentVideo.value = null
      pendingVideoSelection.value = null
      videoSelectionIssue.value = null
      myStreamUrl.value = null
      playbackState.value = { playing: false, time: 0, last_update: '' }
      readyCheckActive.value = false
    })

    socket.on('video_ended', () => {
      playbackState.value = { playing: false, time: 0, last_update: '' }
      readyCheckActive.value = false
    })

    socket.on('play', (data: ServerToClientPayloads['play']) => {
      playbackState.value.playing = true
      if (data.time !== undefined) {
        playbackState.value.time = data.time
      }
    })

    socket.on('pause', (data: ServerToClientPayloads['pause']) => {
      playbackState.value.playing = false
      if (data.time !== undefined) {
        playbackState.value.time = data.time
      }
    })

    socket.on('seek', (data: ServerToClientPayloads['seek']) => {
      playbackState.value.playing = !!data.playing
      if (data.time !== undefined) {
        playbackState.value.time = data.time
      }
    })

    // Broadcast to the room rather than the caller, so a host with the party
    // open in two tabs does not leave a stale switch in the other one.
    socket.on('party_visibility_changed', (data: ServerToClientPayloads['party_visibility_changed']) => {
      hidden.value = !!data.hidden
    })

    socket.on('binge_watch_state_changed', (data: ServerToClientPayloads['binge_watch_state_changed']) => {
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

    socket.on('auto_advance_pending', (data: ServerToClientPayloads['auto_advance_pending']) => {
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

    socket.on('streams_changed', (data: ServerToClientPayloads['streams_changed']) => {
      // Per-user: only this user receives their updated stream.
      // `current_time` is the position the backend actually started the new
      // transcode at, so this stream's time 0 maps onto it. It is the party
      // clock in the normal case, but a switch to a version shorter than the
      // current position is clamped to land inside the new source, and the
      // offset has to follow the stream rather than the clock.
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

    socket.on('ready_check_update', (data: ServerToClientPayloads['ready_check_update']) => {
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

    socket.on('all_ready', (data: ServerToClientPayloads['all_ready']) => {
      if (data?.time !== undefined) {
        playbackState.value.time = data.time
      }
      if (data?.playing !== undefined) {
        playbackState.value.playing = !!data.playing
      }
      clearReadyCheck()
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

  function beginVideoSelection(selection: PendingVideoSelection) {
    pendingVideoSelection.value = selection
    videoSelectionIssue.value = null
  }

  function retryVideoSelection() {
    const selectionId = pendingVideoSelection.value?.selection_id
      || videoSelectionIssue.value?.selectionId
    if (!partyId.value || !selectionId) return
    useSocketStore().emit('retry_video_selection', {
      party_id: partyId.value,
      selection_id: selectionId,
    })
  }

  function cancelVideoSelection() {
    if (!partyId.value || !pendingVideoSelection.value) return
    useSocketStore().emit('cancel_video_selection', {
      party_id: partyId.value,
      selection_id: pendingVideoSelection.value.selection_id,
    })
  }

  return {
    partyId, username, users, members, currentVideo, pendingVideoSelection,
    videoSelectionIssue, playbackState, userCount,
    myStreamUrl, streamOffset, readyCheckActive, readyUsers, waitingUsers,
    pendingVote,
    bingeWatch, pendingAutoAdvance, hidden, setHidden,
    sessionError, partyMissing, sessionRetrying, sessionRetryAfter, supersededBy,
    join, leave, setupListeners, submitVote, retrySession,
    setBingeWatchActive, cancelAutoAdvance, beginVideoSelection,
    retryVideoSelection, cancelVideoSelection,
  }
})
