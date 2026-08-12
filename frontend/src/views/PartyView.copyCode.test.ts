import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { usePartyStore } from '@/stores/party'
import { copyToClipboard } from '@/utils/clipboard'
import PartyView from './PartyView.vue'

/**
 * Feedback after copying the party code.
 *
 * The design refresh replaced the old "Copy" / "Copied!" button text with an
 * icon pill and moved the label into a title attribute. A title only raises a
 * tooltip when the pointer arrives, so after a click -- pointer already
 * stationary on the pill -- the confirmation was never shown at all, and the
 * user had no way to tell a successful copy from a dead button.
 */

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: 'B39AZ' }, query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  RouterLink: { template: '<a><slot /></a>' },
}))

vi.mock('@/stores/socket', () => ({
  useSocketStore: () => ({
    emit: vi.fn(),
    connect: vi.fn(),
    disconnect: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    connected: true,
  }),
}))

vi.mock('@/utils/clipboard', () => ({ copyToClipboard: vi.fn() }))

const copyMock = vi.mocked(copyToClipboard)
let pinia: ReturnType<typeof createPinia>

/**
 * The header only exists once the server has confirmed the join, which the
 * component latches off party.users rather than off its own emit.
 */
async function mountJoinedParty() {
  const party = usePartyStore()
  vi.spyOn(party, 'join').mockResolvedValue(undefined as never)

  const wrapper = mount(PartyView, {
    global: {
      plugins: [pinia],
      stubs: {
        VideoPlayer: true,
        VideoControls: true,
        LibraryBrowser: true,
        EmojiPicker: true,
        JoinVoteModal: true,
        JoinWaitingRoom: true,
        EmbyLoginModal: true,
        RouterLink: true,
        Teleport: true,
      },
    },
  })

  party.users = ['Alice']
  await nextTick()
  await nextTick()
  return wrapper
}

/** Settles the awaited clipboard call and the render it triggers. */
async function settle() {
  await nextTick()
  await nextTick()
}

describe('copying the party code', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.useFakeTimers()
    copyMock.mockReset()
    copyMock.mockResolvedValue(true)
    localStorage.setItem('emby-watchparty-username', 'Alice')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('confirms a successful copy on the pill itself, then reverts', async () => {
    const wrapper = await mountJoinedParty()
    const pill = wrapper.get('.party-pill')

    expect(pill.classes()).not.toContain('is-copied')

    await pill.trigger('click')
    await settle()

    expect(copyMock).toHaveBeenCalledWith('B39AZ')
    // Visible without hovering: the tint, and the icon swapping to a tick.
    expect(pill.classes()).toContain('is-copied')
    expect(pill.attributes('title')).toBe('Copied!')
    expect(wrapper.get('.party-pill-status').text()).toBe('Copied!')

    vi.advanceTimersByTime(2000)
    await settle()

    expect(pill.classes()).not.toContain('is-copied')
    expect(pill.attributes('title')).toBe('Copy party code')
    wrapper.unmount()
  })

  it('shows a failure state when the clipboard is unavailable', async () => {
    // Plain-LAN deployments hit this: no secure context, execCommand refused.
    copyMock.mockResolvedValue(false)
    const wrapper = await mountJoinedParty()
    const pill = wrapper.get('.party-pill')

    await pill.trigger('click')
    await settle()

    expect(pill.classes()).toContain('is-failed')
    expect(pill.classes()).not.toContain('is-copied')
    expect(pill.attributes('title')).toBe('Copy failed')
    wrapper.unmount()
  })

  it('restarts the window on a second click instead of inheriting the first timer', async () => {
    const wrapper = await mountJoinedParty()
    const pill = wrapper.get('.party-pill')

    await pill.trigger('click')
    await settle()
    vi.advanceTimersByTime(1900)

    await pill.trigger('click')
    await settle()
    // The first click's timer would fire here and clear a 100ms-old
    // confirmation.
    vi.advanceTimersByTime(100)
    await settle()

    expect(pill.classes()).toContain('is-copied')
    wrapper.unmount()
  })
})
