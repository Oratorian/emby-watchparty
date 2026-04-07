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
  const readyCheckActive = ref(false)
  const readyUsers = ref<string[]>([])
  const waitingUsers = ref<string[]>([])

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
    playbackState.value = { playing: false, time: 0, last_update: '' }
    readyCheckActive.value = false
    readyUsers.value = []
    waitingUsers.value = []
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
      // Per-user stream URL comes inside current_video for late joiners
      if (data.current_video?.stream_url) {
        myStreamUrl.value = data.current_video.stream_url
      }
    })

    socket.on('video_selected', (data: any) => {
      currentVideo.value = data.video
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

    socket.on('streams_changed', (data: any) => {
      // Per-user: only this user receives their updated stream
      currentVideo.value = data.video
      if (data.video?.stream_url) {
        myStreamUrl.value = data.video.stream_url
      }
      if (data.current_time !== undefined) {
        playbackState.value.time = data.current_time
      }
    })

    socket.on('ready_check_update', (data: any) => {
      readyCheckActive.value = true
      readyUsers.value = data.ready || []
      waitingUsers.value = data.waiting || []
    })

    socket.on('all_ready', () => {
      readyCheckActive.value = false
      readyUsers.value = []
      waitingUsers.value = []
    })
  }

  return {
    partyId, username, users, currentVideo, playbackState, userCount,
    myStreamUrl, readyCheckActive, readyUsers, waitingUsers,
    join, leave, setupListeners,
  }
})
