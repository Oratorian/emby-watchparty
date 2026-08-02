import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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
})
