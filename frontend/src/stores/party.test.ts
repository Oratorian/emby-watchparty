import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from '@/api/client'
import { usePartyStore } from './party'
import { useSocketStore } from './socket'

describe('party socket listeners', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    sessionStorage.clear()
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

  it('tracks selection start, failure, retry, and cancellation', () => {
    const handlers = new Map<string, (data: never) => void>()
    const socket = useSocketStore()
    vi.spyOn(socket, 'on').mockImplementation(((event: string, handler: (data: never) => void) => {
      handlers.set(event, handler)
    }) as never)
    vi.spyOn(socket, 'off').mockImplementation((() => undefined) as never)
    const emit = vi.spyOn(socket, 'emit').mockImplementation(() => undefined)
    const party = usePartyStore()
    party.partyId = 'B39AZ'
    party.setupListeners()
    const selection = {
      selection_id: 'selection-1', item_id: 'movie-1', title: 'Fake Movie', overview: '',
      status: 'preparing', selected_by: 'client-1', selected_by_username: 'Alice',
      production_year: 2024, run_time_seconds: 3600, item_type: 'Movie',
      series_name: null, season_number: null, episode_number: null,
      started_at: new Date().toISOString(), error: null,
    }

    handlers.get('video_selection_started')?.({ selection } as never)
    expect(party.pendingVideoSelection?.selection_id).toBe('selection-1')
    handlers.get('video_selection_failed')?.({
      selection: { ...selection, status: 'failed', error: 'Could not start.' },
      message: 'Could not start.', failed_users: ['Alice'], affected: true,
    } as never)
    expect(party.pendingVideoSelection?.status).toBe('failed')
    expect(party.videoSelectionIssue?.failedUsers).toEqual(['Alice'])

    party.retryVideoSelection()
    expect(emit).toHaveBeenCalledWith('retry_video_selection', {
      party_id: 'B39AZ', selection_id: 'selection-1',
    })
    party.cancelVideoSelection()
    expect(emit).toHaveBeenCalledWith('cancel_video_selection', {
      party_id: 'B39AZ', selection_id: 'selection-1',
    })

    handlers.get('video_selection_cancelled')?.({ selection_id: 'selection-1' } as never)
    expect(party.pendingVideoSelection).toBeNull()
    expect(party.videoSelectionIssue).toBeNull()
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

  it('rotates this tab identity when an active participant owns the browser identity', async () => {
    const socket = useSocketStore()
    const emit = vi.spyOn(socket, 'emit').mockImplementation(() => undefined)
    const join = vi.spyOn(api, 'joinParty')
      .mockResolvedValueOnce({
        success: false,
        message: 'Participant identity is already in use',
      })
      .mockResolvedValueOnce({ success: true })
    vi.spyOn(api, 'authStatus').mockRejectedValue(new Error('not needed'))

    const party = usePartyStore()
    await party.join('ABC123', 'Alice')

    expect(join).toHaveBeenCalledTimes(2)
    const firstClientId = join.mock.calls[0]?.[1]
    const secondClientId = join.mock.calls[1]?.[1]
    expect(secondClientId).not.toBe(firstClientId)
    expect(party.sessionError).toBeNull()
    expect(emit).toHaveBeenCalledWith('join_party', expect.objectContaining({
      client_id: secondClientId,
    }))
    expect(emit).toHaveBeenCalledTimes(1)
  })

  it('identifies a different-party binding from another tab', async () => {
    const channels: Array<{
      onmessage: ((event: { data: { partyId: string } }) => void) | null
      postMessage: ReturnType<typeof vi.fn>
    }> = []
    vi.stubGlobal('BroadcastChannel', class {
      onmessage: ((event: { data: { partyId: string } }) => void) | null = null
      postMessage = vi.fn()

      constructor() {
        channels.push(this)
      }
    })
    const socket = useSocketStore()
    vi.spyOn(socket, 'emit').mockImplementation(() => undefined)
    vi.spyOn(api, 'joinParty').mockResolvedValue({ success: true })
    vi.spyOn(api, 'authStatus').mockRejectedValue(new Error('not needed'))

    const party = usePartyStore()
    await party.join('ABC123', 'Alice')

    expect(channels).toHaveLength(1)
    expect(channels[0]?.postMessage).toHaveBeenCalledWith({ partyId: 'ABC123' })
    channels[0]?.onmessage?.({ data: { partyId: 'ABC123' } })
    expect(party.supersededBy).toBeNull()
    channels[0]?.onmessage?.({ data: { partyId: 'XYZ789' } })
    expect(party.supersededBy).toBe('XYZ789')
    vi.unstubAllGlobals()
  })
})
