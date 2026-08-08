import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from '@/api/client'
import { usePartyStore } from './party'
import { useSocketStore } from './socket'

describe('party socket listeners', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('keeps one members_update listener across repeated setup', () => {
    const handlers = new Map<string, Set<unknown>>()
    const socket = useSocketStore()
    vi.spyOn(socket, 'on').mockImplementation(((event: string, handler: unknown) => {
      const eventHandlers = handlers.get(event) ?? new Set()
      eventHandlers.add(handler)
      handlers.set(event, eventHandlers)
    }) as never)
    vi.spyOn(socket, 'off').mockImplementation(((event: string) => {
      handlers.delete(event)
    }) as never)

    const party = usePartyStore()
    party.setupListeners()
    party.setupListeners()

    expect(handlers.get('members_update')?.size).toBe(1)
  })

  it('surfaces a limited session bind without retrying the mutating request', async () => {
    vi.useFakeTimers()
    const socket = useSocketStore()
    vi.spyOn(socket, 'emit').mockImplementation(() => undefined)
    const join = vi.spyOn(api, 'joinParty').mockRejectedValue(new ApiError(
      429,
      'Too many party join attempts. Try again in 42 seconds.',
      { code: 'rate_limited', retry_after: 42 },
      'rate_limited',
      42,
    ))

    const party = usePartyStore()
    await party.join('ABC123', 'Alice')

    expect(join).toHaveBeenCalledTimes(1)
    expect(party.sessionError).toBe(
      'Too many party join attempts. Try again in 42 seconds.',
    )
    expect(party.sessionRetryAfter).toBe(42)
    vi.useRealTimers()
  })
})
