import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAvatarStore } from '@/stores/avatar'
import { usePartyStore } from '@/stores/party'
import PartyView from './PartyView.vue'

/**
 * Returning to a party after in-app navigation.
 *
 * PartyView unmounts on every navigation, and the Pinia store deliberately
 * survives that (see the comment on its onUnmounted). So a second mount sees a
 * store that still knows the party while the component itself has emitted no
 * join_party. Gating the auto-join on store state rather than component state
 * therefore skipped the join, nothing reassigned party.users, the watcher that
 * flips `joined` never fired, and the viewer sat behind the "Joining party..."
 * overlay with no video, chat, controls or Leave button until a full reload.
 */

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: 'ABC12' }, query: {} }),
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

describe('returning to a party after in-app navigation', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.restoreAllMocks()
    localStorage.setItem('emby-watchparty-username', 'Alice')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  })

  afterEach(() => {
    localStorage.clear()
    vi.unstubAllGlobals()
  })

  it('joins again when the store already knows the party', async () => {
    const party = usePartyStore()
    const join = vi.spyOn(party, 'join').mockResolvedValue(undefined as never)
    // Exactly the state after the Full Version Info link or Admin's
    // "Back to Watch Party": the store survived, this component did not.
    party.partyId = 'ABC12'

    const wrapper = mountParty()
    await flushPromises()

    expect(join).toHaveBeenCalledWith('ABC12', 'Alice')
    wrapper.unmount()
  })

  it('still auto-joins on a first visit with a saved username', async () => {
    const party = usePartyStore()
    const join = vi.spyOn(party, 'join').mockResolvedValue(undefined as never)

    const wrapper = mountParty()
    await flushPromises()

    expect(join).toHaveBeenCalledWith('ABC12', 'Alice')
    wrapper.unmount()
  })

  it('does not auto-join without a saved username', async () => {
    localStorage.removeItem('emby-watchparty-username')
    const party = usePartyStore()
    const join = vi.spyOn(party, 'join').mockResolvedValue(undefined as never)

    const wrapper = mountParty()
    await flushPromises()

    // Falls through to the manual name prompt instead.
    expect(join).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not re-join a name typed while startup was still running', async () => {
    // No saved name, so nothing should auto-join. The window is real: mount
    // awaits the avatar load before reaching the auto-join, and a manual Join
    // completing inside that window writes the typed name to storage.
    localStorage.removeItem('emby-watchparty-username')
    const party = usePartyStore()
    const join = vi.spyOn(party, 'join').mockResolvedValue(undefined as never)

    let releaseAvatar!: (value: string | null) => void
    const avatar = useAvatarStore()
    vi.spyOn(avatar, 'load').mockReturnValue(
      new Promise((resolve) => { releaseAvatar = resolve }),
    )

    const wrapper = mountParty()
    await flushPromises()

    // Startup is parked on the avatar load; the name prompt is already up.
    await wrapper.get('.modal-card input').setValue('Bob')
    await wrapper.get('.modal-card button').trigger('click')
    await flushPromises()
    expect(join).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem('emby-watchparty-username')).toBe('Bob')

    releaseAvatar(null)
    await flushPromises()

    // Reading storage after the awaits instead of snapshotting it at mount
    // would find "Bob", mistake a name typed one moment ago for a preexisting
    // auto-join, and claim the same socket identity a second time.
    expect(join).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
