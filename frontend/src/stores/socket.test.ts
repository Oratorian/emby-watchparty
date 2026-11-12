import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { io } from 'socket.io-client'

const socketHarness = vi.hoisted(() => {
  const handlers = new Map<string, (value?: unknown) => void>()
  return {
    handlers,
    socket: {
      on: vi.fn((event: string, handler: (value?: unknown) => void) => {
        handlers.set(event, handler)
      }),
      emit: vi.fn(),
      off: vi.fn(),
      disconnect: vi.fn(),
      connect: vi.fn(),
      io: { reconnection: vi.fn() },
    },
  }
})

vi.mock('socket.io-client', () => ({ io: vi.fn(() => socketHarness.socket) }))

import { useSocketStore } from './socket'

describe('socket connection rate limits', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    socketHarness.handlers.clear()
    setActivePinia(createPinia())
  })

  it('shows the refusal, pauses reconnects, then reconnects after Retry-After', () => {
    const store = useSocketStore()
    store.connect()
    expect(socketHarness.socket.connect).toHaveBeenCalledTimes(1)
    const error = Object.assign(new Error(
      'Too many connection attempts. Try again in 2 seconds.',
    ), { data: { code: 'rate_limited', retry_after: 2 } })

    socketHarness.handlers.get('connect_error')!(error)

    expect(store.connectionError).toBe(error.message)
    expect(store.connectionRetryAfter).toBe(2)
    expect(socketHarness.socket.io.reconnection).toHaveBeenCalledWith(false)

    vi.advanceTimersByTime(2000)

    expect(socketHarness.socket.io.reconnection).toHaveBeenLastCalledWith(true)
    expect(socketHarness.socket.connect).toHaveBeenCalledTimes(2)
    expect(store.connectionRetryAfter).toBe(0)
    vi.useRealTimers()
  })

  it('does not surface raw engine.io text on an ordinary handshake failure', () => {
    const store = useSocketStore()
    store.connect()

    // engine.io fires connect_error for every failed transport probe, with a
    // library string as the message. Assigning it unconditionally put "xhr
    // poll error" into an assertive red banner during routine churn.
    socketHarness.handlers.get('connect_error')!(new Error('xhr poll error'))

    expect(store.connectionError).toBeNull()
    expect(store.connectionRetryAfter).toBe(0)
    expect(socketHarness.socket.io.reconnection).not.toHaveBeenCalledWith(false)
  })

  it('reports a lost connection in its own words once the party was joined', () => {
    const store = useSocketStore()
    store.connect()
    socketHarness.handlers.get('connect')!()

    socketHarness.handlers.get('connect_error')!(new Error('websocket error'))

    expect(store.connectionError).toBe('Lost connection to the party. Reconnecting…')
    expect(store.connectionError).not.toContain('websocket error')
  })

  it('prepares listeners without starting a cookie handshake', () => {
    const store = useSocketStore()
    store.prepare()
    const listener = vi.fn()
    store.on('chat_message', listener)
    store.prepare()

    expect(io).toHaveBeenCalledTimes(1)
    expect(io).toHaveBeenCalledWith('', expect.objectContaining({ autoConnect: false }))
    expect(socketHarness.socket.connect).not.toHaveBeenCalled()
    expect(socketHarness.socket.on).toHaveBeenCalledWith('chat_message', listener)
  })

  it('refreshes the handshake on the same instance and flushes exactly one latest join', async () => {
    const store = useSocketStore()
    store.prepare()
    const listener = vi.fn()
    store.on('chat_message', listener)
    const payload = { party_id: 'ROOM', username: 'Alice', client_id: 'client-1', avatar_uuid: null }
    store.beginSessionBinding()
    store.connect({ freshSession: true })
    store.emit('join_party', { ...payload, username: 'Old attempt' })
    expect(socketHarness.socket.emit).not.toHaveBeenCalled()

    // A manual retry replaces the pending explicit join, rather than putting
    // another entry into Socket.IO's send buffer.
    store.beginSessionBinding()
    store.connect({ freshSession: true })
    store.emit('join_party', payload)
    socketHarness.handlers.get('connect')!()

    expect(io).toHaveBeenCalledTimes(1)
    expect(socketHarness.socket.off).not.toHaveBeenCalled()
    expect(socketHarness.socket.emit).toHaveBeenCalledExactlyOnceWith('join_party', payload)
    expect(store.sessionRebinding).toBe(true)
    await Promise.resolve()
    expect(store.sessionRebinding).toBe(false)
  })

  it('does not flush an older join or clear the binding guard while HTTP is pending', async () => {
    const store = useSocketStore()
    store.prepare()
    store.beginSessionBinding()
    socketHarness.handlers.get('connect')!()
    await Promise.resolve()
    expect(store.sessionRebinding).toBe(true)
    expect(socketHarness.socket.emit).not.toHaveBeenCalled()
    store.cancelSessionBinding()
    expect(store.sessionRebinding).toBe(false)
  })
})
