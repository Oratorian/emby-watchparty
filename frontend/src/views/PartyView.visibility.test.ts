import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import { usePartyStore } from '@/stores/party'
import PartyView from './PartyView.vue'

/**
 * Two header/overlay behaviours the UX pass introduced.
 *
 * The hide-party eye is rendered for everyone and disabled for non-hosts. A
 * button that looks live but is refused server-side is worse than a disabled
 * one, and with no host at all the state still matters to the room, so the
 * control must not disappear when nobody is logged in.
 *
 * The dead-party card replaced a Retry button that could never succeed. It
 * has to actually leave -- clearing the party-bound cookie on the way, or the
 * stale binding follows the viewer into the next party they join.
 */

const routerPush = vi.fn()

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: 'B39AZ' }, query: {} }),
  useRouter: () => ({ push: routerPush, replace: vi.fn() }),
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

let pinia: ReturnType<typeof createPinia>

function mountParty() {
  return mount(PartyView, {
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
}

async function settle() {
  await nextTick()
  await nextTick()
}

describe('the hide-party control', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.restoreAllMocks()
    routerPush.mockClear()
    localStorage.setItem('emby-watchparty-username', 'Alice')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  /**
   * The header only exists once the server has confirmed the join. refresh()
   * is stubbed because it re-reads is_host from the network and would land
   * mid-test, overwriting whichever role the case is exercising.
   */
  async function mountJoined(isHost: boolean) {
    const party = usePartyStore()
    vi.spyOn(party, 'join').mockResolvedValue(undefined as never)
    const auth = useAuthStore()
    vi.spyOn(auth, 'refresh').mockResolvedValue(undefined)
    auth.isHost = isHost
    const wrapper = mountParty()
    party.users = ['Alice']
    await settle()
    return { wrapper, party, auth }
  }

  function eye(wrapper: ReturnType<typeof mountParty>) {
    return wrapper.get('button[aria-label^="Party is"]')
  }

  it('is present but inert for someone who is not the host', async () => {
    const { wrapper, party } = await mountJoined(false)
    const setHidden = vi.spyOn(party, 'setHidden').mockImplementation(() => undefined)

    // Present: this is the state where the "become host" button shows, and the
    // control used to vanish entirely.
    expect(eye(wrapper).attributes('disabled')).toBeDefined()
    await eye(wrapper).trigger('click')
    expect(setHidden).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('lets the host flip the listing, sending the negated state', async () => {
    const { wrapper, party } = await mountJoined(true)
    const setHidden = vi.spyOn(party, 'setHidden').mockImplementation(() => undefined)
    party.hidden = true
    await settle()

    expect(eye(wrapper).attributes('disabled')).toBeUndefined()
    await eye(wrapper).trigger('click')

    expect(setHidden).toHaveBeenCalledWith(false)
    wrapper.unmount()
  })

  it('reflects the current visibility rather than the last click', async () => {
    const { wrapper, party } = await mountJoined(true)
    party.hidden = false
    await settle()

    expect(eye(wrapper).classes()).not.toContain('ico-btn-active')
    expect(eye(wrapper).attributes('aria-pressed')).toBe('false')

    // Arrives from the server broadcast, not from this tab's click.
    party.hidden = true
    await settle()

    expect(eye(wrapper).classes()).toContain('ico-btn-active')
    expect(eye(wrapper).attributes('aria-pressed')).toBe('true')
    wrapper.unmount()
  })
})

describe('landing on a party that no longer exists', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.restoreAllMocks()
    vi.useFakeTimers()
    routerPush.mockClear()
    // Drives the auto-join overlay this card lives inside.
    localStorage.setItem('emby-watchparty-username', 'Alice')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  async function mountGone() {
    const party = usePartyStore()
    vi.spyOn(party, 'join').mockResolvedValue(undefined as never)
    const leave = vi.spyOn(party, 'leave').mockResolvedValue(undefined as never)
    const wrapper = mountParty()
    await settle()
    party.partyMissing = true
    await settle()
    return { wrapper, party, leave }
  }

  it('explains what happened instead of offering a doomed retry', async () => {
    const { wrapper } = await mountGone()

    const card = wrapper.get('.party-gone')
    expect(card.text()).toContain('This party no longer exists')
    expect(card.get('.party-gone-countdown').text()).toContain('8s')
    // The retry path must not be what a viewer sees here: it can never succeed.
    expect(wrapper.find('.session-retry').exists()).toBe(false)
    wrapper.unmount()
  })

  it('counts down and takes the viewer back on its own', async () => {
    const { wrapper, leave } = await mountGone()

    vi.advanceTimersByTime(3000)
    await settle()
    expect(wrapper.get('.party-gone-countdown').text()).toContain('5s')
    expect(routerPush).not.toHaveBeenCalled()

    vi.advanceTimersByTime(5000)
    await settle()

    // leave() clears the party-bound cookie; without it the stale binding
    // follows them into the next party.
    expect(leave).toHaveBeenCalled()
    expect(routerPush).toHaveBeenCalledWith('/')
    wrapper.unmount()
  })

  it('goes immediately when asked', async () => {
    const { wrapper, leave } = await mountGone()

    await wrapper.get('.party-gone button').trigger('click')

    expect(leave).toHaveBeenCalled()
    expect(routerPush).toHaveBeenCalledWith('/')
    wrapper.unmount()
  })

  it('stops counting when the view goes away', async () => {
    const { wrapper } = await mountGone()

    wrapper.unmount()
    vi.advanceTimersByTime(20000)
    await settle()

    // Otherwise it keeps ticking and pushes a route the viewer already left.
    expect(routerPush).not.toHaveBeenCalled()
  })

  it('stands down if the party turns out to be there after all', async () => {
    const { wrapper, party } = await mountGone()

    vi.advanceTimersByTime(3000)
    await settle()
    party.partyMissing = false
    await settle()

    vi.advanceTimersByTime(20000)
    await settle()

    expect(routerPush).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
