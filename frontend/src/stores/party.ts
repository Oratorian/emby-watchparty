import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useSocketStore } from './socket'

export const usePartyStore = defineStore('party', () => {
  const partyId = ref<string | null>(null)
  const username = ref<string | null>(null)
  const users = ref<string[]>([])
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

  function join(id: string, name: string) {
    const socket = useSocketStore()
    partyId.value = id.toUpperCase()
    username.value = name
    socket.emit('join_party', { party_id: partyId.value, username: name })
  }

  function leave() {
    if (!partyId.value) return
    const socket = useSocketStore()
    socket.emit('leave_party', { party_id: partyId.value })
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

    socket.on('user_joined', (data: any) => {
      users.value = data.users
    })

    socket.on('user_left', (data: any) => {
      users.value = data.users || []
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

    socket.on('all_ready', () => {
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
        // The late joiner was rejected -- clear local party state
        // and redirect home.
        leave()
        // Router redirect is handled by the component watching `partyId`
      } else if (result === 'cancelled') {
        // The vote was cancelled (e.g. late joiner left). No action
        // needed for existing users beyond dismissing the modal.
      }
    })

    // Immediate rejection (e.g. another vote already in progress)
    socket.on('join_rejected', (data: any) => {
      pendingVote.value = null
      // The caller (IndexView or PartyView) should observe this event
      // and show a toast. We just clear the local state here.
      leave()
    })
  }

  return {
    partyId, username, users, currentVideo, playbackState, userCount,
    myStreamUrl, streamOffset, readyCheckActive, readyUsers, waitingUsers,
    pendingVote,
    join, leave, setupListeners, submitVote,
  }
})
