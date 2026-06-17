import { defineStore } from 'pinia'
import { ref } from 'vue'
import { io, Socket } from 'socket.io-client'
import { APP_PREFIX } from '@/utils/appPrefix'

export const useSocketStore = defineStore('socket', () => {
  const socket = ref<Socket | null>(null)
  const connected = ref(false)
  const sid = ref<string | null>(null)

  function connect() {
    // Skip if a socket already exists for this Pinia singleton, even
    // when it has not finished the handshake yet. The old guard only
    // checked `connected`, so a second connect() call during the brief
    // mid-handshake window (Vue dev double-mounts, route re-entries,
    // HMR re-runs of setup) created a second WebSocket. Listeners
    // ended up registered on one socket while events arrived on the
    // other, which surfaced as sync_state being "lost" on late joiners.
    // socket.io-client auto-reconnects on its own, so we only ever
    // need to create a single socket per app lifetime.
    if (socket.value) return

    // Socket.IO's `path` is the URL path the client connects to. The
    // backend mounts the socket app under `${APP_PREFIX}/socket.io`, so
    // the client has to use the same. Empty APP_PREFIX collapses to
    // `/socket.io`, matching the no-proxy default.
    const s = io('', {
      path: `${APP_PREFIX}/socket.io`,
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

    // Surface handshake failures so the UI does not silently hang when
    // the backend rejects the connection or the WS upgrade fails.
    s.on('connect_error', (err: Error) => {
      console.warn('Socket connect_error:', err.message)
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
