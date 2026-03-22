import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useSocketStore } from './socket'

export const usePartyStore = defineStore('party', () => {
  const partyId = ref<string | null>(null)
  const username = ref<string | null>(null)
  const users = ref<string[]>([])
  const currentVideo = ref<any>(null)
  const playbackState = ref({ playing: false, time: 0, last_update: '' })

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
    playbackState.value = { playing: false, time: 0, last_update: '' }
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
    })

    socket.on('video_selected', (data: any) => {
      currentVideo.value = data.video
    })

    socket.on('video_stopped', () => {
      currentVideo.value = null
      playbackState.value = { playing: false, time: 0, last_update: '' }
    })

    socket.on('video_ended', () => {
      playbackState.value = { playing: false, time: 0, last_update: '' }
    })

    socket.on('streams_changed', (data: any) => {
      currentVideo.value = data.video
    })
  }

  return {
    partyId, username, users, currentVideo, playbackState, userCount,
    join, leave, setupListeners,
  }
})
