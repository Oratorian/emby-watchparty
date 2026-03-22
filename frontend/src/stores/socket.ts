import { defineStore } from 'pinia'
import { ref } from 'vue'
import { io, Socket } from 'socket.io-client'

export const useSocketStore = defineStore('socket', () => {
  const socket = ref<Socket | null>(null)
  const connected = ref(false)
  const sid = ref<string | null>(null)

  function connect() {
    if (socket.value?.connected) return

    const s = io('', {
      path: '/socket.io',
      transports: ['websocket', 'polling'],
    })

    s.on('connect', () => {
      connected.value = true
    })

    s.on('connected', (data: { sid: string }) => {
      sid.value = data.sid
    })

    s.on('disconnect', () => {
      connected.value = false
      sid.value = null
    })

    socket.value = s
  }

  function disconnect() {
    socket.value?.disconnect()
    socket.value = null
    connected.value = false
    sid.value = null
  }

  function emit(event: string, data: any) {
    socket.value?.emit(event, data)
  }

  function on(event: string, handler: (...args: any[]) => void) {
    socket.value?.on(event, handler)
  }

  function off(event: string, handler?: (...args: any[]) => void) {
    socket.value?.off(event, handler)
  }

  return { socket, connected, sid, connect, disconnect, emit, on, off }
})
