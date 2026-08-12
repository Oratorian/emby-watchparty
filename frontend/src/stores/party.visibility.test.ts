import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { usePartyStore } from './party'
import { useSocketStore } from './socket'

/**
 * Party visibility and the dead-party probe, at the store level.
 *
 * Visibility is optimistic locally and authoritative on the server: the
 * toggle paints immediately, and a refusal simply never echoes back. So the
 * inbound listener is not decoration, it is the only thing that corrects a
 * wrong guess, and `hidden` has to survive both the broadcast and sync_state.
 */

function socketWithSpies() {
  const socket = useSocketStore()
  const handlers = new Map<string, (data: unknown) => void>()
  vi.spyOn(socket, 'on').mockImplementation(((event: string, handler: (d: unknown) => void) => {
    handlers.set(event, handler)
  }) as never)
  vi.spyOn(socket, 'off').mockImplementation((() => undefined) as never)
  const emit = vi.spyOn(socket, 'emit').mockImplementation(() => undefined)
  return { handlers, emit }
}

describe('party visibility', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('emits the requested state and paints it without waiting for the server', () => {
    const { emit } = socketWithSpies()
    const party = usePartyStore()
    party.partyId = 'B39AZ'

    // Asserted away from the ref's initial value in both directions, so the
    // optimistic write is what is being observed and not the default.
    party.setHidden(true)
    expect(emit).toHaveBeenLastCalledWith('set_party_hidden', {
      party_id: 'B39AZ',
      hidden: true,
    })
    expect(party.hidden).toBe(true)

    party.setHidden(false)
    expect(emit).toHaveBeenLastCalledWith('set_party_hidden', {
      party_id: 'B39AZ',
      hidden: false,
    })
    expect(party.hidden).toBe(false)
  })

  it('does not emit without a party to scope the request to', () => {
    const { emit } = socketWithSpies()
    const party = usePartyStore()
    party.partyId = ''

    party.setHidden(false)

    expect(emit).not.toHaveBeenCalled()
  })

  it('corrects the optimistic value from the broadcast', () => {
    const { handlers } = socketWithSpies()
    const party = usePartyStore()
    party.setupListeners()
    party.partyId = 'B39AZ'

    // What a second tab sees, and what corrects this tab if the server
    // disagreed with the optimistic paint.
    party.setHidden(false)
    handlers.get('party_visibility_changed')?.({ hidden: true })

    expect(party.hidden).toBe(true)
  })

  it('takes the visibility a joiner is handed in sync_state', () => {
    const { handlers } = socketWithSpies()
    const party = usePartyStore()
    party.setupListeners()

    handlers.get('sync_state')?.({
      playback_state: { playing: false, time: 0, last_update: '' },
      users: [],
      hidden: true,
    })

    expect(party.hidden).toBe(true)
  })
})

/**
 * The probe is deliberately not exported: it is only meaningful after a join
 * has already failed, so these drive it the way the app reaches it, through
 * join() -> bindSession() -> checkPartyMissing().
 */
describe('detecting a party that is gone', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    sessionStorage.clear()
    vi.restoreAllMocks()
    const socket = useSocketStore()
    vi.spyOn(socket, 'emit').mockImplementation(() => undefined)
    vi.spyOn(socket, 'on').mockImplementation((() => undefined) as never)
    vi.spyOn(socket, 'off').mockImplementation((() => undefined) as never)
    vi.spyOn(socket, 'connect').mockImplementation((() => undefined) as never)
  })

  it('flags a party the server refused and then says is gone', async () => {
    vi.spyOn(api, 'joinParty').mockResolvedValue({
      success: false,
      message: 'Party no longer exists',
    } as never)
    const exists = vi.spyOn(api, 'partyExists').mockResolvedValue({ exists: false })

    const party = usePartyStore()
    await party.join('B39AZ', 'Alice')

    // Asked, not inferred from the message prose, which the server may reword.
    expect(exists).toHaveBeenCalledWith('B39AZ')
    expect(party.partyMissing).toBe(true)
  })

  it('leaves a live party alone when the join failed for another reason', async () => {
    vi.spyOn(api, 'joinParty').mockResolvedValue({
      success: false,
      message: 'Party is full',
    } as never)
    vi.spyOn(api, 'partyExists').mockResolvedValue({ exists: true })

    const party = usePartyStore()
    await party.join('B39AZ', 'Alice')

    expect(party.sessionError).toBe('Party is full')
    expect(party.partyMissing).toBe(false)
  })

  it('does not evict anyone over a network blip', async () => {
    // A failure to reach the server is not evidence the party is gone, and
    // this flag routes people off the page on a timer.
    vi.spyOn(api, 'joinParty').mockResolvedValue({
      success: false,
      message: 'Could not join',
    } as never)
    vi.spyOn(api, 'partyExists').mockRejectedValue(new Error('offline'))

    const party = usePartyStore()
    await party.join('B39AZ', 'Alice')

    expect(party.partyMissing).toBe(false)
  })

  it('does not carry the flag into the next party', async () => {
    vi.spyOn(api, 'joinParty').mockResolvedValue({
      success: false,
      message: 'gone',
    } as never)
    vi.spyOn(api, 'partyExists').mockResolvedValue({ exists: false })
    vi.spyOn(api, 'leaveParty').mockResolvedValue({ success: true } as never)

    const party = usePartyStore()
    await party.join('B39AZ', 'Alice')
    party.hidden = true
    expect(party.partyMissing).toBe(true)

    await party.leave()

    // The store outlives the view. Left set, the next party opens showing
    // the dead-party card, frozen, because the countdown watcher only fires
    // on the transition into missing and that already happened.
    expect(party.partyMissing).toBe(false)
    expect(party.hidden).toBe(false)
  })

  it('clears the flag before the next join resolves, not after', async () => {
    let release: (value: unknown) => void = () => {}
    const inFlight = new Promise((resolve) => { release = resolve })
    vi.spyOn(api, 'joinParty').mockReturnValue(inFlight as never)

    const party = usePartyStore()
    party.partyMissing = true

    const joining = party.join('B39AZ', 'Alice')
    await Promise.resolve()

    // Clearing this only on a successful bind would leave the dead-party card
    // on screen for the whole round trip when someone goes straight from a
    // dead party to a live one.
    expect(party.partyMissing).toBe(false)

    release({ success: true })
    await joining
  })

  it('clears the flag once a join succeeds', async () => {
    const joinParty = vi.spyOn(api, 'joinParty')
      .mockResolvedValue({ success: false, message: 'gone' } as never)
    vi.spyOn(api, 'partyExists').mockResolvedValue({ exists: false })

    const party = usePartyStore()
    await party.join('B39AZ', 'Alice')
    expect(party.partyMissing).toBe(true)

    // The server came back. Nothing should still be counting them out.
    joinParty.mockResolvedValue({ success: true } as never)
    await party.join('B39AZ', 'Alice')

    expect(party.partyMissing).toBe(false)
  })
})
