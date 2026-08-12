import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import { usePartyStore } from '@/stores/party'
import PartyView from './PartyView.vue'

/**
 * The mobile library header, all of it new on this branch and none of it
 * covered: the header itself, the breadcrumb it shows, "All Libraries", and
 * the container class the narrow-screen rules hang off.
 *
 * On a phone the library takes the whole screen, so once you are three levels
 * into a collection there is nothing on screen saying where you are or how to
 * get back out. That is what this header exists for -- and every part of it
 * fails by simply not being there, which is exactly what a test notices and a
 * glance at a desktop browser does not.
 */

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: 'B39AZ' }, query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  RouterLink: { template: '<a><slot /></a>' },
}))

vi.mock('@/stores/socket', () => ({
  useSocketStore: () => ({
    emit: vi.fn(), connect: vi.fn(), disconnect: vi.fn(),
    on: vi.fn(), off: vi.fn(), connected: true,
  }),
}))

let pinia: ReturnType<typeof createPinia>
let goToRoot: ReturnType<typeof vi.fn>

async function joinedHost() {
  const party = usePartyStore()
  vi.spyOn(party, 'join').mockResolvedValue(undefined as never)
  const auth = useAuthStore()
  vi.spyOn(auth, 'refresh').mockResolvedValue(undefined)
  auth.isHost = true
  // Browsing is gated on the party being unlocked, not on being host.
  auth.partyUnlocked = true

  goToRoot = vi.fn().mockResolvedValue(undefined)
  const wrapper = mount(PartyView, {
    global: {
      plugins: [pinia],
      stubs: {
        // Exposes goToRoot so the ref-driven call is observable; a `true`
        // stub has no exposed methods and the call silently no-ops.
        LibraryBrowser: {
          name: 'LibraryBrowser',
          template: '<div class="library-stub" />',
          setup(_props, ctx) {
            ctx.expose({ goToRoot })
          },
        },
        VideoPlayer: true,
        VideoControls: true,
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
  party.partyId = 'B39AZ'
  await nextTick()
  await nextTick()
  return { wrapper, party }
}

async function openLibrary(wrapper: Awaited<ReturnType<typeof joinedHost>>['wrapper']) {
  const browse = wrapper.findAll('button').find((button) => button.text() === 'Browse Library')
  expect(browse, 'no way to open the library').toBeTruthy()
  await browse!.trigger('click')
  await flushPromises()
}

describe('the mobile library header', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.restoreAllMocks()
    localStorage.setItem('emby-watchparty-username', 'Alice')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  })

  it('appears only while the library is open', async () => {
    const { wrapper } = await joinedHost()
    expect(wrapper.find('.mobile-library-header').exists()).toBe(false)

    await openLibrary(wrapper)
    expect(wrapper.find('.mobile-library-header').exists()).toBe(true)
    wrapper.unmount()
  })

  it('marks the container so the narrow-screen layout applies', async () => {
    const { wrapper } = await joinedHost()
    await openLibrary(wrapper)

    // `library-open` is what the phone rules key off. Without it the library
    // and the video try to share a screen that fits neither.
    expect(wrapper.get('.party-container').classes()).toContain('library-open')
    wrapper.unmount()
  })

  it('follows the browser rather than showing a fixed label', async () => {
    const { wrapper } = await joinedHost()
    await openLibrary(wrapper)

    expect(wrapper.get('.mobile-library-location').text()).toBe('Libraries')

    wrapper.findComponent({ name: 'LibraryBrowser' }).vm.$emit('navigation-change', 'Films / Sci-Fi')
    await nextTick()

    // Dropped, the header reads "Libraries" forever and is worse than absent:
    // it states a location that is wrong.
    expect(wrapper.get('.mobile-library-location').text()).toBe('Films / Sci-Fi')
    wrapper.unmount()
  })

  it('sends the browser back to the root without closing the panel', async () => {
    const { wrapper } = await joinedHost()
    await openLibrary(wrapper)

    const allLibraries = wrapper.findAll('.mobile-library-btn')
      .find((button) => button.text() === 'All Libraries')
    await allLibraries!.trigger('click')
    await flushPromises()

    expect(goToRoot).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.mobile-library-header').exists()).toBe(true)
    wrapper.unmount()
  })

  it('closes the library from the header', async () => {
    const { wrapper } = await joinedHost()
    await openLibrary(wrapper)

    const hide = wrapper.findAll('.mobile-library-btn')
      .find((button) => button.text() === 'Hide Library')
    await hide!.trigger('click')
    await nextTick()

    // The only exit on a phone, where the library covers the whole screen.
    expect(wrapper.find('.mobile-library-header').exists()).toBe(false)
    expect(wrapper.get('.party-container').classes()).not.toContain('library-open')
    wrapper.unmount()
  })
})
