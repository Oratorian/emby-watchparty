import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { detectVideoCodecs } from '@/utils/videoCodecs'
import { usePartyStore } from './party'
import { useSocketStore } from './socket'

// Which codecs a given browser reports is already pinned against real
// measured browsers in utils/videoCodecs.test.ts. What is untested, and what
// these cover, is that the store puts that answer on the wire at all.
vi.mock('@/utils/videoCodecs', () => ({ detectVideoCodecs: vi.fn(() => ['h264']) }))

const codecs = vi.mocked(detectVideoCodecs)

/**
 * What the join_party emit carries, and when it is allowed to happen.
 *
 * These are all silent failures: the party still works, so nothing on screen
 * says anything is wrong.
 *
 * `video_codecs` is the worst of them. It is the client telling the server
 * what this browser can decode, and it is the only input to that decision.
 * Dropped, every viewer silently falls back to H.264 and every HEVC source
 * gets re-encoded for people whose hardware would have played it directly.
 * A merge on this branch very nearly dropped it, with a green suite.
 */

function socketSpy() {
  const socket = useSocketStore()
  vi.spyOn(socket, 'on').mockImplementation((() => undefined) as never)
  vi.spyOn(socket, 'off').mockImplementation((() => undefined) as never)
  vi.spyOn(socket, 'connect').mockImplementation((() => undefined) as never)
  return vi.spyOn(socket, 'emit').mockImplementation(() => undefined)
}

interface JoinPayload {
  client_id: string
  video_codecs: string[]
}

function joinEmits(emit: ReturnType<typeof socketSpy>) {
  return emit.mock.calls.filter(([event]) => event === 'join_party')
}

function lastJoinPayload(emit: ReturnType<typeof socketSpy>): JoinPayload {
  const last = joinEmits(emit).at(-1)
  if (!last) throw new Error('no join_party was emitted')
  return last[1] as JoinPayload
}

describe('the join_party emit', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('tells the server which codecs this browser reported', async () => {
    const emit = socketSpy()
    vi.spyOn(api, 'joinParty').mockResolvedValue({ success: true } as never)
    codecs.mockReturnValue(['h264', 'hevc'])

    const party = usePartyStore()
    await party.join('B39AZ', 'Alice')

    expect(lastJoinPayload(emit).video_codecs).toEqual(['h264', 'hevc'])
  })

  it('passes the probe result through rather than a fixed list', async () => {
    const emit = socketSpy()
    vi.spyOn(api, 'joinParty').mockResolvedValue({ success: true } as never)
    // A hardcoded ['h264','hevc'] would satisfy the case above while giving
    // this viewer a black video in a party where everyone else is fine.
    codecs.mockReturnValue(['h264'])

    const party = usePartyStore()
    await party.join('B39AZ', 'Alice')

    expect(lastJoinPayload(emit).video_codecs).toEqual(['h264'])
  })

  it('stays quiet when the session never bound', async () => {
    const emit = socketSpy()
    vi.spyOn(api, 'joinParty').mockResolvedValue({
      success: false,
      message: 'Party is full',
    } as never)
    vi.spyOn(api, 'partyExists').mockResolvedValue({ exists: true })

    const party = usePartyStore()
    await party.join('B39AZ', 'Alice')

    // Announcing a join whose cookie never bound puts a member in the room
    // whose HTTP requests all 401, with nothing on screen to explain it.
    expect(joinEmits(emit)).toHaveLength(0)
  })

  it('rotates onto a tab-scoped id when the identity is already taken', async () => {
    const emit = socketSpy()
    const joinParty = vi.spyOn(api, 'joinParty')
      // Exact wording the backend returns; see the cross-check in
      // party.identity.test.ts that keeps the two literals in step.
      .mockResolvedValueOnce({
        success: false,
        message: 'Participant identity is already in use',
      } as never)
      .mockResolvedValue({ success: true } as never)

    const party = usePartyStore()
    await party.join('B39AZ', 'Alice')

    expect(joinParty).toHaveBeenCalledTimes(2)
    const rotated = sessionStorage.getItem('emby-watchparty-tab-client-id')
    // sessionStorage, not localStorage: the rotation must be scoped to this
    // tab, and it must survive a reload or the same collision recurs.
    expect(rotated).toBeTruthy()
    expect(rotated).not.toBe(localStorage.getItem('emby-watchparty-client-id'))

    expect(lastJoinPayload(emit).client_id).toBe(rotated)
  })
})
