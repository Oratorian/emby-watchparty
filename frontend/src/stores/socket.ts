import { defineStore } from 'pinia'
import { ref } from 'vue'
import { io, Socket } from 'socket.io-client'
import { APP_PREFIX } from '@/utils/appPrefix'
import type { ClientToServerEvents, ServerToClientEvents } from '@/types/socket'

export const useSocketStore = defineStore('socket', () => {
  const socket = ref<Socket<ServerToClientEvents, ClientToServerEvents> | null>(null)
  const connected = ref(false)
  const sid = ref<string | null>(null)
  // True once we've completed the initial handshake at least once.
  // Consumers use this to distinguish a cold connect ("first time")
  // from a reconnect ("we dropped and came back"), so re-join logic
  // only fires on the reconnect edge.
  const hasEverConnected = ref(false)
  const reconnecting = ref(false)
  const connectionError = ref<string | null>(null)
  const connectionRetryAfter = ref(0)
  let networkListenersInstalled = false
  let connectionRetryTimer: ReturnType<typeof setInterval> | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null

  function clearConnectionRetry() {
    if (connectionRetryTimer) clearInterval(connectionRetryTimer)
    if (reconnectTimer) clearTimeout(reconnectTimer)
    connectionRetryTimer = null
    reconnectTimer = null
    connectionRetryAfter.value = 0
  }

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

    if (!networkListenersInstalled) {
      window.addEventListener('offline', () => {
        reconnecting.value = true
      })
      window.addEventListener('online', () => {
        reconnecting.value = hasEverConnected.value && !connected.value
      })
      networkListenersInstalled = true
    }

    // Socket.IO's `path` is the URL path the client connects to. The
    // backend mounts the socket app under `${APP_PREFIX}/socket.io`, so
    // the client has to use the same. Empty APP_PREFIX collapses to
    // `/socket.io`, matching the no-proxy default.
    const s: Socket<ServerToClientEvents, ClientToServerEvents> = io('', {
      path: `${APP_PREFIX}/socket.io`,
      transports: ['websocket', 'polling'],
    })

    s.on('connect', () => {
      clearConnectionRetry()
      connectionError.value = null
      connected.value = true
      hasEverConnected.value = true
      reconnecting.value = false
    })

    s.on('connected', (data: { sid: string }) => {
      sid.value = data.sid
    })

    s.on('disconnect', () => {
      connected.value = false
      sid.value = null
      if (hasEverConnected.value) reconnecting.value = true
    })

    // Surface handshake failures so the UI does not silently hang when
    // the backend rejects the connection or the WS upgrade fails.
    s.on('connect_error', (err: Error & {
      data?: { code?: string; retry_after?: number }
    }) => {
      console.warn('Socket connect_error:', err.message)
      connectionError.value = err.message || 'Could not connect to the party.'
      if (err.data?.code !== 'rate_limited') return

      const retryAfter = Math.max(1, Math.ceil(err.data.retry_after || 1))
      clearConnectionRetry()
      connectionRetryAfter.value = retryAfter
      s.io.reconnection(false)
      connectionRetryTimer = setInterval(() => {
        connectionRetryAfter.value = Math.max(0, connectionRetryAfter.value - 1)
      }, 1000)
      reconnectTimer = setTimeout(() => {
        if (connectionRetryTimer) clearInterval(connectionRetryTimer)
        connectionRetryTimer = null
        reconnectTimer = null
        connectionRetryAfter.value = 0
        s.io.reconnection(true)
        s.connect()
      }, retryAfter * 1000)
    })

    socket.value = s
  }

  function disconnect() {
    clearConnectionRetry()
    socket.value?.disconnect()
    socket.value = null
    connected.value = false
    reconnecting.value = false
    connectionError.value = null
    sid.value = null
  }

  function emit<K extends keyof ClientToServerEvents>(
    event: K,
    ...args: Parameters<ClientToServerEvents[K]>
  ) {
    socket.value?.emit(event, ...args)
  }

  function on<K extends keyof ServerToClientEvents>(
    event: K,
    handler: ServerToClientEvents[K],
  ) {
    socket.value?.on(event as never, handler as never)
  }

  function off<K extends keyof ServerToClientEvents>(
    event: K,
    handler?: ServerToClientEvents[K],
  ) {
    socket.value?.off(event as never, handler as never)
  }

  return {
    socket,
    connected,
    sid,
    hasEverConnected,
    reconnecting,
    connectionError,
    connectionRetryAfter,
    connect,
    disconnect,
    emit,
    on,
    off,
  }
})
