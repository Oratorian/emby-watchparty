import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAvatarStore } from '@/stores/avatar'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api/client'
import { usePartyStore } from '@/stores/party'
import PartyView from './PartyView.vue'

const socketHandlers = vi.hoisted(() => new Map<string, (data: any) => void>())

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
    prepare: vi.fn(), connect: vi.fn(),
    disconnect: vi.fn(),
    on: vi.fn((event: string, handler: (data: any) => void) => socketHandlers.set(event, handler)),
    off: vi.fn((event: string) => socketHandlers.delete(event)),
    connected: true,
  }),
}))

// PartyView renders this async component on every mount. Mock its module, not
// only its rendered tag, so no CSS import can outlive a fast test teardown.
vi.mock('@/components/JoinWaitingRoom.vue', () => ({
  __esModule: true,
  default: { template: '<div />' },
}))

vi.mock('@/components/EmojiPicker.vue', () => ({
  __esModule: true,
  default: { template: '<div />' },
}))

// These tests exercise the party shell. Vue Test Utils may resolve an async
// child even when its rendered tag is stubbed, so mock the unrelated modules
// too. Their CSS must not load after this test environment has been destroyed.
vi.mock('@/components/JoinVoteModal.vue', () => ({
  __esModule: true,
  default: { name: 'JoinVoteModal', template: '<div />' },
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
    socketHandlers.clear()
    localStorage.setItem('emby-watchparty-username', 'Alice')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  })

  afterEach(() => {
    localStorage.clear()
    vi.unstubAllGlobals()
  })

  it('shows host recovery instead of a login prompt while socket presence is restored', async () => {
    // The real join refreshes auth after binding, before the socket joins.
    vi.spyOn(usePartyStore(), 'join').mockImplementation(async () => {
      await useAuthStore().refresh()
    })
    vi.spyOn(api, 'authStatus').mockResolvedValue({
      is_host: true, is_admin: true, party_unlocked: false,
      host_username: 'Alice', party_id: 'ABC12',
    })
    const wrapper = mountParty()
    await flushPromises()
    usePartyStore().users = ['Alice']
    await flushPromises()
    expect(wrapper.get('button.chip-btn').text()).toBe('Restoring host…')
    expect(wrapper.get('button.chip-btn').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).not.toContain('Login to Become Host')

    useAuthStore().partyUnlocked = true
    await flushPromises()
    expect(wrapper.get('button.chip-btn').text()).toBe('Browse Library')
    expect(wrapper.get('button.chip-btn').attributes('disabled')).toBeUndefined()
    useAuthStore().isHost = false
    useAuthStore().partyUnlocked = false
    await flushPromises()
    expect(wrapper.get('button.chip-btn').text()).toBe('Login to Become Host')
    wrapper.unmount()
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

  it('keeps a rejected saved-name join visible and retries without another reload', async () => {
    const party = usePartyStore()
    const join = vi.spyOn(party, 'join').mockResolvedValue(undefined as never)
    const wrapper = mountParty()
    await flushPromises()
    socketHandlers.get('error')?.({ message: 'Participant identity is already in use' })
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toBe('Participant identity is already in use')
    expect(wrapper.get('.modal-card input').element).toHaveProperty('value', 'Alice')
    expect(wrapper.text()).not.toContain('Join Watch Party')
    await wrapper.get('.modal-card button').trigger('click')
    await flushPromises()
    expect(join).toHaveBeenCalledTimes(2)
    expect(join).toHaveBeenLastCalledWith('ABC12', 'Alice')
    expect(wrapper.find('.join-spinner').exists()).toBe(true)

    party.users = ['Alice']
    await flushPromises()
    expect(wrapper.find('.party-container').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows a manual join failure and retains the typed name for retry', async () => {
    localStorage.removeItem('emby-watchparty-username')
    const party = usePartyStore()
    const join = vi.spyOn(party, 'join').mockImplementation(async () => {
      party.sessionError = 'Could not bind the browser session'
    })
    const wrapper = mountParty()
    await flushPromises()
    await wrapper.get('.modal-card input').setValue('Bob')
    await wrapper.get('.modal-card button').trigger('click')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toBe('Could not bind the browser session')
    expect(wrapper.get('.modal-card input').element).toHaveProperty('value', 'Bob')
    expect(wrapper.get('.modal-card button').text()).toBe('Retry')
    await wrapper.get('.modal-card input').setValue('Robert')
    await wrapper.get('.modal-card button').trigger('click')
    await flushPromises()
    expect(join).toHaveBeenLastCalledWith('ABC12', 'Robert')
    wrapper.unmount()
  })

  it('waits for join confirmation before starting informational requests', async () => {
    vi.spyOn(usePartyStore(), 'join').mockResolvedValue(undefined as never)
    const auth = vi.spyOn(useAuthStore(), 'refresh').mockResolvedValue(undefined)
    const version = vi.spyOn(api, 'version').mockResolvedValue({} as never)
    const wrapper = mountParty()
    await flushPromises()
    expect(auth).not.toHaveBeenCalled()
    expect(version).not.toHaveBeenCalled()
    expect(wrapper.find('.join-spinner').exists()).toBe(true)

    usePartyStore().users = ['Alice']
    await flushPromises()
    expect(version).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
