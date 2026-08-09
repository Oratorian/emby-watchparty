import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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

vi.mock('socket.io-client', () => ({ io: () => socketHarness.socket }))

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
    const error = Object.assign(new Error(
      'Too many connection attempts. Try again in 2 seconds.',
    ), { data: { code: 'rate_limited', retry_after: 2 } })

    socketHarness.handlers.get('connect_error')!(error)

    expect(store.connectionError).toBe(error.message)
    expect(store.connectionRetryAfter).toBe(2)
    expect(socketHarness.socket.io.reconnection).toHaveBeenCalledWith(false)

    vi.advanceTimersByTime(2000)

    expect(socketHarness.socket.io.reconnection).toHaveBeenLastCalledWith(true)
    expect(socketHarness.socket.connect).toHaveBeenCalledTimes(1)
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
})
